from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from agent import agent_executor

app = FastAPI()

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