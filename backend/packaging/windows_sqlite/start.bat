@echo off
REM =====================================================================
REM  start.bat - Launch ResearchMate portable pack (NO Python needed)
REM  Double-click this. Starts ResearchMate.exe (frontend embedded),
REM  then opens the browser. Data is saved under this folder.
REM  (ASCII only to avoid encoding issues)
REM =====================================================================
setlocal
cd /d "%~dp0"
set "APP=%~dp0backend\ResearchMate.exe"
set "PORT=8000"

echo ============================================
echo   Starting ResearchMate (first run ~5-10s)...
echo ============================================

REM ---- start backend if not running ----
tasklist /fi "imagename eq ResearchMate.exe" 2>nul | find /i "ResearchMate.exe" >nul
if errorlevel 1 (
  start "ResearchMate" "%APP%"
)

REM ---- wait for service, then open browser ----
for /l %%i in (1,1,30) do (
  powershell -Command "try{(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/ -TimeoutSec 1)|Out-Null;exit 0}catch{exit 1}" >nul 2>nul
  if not errorlevel 1 goto :open
  timeout /t 1 >nul
)

:open
start "" "http://localhost:%PORT%/"
endlocal