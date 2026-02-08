from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List
import traceback

from langchain_core.messages import HumanMessage, AIMessage

# agent.py에서 가져옴
from agent import guide_decide, agent_executor

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# 세션별 채팅 메모리
chat_memory: Dict[str, List] = {}

class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_user"

@app.get("/")
def read_root():
    return {"status": "Running"}

@app.post("/chat")
async def chat(request: ChatRequest):
    """
    흐름:
    1) Guide가 사용자 입력을 보고 '질문할지 / 검색할지' + '상품유형' 판단 (JSON)
    2) proceed면 Agent에게 product_type을 강제로 넘기고 DB 기반 추천
    3) ask면 Guide가 만든 질문을 그대로 사용자에게 전달
    """
    try:
        history = chat_memory.setdefault(request.session_id, [])

        # 1) Guide 판단
        guide = guide_decide(request.message, history)

        if guide["action"] == "ask":
            reply = guide["question"]

        elif guide["action"] == "proceed":
            product_type = guide["product_type"]  # 예: "적금", "예금" 등

            # 2) Agent 실행: product_type을 "강제"로 넘겨서 유형 튐 방지
            result = agent_executor.invoke({
                "input": request.message,
                "product_type": product_type,
                "chat_history": history,
            })
            reply = result["output"]

        else:
            # 혹시 모를 방어
            reply = "상담을 위해 몇 가지만 더 여쭤볼게요. 어떤 목적으로 돈을 모으고 싶으신가요?"

        # 3) 메모리 업데이트
        history.append(HumanMessage(content=request.message))
        history.append(AIMessage(content=reply))

        return {"reply": reply}

    except Exception:
        print("❌ Server Error:", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
