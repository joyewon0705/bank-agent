from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Any
import traceback
import asyncio
import datetime

from langchain_core.messages import HumanMessage, AIMessage

from agent import (
    decide_kind,
    guide_decide,
    orchestrate_next_step,
    fetch_products,
)

from scripts.sync_data import run_sync

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
    return {"product_types": ["적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"]}


@app.get("/products")
def list_products(
    product_type: str,
    page: int = 1,
    page_size: int = 20,
    sort: str = "rate_desc",
    q: str = "",
):
    if product_type not in ["적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"]:
        raise HTTPException(status_code=400, detail="Invalid product type")
    return fetch_products(product_type, page, page_size, sort, q)



def _product_type_ack(product_type: str) -> str:
    # 첫 1회만: 사용자가 이해하기 쉬운 톤으로 타입을 자연스럽게 확인
    pt = (product_type or "").strip()
    if pt == "적금":
        return "말씀하신 상황이면 **적금** 쪽이 잘 맞을 것 같아요. 몇 가지만 확인해볼게요!"
    if pt == "예금":
        return "지금 목적이면 **예금** 쪽이 더 잘 맞을 것 같아요. 몇 가지만 확인해볼게요!"
    if pt == "연금저축":
        return "장기/절세 목적이라면 **연금저축** 쪽이 좋아 보여요. 몇 가지만 확인해볼게요!"
    if pt == "주담대":
        return "집 마련 목적이라면 **주담대** 쪽을 먼저 보는 게 좋아 보여요. 몇 가지만 확인해볼게요!"
    if pt == "전세자금대출":
        return "전세 관련이면 **전세자금대출** 쪽을 먼저 확인해볼게요. 몇 가지만 여쭤볼게요!"
    if pt == "신용대출":
        return "급전/신용으로 알아보는 상황이면 **신용대출** 쪽을 먼저 보는 게 좋아 보여요. 몇 가지만 여쭤볼게요!"
    return f"일단 **{pt}** 쪽이 잘 맞을 것 같아요. 몇 가지만 확인해볼게요!"


def _is_greeting(msg: str) -> bool:
    t = (msg or "").strip().lower()
    return t in {"안녕", "안녕하세요", "hi", "hello", "ㅎㅇ", "헬로"}


@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id
    user_msg = req.message

    if session_id not in chat_memory:
        chat_memory[session_id] = []
    if session_id not in session_state:
        session_state[session_id] = {
            "stage": "start",          # start -> kind -> chat
            "kind": None,              # save/borrow
            "product_type": None,
            "asked": set(),
            "slots": {},
            "eligibility": {},
            "slot_ask_counts": {},
            "last_question_key": None,
            "last_question": None,
            # 추천 이후 확장용
            "last_final_ranked": None,
            "final_offset": 0,
            "preface_idx": 0,
            "last_meta_uncertain": False,
            "product_type_ack_sent": False,
        }

    history = chat_memory[session_id]
    state = session_state[session_id]

    try:
        # 1) 시작: 인사/첫 질문 개선
        if state["stage"] == "start":
            if _is_greeting(user_msg):
                reply = "안녕하세요 🙂\n돈을 모으고 싶나요, 아니면 돈을 빌리고 싶나요?"
                history.append(HumanMessage(content=user_msg))
                history.append(AIMessage(content=reply))
                state["stage"] = "kind"
                return {"reply": reply}

            # 인사가 아니면 메시지로 바로 판단 시도
            k = decide_kind(user_msg)
            if k["kind"] == "unknown":
                reply = "돈을 모으고 싶나요, 아니면 돈을 빌리고 싶나요?"
                history.append(HumanMessage(content=user_msg))
                history.append(AIMessage(content=reply))
                state["stage"] = "kind"
                return {"reply": reply}

            state["kind"] = k["kind"]
            state["stage"] = "chat"

            # save/borrow로 들어오면 product_type도 바로 잡고 첫 질문까지 진행
            guide = guide_decide(user_msg, history)
            state["product_type"] = guide["product_type"]

            # 바로 다음 질문 1개 생성
            result = orchestrate_next_step(state["product_type"], user_msg, history, state)
            if result["stage"] == "ask":
                q = result["question"]
                state["last_question_key"] = q["key"]
                state["last_question"] = q["text"]
                base = (q.get("preface", "") + "\n" + q["text"]).strip()
                if not state.get("product_type_ack_sent"):
                    base = (_product_type_ack(state.get("product_type")) + "\n" + base).strip()
                    state["product_type_ack_sent"] = True
                reply = base
            else:
                reply = result["final_json"]

            history.append(HumanMessage(content=user_msg))
            history.append(AIMessage(content=reply))
            return {"reply": reply}

        # 2) kind 단계: 모을래/빌릴래 대답 받기
        if state["stage"] == "kind":
            k = decide_kind(user_msg)
            if k["kind"] == "unknown":
                reply = "모으기(적금/예금/연금저축)랑 빌리기(대출) 중에 어떤 쪽이에요? 예: ‘모으려고’ / ‘대출받으려고’"
                history.append(HumanMessage(content=user_msg))
                history.append(AIMessage(content=reply))
                return {"reply": reply}

            state["kind"] = k["kind"]
            state["stage"] = "chat"

            guide = guide_decide(user_msg, history)
            state["product_type"] = guide["product_type"]

            result = orchestrate_next_step(state["product_type"], user_msg, history, state)
            if result["stage"] == "ask":
                q = result["question"]
                state["last_question_key"] = q["key"]
                state["last_question"] = q["text"]
                base = (q.get("preface", "") + "\n" + q["text"]).strip()
                if not state.get("product_type_ack_sent"):
                    base = (_product_type_ack(state.get("product_type")) + "\n" + base).strip()
                    state["product_type_ack_sent"] = True
                reply = base
            else:
                reply = result["final_json"]

            history.append(HumanMessage(content=user_msg))
            history.append(AIMessage(content=reply))
            return {"reply": reply}

        # 3) chat 단계
        product_type = state["product_type"] or "적금"
        result = orchestrate_next_step(product_type, user_msg, history, state)

        if result["stage"] == "ask":
            q = result["question"]
            state["last_question_key"] = q["key"]
            state["last_question"] = q["text"]
            base = (q.get("preface", "") + "\n" + q["text"]).strip()
            if not state.get("product_type_ack_sent"):
                base = (_product_type_ack(state.get("product_type")) + "\n" + base).strip()
                state["product_type_ack_sent"] = True
            reply = base
        else:
            reply = result["final_json"]

        history.append(HumanMessage(content=user_msg))
        history.append(AIMessage(content=reply))
        return {"reply": reply}

    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"{e}\n{tb}")


# -----------------------------
# 내부 스케줄: sync 자동 실행
# -----------------------------
async def scheduler():
    while True:
        now = datetime.datetime.now()
        # 예시: 매일 04:10에 daily sync
        if now.hour == 4 and now.minute == 10:
            try:
                run_sync("daily")
            except Exception:
                pass
            await asyncio.sleep(60)
        await asyncio.sleep(10)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(scheduler())
