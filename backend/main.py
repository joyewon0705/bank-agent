# main.py
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from typing import Dict, List, Any
import traceback
import asyncio
import datetime

from langchain_core.messages import HumanMessage, AIMessage
from agent import guide_decide, orchestrate_next_step, fetch_products

# ✅ 코드 내부 스케줄: sync 실행
from scripts.sync_data import run_sync

# Groq rate limit 예외
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
    if product_type not in {"적금", "예금", "연금저축", "주담대", "전세자금대출", "신용대출"}:
        raise HTTPException(status_code=400, detail="Invalid product_type")
    page_size = min(max(page_size, 1), 50)
    return fetch_products(product_type, page=page, page_size=page_size, sort=sort, q=q)


# -----------------------------
# ✅ 내부 스케줄러 (FastAPI startup)
# -----------------------------
async def _sleep_until(dt: datetime.datetime):
    now = datetime.datetime.now()
    if dt <= now:
        return
    await asyncio.sleep((dt - now).total_seconds())

async def _daily_job_loop():
    while True:
        now = datetime.datetime.now()
        target = now.replace(hour=4, minute=10, second=0, microsecond=0)
        if target <= now:
            target += datetime.timedelta(days=1)

        await _sleep_until(target)

        # daily sync
        try:
            print("🕒 [SCHED] daily sync start")
            run_sync("daily")
            print("✅ [SCHED] daily sync done")
        except Exception as e:
            print("❌ [SCHED] daily sync failed:", e)

        # 다음 루프에서 다시 계산

async def _monthly_job_loop():
    while True:
        now = datetime.datetime.now()
        # 매월 23일 03:00
        # 이번 달 23일이 지났으면 다음 달로
        year = now.year
        month = now.month

        def make_dt(y, m):
            return datetime.datetime(y, m, 23, 3, 0, 0)

        target = make_dt(year, month)
        if target <= now:
            # 다음 달
            if month == 12:
                target = make_dt(year + 1, 1)
            else:
                target = make_dt(year, month + 1)

        await _sleep_until(target)

        # monthly sync
        try:
            print("🗓️ [SCHED] monthly sync start")
            run_sync("monthly")
            print("✅ [SCHED] monthly sync done")
        except Exception as e:
            print("❌ [SCHED] monthly sync failed:", e)

        # 다음 루프에서 다음 달로 재계산

@app.on_event("startup")
async def startup_event():
    # 서버 켜질 때 최초 1회 daily sync도 돌리고 싶으면 아래 주석 해제
    # asyncio.get_running_loop().run_in_executor(None, run_sync, "daily")

    asyncio.create_task(_daily_job_loop())
    asyncio.create_task(_monthly_job_loop())


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
                "last_question": None,
                "last_question_key": None,
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

        # 2) 다음 스텝
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
            next_q = out.get("next_question")

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
        if RateLimitError is not None and isinstance(e, RateLimitError):
            raise HTTPException(
                status_code=429,
                detail="지금 AI 사용량이 잠시 초과되어 추천이 지연되고 있어요. 5분 뒤 다시 시도해 주세요.",
            )

        print("❌ Server Error:", traceback.format_exc())
        raise HTTPException(status_code=500, detail="Internal Server Error")
