import os
import json
import sqlite3
import re
import httpx
from typing import Optional, List, Dict, Any

from dotenv import load_dotenv

from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_tool_calling_agent

load_dotenv()

# Groq / SSL(사내망 등) 대응
custom_client = httpx.Client(verify=False)

# LLM
llm = ChatGroq(
    temperature=0,
    model_name="llama-3.3-70b-versatile",
    groq_api_key=os.getenv("GROQ_API_KEY"),
    http_client=custom_client,
)

# ---------------------------
# 1) GUIDE (상품 유형 확정/질문 생성)
# ---------------------------

GUIDE_SYSTEM = """
당신은 금융 상담 흐름을 제어하는 컨트롤러입니다.
당신의 목표는 '상품 유형(product_type)'을 하나로 확정하거나,
확정이 안 되면 딱 1~2개의 질문만 해서 확정 가능한 정보를 얻는 것입니다.

[DB에 있는 상품 유형]
- 적금, 예금, 연금저축, 주담대, 전세자금대출, 신용대출

[유형 판단 규칙 - 매우 중요]
1) 사용자가 "매달/월마다/달에/월 00"처럼 '정기적으로 넣을 금액'을 말하면 → 무조건 '적금'
2) 사용자가 "목돈이 있어/한 번에 넣을 돈"처럼 '일시금'을 말하면 → '예금'
3) 노후/세액공제/연금 목적의 장기 저축이면 → '연금저축'
4) 집 구매/주택담보/주담대 키워드면 → '주담대'
5) 전세/전월세/보증금 키워드면 → '전세자금대출'
6) 신용/마이너스/비상금/신용점수/무담보면 → '신용대출'

[질문 규칙]
- 유형이 확정되지 않았을 때만 질문하세요.
- 질문은 1~2개만, 쉬운 한국어로.
- 한자/중국어 표현 금지.

[출력 형식 - 반드시 JSON 하나만]
아래 형식으로만 출력하세요.

{
  "action": "ask" 또는 "proceed",
  "product_type": "적금|예금|연금저축|주담대|전세자금대출|신용대출|null",
  "question": "사용자에게 할 질문(ask일 때만), proceed면 빈 문자열"
}
"""

def _safe_json_loads(text: str) -> Optional[dict]:
    """LLM이 JSON 외 문자를 섞어도 최대한 복구해서 파싱"""
    if not text:
        return None
    # JSON 블록만 대충 추출
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return None
    try:
        return json.loads(m.group(0))
    except Exception:
        return None

def guide_decide(user_message: str, chat_history: List[Any]) -> Dict[str, Any]:
    """
    Guide LLM을 호출해서:
    - action: ask/proceed
    - product_type: 확정된 상품 유형
    - question: ask 시 사용자에게 물을 질문
    """
    resp = llm.invoke([
        ("system", GUIDE_SYSTEM),
        *chat_history,
        ("human", user_message),
    ])

    data = _safe_json_loads(resp.content) or {}

    action = data.get("action")
    product_type = data.get("product_type")
    question = data.get("question")

    # 방어 로직
    allowed_types = {"적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출", None, "null"}

    if action not in {"ask", "proceed"}:
        action = "ask"
    if product_type not in allowed_types:
        product_type = None
    if product_type == "null":
        product_type = None
    if not isinstance(question, str):
        question = ""

    if action == "ask" and not question.strip():
        # 최소 질문 fallback
        question = "돈을 모으는 목적이 무엇인가요? (예: 그냥 저축 / 목돈 마련 / 전세 / 집 구매 등)"

    if action == "proceed" and not product_type:
        # proceed인데 유형이 없으면 ask로 강등
        action = "ask"
        question = "원하시는 게 매달 일정 금액을 모으는 건가요, 아니면 목돈을 한 번에 맡기는 건가요?"

    return {"action": action, "product_type": product_type, "question": question}


# ---------------------------
# 2) TOOLS (DB 조회)
# ---------------------------

def _map_to_db_type(product_type: str) -> str:
    """
    DB의 product_type 값이 영문/다른 키일 수 있어서 매핑.
    필요하면 여기만 네 DB에 맞게 수정하면 됨.
    """
    mapping = {
        "적금": "saving",
        "예금": "deposit",
        "연금저축": "pension",
        "주담대": "mortgage",
        "전세자금대출": "jeonse_loan",
        "신용대출": "credit_loan",
    }
    return mapping.get(product_type, product_type)

@tool
def search_products(product_type: str, keyword: str = None, top_n: int = 5) -> str:
    """
    DB에서 상품을 검색합니다.
    - 예적금: 금리 높은 순 (intr_rate2 DESC)
    - 대출: 최저금리 낮은 순 (lend_rate_min ASC)
    결과는 JSON 문자열로 반환합니다(에이전트가 파싱하기 쉽게).
    """
    db_type = _map_to_db_type(product_type)

    conn = sqlite3.connect("bank_data.db")
    cursor = conn.cursor()

    # 예적금
    if db_type in ["saving", "deposit", "적금", "예금"]:
        sql = """
        SELECT b.kor_co_nm, b.fin_prdt_nm, o.intr_rate2, b.spcl_cnd
        FROM products_base b
        JOIN options_savings o ON b.fin_prdt_cd = o.fin_prdt_cd
        WHERE b.product_type = ?
        """
        params = [db_type]

        if keyword:
            sql += " AND (b.spcl_cnd LIKE ? OR b.fin_prdt_nm LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        sql += " ORDER BY o.intr_rate2 DESC LIMIT ?"
        params.append(top_n)

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()

        products = []
        for bank, name, rate, spcl in rows:
            products.append({
                "bank": bank,
                "name": name,
                "rate": rate,
                "special_condition": spcl or "",
                "type": product_type
            })

        return json.dumps(products, ensure_ascii=False)

    # 대출
    else:
        sql = """
        SELECT b.kor_co_nm, b.fin_prdt_nm, o.lend_rate_min, b.spcl_cnd
        FROM products_base b
        JOIN options_loan o ON b.fin_prdt_cd = o.fin_prdt_cd
        WHERE b.product_type = ?
        """
        params = [db_type]

        if keyword:
            sql += " AND (b.spcl_cnd LIKE ? OR b.fin_prdt_nm LIKE ?)"
            params.extend([f"%{keyword}%", f"%{keyword}%"])

        sql += " ORDER BY o.lend_rate_min ASC LIMIT ?"
        params.append(top_n)

        cursor.execute(sql, params)
        rows = cursor.fetchall()
        conn.close()

        products = []
        for bank, name, rate, spcl in rows:
            products.append({
                "bank": bank,
                "name": name,
                "rate": rate,
                "special_condition": spcl or "",
                "type": product_type
            })

        return json.dumps(products, ensure_ascii=False)


@tool
def calculate_saving_interest(monthly_amount: int, annual_rate: float, months: int = 12) -> str:
    """
    아주 단순한 적금 세후 이자 추정(대략치).
    - 월 납입 적금: 단리 근사
    - 세금 15.4% 적용 (이자소득세 + 지방소득세)
    """
    # 적금: 월 납입이므로 평균 잔액 근사: monthly_amount * (months+1)/2
    gross_interest = monthly_amount * ((months + 1) / 2) * (annual_rate / 100) * (months / 12)
    net_interest = gross_interest * (1 - 0.154)
    return f"{months}개월 기준 예상 세후 이자는 약 {int(net_interest):,}원(대략치)입니다."


# ---------------------------
# 3) AGENT (DB 기반 추천)
# ---------------------------

AGENT_SYSTEM = """
당신은 금융 상품 추천 AI입니다.
반드시 DB 데이터(도구 결과)에만 근거해서 추천해야 합니다.
추측하거나 DB에 없는 정보를 만들면 안 됩니다.

[입력]
- product_type: 사용자가 원하는 상품 유형(이미 확정됨)
- input: 사용자의 추가 설명

[행동 절차]
1) 먼저 search_products(product_type)을 실행해 대표 상품을 가져오세요.
2) 결과의 special_condition(우대조건)에서 실제로 등장하는 키워드를 보고,
   사용자에게 확인할 조건을 2~3개만 골라 Yes/No 질문으로 물으세요.
   - 사용자가 이미 답을 준 조건은 다시 묻지 마세요.
3) 사용자가 "잘 모르겠어요"라고 하면 그 조건은 제외하세요.
4) 조건을 반영해 1~3개 상품만 최종 추천하세요.
5) 적금(월 납입) 유형이면 calculate_saving_interest를 이용해 '대략' 혜택도 함께 제시할 수 있습니다.
   (단, 월 납입액이 입력에서 확인될 때만)

[말투/언어]
- 자연스러운 한국어만 사용하세요. 한자/중국어 표현 금지.
- 금융 초보가 이해할 쉬운 말로 설명하세요.

[최종 출력 형식 - 매우 중요]
최종 응답은 반드시 아래 JSON 하나만 출력하세요(설명 문장 추가 금지).

{{
  "product_type": "{product_type}",
  "reason": "",
  "products": [
    {{
      "bank": "",
      "name": "",
      "rate": "",
      "special_condition": "",
      "why_recommended": ""
    }}
  ],
  "notes": ""
}}
"""

prompt = ChatPromptTemplate.from_messages([
    ("system", AGENT_SYSTEM),
    MessagesPlaceholder(variable_name="chat_history"),
    ("human", "사용자 입력: {input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

tools = [search_products, calculate_saving_interest]

agent = create_tool_calling_agent(llm, tools, prompt)

agent_executor = AgentExecutor(
    agent=agent,
    tools=tools,
    verbose=True,
)
