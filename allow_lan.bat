@echo off
REM =====================================================================
REM  allow_lan.bat - Allow phone / LAN devices to access ResearchMate
REM  Run as Administrator once. Change PORT below if you use another port.
REM =====================================================================
setlocal
if "%PORT%"=="" set "PORT=8000"

netsh advfirewall firewall delete rule name="ResearchMate LAN" >nul 2>nul
netsh advfirewall firewall add rule name="ResearchMate LAN" dir=in action=allow protocol=TCP localport=%PORT% profile=private,domain

echo.
echo Firewall rule added for TCP port %PORT%.
echo Phone access:  http://<this-pc-lan-ip>:%PORT%/
echo.
pause
endlocal
