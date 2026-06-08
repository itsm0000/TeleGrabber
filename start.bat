@echo off
title TeleGrabber Launcher
color 0A

echo ================================================
echo   TeleGrabber - Starting Services
echo ================================================
echo.

REM ── Backend (FastAPI on port 8000) ─────────────────────────────────────────
echo [1/2] Starting Backend (FastAPI)...
start "TeleGrabber - Backend" cmd /k "cd /d %~dp0backend && .venv\Scripts\uvicorn.exe app.main:app --host 127.0.0.1 --port 8000 --reload"

REM Give the backend a moment to boot before the frontend starts
timeout /t 3 /nobreak >nul

REM ── Frontend (Next.js on port 3000) ────────────────────────────────────────
echo [2/2] Starting Frontend (Next.js)...
start "TeleGrabber - Frontend" cmd /k "cd /d %~dp0frontend && npm run dev"

echo.
echo ================================================
echo   Both services are starting up!
echo   Backend  : http://localhost:8000
echo   Frontend : http://localhost:3000
echo   API Docs : http://localhost:8000/docs
echo ================================================
echo.
echo   Close the two terminal windows to stop the services.
echo   Press any key to open the app in your browser...
pause >nul

start http://localhost:3000
