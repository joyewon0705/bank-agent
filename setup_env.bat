@echo off
REM ============================================
REM Python 가상환경 자동 세팅 스크립트
REM - 기존 venv 삭제 후 재생성
REM - 패키지 설치
REM - 가상환경은 사용자가 직접 활성화
REM ============================================

echo [1/4] 가상환경 생성 중...

if exist venv (
    echo 기존 venv 발견 - 삭제 중...
    rmdir /s /q venv
)

python -m venv venv

echo.
echo [2/4] pip 업데이트 및 패키지 설치 중 (캐시 무시)...

call venv\Scripts\activate.bat
python -m pip install --upgrade pip
python -m pip install --no-cache-dir ^
    langchain==0.3.0 ^
    langchain-community==0.3.0 ^
    langchain-core==0.3.0 ^
    langchain-groq==0.2.0 ^
    python-dotenv ^
    fastapi ^
    uvicorn

echo.
echo [3/3] 설치 완료!
echo 가상환경을 사용하려면 아래 명령어를 순서대로 실행하세요:
echo   1) 권한 문제 발생 방지:
echo      Set-ExecutionPolicy -ExecutionPolicy Bypass -Scope Process
echo   2) 가상환경 활성화:
echo      .\venv\Scripts\activate
pause
