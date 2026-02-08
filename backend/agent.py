import os
import json
import re
import sqlite3
import httpx
from typing import Any, Dict, List, Optional, Tuple

from dotenv import load_dotenv
from langchain_groq import ChatGroq

load_dotenv()

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
    if not text:
        return None
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def _norm(s: str) -> str:
    return (s or "").strip()

YES_TOKENS = {"응", "웅", "네", "예", "ㅇㅇ", "가능", "오케이", "좋아", "괜찮아", "할 수 있어", "할수있어"}
NO_TOKENS  = {"아니", "아니요", "ㄴㄴ", "불가", "못해", "안돼", "어려워"}

def quick_yes_no(msg: str) -> Optional[str]:
    m = _norm(msg)
    if len(m) <= 8:
        if m in YES_TOKENS:
            return "yes"
        if m in NO_TOKENS:
            return "no"
    return None

def user_is_confused(msg: str) -> bool:
    m = _norm(msg)
    # “월실적?” “무슨말?” 같은 반문/혼란 패턴
    patterns = ["무슨", "뭔", "뭐야", "??", "?", "이해", "헷갈", "월실적", "실적이", "카드실적"]
    return any(p in m for p in patterns) and len(m) <= 40

def dedupe_products(products: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    seen = set()
    out = []
    for p in products:
        key = (p.get("bank"), p.get("name"))
        if key in seen:
            continue
        seen.add(key)
        out.append(p)
    return out

# -----------------------------
# 1) GUIDE
# -----------------------------
GUIDE_SYSTEM = """
너는 금융 상담 흐름을 제어하는 컨트롤러야.
목표는 사용자가 원하는 "상품 유형"을 확정하는 거야.

[DB에 있는 상품 유형]
- 적금, 예금, 연금저축, 주담대, 전세자금대출, 신용대출

[판단 규칙]
1) "매달/월마다/달에/정기적으로" → 적금
2) "목돈/한 번에/일시금" → 예금
3) 노후/세액공제/연금 → 연금저축
4) 전세/보증금/전월세 → 전세자금대출
5) 집 구매/주택담보 → 주담대
6) 비상금/마이너스/신용 → 신용대출

[말투]
- 자연스러운 한국어, 공손한 존댓말, 공문체 금지, 한자/중국어 표현 금지.

[출력 형식 - JSON 하나]
{
  "action": "ask" 또는 "proceed",
  "product_type": "적금|예금|연금저축|주담대|전세자금대출|신용대출|null",
  "question": "ask일 때만 질문"
}
"""

def guide_decide(user_message: str, history: List[Any]) -> Dict[str, Any]:
    resp = llm.invoke([
        ("system", GUIDE_SYSTEM),
        *history,
        ("human", user_message),
    ])
    data = _safe_json(resp.content) or {}
    action = data.get("action", "ask")
    ptype = data.get("product_type", None)
    q = data.get("question", "")

    allowed = {"적금","예금","연금저축","주담대","전세자금대출","신용대출",None,"null"}
    if action not in {"ask","proceed"}:
        action = "ask"
    if ptype not in allowed:
        ptype = None
    if ptype == "null":
        ptype = None

    if action == "ask" and not _norm(q):
        q = "어떤 걸 도와드릴까요? 저축(돈 모으기) / 대출 중에 가까운 쪽이 있어요?"
    if action == "proceed" and not ptype:
        action = "ask"
        q = "저축(돈 모으기)인지, 대출인지 먼저 알려주실래요?"
    return {"action": action, "product_type": ptype, "question": q}


# -----------------------------
# 2) DB
# -----------------------------
def _map_to_db_type(product_type: str) -> str:
    mapping = {
        "적금": "saving",
        "예금": "deposit",
        "연금저축": "annuity",
        "주담대": "mortgage",
        "전세자금대출": "rent",
        "신용대출": "credit",
    }
    return mapping.get(product_type, product_type)

def fetch_top_products(product_type: str, top_n: int = 30) -> List[Dict[str, Any]]:
    db_type = _map_to_db_type(product_type)
    conn = sqlite3.connect("bank_data.db")
    cur = conn.cursor()

    if db_type in ["saving","deposit","적금","예금"]:
        sql = """
        SELECT b.kor_co_nm, b.fin_prdt_nm, o.intr_rate2, b.spcl_cnd
        FROM products_base b
        JOIN options_savings o ON b.fin_prdt_cd = o.fin_prdt_cd
        WHERE b.product_type = ?
        ORDER BY o.intr_rate2 DESC
        LIMIT ?
        """
        cur.execute(sql, (db_type, top_n))
        rows = cur.fetchall()
        conn.close()
        return [{"bank":r[0],"name":r[1],"rate":r[2],"special_condition_raw":(r[3] or "")} for r in rows]

    sql = """
    SELECT b.kor_co_nm, b.fin_prdt_nm, o.lend_rate_min, b.spcl_cnd
    FROM products_base b
    JOIN options_loan o ON b.fin_prdt_cd = o.fin_prdt_cd
    WHERE b.product_type = ?
    ORDER BY o.lend_rate_min ASC
    LIMIT ?
    """
    cur.execute(sql, (db_type, top_n))
    rows = cur.fetchall()
    conn.close()
    return [{"bank":r[0],"name":r[1],"rate":r[2],"special_condition_raw":(r[3] or "")} for r in rows]


# -----------------------------
# 3) DB 기반 조건 키워드
# -----------------------------
CONDITION_KEYWORDS = [
    ("salary_transfer", ["급여이체", "급여", "급여입금"]),
    ("auto_transfer", ["자동이체", "정기이체"]),
    ("card_spend", ["카드실적", "카드 이용", "체크카드", "신용카드"]),
    ("primary_bank", ["주거래", "주거래은행"]),
    ("non_face", ["비대면", "모바일", "앱", "온라인"]),
    ("youth", ["청년", "만 34", "만34", "사회초년생", "1934"]),
    ("marketing", ["마케팅", "동의"]),
]

QUESTION_BY_KEY = {
    "salary_transfer": "급여이체(월급 들어오는 계좌로 설정) 가능하세요? (예/아니오/모름)",
    "auto_transfer": "매달 자동이체로 납입 설정 가능하세요? (예/아니오/모름)",
    "card_spend": "카드 실적(한 달에 카드로 일정 금액 쓰기) 맞출 수 있나요? (예/아니오/모름)",
    "primary_bank": "주거래로(이체/자동이체를 한 은행으로 모으기) 설정 가능하세요? (예/아니오/모름)",
    "non_face": "비대면(앱으로 가입)도 괜찮으세요? (예/아니오/모름)",
    "youth": "청년 우대(대략 만 19~34세)에 해당하세요? (예/아니오/모름)",
    "marketing": "마케팅 수신 동의 같은 항목에 동의 가능하세요? (예/아니오/모름)",
}

EXPLAIN_BY_KEY = {
    "card_spend": "카드 실적은 ‘한 달에 카드로 일정 금액 이상 쓰면’ 우대금리를 주는 조건이에요.",
}

def extract_condition_keys(products: List[Dict[str, Any]]) -> List[str]:
    text = "\n".join([p.get("special_condition_raw", "") for p in products])
    found = []
    for key, pats in CONDITION_KEYWORDS:
        for pat in pats:
            if pat and pat in text:
                found.append(key)
                break
    uniq = []
    for k in found:
        if k not in uniq:
            uniq.append(k)
    return uniq


# -----------------------------
# 4) 파서: 사용자 메시지에서 숫자/기간/해당여부
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
    "salary_transfer": "yes|no|unknown",
    "auto_transfer": "yes|no|unknown",
    "card_spend": "yes|no|unknown",
    "primary_bank": "yes|no|unknown",
    "non_face": "yes|no|unknown",
    "youth": "yes|no|unknown",
    "marketing": "yes|no|unknown"
  },
  "meta": { "user_uncertain": true|false }
}

규칙:
- 숫자/기간이 실제로 없으면 slots에 절대 넣지 마.
- 숫자는 원 단위로 변환(300만원=3000000, 1억=100000000, 5천만=50000000)
- 기간은 6/12/24/36개월 또는 "1년/2년" 같은 표현이 있을 때만 term_months로 채워.
- last_question_key가 cond:xxx면, 사용자가 예/아니오로 답하면 eligibility.xxx를 채워.
- 사용자가 "모름/대충/잘 모르겠어"면 meta.user_uncertain=true
- 한국어만, 공문체/한자/중국어 표현 금지
"""

def parse_user_facts(product_type: str, last_question_key: Optional[str], user_message: str, history: List[Any]) -> Dict[str, Any]:
    payload = {
        "product_type": product_type,
        "last_question_key": last_question_key or "",
        "user_message": user_message,
    }
    resp = llm.invoke([
        ("system", FACT_PARSER_SYSTEM),
        *history,
        ("human", json.dumps(payload, ensure_ascii=False))
    ])
    data = _safe_json(resp.content) or {}
    return {
        "slots": data.get("slots", {}) or {},
        "eligibility": data.get("eligibility", {}) or {},
        "meta": data.get("meta", {}) or {},
    }


# -----------------------------
# 5) 필수 슬롯(바로 확정 방지)
# -----------------------------
REQUIRED_SLOTS = {
    "적금": ["monthly_amount", "term_months"],
    "예금": ["lump_sum", "term_months"],
    "연금저축": ["monthly_amount"],
    "전세자금대출": ["income_monthly", "desired_amount"],
    "신용대출": ["income_monthly", "desired_amount"],
    "주담대": ["income_monthly", "desired_amount"],
}

SLOT_QUESTIONS = {
    "monthly_amount": [
        "월에 대략 얼마 정도 넣고 싶으세요? (예: 20/30/50만원, 모르면 ‘대충’도 가능)",
        "월 납입액을 대략 범위로라도 알려주실래요? (예: 20~30 / 50 정도)"
    ],
    "term_months": [
        "기간은 어느 정도로 생각하세요? (예: 6/12/24/36개월, 모르면 ‘대충 1년’도 좋아요)",
        "대략 몇 년 정도로 모으고 싶으세요? (예: 1년/2년/3년)"
    ],
    "lump_sum": [
        "한 번에 맡길 목돈이 대략 얼마 정도예요? (예: 1천만/3천만/5천만)",
    ],
    "income_monthly": [
        "월 소득이 대략 얼마 정도세요? (예: 300만원 / 모르면 범위도 OK)",
    ],
    "desired_amount": [
        "필요한 금액(희망 금액)이 대략 얼마예요? (예: 5천만/1억, 모르면 ‘모름’ 가능)",
    ],
}

def pick_one_slot_question(product_type: str, missing: List[str], state: Dict[str, Any]) -> Optional[Dict[str, str]]:
    asked: set = state["asked"]
    slot_ask_counts: Dict[str, int] = state["slot_ask_counts"]

    for slot in missing:
        key = f"slot:{slot}"
        cnt = slot_ask_counts.get(slot, 0)

        # 같은 슬롯은 최대 2번만 묻고 포기(정보 안주는 고객 대비)
        if cnt >= 2:
            continue

        qlist = SLOT_QUESTIONS.get(slot, [])
        if not qlist:
            continue

        text = qlist[min(cnt, len(qlist) - 1)]
        slot_ask_counts[slot] = cnt + 1
        state["slot_ask_counts"] = slot_ask_counts
        state["asked"].add(key)

        return {
            "key": key,
            "text": text,
            "preface": "좋아요. 정확히 추천하려면 이것만 먼저 알려주세요 🙂"
        }

    return None


def pick_one_condition_question(condition_keys: List[str], state: Dict[str, Any]) -> Optional[Dict[str, str]]:
    asked: set = state["asked"]
    eligibility: Dict[str, str] = state["eligibility"]

    for ck in condition_keys:
        key = f"cond:{ck}"
        if key in asked:
            continue
        if ck in eligibility and eligibility.get(ck) in {"yes","no"}:
            continue

        asked.add(key)
        state["asked"] = asked
        return {
            "key": key,
            "text": QUESTION_BY_KEY[ck],
            "preface": "좋아요. 우대금리(금리 추가)를 받을 수 있는지 이것도 한 번만 볼게요 🙂"
        }
    return None


# -----------------------------
# 6) 조건 요약
# -----------------------------
def summarize_special_condition(raw: str) -> str:
    r = (raw or "").strip()
    if not r:
        return "우대조건 정보 없음"

    picks = []
    for key, patterns in CONDITION_KEYWORDS:
        for pat in patterns:
            if pat and pat in r:
                if key == "salary_transfer": picks.append("급여이체")
                elif key == "auto_transfer": picks.append("자동이체")
                elif key == "card_spend": picks.append("카드실적")
                elif key == "primary_bank": picks.append("주거래")
                elif key == "non_face": picks.append("비대면")
                elif key == "youth": picks.append("청년우대")
                elif key == "marketing": picks.append("마케팅동의")
                break

    if not picks:
        return (r[:60] + "...") if len(r) > 60 else r
    # 중복 제거
    out = []
    for x in picks:
        if x not in out:
            out.append(x)
    return " / ".join(out)


# -----------------------------
# 7) 스코어링/추천
# -----------------------------
def score_product(product_type: str, p: Dict[str, Any], eligibility: Dict[str, str]) -> float:
    try:
        rate = float(p.get("rate") or 0.0)
    except Exception:
        rate = 0.0

    base = rate if product_type not in {"전세자금대출","신용대출","주담대"} else -rate

    raw = p.get("special_condition_raw", "") or ""
    keys = []
    for k, pats in CONDITION_KEYWORDS:
        for pat in pats:
            if pat and pat in raw:
                keys.append(k)
                break

    bonus = 0.0
    for k in keys:
        ans = eligibility.get(k)
        if ans == "yes":
            bonus += 0.15
        elif ans == "no":
            bonus -= 0.10

    # 조건이 너무 복잡한 상품은(키가 많을수록) 기본 추천에서는 살짝 불리하게
    if len(keys) >= 4:
        bonus -= 0.10

    return base + bonus


def choose_candidates(product_type: str, products: List[Dict[str, Any]], eligibility: Dict[str, str], top_k: int = 3) -> List[Dict[str, Any]]:
    scored = [(score_product(product_type, p, eligibility), p) for p in products]
    scored.sort(key=lambda x: x[0], reverse=True)
    ranked = [p for _, p in scored]
    ranked = dedupe_products(ranked)
    return ranked[:top_k]


def candidates_to_text(cands: List[Dict[str, Any]]) -> str:
    lines = []
    for i, p in enumerate(cands):
        lines.append(
            f"[후보 {i+1}] {p['bank']} / {p['name']} (금리·최저금리: {p.get('rate','')})\n"
            f" - 우대조건 요약: {summarize_special_condition(p.get('special_condition_raw',''))}"
        )
    return "\n\n".join(lines)


# -----------------------------
# 8) Orchestrator (질문 1개씩 / 초안→확정)
# -----------------------------
def orchestrate_next_step(product_type: str, user_message: str, history: List[Any], state: Dict[str, Any]) -> Dict[str, Any]:
    asked: set = state.get("asked", set())
    if not isinstance(asked, set):
        asked = set(asked)
    state["asked"] = asked

    # (A) 사용자가 직전 질문을 이해 못했을 때: 용어 설명 + 질문 재제시
    last_key = state.get("last_question_key")
    last_text = state.get("last_question")

    if last_key and last_key.startswith("cond:") and user_is_confused(user_message):
        ck = last_key.split("cond:", 1)[1]
        explain = EXPLAIN_BY_KEY.get(ck)
        if explain:
            # 같은 질문을 "설명 1문장 + 질문"으로 다시
            return {
                "stage": "ask",
                "question": {
                    "key": last_key,
                    "preface": f"{explain}\n괜찮으면 이것만 답해줘요 🙂",
                    "text": last_text
                }
            }

    # (B) 빠른 yes/no 단답 처리: 직전 cond 질문이면 eligibility에 바로 반영
    qyn = quick_yes_no(user_message)
    if qyn and last_key and last_key.startswith("cond:"):
        ck = last_key.split("cond:", 1)[1]
        state["eligibility"][ck] = qyn

    # (C) LLM 파서로 슬롯/조건 업데이트
    parsed = parse_user_facts(product_type, last_key, user_message, history)
    for k, v in (parsed.get("slots", {}) or {}).items():
        state["slots"][k] = v
    for k, v in (parsed.get("eligibility", {}) or {}).items():
        if v in {"yes","no","unknown"}:
            state["eligibility"][k] = v
    meta = parsed.get("meta", {}) or {}
    user_uncertain = bool(meta.get("user_uncertain", False))

    # (D) DB 조회 + 조건 키워드
    products = fetch_top_products(product_type, top_n=30)
    condition_keys = extract_condition_keys(products)

    # (E) 필수 슬롯 체크
    required = REQUIRED_SLOTS.get(product_type, [])
    missing = [s for s in required if s not in state["slots"]]

    # 적금/예금처럼 “기본 정보가 없으면 확정 추천 금지”
    # 대신 ‘초안 후보(draft)’로 보여주고 질문 1개 더
    if missing:
        # 먼저 슬롯 질문 1개
        slot_q = pick_one_slot_question(product_type, missing, state)

        # 만약 슬롯 질문도 2번씩 다 했는데도 못 받으면(정보 안주는 고객),
        # 그땐 그냥 초안→final로 진행(조건 적은 후보 위주)
        all_gave_up = all(state["slot_ask_counts"].get(s, 0) >= 2 for s in missing)
        if slot_q and not all_gave_up:
            # 초안은 한 번만 보여주자(너무 자주 보여주면 피로)
            cands = choose_candidates(product_type, products, state["eligibility"], top_k=3)
            return {
                "stage": "draft",
                "preface": "오케이! 일단 일반 조건 기준으로 후보를 먼저 골라봤어요. (확정은 아니고 ‘초안’이에요)",
                "candidates_text": candidates_to_text(cands),
                "draft_json": json.dumps(cands, ensure_ascii=False),
                "next_question": slot_q
            }

        # 슬롯 질문을 더 못 하거나 포기 상황이면 조건 질문 1개만 더 유도 후 final로 감
        cond_q = pick_one_condition_question(condition_keys, state)
        if cond_q:
            cands = choose_candidates(product_type, products, state["eligibility"], top_k=3)
            return {
                "stage": "draft",
                "preface": "정보가 딱 맞게 안 잡혀도 괜찮아요. 일단 후보를 잡아뒀고, 이것만 답하면 더 좋아져요 🙂",
                "candidates_text": candidates_to_text(cands),
                "draft_json": json.dumps(cands, ensure_ascii=False),
                "next_question": cond_q
            }

        # 여기까지 오면 그냥 final로
        # (missing 있어도 추천은 하되 notes에 “정보 주면 더 정확”을 강조)
        pass

    # (F) 필수 슬롯이 어느 정도 채워졌으면 조건 질문 1개로 ‘생각 못한 조건’ 유도 (너무 많이 안 묻고)
    cond_q = pick_one_condition_question(condition_keys, state)
    if cond_q:
        return {"stage": "ask", "question": cond_q}

    # (G) FINAL
    cands = choose_candidates(product_type, products, state["eligibility"], top_k=3)

    reason = ""
    if product_type == "적금":
        reason = "정기적으로 모으는 목적이라 적금이 자연스러워요. (DB 기준 금리/조건을 같이 봤어요)"
    elif product_type == "예금":
        reason = "목돈을 한 번에 맡기는 목적이라 예금이 자연스러워요. (DB 기준 금리/조건을 같이 봤어요)"
    else:
        reason = "목적에 맞는 유형으로 DB 기준(금리/조건)에서 골랐어요."

    notes = []
    if product_type == "적금":
        if "monthly_amount" not in state["slots"] or "term_months" not in state["slots"]:
            notes.append("납입액/기간을 알려주시면 예상 이자까지 계산해서 더 정확히 비교해드릴게요.")
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
                "special_condition_summary": summarize_special_condition(p.get("special_condition_raw", "")),
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

def _map_to_db_type_for_list(product_type: str) -> str:
    # sync_data.py에 저장되는 키 기준
    mapping = {
        "적금": "saving",
        "예금": "deposit",
        "연금저축": "annuity", 
        "주담대": "mortgage",
        "전세자금대출": "rent",
        "신용대출": "credit",
    }
    return mapping.get(product_type, product_type)

def fetch_products(
    product_type: str,
    page: int = 1,
    page_size: int = 20,
    sort: str = "rate_desc",   # 예적금/연금: rate_desc, 대출: rate_asc 추천
    q: str = "",
):
    db_type = _map_to_db_type_for_list(product_type)
    offset = max(page - 1, 0) * page_size
    q_like = f"%{q.strip()}%" if q else "%"

    conn = sqlite3.connect("bank_data.db")
    cur = conn.cursor()

    # 1) 적금/예금
    if db_type in ("saving", "deposit"):
        order = "o.intr_rate2 DESC" if sort == "rate_desc" else "o.intr_rate2 ASC"

        cur.execute(
            """
            SELECT COUNT(*)
            FROM products_base b
            JOIN options_savings o ON b.fin_prdt_cd = o.fin_prdt_cd
            WHERE b.product_type = ?
              AND (b.kor_co_nm LIKE ? OR b.fin_prdt_nm LIKE ?)
            """,
            (db_type, q_like, q_like),
        )
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.intr_rate2, b.join_way, b.spcl_cnd
            FROM products_base b
            JOIN options_savings o ON b.fin_prdt_cd = o.fin_prdt_cd
            WHERE b.product_type = ?
              AND (b.kor_co_nm LIKE ? OR b.fin_prdt_nm LIKE ?)
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            (db_type, q_like, q_like, page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": r[0],
                    "bank": r[1],
                    "name": r[2],
                    "rate": r[3],
                    "join_way": r[4] or "",
                    "spcl_cnd": r[5] or "",
                }
                for r in rows
            ],
        }

    # 2) 연금저축
    if db_type == "annuity":
        order = "o.avg_prft_rate DESC" if sort == "rate_desc" else "o.avg_prft_rate ASC"

        cur.execute(
            """
            SELECT COUNT(*)
            FROM products_base b
            JOIN options_annuity o ON b.fin_prdt_cd = o.fin_prdt_cd
            WHERE b.product_type = ?
              AND (b.kor_co_nm LIKE ? OR b.fin_prdt_nm LIKE ?)
            """,
            (db_type, q_like, q_like),
        )
        total = cur.fetchone()[0]

        cur.execute(
            f"""
            SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.avg_prft_rate, b.join_way, b.spcl_cnd
            FROM products_base b
            JOIN options_annuity o ON b.fin_prdt_cd = o.fin_prdt_cd
            WHERE b.product_type = ?
              AND (b.kor_co_nm LIKE ? OR b.fin_prdt_nm LIKE ?)
            ORDER BY {order}
            LIMIT ? OFFSET ?
            """,
            (db_type, q_like, q_like, page_size, offset),
        )
        rows = cur.fetchall()
        conn.close()

        return {
            "total": total,
            "page": page,
            "page_size": page_size,
            "items": [
                {
                    "id": r[0],
                    "bank": r[1],
                    "name": r[2],
                    "rate": r[3],  # 화면 라벨은 "평균수익률" 추천
                    "join_way": r[4] or "",
                    "spcl_cnd": r[5] or "",
                }
                for r in rows
            ],
        }

    # 3) 대출(주담대/전세/신용)
    order = "o.lend_rate_min ASC" if sort != "rate_desc" else "o.lend_rate_min DESC"

    cur.execute(
        """
        SELECT COUNT(*)
        FROM products_base b
        JOIN options_loan o ON b.fin_prdt_cd = o.fin_prdt_cd
        WHERE b.product_type = ?
          AND (b.kor_co_nm LIKE ? OR b.fin_prdt_nm LIKE ?)
        """,
        (db_type, q_like, q_like),
    )
    total = cur.fetchone()[0]

    cur.execute(
        f"""
        SELECT b.fin_prdt_cd, b.kor_co_nm, b.fin_prdt_nm, o.lend_rate_min, b.join_way, b.spcl_cnd
        FROM products_base b
        JOIN options_loan o ON b.fin_prdt_cd = o.fin_prdt_cd
        WHERE b.product_type = ?
          AND (b.kor_co_nm LIKE ? OR b.fin_prdt_nm LIKE ?)
        ORDER BY {order}
        LIMIT ? OFFSET ?
        """,
        (db_type, q_like, q_like, page_size, offset),
    )
    rows = cur.fetchall()
    conn.close()

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "items": [
            {
                "id": r[0],
                "bank": r[1],
                "name": r[2],
                "rate": r[3],  # 최저금리
                "join_way": r[4] or "",
                "spcl_cnd": r[5] or "",
            }
            for r in rows
        ],
    }
