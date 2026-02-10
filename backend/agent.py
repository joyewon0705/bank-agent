import os
import json
import re
import sqlite3
import httpx
from typing import Any, Dict, List, Optional

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pathlib import Path

load_dotenv()

# DB 경로를 실행 위치와 무관하게 고정
DB_PATH = os.getenv("BANK_DB_PATH")
if not DB_PATH:
    DB_PATH = str(Path(__file__).resolve().parent / "bank_data.db")


def _db_connect():
    return sqlite3.connect(DB_PATH)


def load_condition_catalog() -> Dict[str, Dict[str, Any]]:
    """condition_catalog 테이블에서 (patterns/question/explain)을 로드"""
    conn = _db_connect()
    cur = conn.cursor()
    try:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS condition_catalog (
                key TEXT PRIMARY KEY,
                patterns_json TEXT NOT NULL,
                question TEXT NOT NULL,
                explain TEXT DEFAULT NULL,
                is_active INTEGER DEFAULT 1,
                updated_at TEXT NOT NULL
            )
        """)
        conn.commit()

        cur.execute("SELECT key, patterns_json, question, explain FROM condition_catalog WHERE is_active=1")
        rows = cur.fetchall()
    finally:
        conn.close()

    catalog: Dict[str, Dict[str, Any]] = {}
    for k, pj, q, ex in rows:
        try:
            pats = json.loads(pj) if pj else []
        except Exception:
            pats = []
        catalog[k] = {
            "patterns": [p for p in pats if isinstance(p, str) and p.strip()],
            "question": q or "",
            "explain": ex or "",
        }
    return catalog


custom_client = httpx.Client(verify=False)

llm = ChatGroq(
    temperature=0,
    model_name="llama-3.3-70b-versatile",
    groq_api_key=os.getenv("GROQ_API_KEY"),
    http_client=custom_client,
)

# -----------------------------
# Helpers
# -----------------------------
def _safe_json(text: str) -> Optional[dict]:
    try:
        return json.loads(text)
    except Exception:
        m = re.search(r"\{.*\}", text, re.S)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
        return None


def _norm(s: str) -> str:
    return (s or "").strip().lower()


def quick_yes_no(user_message: str) -> Optional[str]:
    t = _norm(user_message)
    if t in {"예", "네", "응", "ㅇㅇ", "가능", "할게", "할수있어", "할 수 있어", "가능해"}:
        return "yes"
    if t in {"아니오", "아니", "못해", "불가", "어려워", "안돼", "안 돼"}:
        return "no"
    if t in {"모름", "몰라", "잘 모르겠어", "글쎄", "애매", "대충", "잘 모르겠다"}:
        return "unknown"
    return None


def user_is_confused(user_message: str) -> bool:
    t = _norm(user_message)
    conf = ["무슨", "뭐야", "이해", "잘 모르", "설명", "어떤 뜻", "헷갈", "??", "어케"]
    return any(c in t for c in conf)


def dedupe_products(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for p in products:
        pid = p.get("fin_prdt_cd") or (p.get("bank"), p.get("name"))
        if pid in seen:
            continue
        seen.add(pid)
        out.append(p)
    return out


# -----------------------------
# 1) "가이드(질문 흐름)" 결정
# -----------------------------
GUIDE_DECIDER_SYSTEM = """
너는 금융 상담 챗봇의 '질문 흐름'을 결정하는 에이전트야.
사용자가 원하는 금융 목적을 파악해서 다음 중 하나로 분류해.

가능한 출력:
- "적금"
- "예금"
- "연금저축"
- "주담대"
- "전세자금대출"
- "신용대출"

규칙:
- 모으기/저축/목돈 마련: 적금/예금/연금저축 중 하나
- 빌리기/대출/주택/전세/신용: 대출 3종 중 하나
- 확실하지 않으면 사용자의 표현을 존중해서 가장 근접한 걸 골라
- 한국어만
출력은 JSON: {"product_type":"...","reason":"..."}
"""


def guide_decide(user_message: str, history: List[Any]) -> Dict[str, str]:
    resp = llm.invoke(
        [
            {"role": "system", "content": GUIDE_DECIDER_SYSTEM},
            {"role": "user", "content": user_message},
        ]
    )
    data = _safe_json(getattr(resp, "content", "") or "")
    if not data or "product_type" not in data:
        return {"product_type": "적금", "reason": "모으기/저축 의도가 있어 보여서 적금으로 시작할게요."}
    return {
        "product_type": data.get("product_type", "적금"),
        "reason": data.get("reason", ""),
    }


# -----------------------------
# 2) 타입 매핑 / DB 조회
# -----------------------------
def _map_to_db_type(product_type: str) -> str:
    pt = (product_type or "").strip()
    if pt in {"적금", "saving"}:
        return "saving"
    if pt in {"예금", "deposit"}:
        return "deposit"
    if pt in {"연금저축", "annuity"}:
        return "annuity"
    return pt  # 주담대/전세자금대출/신용대출은 그대로


def fetch_top_products(product_type: str, top_n: int = 30) -> List[Dict[str, Any]]:
    db_type = _map_to_db_type(product_type)
    conn = _db_connect()
    cur = conn.cursor()

    if db_type in ["saving", "deposit"]:
        sql = """
        SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.intr_rate2, b.spcl_cnd
        FROM products_base b
        JOIN options_savings o ON b.fin_prdt_cd = o.fin_prdt_cd
        WHERE b.product_type = ?
          AND b.is_active = 1
        ORDER BY o.intr_rate2 DESC
        LIMIT ?
        """
        cur.execute(sql, (db_type, top_n))
        rows = cur.fetchall()
        conn.close()
        return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

    if db_type == "annuity":
        sql = """
        SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.avg_prft_rate, b.spcl_cnd
        FROM products_base b
        JOIN options_annuity o ON b.fin_prdt_cd = o.fin_prdt_cd
        WHERE b.product_type = ?
          AND b.is_active = 1
        ORDER BY o.avg_prft_rate DESC
        LIMIT ?
        """
        cur.execute(sql, (db_type, top_n))
        rows = cur.fetchall()
        conn.close()
        return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

    sql = """
    SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.lend_rate_min, b.spcl_cnd
    FROM products_base b
    JOIN options_loan o ON b.fin_prdt_cd = o.fin_prdt_cd
    WHERE b.product_type = ?
      AND b.is_active = 1
    ORDER BY o.lend_rate_min ASC
    LIMIT ?
    """
    cur.execute(sql, (db_type, top_n))
    rows = cur.fetchall()
    conn.close()
    return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]


def fetch_candidate_pool(product_type: str, k_rate: int = 250, k_spcl: int = 250, per_bank: int = 3) -> List[Dict[str, Any]]:
    """상위 N 하나로 끝내지 않고, 여러 기준의 합집합으로 후보 풀을 넓게 만든다."""
    db_type = _map_to_db_type(product_type)
    conn = _db_connect()
    cur = conn.cursor()

    # 1) 금리/최저금리 기준 후보
    rate_list = fetch_top_products(product_type, top_n=k_rate)

    # 2) 우대조건 문구가 '풍부한' 후보
    spcl_list: List[Dict[str, Any]] = []
    try:
        if db_type in ["saving", "deposit"]:
            sql = """
            SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.intr_rate2, b.spcl_cnd
            FROM products_base b
            JOIN options_savings o ON b.fin_prdt_cd = o.fin_prdt_cd
            WHERE b.product_type = ? AND b.is_active = 1
            ORDER BY LENGTH(COALESCE(b.spcl_cnd,'')) DESC, o.intr_rate2 DESC
            LIMIT ?
            """
            cur.execute(sql, (db_type, k_spcl))
            rows = cur.fetchall()
            spcl_list = [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

        elif db_type == "annuity":
            sql = """
            SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.avg_prft_rate, b.spcl_cnd
            FROM products_base b
            JOIN options_annuity o ON b.fin_prdt_cd = o.fin_prdt_cd
            WHERE b.product_type = ? AND b.is_active = 1
            ORDER BY LENGTH(COALESCE(b.spcl_cnd,'')) DESC, o.avg_prft_rate DESC
            LIMIT ?
            """
            cur.execute(sql, (db_type, k_spcl))
            rows = cur.fetchall()
            spcl_list = [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

        else:
            sql = """
            SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.lend_rate_min, b.spcl_cnd
            FROM products_base b
            JOIN options_loan o ON b.fin_prdt_cd = o.fin_prdt_cd
            WHERE b.product_type = ? AND b.is_active = 1
            ORDER BY LENGTH(COALESCE(b.spcl_cnd,'')) DESC, o.lend_rate_min ASC
            LIMIT ?
            """
            cur.execute(sql, (db_type, k_spcl))
            rows = cur.fetchall()
            spcl_list = [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]
    finally:
        conn.close()

    # 3) 은행 다양성 보정(금리 상위에서 은행별 per_bank개만 추려서 추가)
    per_bank_list: List[Dict[str, Any]] = []
    bank_count: Dict[str, int] = {}
    for p in rate_list:
        b = p.get("bank") or ""
        bank_count.setdefault(b, 0)
        if bank_count[b] >= per_bank:
            continue
        bank_count[b] += 1
        per_bank_list.append(p)

    combined = dedupe_products(rate_list + spcl_list + per_bank_list)
    return combined


# -----------------------------
# 3) DB 기반 조건 카탈로그
# -----------------------------
def extract_condition_keys(products: List[Dict[str, Any]], catalog: Dict[str, Dict[str, Any]]) -> List[str]:
    """후보 상품들의 spcl_cnd를 훑어서, '현재 후보군에 실제로 존재하는' 조건 키만 뽑음"""
    text = "\n".join([p.get("special_condition_raw", "") or "" for p in products])

    found: List[str] = []
    for key, meta in (catalog or {}).items():
        pats = meta.get("patterns") or []
        for pat in pats:
            if pat and pat in text:
                found.append(key)
                break

    uniq: List[str] = []
    for k in found:
        if k not in uniq:
            uniq.append(k)
    return uniq


# -----------------------------
# 4) 파서
# -----------------------------
FACT_PARSER_SYSTEM = """
너는 금융 상담 파서야.
입력 JSON:
{
  "product_type": "...",
  "last_question_key": "...",
  "user_message": "..."
}

출력 JSON:
{
  "slots": {
    "monthly_amount": 500000,
    "term_months": 12,
    "lump_sum": 20000000,
    "income_monthly": 3000000,
    "desired_amount": 50000000
  },
  "eligibility": {
    "some_key": "yes|no|unknown"
  },
  "meta": { "user_uncertain": true|false }
}

규칙:
- 숫자/기간이 실제로 없으면 slots에 절대 넣지 마.
- 숫자는 원 단위로 변환(300만원=3000000, 1억=100000000, 5천만=50000000)
- 기간은 6/12/24/36개월 또는 "1년/2년" 같은 표현이 있을 때만 term_months로 채워.
- last_question_key가 cond:xxx면, 사용자가 예/아니오로 답하면 eligibility.xxx를 채워.
- 사용자가 "모름/대충/잘 모르겠어"면 meta.user_uncertain=true
- 한국어만
"""


def parse_user_facts(product_type: str, last_key: Optional[str], user_message: str, history: List[Any]) -> Dict[str, Any]:
    payload = {
        "product_type": product_type,
        "last_question_key": last_key or "",
        "user_message": user_message,
    }
    resp = llm.invoke(
        [
            {"role": "system", "content": FACT_PARSER_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
    )
    data = _safe_json(getattr(resp, "content", "") or "") or {}
    slots = data.get("slots", {}) or {}
    elig = data.get("eligibility", {}) or {}
    meta = data.get("meta", {}) or {}
    return {"slots": slots, "eligibility": elig, "meta": meta}


# -----------------------------
# 5) 질문 선택(슬롯/조건)
# -----------------------------
REQUIRED_SLOTS = {
    "적금": ["monthly_amount", "term_months"],
    "예금": ["lump_sum", "term_months"],
    "연금저축": ["monthly_amount"],
    "주담대": ["desired_amount", "income_monthly"],
    "전세자금대출": ["desired_amount", "income_monthly"],
    "신용대출": ["desired_amount", "income_monthly"],
}

SLOT_QUESTIONS = {
    "monthly_amount": "매달 얼마 정도 넣을 계획이세요? (예: 30만원)",
    "lump_sum": "목돈이 얼마 정도 있으세요? (예: 1000만원)",
    "term_months": "기간은 어느 정도로 생각하세요? (예: 12개월/24개월)",
    "income_monthly": "월 소득(세후 기준 대략) 어느 정도세요? (예: 300만원)",
    "desired_amount": "필요한 대출 금액은 어느 정도세요? (예: 5000만원)",
}


def pick_one_slot_question(product_type: str, missing: List[str], state: Dict[str, Any]) -> Optional[Dict[str, str]]:
    counts: Dict[str, int] = state.setdefault("slot_ask_counts", {})
    asked: set = state["asked"]

    for s in missing:
        key = f"slot:{s}"
        if key in asked:
            continue
        if counts.get(s, 0) >= 2:
            continue
        asked.add(key)
        state["asked"] = asked
        counts[s] = counts.get(s, 0) + 1
        return {"key": key, "text": SLOT_QUESTIONS.get(s, "정보를 알려주세요"), "preface": "조금만 더 물어볼게요 🙂"}
    return None


def pick_one_condition_question(
    condition_keys: List[str],
    state: Dict[str, Any],
    catalog: Dict[str, Dict[str, Any]],
) -> Optional[Dict[str, str]]:
    asked: set = state["asked"]
    eligibility: Dict[str, str] = state["eligibility"]

    for ck in condition_keys:
        key = f"cond:{ck}"
        if key in asked:
            continue
        if ck in eligibility and eligibility.get(ck) in {"yes", "no"}:
            continue

        q = (catalog.get(ck, {}) or {}).get("question") or ""
        if not q:
            continue

        asked.add(key)
        state["asked"] = asked
        return {
            "key": key,
            "text": q,
            "preface": "좋아요. 우대금리(금리 추가)를 받을 수 있는지 이것도 한 번만 볼게요 🙂",
        }
    return None


# -----------------------------
# 6) 요약/스코어링/추천
# -----------------------------
def summarize_special_condition(raw: str, catalog: Dict[str, Dict[str, Any]]) -> str:
    r = (raw or "").strip()
    if not r:
        return "우대조건 정보 없음"

    picks: List[str] = []
    for key, meta in (catalog or {}).items():
        pats = meta.get("patterns") or []
        if any(p and (p in r) for p in pats):
            picks.append(key)

    if picks:
        short = ", ".join(picks[:2])
        if len(picks) > 2:
            short += " 외"
        return f"주요 우대조건 키워드: {short}"

    first = re.split(r"[\n\.]", r)[0].strip()
    if first:
        return first[:80] + ("…" if len(first) > 80 else "")
    return "우대조건 정보 있음"


def score_product(product_type: str, p: Dict[str, Any], eligibility: Dict[str, str], catalog: Dict[str, Dict[str, Any]]) -> float:
    try:
        rate = float(p.get("rate") or 0.0)
    except Exception:
        rate = 0.0

    base = rate if product_type not in {"전세자금대출", "신용대출", "주담대"} else -rate

    raw = p.get("special_condition_raw", "") or ""
    keys: List[str] = []
    for k, meta in (catalog or {}).items():
        pats = meta.get("patterns") or []
        for pat in pats:
            if pat and pat in raw:
                keys.append(k)
                break

    bonus = 0.0
    for k in keys:
        ans = (eligibility or {}).get(k)
        if ans == "yes":
            bonus += 0.15
        elif ans == "no":
            bonus -= 0.10

    if len(keys) >= 4:
        bonus -= 0.10

    return base + bonus


def choose_candidates(
    product_type: str,
    products: List[Dict[str, Any]],
    eligibility: Dict[str, str],
    catalog: Dict[str, Dict[str, Any]],
    top_k: int = 3,
) -> List[Dict[str, Any]]:
    scored = [(score_product(product_type, p, eligibility, catalog), p) for p in products]
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [p for _, p in scored]
    ranked = dedupe_products(ranked)
    return ranked[:top_k]


def candidates_to_text(cands: List[Dict[str, Any]]) -> str:
    lines = []
    for i, p in enumerate(cands, 1):
        lines.append(f"{i}. {p['bank']} - {p['name']} (기준: {p.get('rate','')})")
    return "\n".join(lines)


# -----------------------------
# 7) 오케스트레이션
# -----------------------------
def orchestrate_next_step(product_type: str, user_message: str, history: List[Any], state: Dict[str, Any]) -> Dict[str, Any]:
    asked: set = state.get("asked", set())
    if not isinstance(asked, set):
        asked = set(asked)
    state["asked"] = asked

    catalog = load_condition_catalog()

    last_key = state.get("last_question_key")
    last_text = state.get("last_question")

    # (A) 이해 못했을 때: 설명 + 질문 재제시
    if last_key and last_key.startswith("cond:") and user_is_confused(user_message):
        ck = last_key.split("cond:", 1)[1]
        explain = (catalog.get(ck, {}) or {}).get("explain")
        if explain:
            return {
                "stage": "ask",
                "question": {
                    "key": last_key,
                    "preface": f"{explain}\n괜찮으면 이것만 답해줘요 🙂",
                    "text": last_text
                }
            }

    # (B) 빠른 yes/no: 직전 cond 질문이면 eligibility 반영
    qyn = quick_yes_no(user_message)
    if qyn and last_key and last_key.startswith("cond:"):
        ck = last_key.split("cond:", 1)[1]
        state["eligibility"][ck] = qyn

    # (C) LLM 파서로 슬롯/조건 업데이트
    parsed = parse_user_facts(product_type, last_key, user_message, history)
    for k, v in (parsed.get("slots", {}) or {}).items():
        state["slots"][k] = v
    for k, v in (parsed.get("eligibility", {}) or {}).items():
        if v in {"yes", "no", "unknown"}:
            state["eligibility"][k] = v

    # (D) 후보 풀(합집합) + 조건키 추출
    products = fetch_candidate_pool(product_type, k_rate=250, k_spcl=250, per_bank=3)
    condition_keys = extract_condition_keys(products, catalog)

    # (E) 필수 슬롯 체크
    required = REQUIRED_SLOTS.get(product_type, [])
    missing = [s for s in required if s not in state["slots"]]

    if missing:
        slot_q = pick_one_slot_question(product_type, missing, state)
        all_gave_up = all(state.setdefault("slot_ask_counts", {}).get(s, 0) >= 2 for s in missing)

        if slot_q and not all_gave_up:
            cands = choose_candidates(product_type, products, state["eligibility"], catalog, top_k=3)
            return {
                "stage": "draft",
                "preface": "오케이! 일단 일반 조건 기준으로 후보를 먼저 골라봤어요. (확정은 아니고 ‘초안’이에요)",
                "candidates_text": candidates_to_text(cands),
                "draft_json": json.dumps(cands, ensure_ascii=False),
                "next_question": slot_q
            }

        cond_q = pick_one_condition_question(condition_keys, state, catalog)
        if cond_q:
            cands = choose_candidates(product_type, products, state["eligibility"], catalog, top_k=3)
            return {
                "stage": "draft",
                "preface": "정보가 딱 맞게 안 잡혀도 괜찮아요. 일단 후보를 잡아뒀고, 이것만 답하면 더 좋아져요 🙂",
                "candidates_text": candidates_to_text(cands),
                "draft_json": json.dumps(cands, ensure_ascii=False),
                "next_question": cond_q
            }

    # (F) 조건 질문 1개
    cond_q = pick_one_condition_question(condition_keys, state, catalog)
    if cond_q:
        return {"stage": "ask", "question": cond_q}

    # (G) FINAL
    cands = choose_candidates(product_type, products, state["eligibility"], catalog, top_k=3)

    if product_type == "적금":
        reason = "정기적으로 모으는 목적이라 적금이 자연스러워요. (DB 기준 금리/조건을 같이 봤어요)"
    elif product_type == "예금":
        reason = "목돈을 한 번에 맡기는 목적이라 예금이 자연스러워요. (DB 기준 금리/조건을 같이 봤어요)"
    else:
        reason = "목적에 맞는 유형으로 DB 기준(금리/조건)에서 골랐어요."

    notes = []
    if product_type in {"적금", "예금", "연금저축"}:
        notes.append("급여이체/카드실적/비대면 같은 조건에 따라 금리가 더 올라갈 수 있어요.")
    else:
        notes.append("우대조건(소득증빙/거래실적 등)에 따라 실제 금리/한도가 달라질 수 있어요.")

    final = {
        "product_type": product_type,
        "reason": reason,
        "products": [
            {
                "bank": p["bank"],
                "name": p["name"],
                "rate": str(p.get("rate", "")),
                "special_condition_summary": summarize_special_condition(p.get("special_condition_raw", ""), catalog),
                "special_condition_raw": p.get("special_condition_raw", ""),
                "why_recommended": "현재 답변 기준으로 조건을 맞출 가능성이 높고, 금리/최저금리 기준도 상위권이라서요."
            }
            for p in cands
        ],
        "notes": " ".join(notes).strip(),
        "collected": {
            "slots": state["slots"],
            "eligibility": state["eligibility"]
        }
    }

    return {"stage": "final", "final_json": json.dumps(final, ensure_ascii=False)}


# -----------------------------
# 8) 상품 리스트 API용
# -----------------------------
def fetch_products(product_type: str, page: int = 1, page_size: int = 20, sort: str = "rate_desc", q: str = "") -> Dict[str, Any]:
    db_type = _map_to_db_type(product_type)

    conn = _db_connect()
    cur = conn.cursor()

    where = "WHERE b.product_type=? AND b.is_active=1"
    params: List[Any] = [db_type]

    if q:
        where += " AND (b.kor_co_nm LIKE ? OR b.fin_prdt_nm LIKE ?)"
        like = f"%{q}%"
        params.extend([like, like])

    order = "ORDER BY rate DESC"
    if db_type in {"주담대", "전세자금대출", "신용대출"}:
        order = "ORDER BY rate ASC"

    if sort == "rate_asc":
        order = "ORDER BY rate ASC"
    elif sort == "rate_desc":
        order = "ORDER BY rate DESC"

    if db_type in {"saving", "deposit"}:
        sql = f"""
        SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, MAX(o.intr_rate2) AS rate, b.spcl_cnd
        FROM products_base b
        JOIN options_savings o ON b.fin_prdt_cd = o.fin_prdt_cd
        {where}
        GROUP BY b.fin_prdt_cd
        {order}
        LIMIT ? OFFSET ?
        """
    elif db_type == "annuity":
        sql = f"""
        SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, MAX(o.avg_prft_rate) AS rate, b.spcl_cnd
        FROM products_base b
        JOIN options_annuity o ON b.fin_prdt_cd = o.fin_prdt_cd
        {where}
        GROUP BY b.fin_prdt_cd
        {order}
        LIMIT ? OFFSET ?
        """
    else:
        sql = f"""
        SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, MIN(o.lend_rate_min) AS rate, b.spcl_cnd
        FROM products_base b
        JOIN options_loan o ON b.fin_prdt_cd = o.fin_prdt_cd
        {where}
        GROUP BY b.fin_prdt_cd
        {order}
        LIMIT ? OFFSET ?
        """

    offset = (page - 1) * page_size
    params2 = params + [page_size, offset]
    cur.execute(sql, params2)
    rows = cur.fetchall()

    cur.execute(f"SELECT COUNT(*) FROM products_base b {where}", params)
    total = cur.fetchone()[0]
    conn.close()

    items = [
        {
            "fin_prdt_cd": r[0],
            "bank": r[1],
            "name": r[2],
            "rate": r[3],
            "special_condition_raw": r[4] or "",
        }
        for r in rows
    ]

    return {"items": items, "total": total, "page": page, "page_size": page_size}
