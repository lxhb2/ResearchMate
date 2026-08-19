@echo off
REM ============================================
REM  ResearchMate launcher (Windows)
REM  ASCII-only. Robust venv / dep bootstrap.
REM  Requires: Python 3.10+ on PATH.
REM ============================================
cd /d "%~dp0backend"

REM 1) Python must be on PATH
where python >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Python not found. Install Python 3.10+ and add it to PATH.
  pause
  exit /b 1
)

REM 2) Create venv if missing
if not exist ".venv\Scripts\python.exe" (
  echo [setup] creating virtual environment...
  python -m venv .venv
)

REM 3) Install deps if uvicorn is missing
if not exist ".venv\Scripts\uvicorn.exe" (
  echo [setup] installing dependencies, this may take a while...
  .venv\Scripts\python -m pip install --upgrade pip
  .venv\Scripts\python -m pip install -r requirements.txt
)

set "FRONTEND_DIST=..\frontend\dist"
if "%PORT%"=="" set "PORT=8000"
echo =============================================
echo ResearchMate starting -^> http://localhost:%PORT%/
echo =============================================
.venv\Scripts\python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
pause