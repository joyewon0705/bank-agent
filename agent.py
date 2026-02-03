import os
import ssl
import sqlite3
import httpx
from dotenv import load_dotenv
from langchain_groq import ChatGroq
from langchain_core.tools import tool
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain.agents import AgentExecutor, create_tool_calling_agent

# TODO
# - 프롬프트 개선
# - 테스트 필요

load_dotenv()

# 0. SSL 인증서 검증 무시 설정
ssl._create_default_https_context = ssl._create_unverified_context

# 1. LLM 설정
custom_client = httpx.Client(verify=False) # SSL 우회 클라이언트
llm = ChatGroq(
    temperature=0, 
    model_name="llama-3.3-70b-versatile", 
    groq_api_key=os.getenv("GROQ_API_KEY"),
    http_client=custom_client
)

# 2. 도구(Tool) 정의: DB 검색
@tool
def search_savings_db(query: str):
    """
    사용자의 질문과 관련된 적금 상품 정보를 DB에서 검색합니다.
    은행명, 상품명, 혹은 '우대조건' 키워드를 바탕으로 데이터를 가져옵니다.
    """
    conn = sqlite3.connect("bank_data.db")
    cursor = conn.cursor()
    
    # 키워드 매칭 검색
    sql = "SELECT * FROM savings WHERE bank_name LIKE ? OR product_name LIKE ? OR special_condition LIKE ?"
    search_term = f"%{query}%"
    cursor.execute(sql, (search_term, search_term, search_term))
    
    rows = cursor.fetchall()
    conn.close()
    
    if not rows:
        return "관련 상품을 찾지 못했습니다."
    
    # 에이전트가 읽기 편하게 문자열로 변환
    results = []
    for r in rows:
        results.append(f"은행: {r[1]}, 상품명: {r[2]}, 우대조건: {r[3]}, 금리유형: {r[4]}, 기본금리: {r[5]}%, 최고금리: {r[6]}%")
    
    return "\n".join(results)

# 3. 도구(Tool) 정의: 이자 계산기
@tool
def calculate_interest_benefit(monthly_amount: int, base_rate: float, special_rate: float, term_months: int = 12):
    """
    월 납입금, 기본금리, 우대금리를 받아 세후 이자를 정확히 계산합니다.
    """
    total_rate = base_rate + special_rate
    # 단리 적금 이자 공식: 월부금 * {n*(n+1)/2} * (연금리/12)
    raw_interest = monthly_amount * (term_months * (term_months + 1) / 2) * (total_rate / 100 / 12)
    tax = raw_interest * 0.154 # 이자소득세 15.4%
    net_interest = raw_interest - tax
    
    return {
        "총납입원금": monthly_amount * term_months,
        "최종금리": f"{total_rate:.2f}%",
        "세후이자": int(net_interest)
    }

# 4. 에이전트 프롬프트 (금융 전문가 페르소나)
prompt = ChatPromptTemplate.from_messages([
    ("system", """당신은 사회초년생을 위한 금융 탐정 에이전트입니다.
    사용자의 상황(나이, 주거래, 행동 특성 등)을 듣고 가장 유리한 적금을 '수치'로 제안하세요.

    [작업 프로세스]
    1. 사용자의 질문에서 가입 금액, 주거래 은행, 특이사항(헌혈, 앱 설치 등)을 파악하세요.
    2. 'search_savings_db'로 관련 상품을 찾으세요.
    3. 가져온 상품들의 '우대조건' 텍스트를 분석하여, 사용자가 실제로 받을 수 있는 우대금리를 추론하세요.
    4. 'calculate_interest_benefit'을 사용하여 사용자가 얻을 실제 '이자 수익'을 계산하세요.
    5. 비교 결과와 함께 "이 상품을 고르면 얼마를 더 법니다"라고 결론을 내리세요.
    """),
    MessagesPlaceholder(variable_name="chat_history", optional=True),
    ("human", "{input}"),
    MessagesPlaceholder(variable_name="agent_scratchpad"),
])

# 5. 에이전트 조립
tools = [search_savings_db, calculate_interest_benefit]
agent = create_tool_calling_agent(llm, tools, prompt)
agent_executor = AgentExecutor(agent=agent, tools=tools, verbose=True)

# 6. 테스트 코드
if __name__ == "__main__":
    print("🚀 에이전트 준비 완료!")
    test_input = "나 이번에 취업한 27살인데, 우리은행이 주거래야. 월 50만원씩 12개월 적금 들려는데 어디가 제일 좋아? 헌혈도 자주 해!"
    response = agent_executor.invoke({"input": test_input})
    print("\n\n=== 에이전트 제안 ===")
    print(response["output"])