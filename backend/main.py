from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Any
import traceback
import asyncio
import datetime

from langchain_core.messages import HumanMessage, AIMessage
from agent import guide_decide, orchestrate_next_step, fetch_products

from scripts.sync_data import run_sync, DB_PATH

try:
    from groq import RateLimitError
except Exception:
    RateLimitError = None

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
    ensure_db_exists()
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
    ensure_db_exists()
    if product_type not in ["적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"]:
        raise HTTPException(status_code=400, detail="Invalid product type")

    return fetch_products(product_type, page, page_size, sort, q)


@app.post("/chat")
async def chat(req: ChatRequest):
    session_id = req.session_id
    user_msg = req.message

    if session_id not in chat_memory:
        chat_memory[session_id] = []
    if session_id not in session_state:
        session_state[session_id] = {
            "stage": "decide",
            "product_type": None,
            "asked": set(),
            "slots": {},
            "eligibility": {},
            "slot_ask_counts": {},
            "last_question_key": None,
            "last_question": None,
        }

    history = chat_memory[session_id]
    state = session_state[session_id]

    try:
        if state["stage"] == "decide":
            guide = guide_decide(user_msg, history)
            product_type = guide["product_type"]
            state["product_type"] = product_type
            state["stage"] = "chat"

            reply = f"{guide.get('reason','')}\n\n돈을 모으거나 빌리려는 목적이 무엇인가요?"
            history.append(HumanMessage(content=user_msg))
            history.append(AIMessage(content=reply))
            return {"reply": reply}

        product_type = state["product_type"] or "적금"
        result = orchestrate_next_step(product_type, user_msg, history, state)

        if result["stage"] == "ask":
            q = result["question"]
            state["last_question_key"] = q["key"]
            state["last_question"] = q["text"]
            reply = (q.get("preface", "") + "\n" + q["text"]).strip()

        elif result["stage"] == "draft":
            nq = result["next_question"]
            state["last_question_key"] = nq["key"]
            state["last_question"] = nq["text"]
            reply = (
                f"{result['preface']}\n\n"
                f"{result['candidates_text']}\n\n"
                f"{nq.get('preface','')}\n{nq['text']}"
            ).strip()

        else:
            reply = result["final_json"]

        history.append(HumanMessage(content=user_msg))
        history.append(AIMessage(content=reply))
        return {"reply": reply}

    except Exception as e:
        tb = traceback.format_exc()
        raise HTTPException(status_code=500, detail=f"{e}\n{tb}")


def ensure_db_exists():
    if not os.path.exists(DB_PATH):
        print("DB not found. Running initial sync...")
        run_sync("daily")

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
    ensure_db_exists()
    asyncio.create_task(scheduler())