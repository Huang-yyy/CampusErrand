@echo off
cd /d C:\Users\1\CampusErrand
"C:\Users\1\AppData\Local\Hermes Agent CN Desktop\data\hermes-home\hermes-agent\venv\Scripts\python.exe" start_app.py
if errorlevel 2 exit /b
echo.
echo Server stopped. Press any key to close this window.
pause >nul
