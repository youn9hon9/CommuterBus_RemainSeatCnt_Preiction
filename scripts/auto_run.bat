@echo off
chcp 65001 >nul
setlocal

cd /d "%~dp0.."

if not defined VIRTUAL_ENV (
  if exist .venv\Scripts\activate.bat (
    call .venv\Scripts\activate.bat
  )
)

REM 운영 모드: 6시 30분까지 대기 후 1분마다 수집, API 한도 초과 시에만 Python에서 PC 종료(config.SHUTDOWN_DELAY_SEC 대기 후).
python main.py --mode run

REM 또는 Python에서 종료 처리하지 않으면: 수집 종료 후 10분 대기 후 PC 종료
REM timeout /t 600 /nobreak >nul
REM shutdown /s /t 0

endlocal
