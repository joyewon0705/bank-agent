# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Any
import traceback

from langchain_core.messages import HumanMessage, AIMessage
from agent import guide_decide, orchestrate_next_step, fetch_products

# Groq rate limit 예외 (환경/버전에 따라 import 경로가 다를 수 있어서 안전하게 처리)
try:
    from groq import RateLimitError  # groq SDK
except Exception:  # pragma: no cover
    RateLimitError = None  # fallback

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

chat_memory: Dict[str, List[Any]] = {}
session_state: Dict[str, Dict[str, Any]] = {}


class ChatRequest(BaseModel):
    message: str
    session_id: str = "default_user"


@app.get("/")
def read_root():
    return {"status": "Running"}


@app.get("/product-types")
def product_types():
    return {
        "product_types": ["적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"]
    }


@app.get("/products")
def list_products(
    product_type: str,
    page: int = 1,
    page_size: int = 20,
    sort: str = "rate_desc",
    q: str = "",
):
    if product_type not in {"적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"}:
        raise HTTPException(status_code=400, detail="Invalid product_type")
    page_size = min(max(page_size, 1), 50)
    return fetch_products(product_type, page=page, page_size=page_size, sort=sort, q=q)


@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        user_msg = (request.message or "").strip()
        history = chat_memory.setdefault(request.session_id, [])

        state = session_state.setdefault(
            request.session_id,
            {
                "product_type": None,
                "slots": {},
                "eligibility": {},
                "asked": set(),
                "last_question": None,        # 직전 질문 텍스트(1개)
                "last_question_key": None,    # 직전 질문 키(1개)
                "slot_ask_counts": {},
                "draft_shown": False,
            },
        )

        # 1) 유형 확정
        if not state["product_type"]:
            guide = guide_decide(user_msg, history)
            if guide["action"] == "ask":
                reply = guide["question"]
                history.append(HumanMessage(content=user_msg))
                history.append(AIMessage(content=reply))
                return {"reply": reply}
            state["product_type"] = guide["product_type"]

        # 2) 다음 스텝(질문 1개 / 초안 / 최종)
        out = orchestrate_next_step(
            product_type=state["product_type"],
            user_message=user_msg,
            history=history,
            state=state,
        )

        stage = out.get("stage")

        if stage == "ask":
            q = out.get("question", {})
            state["last_question_key"] = q.get("key")
            state["last_question"] = q.get("text")
            preface = q.get("preface") or "좋아요. 딱 한 가지만 확인할게요 🙂"
            reply = f"{preface}\n{q.get('text')}"

        elif stage == "draft":
            state["draft_shown"] = True

            preface = out.get("preface") or "일단 조건이 덜 까다로운 후보를 먼저 골라봤어요. (확정은 아니고 ‘초안’이에요)"
            candidates_text = out.get("candidates_text") or ""
            next_q = out.get("next_question")  # {"key","text","preface"} or None

            if next_q:
                state["last_question_key"] = next_q.get("key")
                state["last_question"] = next_q.get("text")
                qpref = next_q.get("preface") or "이 후보들 중에서 더 딱 맞추려면 이것만 알려주세요 🙂"
                reply = f"{preface}\n\n{candidates_text}\n\n{qpref}\n{next_q.get('text')}"
            else:
                reply = f"{preface}\n\n{candidates_text}"

        else:  # final
            reply = out.get("final_json", "{}")

        history.append(HumanMessage(content=user_msg))
        history.append(AIMessage(content=reply))
        return {"reply": reply}

    except Exception as e:
        # ✅ 1번 반영: Groq RateLimitError는 429로 내려서 "서버 오류"처럼 보이지 않게
        if RateLimitError is not None and isinstance(e, RateLimitError):
            raise HTTPException(
                status_code=429,
                detail="지금 AI 사용량이 잠시 초과되어 추천이 지연되고 있어요. 5분 뒤 다시 시도해 주세요.",
            )

        print("❌ Server Error:", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")
