@echo off
title Vosk Pi Voice Client Web Server
echo =======================================================
echo   Starting Vosk Pi Voice Controller Web Client Server   
echo =======================================================
echo.
echo Options:
echo   1. Start HTTP Server (Default, port 8080)
echo   2. Start HTTPS Server (Self-signed SSL, port 8443 - Recommended for Mobile)
echo   3. Start Mock Mode (Test UI without physical Pi)
echo.
if not "%~1"=="" (
    echo Launching with custom arguments: %*
    python clients\client_web_server.py %*
    pause
    exit /b
)

set /p choice="Select mode [1/2/3, default: 1]: "

if "%choice%"=="3" (
    echo Starting in Mock Mode on port 8080...
    python clients\client_web_server.py --mock-pi
    pause
    exit /b
)

set /p pi_ip="Enter Pi IP address or hostname [default: raspberrypi.local]: "
if "%pi_ip%"=="" set pi_ip=raspberrypi.local
if not "%pi_ip:~0,4%"=="http" set pi_ip=http://%pi_ip%:8765

if "%choice%"=="2" (
    echo Starting with SSL enabled on port 8443 for Pi at %pi_ip%...
    python clients\client_web_server.py --pi %pi_ip% --ssl
) else (
    echo Starting HTTP server on port 8080 for Pi at %pi_ip%...
    python clients\client_web_server.py --pi %pi_ip%
)

pause
