@echo off
setlocal enabledelayedexpansion
REM =====================================================================
REM  build_windows.bat - Build ResearchMate portable pack on Windows
REM  (ASCII only - no Chinese to avoid encoding issues)
REM
REM  Usage:
REM    build_windows.bat -PgRoot "C:\pg\postgresql" -PgVectorZip "C:\pg\pgvector-win.zip"
REM  Or set env vars PGROOT / PGVECTOR_ZIP first.
REM =====================================================================

REM this script runs from backend\packaging\windows
REM project root (researchmate) is 3 levels up
set "ROOT=..\..\.."
set "BACKEND=%ROOT%\backend"
set "FRONTEND=%ROOT%\frontend"
set "BUILD=%ROOT%\_build"
set "PKG=%BUILD%\ResearchMate"

REM ---- parse args ----
set "PGROOT=%PGROOT%"
set "PGVECTOR_ZIP=%PGVECTOR_ZIP%"
:parse
if "%~1"=="" goto :parsed
if /i "%~1"=="-PgRoot"      ( set "PGROOT=%~2" & shift & shift & goto :parse )
if /i "%~1"=="-PgVectorZip" ( set "PGVECTOR_ZIP=%~2" & shift & shift & goto :parse )
shift
goto :parse
:parsed

echo.
echo ============================================================
echo  ResearchMate Windows portable pack build
echo ============================================================
echo.

REM ---- 0. prechecks ----
where python >nul 2>nul || ( echo [ERROR] python not found, install Python 3.12+ and add to PATH & exit /b 1 )
where node    >nul 2>nul || ( echo [ERROR] node not found, install Node.js 20+ and add to PATH & exit /b 1 )
if "%PGROOT%"=="" ( echo [ERROR] PGROOT not set, use -PgRoot or set PGROOT env & exit /b 1 )
if "%PGVECTOR_ZIP%"=="" ( echo [ERROR] PGVECTOR_ZIP not set, use -PgVectorZip or set PGVECTOR_ZIP env & exit /b 1 )
if not exist "%PGROOT%\bin\initdb.exe" ( echo [ERROR] initdb.exe not found in %PGROOT% & exit /b 1 )

REM ---- 1. backend deps + PyInstaller ----
echo [1/6] Preparing Python env...
if not exist "%BACKEND%\.venv-win" python -m venv "%BACKEND%\.venv-win"
call "%BACKEND%\.venv-win\Scripts\activate.bat"
python -m pip install --upgrade pip >nul
pip install -r "%BACKEND%\requirements.txt" pyinstaller >nul

REM ---- 2. build frontend ----
echo [2/6] Building frontend...
pushd "%FRONTEND%"
call npm install >nul
call npm run build || ( echo [ERROR] frontend build failed & exit /b 1 )
popd

REM ---- 3. init portable PostgreSQL data dir ----
echo [3/6] Initializing portable PostgreSQL data dir...
powershell -ExecutionPolicy Bypass -File "init_db.ps1" -PgRoot "%PGROOT%" -PgVectorZip "%PGVECTOR_ZIP%" -DataDir "..\..\..\_build\pgdata" || ( echo [ERROR] DB init failed & exit /b 1 )

REM ---- 4. PyInstaller backend (embed frontend dist) ----
echo [4/6] Packing backend to exe...
pyinstaller --clean --noconfirm "researchmate_backend.spec" || ( echo [ERROR] backend pack failed & exit /b 1 )

REM ---- 5. assemble portable dir ----
echo [5/6] Assembling portable dir...
REM Kill any running instance from a previous pack so output dir is not locked
taskkill /f /im ResearchMate.exe >nul 2>nul
taskkill /f /im postgres.exe >nul 2>nul
ping 127.0.0.1 -n 2 >nul
if exist "%PKG%" rmdir /s /q "%PKG%"
mkdir "%PKG%\backend"
mkdir "%PKG%\postgres"
mkdir "%PKG%\storage\pdfs"
xcopy /e /i /q "dist\ResearchMate.exe" "%PKG%\backend\" >nul
REM .env next to the exe so the app connects to the bundled portable PostgreSQL
REM even when launched directly (pydantic reads exe-dir .env as a fallback).
>  "%PKG%\backend\.env" echo DATABASE_URL=postgresql+psycopg2://researchmate:researchmate@127.0.0.1:55432/researchmate
>> "%PKG%\backend\.env" echo PDF_PARSING_ENABLED=false
>> "%PKG%\backend\.env" echo PDF_DIR=storage\pdfs
>> "%PKG%\backend\.env" echo STORAGE_DIR=storage
>> "%PKG%\backend\.env" echo CORS_ORIGINS=http://localhost:8000
xcopy /e /i /q "%PGROOT%\" "%PKG%\postgres\" >nul
xcopy /e /i /q "..\..\..\_build\pgdata" "%PKG%\pgdata\" >nul
copy /y "start.bat" "%PKG%\start.bat" >nul
copy /y "stop.bat"  "%PKG%\stop.bat"  >nul
copy /y "README.txt" "%PKG%\README.txt" >nul

REM ---- 6. zip ----
echo [6/6] Zipping...
powershell -ExecutionPolicy Bypass -Command "Compress-Archive -Path '%PKG%' -DestinationPath '..\..\..\_build\ResearchMate-test.zip' -Force" || ( echo [WARN] zip failed, dir still at %PKG% )

echo.
echo ============================================================
echo  BUILD COMPLETE!
echo  Portable dir : %PKG%
echo  Zip          : ..\..\..\_build\ResearchMate-test.zip
echo  Send zip to user, unzip, double-click start.bat to run.
echo ============================================================
endlocal