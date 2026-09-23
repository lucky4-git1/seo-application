@echo off
REM Start the SEO API (uvicorn) — used by the SEO-API scheduled task and manual runs.
cd /d "%~dp0..\apps\api"
if not exist "%LOCALAPPDATA%\seo-app\logs" mkdir "%LOCALAPPDATA%\seo-app\logs"
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 >> "%LOCALAPPDATA%\seo-app\logs\api.log" 2>&1
