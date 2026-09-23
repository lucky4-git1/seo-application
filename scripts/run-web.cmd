@echo off
REM Start the SEO web frontend (Vite dev) — used by the SEO-Web scheduled task and manual runs.
cd /d "%~dp0.."
if not exist "%LOCALAPPDATA%\seo-app\logs" mkdir "%LOCALAPPDATA%\seo-app\logs"
call npm run dev --workspace apps/web -- --port 5200 --strictPort >> "%LOCALAPPDATA%\seo-app\logs\web.log" 2>&1
