import argparse
import datetime
import hashlib
import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from typing import Optional, Tuple, List, Dict

import requests
from dotenv import load_dotenv

from langchain_groq import ChatGroq
import httpx

load_dotenv()
API_KEY = os.getenv("FINLIFE_API_KEY")

# 경로 고정 (실행 위치 상관없이 backend/bank_data.db 사용)
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))           # backend/scripts
BACKEND_DIR = os.path.abspath(os.path.join(SCRIPT_DIR, ".."))     # backend
DB_PATH = os.path.join(BACKEND_DIR, "bank_data.db")

# --- LLM (Groq) for auto condition catalog expansion ---
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
_llm_client = httpx.Client(verify=False)

_llm = None
if GROQ_API_KEY:
    _llm = ChatGroq(
        temperature=0,
        model_name="llama-3.3-70b-versatile",
        groq_api_key=GROQ_API_KEY,
        http_client=_llm_client,
    )


@contextmanager
def db_conn(db_path: str = DB_PATH):
    conn = sqlite3.connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def setup_db(conn: sqlite3.Connection):
    """필수 테이블 생성"""
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

    # ✅ 우대/조건 기반 질문 카탈로그 (하드코딩 제거용)
    cur.execute('''CREATE TABLE IF NOT EXISTS condition_catalog (
        key TEXT PRIMARY KEY,
        patterns_json TEXT NOT NULL,         -- JSON list[str]
        question TEXT NOT NULL,
        explain TEXT DEFAULT NULL,
        is_active INTEGER DEFAULT 1,
        updated_at TEXT NOT NULL
    )''')

    conn.commit()
    ensure_condition_catalog_seeds(conn)


def ensure_condition_catalog_seeds(conn: sqlite3.Connection):
    """초기/기본 조건 사전. (없으면 넣고, 있으면 유지)"""
    seeds = [
        {
            "key": "salary_transfer",
            "patterns": ["급여이체", "급여", "급여입금", "월급"],
            "question": "급여이체(월급 들어오는 계좌로 설정) 가능하세요? (예/아니오/모름)",
            "explain": "",
        },
        {
            "key": "auto_transfer",
            "patterns": ["자동이체", "정기이체", "CMS", "계좌자동이체"],
            "question": "매달 자동이체로 납입 설정 가능하세요? (예/아니오/모름)",
            "explain": "",
        },
        {
            "key": "card_spend",
            "patterns": ["카드실적", "카드 이용", "체크카드", "신용카드", "카드사용"],
            "question": "카드 실적(한 달에 카드로 일정 금액 쓰기) 맞출 수 있나요? (예/아니오/모름)",
            "explain": "카드 실적은 ‘한 달에 카드로 일정 금액 이상 쓰면’ 우대금리를 주는 조건이에요.",
        },
        {
            "key": "primary_bank",
            "patterns": ["주거래", "주거래은행", "거래실적", "실적"],
            "question": "주거래로(이체/자동이체를 한 은행으로 모으기) 설정 가능하세요? (예/아니오/모름)",
            "explain": "",
        },
        {
            "key": "non_face",
            "patterns": ["비대면", "모바일", "앱", "온라인", "인터넷"],
            "question": "비대면(앱으로 가입)도 괜찮으세요? (예/아니오/모름)",
            "explain": "",
        },
        {
            "key": "youth",
            "patterns": ["청년", "만 34", "만34", "사회초년생", "19~34", "19-34"],
            "question": "청년 우대(대략 만 19~34세)에 해당하세요? (예/아니오/모름)",
            "explain": "",
        },
        {
            "key": "marketing",
            "patterns": ["마케팅", "수신동의", "동의"],
            "question": "마케팅 수신 동의 같은 항목에 동의 가능하세요? (예/아니오/모름)",
            "explain": "",
        },
    ]

    cur = conn.cursor()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for s in seeds:
        cur.execute("SELECT 1 FROM condition_catalog WHERE key = ?", (s["key"],))
        if cur.fetchone():
            continue
        cur.execute(
            """
            INSERT INTO condition_catalog(key, patterns_json, question, explain, is_active, updated_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (s["key"], json.dumps(s["patterns"], ensure_ascii=False), s["question"], s["explain"], now),
        )
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


def _clear_options_for_type(cur: sqlite3.Cursor, product_type: str):
    if product_type in ("saving", "deposit"):
        cur.execute(
            "DELETE FROM options_savings WHERE fin_prdt_cd IN (SELECT fin_prdt_cd FROM products_base WHERE product_type=?)",
            (product_type,),
        )
        return
    if product_type == "annuity":
        cur.execute(
            "DELETE FROM options_annuity WHERE fin_prdt_cd IN (SELECT fin_prdt_cd FROM products_base WHERE product_type=?)",
            (product_type,),
        )
        return
    cur.execute(
        "DELETE FROM options_loan WHERE fin_prdt_cd IN (SELECT fin_prdt_cd FROM products_base WHERE product_type=?)",
        (product_type,),
    )


# -----------------------------
# API endpoints (금감원 finlife)
# -----------------------------
BASE_URL = "https://finlife.fss.or.kr/finlifeapi"
URLS = {
    "saving": f"{BASE_URL}/savingProductsSearch.json",
    "deposit": f"{BASE_URL}/depositProductsSearch.json",
    "annuity": f"{BASE_URL}/annuitySavingProductsSearch.json",
    "mortgage": f"{BASE_URL}/mortgageLoanProductsSearch.json",
    "rent": f"{BASE_URL}/rentHouseLoanProductsSearch.json",
    "credit": f"{BASE_URL}/creditLoanProductsSearch.json",
}

# 내부에서 쓰는 product_type 표준값
TYPE_MAP = {
    "saving": "saving",
    "deposit": "deposit",
    "annuity": "annuity",
    "mortgage": "주담대",
    "rent": "전세자금대출",
    "credit": "신용대출",
}


def _upsert_products(conn: sqlite3.Connection, product_type: str, base_list: List[dict], opt_list: List[dict]):
    cur = conn.cursor()
    now = datetime.datetime.now().isoformat(timespec="seconds")

    # options 테이블은 유형별로 싹 지우고 다시 넣는 방식(간단/안정)
    _clear_options_for_type(cur, product_type)

    # base upsert + last_seen
    for b in base_list:
        fin_prdt_cd = b.get("fin_prdt_cd")
        if not fin_prdt_cd:
            continue
        cur.execute(
            """
            INSERT INTO products_base(fin_prdt_cd, product_type, kor_co_nm, fin_prdt_nm, join_way, spcl_cnd, last_updated, is_active, ended_at, last_seen_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 1, NULL, ?)
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
                product_type,
                b.get("kor_co_nm"),
                b.get("fin_prdt_nm"),
                b.get("join_way"),
                b.get("spcl_cnd"),
                now,
                now,
            ),
        )

    # options insert
    if product_type in ("saving", "deposit"):
        for o in opt_list:
            cur.execute(
                """
                INSERT INTO options_savings(fin_prdt_cd, save_trm, intr_rate, intr_rate2, intr_rate_type_nm)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    o.get("fin_prdt_cd"),
                    _to_int(o.get("save_trm")),
                    _to_float(o.get("intr_rate")),
                    _to_float(o.get("intr_rate2")),
                    o.get("intr_rate_type_nm"),
                ),
            )

    elif product_type == "annuity":
        for o in opt_list:
            cur.execute(
                """
                INSERT INTO options_annuity(fin_prdt_cd, pnsn_kind_nm, prdt_type_nm, avg_prft_rate, btrm_prft_rate_1)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    o.get("fin_prdt_cd"),
                    o.get("pnsn_kind_nm"),
                    o.get("prdt_type_nm"),
                    _to_float(o.get("avg_prft_rate")),
                    _to_float(o.get("btrm_prft_rate_1")),
                ),
            )

    else:
        for o in opt_list:
            cur.execute(
                """
                INSERT INTO options_loan(fin_prdt_cd, mrtg_typ_nm, rpay_type_nm, lend_rate_type_nm, lend_rate_min, lend_rate_max)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    o.get("fin_prdt_cd"),
                    o.get("mrtg_typ_nm"),
                    o.get("rpay_type_nm"),
                    o.get("lend_rate_type_nm"),
                    _to_float(o.get("lend_rate_min")),
                    _to_float(o.get("lend_rate_max")),
                ),
            )

    conn.commit()


def _mark_ended_products(conn: sqlite3.Connection, product_type: str):
    """이번 sync에서 안 보인 상품은 is_active=0 처리(간단 종료 처리)"""
    cur = conn.cursor()
    now = datetime.datetime.now().isoformat(timespec="seconds")
    cur.execute(
        """
        UPDATE products_base
        SET is_active=0, ended_at=COALESCE(ended_at, ?)
        WHERE product_type=? AND (last_seen_at IS NULL OR last_seen_at < ?)
        """,
        (now, product_type, now),
    )
    conn.commit()


def sync_one(product_type_key: str, top_fin_grp_no: str = "020000") -> Tuple[bool, str]:
    if not API_KEY:
        return False, "FINLIFE_API_KEY env not set"

    url = URLS[product_type_key]
    params = {
        "auth": API_KEY,
        "topFinGrpNo": top_fin_grp_no,
        "pageNo": 1,
    }

    data, err = _fetch_json(url, params)
    if err:
        return False, f"{product_type_key}: {err}"
    if not data or "result" not in data:
        return False, f"{product_type_key}: invalid_response"

    res = data["result"]
    base_list = res.get("baseList", []) or []
    opt_list = res.get("optionList", []) or []

    mapped_type = TYPE_MAP[product_type_key]
    with db_conn() as conn:
        setup_db(conn)
        _upsert_products(conn, mapped_type, base_list, opt_list)
        _mark_ended_products(conn, mapped_type)

    return True, f"{product_type_key}: ok base={len(base_list)} opt={len(opt_list)}"


# -----------------------------
# Auto expand condition_catalog (LLM)
# -----------------------------
AUTO_EXPAND_SYSTEM = """
너는 금융상품 '우대조건(spcl_cnd)' 문구를 분석해, 재사용 가능한 '조건 카탈로그' 항목을 만드는 역할이야.

입력 JSON:
{
  "samples": ["우대조건 문구1", "우대조건 문구2", ...],
  "existing_keys": ["salary_transfer", ...]
}

출력은 반드시 JSON만:
{
  "items": [
    {
      "key": "snake_case_english",
      "patterns": ["한국어 핵심 키워드/짧은 구", "..."],
      "question": "사용자에게 예/아니오/모름으로 답할 수 있게 묻는 한 문장",
      "explain": "짧은 설명(없으면 빈 문자열)",
      "confidence": 0.0~1.0
    }
  ]
}

규칙:
- items는 최대 10개.
- key는 영문 소문자 + 숫자 + 언더스코어만. (예: salary_transfer)
- patterns는 2~8개, 각 2~10자 정도의 짧은 표현. (너무 긴 문장 금지)
- question은 15~80자 정도, 끝에 (예/아니오/모름) 포함 권장.
- existing_keys와 충돌하는 key는 만들지 마.
- 너무 상품 특정적인 패턴(특정 상품명/은행명 등)은 patterns에 넣지 마.
- '우대금리', '추가금리' 같은 너무 범용 패턴은 피하고, 실제 조건을 대표하는 단어를 써.
"""


def _safe_json_parse(text: str):
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            return None
        try:
            return json.loads(m.group(0))
        except Exception:
            return None


def _norm_key(s: str) -> str:
    s = (s or "").strip().lower()
    s = re.sub(r"[^a-z0-9_]+", "_", s)
    s = re.sub(r"_+", "_", s).strip("_")
    return s


def _is_generic_pattern(p: str) -> bool:
    p = (p or "").strip()
    bad = {"우대", "우대금리", "추가금리", "금리", "해당", "조건", "적용", "가입", "이용"}
    return (p in bad) or (len(p) < 2)


def _hash_patterns(patterns: list) -> str:
    raw = "|".join(sorted([str(x) for x in patterns if isinstance(x, str)]))
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:10]


def refresh_condition_catalog_auto(
    db_path: str = DB_PATH,
    max_unmatched_samples: int = 60,   # LLM에 던질 샘플 수
    max_new_items: int = 10,           # 1회 sync에서 추가할 최대 항목
    min_confidence: float = 0.78,      # 자동 등록 기준
) -> Dict[str, int]:
    """
    sync 후 자동으로 condition_catalog를 확장한다.
    - 기존 카탈로그 패턴에 매칭되지 않는 spcl_cnd 문구를 수집
    - LLM으로 새 조건 항목(items) 생성
    - 검증 통과 + confidence>=min_confidence 인 항목만 DB insert
    """
    if _llm is None:
        return {"auto_expand_added": 0, "auto_expand_skipped": 0, "unmatched_samples": 0}

    with db_conn(db_path) as conn:
        setup_db(conn)
        cur = conn.cursor()

        cur.execute("SELECT key, patterns_json FROM condition_catalog WHERE is_active=1")
        rows = cur.fetchall()
        existing_keys = [r[0] for r in rows]

        catalog_patterns = []
        for k, pj in rows:
            try:
                pats = json.loads(pj) if pj else []
            except Exception:
                pats = []
            catalog_patterns.append((k, [p for p in pats if isinstance(p, str) and p.strip()]))

        cur.execute("""
            SELECT spcl_cnd
            FROM products_base
            WHERE is_active=1 AND spcl_cnd IS NOT NULL AND spcl_cnd != ''
            ORDER BY LENGTH(spcl_cnd) DESC
            LIMIT 2000
        """)
        spcls = [r[0] for r in cur.fetchall()]

        unmatched = []
        for txt in spcls:
            hit = False
            for _, pats in catalog_patterns:
                if any(p in txt for p in pats):
                    hit = True
                    break
            if not hit:
                unmatched.append(txt)
            if len(unmatched) >= max_unmatched_samples:
                break

        if not unmatched:
            return {"auto_expand_added": 0, "auto_expand_skipped": 0, "unmatched_samples": 0}

        payload = {"samples": unmatched, "existing_keys": existing_keys}

    resp = _llm.invoke([
        {"role": "system", "content": AUTO_EXPAND_SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ])
    data = _safe_json_parse(getattr(resp, "content", "") or "")
    items = (data or {}).get("items") or []

    added = 0
    skipped = 0
    now = datetime.datetime.now().isoformat(timespec="seconds")

    with db_conn(db_path) as conn:
        setup_db(conn)
        cur = conn.cursor()

        cur.execute("SELECT key, patterns_json FROM condition_catalog")
        existed = {r[0]: r[1] for r in cur.fetchall()}

        for it in items[:max_new_items]:
            try:
                key = _norm_key(it.get("key", ""))
                patterns = it.get("patterns") or []
                question = (it.get("question") or "").strip()
                explain = (it.get("explain") or "").strip()
                conf = float(it.get("confidence", 0.0))
            except Exception:
                skipped += 1
                continue

            if conf < min_confidence:
                skipped += 1
                continue

            if not key or key in existed:
                skipped += 1
                continue
            if not re.fullmatch(r"[a-z0-9_]{3,40}", key):
                skipped += 1
                continue

            if not isinstance(patterns, list):
                skipped += 1
                continue
            cleaned = []
            for p in patterns:
                if not isinstance(p, str):
                    continue
                p = p.strip()
                if not p:
                    continue
                if len(p) > 12:
                    continue
                if _is_generic_pattern(p):
                    continue
                cleaned.append(p)
            cleaned = list(dict.fromkeys(cleaned))
            if len(cleaned) < 2:
                skipped += 1
                continue

            if len(question) < 10 or len(question) > 120:
                skipped += 1
                continue
            if "(예/아니오/모름)" not in question and len(question) <= 100:
                question = question + " (예/아니오/모름)"

            pat_hash = _hash_patterns(cleaned)
            dup = False
            for _, pj in existed.items():
                try:
                    ex_pats = json.loads(pj) if pj else []
                except Exception:
                    ex_pats = []
                if _hash_patterns(ex_pats) == pat_hash:
                    dup = True
                    break
            if dup:
                skipped += 1
                continue

            cur.execute(
                """
                INSERT INTO condition_catalog(key, patterns_json, question, explain, is_active, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)
                """,
                (key, json.dumps(cleaned, ensure_ascii=False), question, explain, now),
            )
            existed[key] = json.dumps(cleaned, ensure_ascii=False)
            added += 1

        conn.commit()

    return {
        "auto_expand_added": added,
        "auto_expand_skipped": skipped,
        "unmatched_samples": len(unmatched),
    }


def run_sync(mode: str = "daily") -> Dict[str, str]:
    """
    mode:
      - daily: 전체 싱크
      - monthly: 동일(프로젝트 단계에서는 단순화)
    """
    started = datetime.datetime.now().isoformat(timespec="seconds")
    with db_conn() as conn:
        setup_db(conn)
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO sync_runs(mode, started_at, status, message) VALUES (?, ?, ?, ?)",
            (mode, started, "running", ""),
        )
        run_id = cur.lastrowid
        conn.commit()

    msgs = []
    ok_all = True
    for key in ["saving", "deposit", "annuity", "mortgage", "rent", "credit"]:
        ok, msg = sync_one(key)
        ok_all = ok_all and ok
        msgs.append(msg)
        time.sleep(0.2)

    finished = datetime.datetime.now().isoformat(timespec="seconds")
    status = "success" if ok_all else "partial_fail"
    message = " | ".join(msgs)

    with db_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "UPDATE sync_runs SET finished_at=?, status=?, message=? WHERE id=?",
            (finished, status, message, run_id),
        )
        conn.commit()

    # ✅ sync 직후: seed 보장 + 자동 확장
    try:
        refresh_condition_catalog_auto(DB_PATH)
    except Exception:
        pass

    return {"status": status, "message": message, "started_at": started, "finished_at": finished}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", default="daily", choices=["daily", "monthly"])
    args = parser.parse_args()

    out = run_sync(args.mode)
    print(json.dumps(out, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
