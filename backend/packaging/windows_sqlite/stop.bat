@echo off
REM =====================================================================
REM  stop.bat - Fully quit ResearchMate (stops the background service)
REM  Double-click this after closing the app window.
REM  (ASCII only to avoid encoding issues)
REM =====================================================================
tasklist /fi "imagename eq ResearchMate.exe" 2>nul | find /i "ResearchMate.exe" >nul
if errorlevel 1 (
  echo ResearchMate is not running.
) else (
  taskkill /f /im ResearchMate.exe >nul 2>nul
  echo ResearchMate stopped.
)
echo.
pause
