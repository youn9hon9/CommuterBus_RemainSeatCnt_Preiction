@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0"

if not defined VIRTUAL_ENV (
  if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
  )
)

REM 운영 모드 실행 (6시 30분 대기 후 1분마다 수집). 수집 종료 후 10분 뒤 PC 종료는 Python --shutdown으로 처리하거나 아래 주석대로 배치에서 처리.
python main.py --shutdown

REM 또는 Python에서 종료 처리하지 않으면: 수집 종료 후 10분 대기 후 PC 종료
REM timeout /t 600 /nobreak >nul
REM shutdown /s /t 0

endlocal
