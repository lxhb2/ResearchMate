@echo off
REM stop.bat - Stop ResearchMate backend and PostgreSQL
setlocal
cd /d "%~dp0"
set "PG_BIN=%~dp0postgres\bin"

echo Stopping ResearchMate...
taskkill /f /im ResearchMate.exe >nul 2>nul

echo Stopping PostgreSQL...
"%PG_BIN%\pg_ctl.exe" -D "%~dp0pgdata" stop -m fast >nul 2>nul

echo Stopped.
endlocal
timeout /t 2 >nul