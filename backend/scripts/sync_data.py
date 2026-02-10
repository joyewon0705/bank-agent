import argparse
import datetime
import json
import os
import sqlite3
import sys
import time
from contextlib import contextmanager
from typing import Optional, Tuple

import requests
from dotenv import load_dotenv

load_dotenv()
API_KEY = os.getenv("FINLIFE_API_KEY")

# 경로 고정 (실행 위치 상관없이 backend/bank_data.db 사용)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))           # backend/scripts
BACKEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))     # backend
DB_PATH = os.path.join(BACKEND_DIR, "bank_data.db")

LOCK_PATH = os.path.join(BACKEND_DIR, ".finlife_sync.lock")

API_CONFIGS = [
    {"key": "saving",  "name": "적금",       "url": "http://finlife.fss.or.kr/finlifeapi/savingProductsSearch.json"},
    {"key": "deposit", "name": "정기예금",   "url": "http://finlife.fss.or.kr/finlifeapi/depositProductsSearch.json"},
    {"key": "annuity", "name": "연금저축",   "url": "http://finlife.fss.or.kr/finlifeapi/annuitySavingProductsSearch.json"},
    {"key": "mortgage","name": "주택담보대출","url": "http://finlife.fss.or.kr/finlifeapi/mortgageLoanProductsSearch.json"},
    {"key": "rent",    "name": "전세자금대출","url": "http://finlife.fss.or.kr/finlifeapi/rentLoanProductsSearch.json"},
    {"key": "credit",  "name": "개인신용대출","url": "http://finlife.fss.or.kr/finlifeapi/creditLoanProductsSearch.json"},
]

def setup_db(conn: sqlite3.Connection):
    cur = conn.cursor()

    cur.execute('''CREATE TABLE IF NOT EXISTS products_base (
        fin_prdt_cd TEXT PRIMARY KEY,
        product_type TEXT,
        kor_co_nm TEXT,
        fin_prdt_nm TEXT,
        join_way TEXT,
        spcl_cnd TEXT,
        last_updated TEXT,

        -- 운영용
        is_active INTEGER DEFAULT 1,
        ended_at TEXT DEFAULT NULL,
        last_seen_at TEXT DEFAULT NULL
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS options_savings (
        fin_prdt_cd TEXT,
        save_trm INTEGER,
        intr_rate REAL,
        intr_rate2 REAL,
        intr_rate_type_nm TEXT
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS options_annuity (
        fin_prdt_cd TEXT,
        pnsn_kind_nm TEXT,
        prdt_type_nm TEXT,
        avg_prft_rate REAL,
        btrm_prft_rate_1 REAL
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS options_loan (
        fin_prdt_cd TEXT,
        mrtg_typ_nm TEXT,
        rpay_type_nm TEXT,
        lend_rate_type_nm TEXT,
        lend_rate_min REAL,
        lend_rate_max REAL
    )''')

    cur.execute('''CREATE TABLE IF NOT EXISTS sync_runs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        mode TEXT,
        started_at TEXT,
        finished_at TEXT,
        status TEXT,
        message TEXT
    )''')

    conn.commit()

def _to_float(x):
    try:
        if x is None or x == "":
            return None
        return float(x)
    except Exception:
        return None

def _to_int(x):
    try:
        if x is None or x == "":
            return None
        return int(x)
    except Exception:
        return None

def _fetch_json(url: str, params: dict, timeout: int = 12) -> Tuple[Optional[dict], Optional[str]]:
    try:
        r = requests.get(url, params=params, timeout=timeout)
    except Exception as e:
        return None, f"request_failed: {e}"

    if r.status_code != 200:
        return None, f"http_{r.status_code}"

    try:
        return r.json(), None
    except (ValueError, json.JSONDecodeError):
        head = (r.text or "")[:200].replace("\n", " ")
        return None, f"json_decode_failed: {head}"

def _clear_options_for_type(cur: sqlite3.Cursor, product_key: str):
    # 옵션 누적 방지: 해당 타입에 속한 옵션은 삭제 후 재적재
    if product_key in ("saving", "deposit"):
        cur.execute("""
            DELETE FROM options_savings
            WHERE fin_prdt_cd IN (SELECT fin_prdt_cd FROM products_base WHERE product_type = ?)
        """, (product_key,))
    elif product_key == "annuity":
        cur.execute("""
            DELETE FROM options_annuity
            WHERE fin_prdt_cd IN (SELECT fin_prdt_cd FROM products_base WHERE product_type = ?)
        """, (product_key,))
    elif product_key in ("mortgage", "rent", "credit"):
        cur.execute("""
            DELETE FROM options_loan
            WHERE fin_prdt_cd IN (SELECT fin_prdt_cd FROM products_base WHERE product_type = ?)
        """, (product_key,))

@contextmanager
def file_lock(lock_path: str, stale_seconds: int = 60 * 60):
    # 간단 락 파일: 중복 실행 방지 + stale 락 자동 해제
    if os.path.exists(lock_path):
        try:
            age = time.time() - os.path.getmtime(lock_path)
        except Exception:
            age = 0

        if age < stale_seconds:
            raise RuntimeError(f"이미 동기화가 실행 중일 수 있어요(락 존재): {lock_path}")
        else:
            try:
                os.remove(lock_path)
            except Exception:
                pass

    with open(lock_path, "w", encoding="utf-8") as f:
        f.write(datetime.datetime.now().isoformat())

    try:
        yield
    finally:
        try:
            os.remove(lock_path)
        except Exception:
            pass

def _groups_for(key: str):
    return ["020000", "030300"] if key in ["annuity", "mortgage", "rent", "credit"] else ["020000"]

def run_sync(mode: str = "daily") -> int:
    """
    mode:
      - daily  : 최신 유지(옵션 테이블 refresh + base upsert)
      - monthly: 종료상품 처리 포함(일단 해당 타입을 inactive로 만들고 이번에 다시 내려온 것만 active로 복구)
    """
    if not API_KEY:
        print("❌ FINLIFE_API_KEY가 .env에 없습니다. (.env에 FINLIFE_API_KEY=... 설정 필요)")
        return 2

    started_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    now = started_at
    monthly = (mode == "monthly")

    with file_lock(LOCK_PATH):
        conn = sqlite3.connect(DB_PATH)
        try:
            setup_db(conn)
            cur = conn.cursor()

            cur.execute(
                "INSERT INTO sync_runs(mode, started_at, status, message) VALUES (?,?,?,?)",
                (mode, started_at, "running", ""),
            )
            run_id = cur.lastrowid
            conn.commit()

            for config in API_CONFIGS:
                print(f"\n📡 {config['name']}({config['key']}) 전체 동기화 시작...")

                # 1) 옵션은 타입별로 싹 갈아끼우기(중복 폭발 방지)
                _clear_options_for_type(cur, config["key"])
                conn.commit()

                # 2) monthly면: 일단 해당 타입 상품을 inactive로 밀어두고
                #    이번 동기화에서 다시 발견된 것만 active로 복구
                if monthly:
                    cur.execute(
                        """UPDATE products_base
                           SET is_active=0,
                               ended_at=COALESCE(ended_at, ?)
                           WHERE product_type=?""",
                        (now, config["key"]),
                    )
                    conn.commit()

                total_base = 0
                total_opt = 0

                # 그룹별 + 페이지네이션
                for group in _groups_for(config["key"]):
                    # 1페이지 먼저 호출해서 max_page_no 확인
                    first_params = {"auth": API_KEY, "topFinGrpNo": group, "pageNo": "1"}
                    first_data, first_err = _fetch_json(config["url"], first_params)
                    if first_err:
                        print(f"   ⚠️ {group} 1p 실패: {first_err}")
                        continue

                    first_result = (first_data or {}).get("result") or {}
                    if first_result.get("err_cd") != "000":
                        print(f"   ⚠️ {group} 비즈니스 에러: {first_result.get('err_msg')}")
                        continue

                    # FINLIFE 응답에 보통 max_page_no가 있음(없으면 1로 처리)
                    max_page = first_result.get("max_page_no")
                    try:
                        max_page = int(max_page) if max_page else 1
                    except Exception:
                        max_page = 1

                    # 1..max_page 반복
                    for page in range(1, max_page + 1):
                        params = {"auth": API_KEY, "topFinGrpNo": group, "pageNo": str(page)}
                        data, err = _fetch_json(config["url"], params)
                        if err:
                            print(f"   ⚠️ {group} {page}p 실패: {err}")
                            continue

                        result = (data or {}).get("result") or {}
                        if result.get("err_cd") != "000":
                            print(f"   ⚠️ {group} {page}p 비즈니스 에러: {result.get('err_msg')}")
                            continue

                        base_list = result.get("baseList") or []
                        opt_list = result.get("optionList") or []

                        # base upsert
                        for base in base_list:
                            fin_prdt_cd = base.get("fin_prdt_cd")
                            if not fin_prdt_cd:
                                continue

                            cur.execute(
                                """INSERT INTO products_base
                                   (fin_prdt_cd, product_type, kor_co_nm, fin_prdt_nm, join_way, spcl_cnd, last_updated,
                                    is_active, ended_at, last_seen_at)
                                   VALUES (?,?,?,?,?,?,?,?,?,?)
                                   ON CONFLICT(fin_prdt_cd) DO UPDATE SET
                                     product_type=excluded.product_type,
                                     kor_co_nm=excluded.kor_co_nm,
                                     fin_prdt_nm=excluded.fin_prdt_nm,
                                     join_way=excluded.join_way,
                                     spcl_cnd=excluded.spcl_cnd,
                                     last_updated=excluded.last_updated,
                                     is_active=1,
                                     ended_at=NULL,
                                     last_seen_at=excluded.last_seen_at
                                """,
                                (
                                    fin_prdt_cd,
                                    config["key"],
                                    base.get("kor_co_nm", ""),
                                    base.get("fin_prdt_nm", ""),
                                    base.get("join_way", ""),
                                    base.get("spcl_cnd", "") or "",
                                    now,
                                    1,
                                    None,
                                    now,
                                ),
                            )
                        total_base += len(base_list)

                        # options insert
                        for opt in opt_list:
                            cd = opt.get("fin_prdt_cd")
                            if not cd:
                                continue

                            if config["key"] in ["saving", "deposit"]:
                                cur.execute(
                                    "INSERT INTO options_savings VALUES (?,?,?,?,?)",
                                    (
                                        cd,
                                        _to_int(opt.get("save_trm")),
                                        _to_float(opt.get("intr_rate")),
                                        _to_float(opt.get("intr_rate2")),
                                        opt.get("intr_rate_type_nm", ""),
                                    ),
                                )
                            elif config["key"] == "annuity":
                                cur.execute(
                                    "INSERT INTO options_annuity VALUES (?,?,?,?,?)",
                                    (
                                        cd,
                                        opt.get("pnsn_kind_nm", ""),
                                        opt.get("prdt_type_nm", ""),
                                        _to_float(opt.get("avg_prft_rate")),
                                        _to_float(opt.get("btrm_prft_rate_1")),
                                    ),
                                )
                            else:  # mortgage/rent/credit
                                cur.execute(
                                    "INSERT INTO options_loan VALUES (?,?,?,?,?,?)",
                                    (
                                        cd,
                                        opt.get("mrtg_typ_nm"),
                                        opt.get("rpay_type_nm") or opt.get("rpay_alph_nm"),
                                        opt.get("lend_rate_type_nm"),
                                        _to_float(opt.get("lend_rate_min")),
                                        _to_float(opt.get("lend_rate_max")),
                                    ),
                                )
                        total_opt += len(opt_list)

                        conn.commit()
                        print(f"   ✅ {config['name']} {group} {page}/{max_page}p: base {len(base_list)} / opt {len(opt_list)}")

                print(f"📦 {config['name']} 합계: base {total_base} / option {total_opt}")

            finished_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cur.execute(
                "UPDATE sync_runs SET finished_at=?, status=?, message=? WHERE id=?",
                (finished_at, "success", "", run_id),
            )
            conn.commit()
            print("\n🏁 동기화 완료")
            return 0

        except Exception as e:
            finished_at = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            try:
                cur = conn.cursor()
                cur.execute(
                    "UPDATE sync_runs SET finished_at=?, status=?, message=? WHERE id=(SELECT MAX(id) FROM sync_runs)",
                    (finished_at, "failed", str(e)[:500]),
                )
                conn.commit()
            except Exception:
                pass
            print(f"\n❌ 동기화 실패: {e}")
            return 1
        finally:
            conn.close()

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["daily", "monthly"], default="daily")
    code = run_sync(mode=parser.parse_args().mode)
    sys.exit(code)

if __name__ == "__main__":
    main()
