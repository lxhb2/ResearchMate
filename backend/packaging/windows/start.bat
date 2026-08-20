@echo off
REM =====================================================================
REM  start.bat - Launch ResearchMate portable pack (double-click this)
REM  Starts portable PostgreSQL + backend (ResearchMate.exe, frontend embedded),
REM  then opens the browser. Can run from any folder.
REM  (ASCII only to avoid encoding issues)
REM =====================================================================
setlocal
cd /d "%~dp0"

set "PG_BIN=%~dp0postgres\bin"
set "PGDATA=%~dp0pgdata"
set "APP=%~dp0backend\ResearchMate.exe"
set "PGLOG=%~dp0postgres.log"
set "PORT=8000"
if "%HOST%"=="" set "HOST=0.0.0.0"

REM ---- backend runtime env ----
set DATABASE_URL=postgresql+psycopg2://researchmate:researchmate@127.0.0.1:55432/researchmate
set PDF_PARSING_ENABLED=false
set PDF_DIR=storage\pdfs
set STORAGE_DIR=storage
set CORS_ORIGINS=http://localhost:%PORT%

echo ============================================================
echo   Starting ResearchMate (first run ~5-10s, please wait...)
echo ============================================================

REM ---- 1. start PostgreSQL (if not running) ----
"%PG_BIN%\pg_isready.exe" -h 127.0.0.1 -p 55432 >nul 2>nul
if errorlevel 1 (
  echo [1/3] Starting PostgreSQL...
  "%PG_BIN%\pg_ctl.exe" -D "%PGDATA%" -l "%PGLOG%" -o "-p 55432" start >nul 2>&1
  if errorlevel 1 ( echo [ERROR] PostgreSQL failed to start, see postgres.log & goto :end )
)
REM Wait until PostgreSQL accepts connections (pg_ctl returns before it is ready)
set "PGOK="
for /l %%i in (1,1,30) do (
  "%PG_BIN%\pg_isready.exe" -h 127.0.0.1 -p 55432 >nul 2>nul
  if not errorlevel 1 ( set "PGOK=1" & goto :pgready )
  timeout /t 1 >nul
)
:pgready
if "%PGOK%"=="" ( echo [ERROR] PostgreSQL not ready after 30s, see postgres.log & goto :end )
echo [1/3] PostgreSQL ready

REM ---- 2. start backend (if not running) ----
tasklist /fi "imagename eq ResearchMate.exe" 2>nul | find /i "ResearchMate.exe" >nul
if errorlevel 1 (
  echo [2/3] Starting backend...
  start "ResearchMate" "%APP%"
  if errorlevel 1 ( echo [ERROR] Backend failed to start & goto :end )
)
echo [2/3] Backend started

REM ---- 3. wait for port, open browser ----
echo [3/3] Waiting for service...
set "OK="
for /l %%i in (1,1,30) do (
  powershell -Command "try{(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/api/v1/settings -TimeoutSec 1).StatusCode|Out-Null}" >nul 2>nul
  if not errorlevel 1 ( set "OK=1" & goto :open )
  timeout /t 1 >nul
)
:open
if "%OK%"=="" ( echo [WARN] Service may not be ready, open http://localhost:%PORT%/ manually ) else ( echo Service ready )
start "" "http://localhost:%PORT%/"

:end
endlocal
