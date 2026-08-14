@echo off
rem Dev launcher: starts backend (port 8000) and frontend (port 5173).
cd /d "%~dp0"

echo [1/2] Starting backend on http://127.0.0.1:8000 ...
start "SEO Backend" cmd /k "cd backend && .venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000"

timeout /t 2 >nul

echo [2/2] Starting frontend on http://localhost:5173 ...
cd frontend
call npm run dev
