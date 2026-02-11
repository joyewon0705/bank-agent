import os
import json
import re
import sqlite3
import httpx
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langchain_groq import ChatGroq
from pathlib import Path

load_dotenv()

DB_PATH = os.getenv("BANK_DB_PATH")
if not DB_PATH:
    DB_PATH = str(Path(__file__).resolve().parent / "bank_data.db")


def _db_connect():
    return sqlite3.connect(DB_PATH)


# -----------------------------
# LLM
# -----------------------------
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
    if t in {"예", "네", "응", "ㅇㅇ", "가능", "할게", "할수있어", "할 수 있어", "가능해", "웅"}:
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


def is_asking_for_more(user_message: str) -> bool:
    t = _norm(user_message)
    triggers = ["다른", "다른거", "다른 거", "더", "더 보여", "또", "추가", "다시 추천", "다른 추천"]
    return any(x in t for x in triggers)


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
# Catalog (DB)
# -----------------------------
QUESTION_BANNED_WORDS = ["미션", "완수", "보상", "리워드", "쿠폰", "지급", "제공되나요", "성공하면", "달성하면"]


def _is_bad_catalog_question(q: str) -> bool:
    q = (q or "").strip()
    if not q:
        return True
    for w in QUESTION_BANNED_WORDS:
        if w in q:
            return True
    # 너무 수동적/의미없는 표현 방지
    if "제공" in q and ("가능" not in q and "할 수" not in q and "동의" not in q and "해당" not in q):
        return True
    return False


def load_condition_catalog() -> Dict[str, Dict[str, Any]]:
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
        if _is_bad_catalog_question(q):
            continue
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


# -----------------------------
# Decide: "모을래/빌릴래" + 타입
# -----------------------------
DECIDE_KIND_SYSTEM = """
너는 금융 상담 챗봇이야.
사용자 메시지로 '모으기'인지 '빌리기'인지 판단해.

출력 JSON:
{"kind":"save|borrow|unknown","reason":"짧게"}

규칙:
- 모으다/저축/적금/예금/목돈/모아 -> save
- 대출/빌리/주담대/전세/신용 -> borrow
- 애매하면 unknown
"""


def decide_kind(user_message: str) -> Dict[str, str]:
    resp = llm.invoke(
        [
            {"role": "system", "content": DECIDE_KIND_SYSTEM},
            {"role": "user", "content": user_message},
        ]
    )
    data = _safe_json(getattr(resp, "content", "") or "") or {}
    kind = data.get("kind") or "unknown"
    if kind not in {"save", "borrow", "unknown"}:
        kind = "unknown"
    return {"kind": kind, "reason": data.get("reason", "")}


GUIDE_DECIDER_SYSTEM = """
너는 금융 상담 챗봇의 '상품 유형'을 고르는 에이전트야.
사용자 메시지로 아래 중 하나를 선택해.

가능한 출력:
- "적금"
- "예금"
- "연금저축"
- "주담대"
- "전세자금대출"
- "신용대출"

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
        return {"product_type": "적금", "reason": "저축 목적이 있어 보여서 적금으로 시작할게요."}
    return {
        "product_type": data.get("product_type", "적금"),
        "reason": data.get("reason", ""),
    }


# -----------------------------
# DB Queries
# -----------------------------
def _map_to_db_type(product_type: str) -> str:
    pt = (product_type or "").strip()
    if pt in {"적금", "saving"}:
        return "saving"
    if pt in {"예금", "deposit"}:
        return "deposit"
    if pt in {"연금저축", "annuity"}:
        return "annuity"
    return pt


def fetch_candidate_pool(product_type: str, k_rate: int = 300, k_spcl: int = 300, per_bank: int = 3) -> List[Dict[str, Any]]:
    db_type = _map_to_db_type(product_type)
    conn = _db_connect()
    cur = conn.cursor()

    def _top_rate():
        if db_type in {"saving", "deposit"}:
            cur.execute("""
                SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.intr_rate2, b.spcl_cnd
                FROM products_base b
                JOIN options_savings o ON b.fin_prdt_cd=o.fin_prdt_cd
                WHERE b.product_type=? AND b.is_active=1
                ORDER BY o.intr_rate2 DESC
                LIMIT ?
            """, (db_type, k_rate))
            rows = cur.fetchall()
            return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

        if db_type == "annuity":
            cur.execute("""
                SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.avg_prft_rate, b.spcl_cnd
                FROM products_base b
                JOIN options_annuity o ON b.fin_prdt_cd=o.fin_prdt_cd
                WHERE b.product_type=? AND b.is_active=1
                ORDER BY o.avg_prft_rate DESC
                LIMIT ?
            """, (db_type, k_rate))
            rows = cur.fetchall()
            return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

        # loans: lower is better
        cur.execute("""
            SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.lend_rate_min, b.spcl_cnd
            FROM products_base b
            JOIN options_loan o ON b.fin_prdt_cd=o.fin_prdt_cd
            WHERE b.product_type=? AND b.is_active=1
            ORDER BY o.lend_rate_min ASC
            LIMIT ?
        """, (db_type, k_rate))
        rows = cur.fetchall()
        return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

    def _top_spcl():
        if db_type in {"saving", "deposit"}:
            cur.execute("""
                SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.intr_rate2, b.spcl_cnd
                FROM products_base b
                JOIN options_savings o ON b.fin_prdt_cd=o.fin_prdt_cd
                WHERE b.product_type=? AND b.is_active=1
                ORDER BY LENGTH(COALESCE(b.spcl_cnd,'')) DESC, o.intr_rate2 DESC
                LIMIT ?
            """, (db_type, k_spcl))
            rows = cur.fetchall()
            return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

        if db_type == "annuity":
            cur.execute("""
                SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.avg_prft_rate, b.spcl_cnd
                FROM products_base b
                JOIN options_annuity o ON b.fin_prdt_cd=o.fin_prdt_cd
                WHERE b.product_type=? AND b.is_active=1
                ORDER BY LENGTH(COALESCE(b.spcl_cnd,'')) DESC, o.avg_prft_rate DESC
                LIMIT ?
            """, (db_type, k_spcl))
            rows = cur.fetchall()
            return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

        cur.execute("""
            SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.lend_rate_min, b.spcl_cnd
            FROM products_base b
            JOIN options_loan o ON b.fin_prdt_cd=o.fin_prdt_cd
            WHERE b.product_type=? AND b.is_active=1
            ORDER BY LENGTH(COALESCE(b.spcl_cnd,'')) DESC, o.lend_rate_min ASC
            LIMIT ?
        """, (db_type, k_spcl))
        rows = cur.fetchall()
        return [{"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": (r[4] or "")} for r in rows]

    try:
        rate_list = _top_rate()
        spcl_list = _top_spcl()
    finally:
        conn.close()

    # bank diversity
    per_bank_list: List[Dict[str, Any]] = []
    bank_count: Dict[str, int] = {}
    for p in rate_list:
        b = p.get("bank") or ""
        bank_count.setdefault(b, 0)
        if bank_count[b] >= per_bank:
            continue
        bank_count[b] += 1
        per_bank_list.append(p)

    return dedupe_products(rate_list + spcl_list + per_bank_list)


def extract_condition_keys(products: List[Dict[str, Any]], catalog: Dict[str, Dict[str, Any]]) -> List[str]:
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
# Parse facts (slots/eligibility)
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
- 기간:
  - "12개월/24개월" 같은 표현은 그대로 term_months
  - "N년"은 N*12로 변환 (예: 5년=60개월)
- last_question_key가 cond:xxx면, 사용자가 예/아니오/모름으로 답하면 eligibility.xxx를 채워.
- 사용자가 "모름/대충/잘 모르겠어"면 meta.user_uncertain=true
- 한국어만
"""


def parse_user_facts(product_type: str, last_key: Optional[str], user_message: str, history: List[Any]) -> Dict[str, Any]:
    payload = {"product_type": product_type, "last_question_key": last_key or "", "user_message": user_message}
    resp = llm.invoke(
        [
            {"role": "system", "content": FACT_PARSER_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
    )
    data = _safe_json(getattr(resp, "content", "") or "") or {}
    return {
        "slots": data.get("slots", {}) or {},
        "eligibility": data.get("eligibility", {}) or {},
        "meta": data.get("meta", {}) or {},
    }


# -----------------------------
# Question selection
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
    "term_months": "기간은 어느 정도로 생각하세요? (예: 12개월/24개월 또는 2년)",
    "income_monthly": "월 소득(세후 기준 대략) 어느 정도세요? (예: 300만원)",
    "desired_amount": "필요한 대출 금액은 어느 정도세요? (예: 5000만원)",
}


def pick_one_slot_question(product_type: str, missing: List[str], state: Dict[str, Any]) -> Optional[Dict[str, str]]:
    asked: set = state["asked"]
    counts: Dict[str, int] = state.setdefault("slot_ask_counts", {})
    for s in missing:
        key = f"slot:{s}"
        if key in asked:
            continue
        if counts.get(s, 0) >= 2:
            continue
        asked.add(key)
        counts[s] = counts.get(s, 0) + 1
        # 프리페이스 반복 줄이기
        prefaces = ["알겠어요 🙂", "좋아요 🙂", "오케이!"]
        pf = prefaces[min(state.get("preface_idx", 0), len(prefaces)-1)]
        state["preface_idx"] = state.get("preface_idx", 0) + 1
        return {"key": key, "text": SLOT_QUESTIONS.get(s, "정보를 알려주세요"), "preface": pf}
    return None


def pick_one_condition_question(condition_keys: List[str], state: Dict[str, Any], catalog: Dict[str, Dict[str, Any]]) -> Optional[Dict[str, str]]:
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
        # 프리페이스 “매크로” 느낌 줄이기: 상황에 따라 다르게
        meta_unknown = state.get("last_meta_uncertain", False)
        if meta_unknown:
            preface = "괜찮아요. 우대조건은 선택사항이니까, 가능하면만 알려줘요 🙂"
        else:
            preface = "우대금리 받을 수 있는지 이것만 확인할게요 🙂"
        return {"key": key, "text": q, "preface": preface}
    return None


# -----------------------------
# Evidence extraction (더 구체적인 근거)
# -----------------------------
def extract_matched_evidence(raw: str, key: str, catalog: Dict[str, Dict[str, Any]], max_lines: int = 2) -> List[str]:
    """
    spcl_cnd 원문에서 해당 조건 키(패턴)와 맞는 줄/문장만 발췌
    """
    raw = (raw or "").strip()
    if not raw:
        return []

    pats = (catalog.get(key, {}) or {}).get("patterns") or []
    lines = re.split(r"[\n•\-\u2022]+", raw)
    hits = []
    for ln in lines:
        ln2 = ln.strip()
        if not ln2:
            continue
        if any(p and p in ln2 for p in pats):
            hits.append(ln2[:120] + ("…" if len(ln2) > 120 else ""))
        if len(hits) >= max_lines:
            break

    # fallback: 문장 단위
    if not hits:
        sents = re.split(r"[\.。!?]\s*", raw)
        for s in sents:
            s2 = s.strip()
            if not s2:
                continue
            if any(p and p in s2 for p in pats):
                hits.append(s2[:120] + ("…" if len(s2) > 120 else ""))
            if len(hits) >= max_lines:
                break
    return hits


def product_condition_keys(p: Dict[str, Any], catalog: Dict[str, Dict[str, Any]]) -> List[str]:
    raw = p.get("special_condition_raw", "") or ""
    keys = []
    for k, meta in (catalog or {}).items():
        pats = meta.get("patterns") or []
        if any(pat and pat in raw for pat in pats):
            keys.append(k)
    return keys


def score_product(product_type: str, p: Dict[str, Any], eligibility: Dict[str, str], catalog: Dict[str, Dict[str, Any]]) -> Tuple[float, Dict[str, Any]]:
    """
    점수 + 근거(구체화용) 같이 반환
    - 저축/연금: rate 높을수록 +
    - 대출: rate 낮을수록 +
    - YES로 답한 조건 매칭 시 가산, NO면 감점
    """
    try:
        rate = float(p.get("rate") or 0.0)
    except Exception:
        rate = 0.0

    is_loan = product_type in {"전세자금대출", "신용대출", "주담대"}
    base = (-rate) if is_loan else rate

    keys = product_condition_keys(p, catalog)
    bonus = 0.0
    matched_yes = []
    matched_no = []
    for k in keys:
        ans = (eligibility or {}).get(k)
        if ans == "yes":
            bonus += 0.18
            matched_yes.append(k)
        elif ans == "no":
            bonus -= 0.12
            matched_no.append(k)

    # 조건이 너무 복잡한 상품은 살짝 불리
    if len(keys) >= 5:
        bonus -= 0.12

    score = base + bonus
    return score, {
        "rate": rate,
        "base": base,
        "bonus": bonus,
        "matched_yes": matched_yes,
        "matched_no": matched_no,
        "all_keys": keys,
    }


def choose_ranked(product_type: str, products: List[Dict[str, Any]], eligibility: Dict[str, str], catalog: Dict[str, Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    scored = []
    for p in products:
        s, why = score_product(product_type, p, eligibility, catalog)
        scored.append((s, p, why))
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = []
    seen = set()
    for _, p, why in scored:
        pid = p.get("fin_prdt_cd") or (p.get("bank"), p.get("name"))
        if pid in seen:
            continue
        seen.add(pid)
        ranked.append((p, why))
    return ranked



def _condition_label(key: str, catalog: Dict[str, Dict[str, Any]]) -> str:
    """조건 key를 사용자 친화 라벨로 변환"""
    meta = (catalog or {}).get(key) or {}
    q = (meta.get("question") or "").strip()
    if not q:
        return key
    q = re.sub(r"^[\-\*\s•]+", "", q)
    q = re.sub(r"\([^\)]*\)", "", q).strip()
    q = re.sub(r"[?？]$", "", q).strip()
    # '가능/할 수/하실 수/동의' 등의 앞부분을 라벨로 사용
    parts = re.split(r"(가능|할 수|하실 수|하실|동의|가입|이체|실적)", q, maxsplit=1)
    base = (parts[0] if parts else q).strip()
    return (base or q)[:18]


def _format_evidence(raw: str, keys: List[str], catalog: Dict[str, Dict[str, Any]], max_lines_total: int = 2) -> List[str]:
    """spcl_cnd 원문에서 매칭 근거 문장을 깔끔하게 추출(최대 N줄)"""
    out: List[str] = []
    for k in keys:
        for ev in extract_matched_evidence(raw, k, catalog, max_lines=2):
            if ev and ev not in out:
                out.append(ev)
            if len(out) >= max_lines_total:
                return out
    return out


def build_final_json(product_type: str, ranked: List[Tuple[Dict[str, Any], Dict[str, Any]]], catalog: Dict[str, Dict[str, Any]], state: Dict[str, Any], offset: int = 0, top_k: int = 3) -> str:
    picked = ranked[offset:offset + top_k]

    products_out = []
    for p, why in picked:
        rate = why.get("rate", p.get("rate", ""))
        matched_yes: List[str] = why.get("matched_yes", []) or []
        matched_no: List[str] = why.get("matched_no", []) or []
        bonus = float(why.get("bonus", 0.0) or 0.0)
        base = float(why.get("base", 0.0) or 0.0)
        score = round(base + bonus, 3)

        yes_labels = [_condition_label(k, catalog) for k in matched_yes[:3]]
        no_labels = [_condition_label(k, catalog) for k in matched_no[:2]]

        raw = p.get("special_condition_raw", "") or ""
        evidences = _format_evidence(raw, matched_yes[:3], catalog, max_lines_total=2)

        # 사용자 친화 템플릿
        summary_parts: List[str] = []
        if product_type in {"적금", "예금", "연금저축"}:
            summary_parts.append("금리가 상위권인 후보예요.")
        else:
            summary_parts.append("금리가 낮은 편인 후보예요.")

        if yes_labels:
            summary_parts.append(f"가능하다고 답한 우대조건({', '.join(yes_labels)})을 적용하면 더 유리할 수 있어요.")
        if no_labels:
            summary_parts.append(f"다만 불가능한 조건({', '.join(no_labels)})은 제외하고 판단했어요.")

        metrics: List[str] = []
        if rate != "":
            metrics.append(f"기준 금리: {rate}")
        if matched_yes:
            metrics.append(f"충족 가능 우대조건: {len(matched_yes)}개")
        if matched_no:
            metrics.append(f"불가/미적용 조건: {len(matched_no)}개")
        metrics.append(f"내부 점수: {score}")

        lines: List[str] = []
        lines.append(" ".join(summary_parts).strip())
        lines.append("")
        lines.append(" / ".join(metrics).strip())

        if evidences:
            lines.append("")
            lines.append("근거:")
            for ev in evidences:
                lines.append(f"- {ev}")

        why_text = "\n".join([ln for ln in lines if ln is not None]).strip()

        products_out.append(
            {
                "bank": p["bank"],
                "name": p["name"],
                "rate": str(p.get("rate", "")),
                "special_condition_summary": " / ".join(evidences[:2]) if evidences else "우대조건은 상품별로 상이해요.",
                "special_condition_raw": p.get("special_condition_raw", ""),
                "why_recommended": why_text,
            }
        )

    reason = ""
    if product_type == "적금":
        reason = "매달 모으는 형태라 적금으로 보는 게 자연스러워요."
    elif product_type == "예금":
        reason = "목돈을 한 번에 맡기는 형태라 예금으로 보는 게 자연스러워요."
    elif product_type == "연금저축":
        reason = "장기 목적(노후/절세)으로 연금저축이 자연스러워요."
    else:
        reason = "요청 목적에 맞는 대출 유형으로 골랐어요."

    notes = []
    if offset > 0:
        notes.append("요청하신 ‘다른 후보’로 다음 상품들을 보여드렸어요.")
    notes.append("원하면 조건(급여이체/카드실적/신규 등)을 더 확인해서 추천을 더 좁힐 수 있어요.")

    final = {
        "product_type": product_type,
        "reason": reason,
        "products": products_out,
        "notes": " ".join(notes).strip(),
        "collected": {
            "slots": state["slots"],
            "eligibility": state["eligibility"],
        },
    }
    return json.dumps(final, ensure_ascii=False)


# -----------------------------
# Orchestrator
# -----------------------------
def orchestrate_next_step(product_type: str, user_message: str, history: List[Any], state: Dict[str, Any]) -> Dict[str, Any]:
    asked = state.get("asked", set())
    if not isinstance(asked, set):
        asked = set(asked)
    state["asked"] = asked

    catalog = load_condition_catalog()

    last_key = state.get("last_question_key")
    last_text = state.get("last_question")

    # 직전 cond 질문 이해 못함 → 설명 후 같은 질문
    if last_key and last_key.startswith("cond:") and user_is_confused(user_message):
        ck = last_key.split("cond:", 1)[1]
        explain = (catalog.get(ck, {}) or {}).get("explain")
        if explain:
            return {
                "stage": "ask",
                "question": {"key": last_key, "preface": f"{explain}\n그래서, 가능 여부만 알려줘요 🙂", "text": last_text},
            }

    # 빠른 yes/no 단답 처리(직전 cond면 바로 반영)
    qyn = quick_yes_no(user_message)
    if qyn and last_key and last_key.startswith("cond:"):
        ck = last_key.split("cond:", 1)[1]
        state["eligibility"][ck] = qyn

    # 파서로 슬롯/조건 업데이트
    parsed = parse_user_facts(product_type, last_key, user_message, history)
    state["last_meta_uncertain"] = bool((parsed.get("meta") or {}).get("user_uncertain", False))

    for k, v in (parsed.get("slots", {}) or {}).items():
        state["slots"][k] = v
    for k, v in (parsed.get("eligibility", {}) or {}).items():
        if v in {"yes", "no", "unknown"}:
            state["eligibility"][k] = v

    # 후보풀/조건키
    products = fetch_candidate_pool(product_type)
    condition_keys = extract_condition_keys(products, catalog)

    # 추천 이후 "다른 거" 요청 처리
    if state.get("last_final_ranked") and is_asking_for_more(user_message):
        ranked = state["last_final_ranked"]
        offset = int(state.get("final_offset", 0)) + 3
        if offset >= len(ranked):
            offset = 0  # 한 바퀴 돌게
        state["final_offset"] = offset
        final_json = build_final_json(product_type, ranked, catalog, state, offset=offset, top_k=3)
        return {"stage": "final", "final_json": final_json}

    # 필수 슬롯 질문 우선
    required = REQUIRED_SLOTS.get(product_type, [])
    missing = [s for s in required if s not in state["slots"]]

    if missing:
        slot_q = pick_one_slot_question(product_type, missing, state)
        if slot_q:
            return {"stage": "ask", "question": slot_q}

    # 조건 질문(너무 매크로 느낌 안 나게, 많아도 6개 정도까지만)
    asked_cond_count = sum(1 for a in asked if str(a).startswith("cond:"))
    if asked_cond_count < 6:
        cond_q = pick_one_condition_question(condition_keys, state, catalog)
        if cond_q:
            return {"stage": "ask", "question": cond_q}

    # FINAL 추천
    ranked = choose_ranked(product_type, products, state["eligibility"], catalog)
    state["last_final_ranked"] = ranked
    state["final_offset"] = 0

    final_json = build_final_json(product_type, ranked, catalog, state, offset=0, top_k=3)
    return {"stage": "final", "final_json": final_json}


# -----------------------------
# Product list API (기존 프론트 유지용)
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
    cur.execute(sql, params + [page_size, offset])
    rows = cur.fetchall()

    cur.execute(f"SELECT COUNT(*) FROM products_base b {where}", params)
    total = cur.fetchone()[0]
    conn.close()

    items = [
        {"fin_prdt_cd": r[0], "bank": r[1], "name": r[2], "rate": r[3], "special_condition_raw": r[4] or ""}
        for r in rows
    ]
    return {"items": items, "total": total, "page": page, "page_size": page_size}
