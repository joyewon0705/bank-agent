from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from agent import agent_executor

from apscheduler.schedulers.background import BackgroundScheduler
from scripts.sync_data import sync
import contextlib

# 서버 시작/종료 시 스케줄러 제어
@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # 1. 서버 시작 시 스케줄러 가동
    scheduler = BackgroundScheduler()
    # 매일 새벽 2시에 실행 (테스트를 위해 1시간마다로 바꾸려면 hours=1)
    scheduler.add_job(sync, 'cron', hour=2, minute=0) 
    scheduler.start()
    print("⏰ 예약 작업 시작: 매일 새벽 2시에 금융 데이터를 동기화합니다.")
    
    yield
    
    # 2. 서버 종료 시 스케줄러 끄기
    scheduler.shutdown()

app = FastAPI(lifespan=lifespan)

# 프론트엔드(Next.js)와 통신하기 위한 CORS 설정
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # 실제 배포 시에는 Next.js 주소만 허용하도록 수정
    allow_methods=["*"],
    allow_headers=["*"],
)

class ChatRequest(BaseModel):
    message: str

@app.get("/")
def read_root():
    return {"status": "AI Banking Agent is running!"}

@app.post("/chat")
async def chat(request: ChatRequest):
    try:
        # 에이전트 실행
        response = agent_executor.invoke({"input": request.message})
        return {"reply": response["output"]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)