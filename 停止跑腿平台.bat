@echo off
echo Stopping CampusErrand server on port 8000 ...
set "found="
for /f "tokens=5" %%a in ('netstat -ano ^| findstr :8000 ^| findstr LISTENING') do (
    taskkill /PID %%a /F >nul 2>&1
    set "found=1"
)
if defined found (echo Done. Server stopped.) else (echo Server was not running.)
ping -n 4 127.0.0.1 >nul
