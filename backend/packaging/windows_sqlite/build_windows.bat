@echo off
REM =====================================================================
REM  build_windows.bat - Build a NO-PYTHON portable ResearchMate (SQLite)
REM  Run this ONCE on a Windows machine that has Python + Node installed.
REM  The output can then be sent to users who have NO programming env.
REM  (ASCII only: no Chinese to avoid encoding issues)
REM
REM  Usage:  build_windows.bat
REM =====================================================================
setlocal enabledelayedexpansion
set "ROOT=..\..\.."
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "BUILD=%ROOT%\_build"
set "PKG=%BUILD%\ResearchMate"

echo.
echo ============================================================
echo  ResearchMate NO-PYTHON portable pack build (SQLite)
echo ============================================================
echo.

REM ---- 0. prechecks ----
where python >nul 2>nul || ( echo [ERROR] python not found, install Python 3.10+ and add to PATH & exit /b 1 )
where node    >nul 2>nul || ( echo [ERROR] node not found, install Node.js 18+ and add to PATH & exit /b 1 )

REM ---- 1. backend deps + PyInstaller ----
echo [1/4] Preparing Python env...
if not exist "%BACKEND%\.venv-win" python -m venv "%BACKEND%\.venv-win"
call "%BACKEND%\.venv-win\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -r "%BACKEND%\requirements.txt" pyinstaller >nul || ( echo [ERROR] pip install failed & exit /b 1 )

REM ---- 2. build frontend ----
echo [2/4] Building frontend...
pushd "%FRONTEND%"
call npm install >nul
call npm run build || ( echo [ERROR] frontend build failed & exit /b 1 )
popd

REM ---- 3. PyInstaller backend (embeds frontend dist + skill templates) ----
echo [3/4] Packing backend to exe...
pushd "%~dp0"
python -m PyInstaller --clean --noconfirm "researchmate_sqlite.spec" || ( echo [ERROR] backend pack failed & exit /b 1 )
popd

REM ---- 4. assemble portable dir ----
echo [4/4] Assembling portable dir...
taskkill /f /im ResearchMate.exe >nul 2>nul
ping 127.0.0.1 -n 2 >nul
if exist "%PKG%" rmdir /s /q "%PKG%"
mkdir "%PKG%\backend"
mkdir "%PKG%\storage\pdfs"
xcopy /e /i /q "%BACKEND%\packaging\windows_sqlite\dist\ResearchMate.exe" "%PKG%\backend\" >nul
copy /y "%~dp0start.bat" "%PKG%\start.bat" >nul
copy /y "%~dp0ResearchMate.vbs" "%PKG%\ResearchMate.vbs" >nul
copy /y "%~dp0stop.bat" "%PKG%\stop.bat" >nul
copy /y "%~dp0README.txt" "%PKG%\README.txt" >nul
copy /y "%ROOT%\allow_lan.bat" "%PKG%\allow_lan.bat" >nul

echo.
echo ============================================================
echo  BUILD COMPLETE!
echo  Portable dir : %PKG%
echo  Zip it and send to users.
echo  They just double-click ResearchMate.vbs (fully hidden, no console).
echo ============================================================
endlocal
pause
