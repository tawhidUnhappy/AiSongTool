@echo off
title AiSongTool
cd /d "%~dp0"

echo.
echo  Checking if Docker is running...
docker info >nul 2>&1
if errorlevel 1 (
    echo.
    echo  [!] Docker is not running.
    echo      Please open Docker Desktop, wait for it to fully start, then run this again.
    echo.
    pause
    exit /b 1
)

echo  Starting AiSongTool...
docker compose -f docker-compose.yml -f docker-compose.gpu.yml up
if errorlevel 1 (
    echo.
    echo  [!] Failed to start the container. Check the error above.
    echo.
    pause
    exit /b 1
)

echo  Waiting for app to be ready...
timeout /t 3 /nobreak >nul

echo  Opening app in browser...
start http://localhost:8000

echo.
echo  ============================================
echo   AiSongTool is running at localhost:8000
echo   Press any key to STOP the app and exit.
echo  ============================================
echo.
pause >nul

echo.
echo  Stopping AiSongTool...
docker compose stop
echo  Done. Goodbye!
timeout /t 2 /nobreak >nul
