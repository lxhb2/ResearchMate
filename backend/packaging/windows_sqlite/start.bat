@echo off
REM =====================================================================
REM  start.bat - Launch ResearchMate portable pack (NO Python needed)
REM  Starts backend\ResearchMate.exe (no console window), then opens
REM  the app window (Edge/Chrome app mode = native app look).
REM  TIP: double-click ResearchMate.vbs instead to launch 100%% hidden
REM  (this bat briefly shows a console; the vbs shows nothing at all).
REM  (ASCII only to avoid encoding issues)
REM =====================================================================
setlocal
cd /d "%~dp0"
set "APP=%~dp0backend\ResearchMate.exe"
set "PORT=8000"

echo ============================================
echo   Starting ResearchMate (first run ~5-10s)...
echo   This window closes automatically.
echo ============================================

REM ---- start backend if not running ----
tasklist /fi "imagename eq ResearchMate.exe" 2>nul | find /i "ResearchMate.exe" >nul
if errorlevel 1 (
  start "ResearchMate" "%APP%"
)

REM ---- wait for service, then open app window ----
for /l %%i in (1,1,30) do (
  powershell -Command "try{(Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT%/ -TimeoutSec 1)|Out-Null;exit 0}catch{exit 1}" >nul 2>nul
  if not errorlevel 1 goto :open
  ping 127.0.0.1 -n 2 >nul
)

:open
REM Prefer Edge/Chrome --app mode: standalone window without tabs or
REM address bar, looks like a native desktop app. Fallback: default browser.
set "URL=http://localhost:%PORT%/"
if exist "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" (
  start "" "%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe" --app=%URL%
  goto :done
)
if exist "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" (
  start "" "%ProgramFiles%\Microsoft\Edge\Application\msedge.exe" --app=%URL%
  goto :done
)
if exist "%ProgramFiles%\Google\Chrome\Application\chrome.exe" (
  start "" "%ProgramFiles%\Google\Chrome\Application\chrome.exe" --app=%URL%
  goto :done
)
if exist "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" (
  start "" "%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe" --app=%URL%
  goto :done
)
start "" "%URL%"

:done
endlocal
