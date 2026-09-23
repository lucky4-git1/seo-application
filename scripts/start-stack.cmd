@echo off
REM Start the full local SEO stack: Postgres (5434) + API (:8000) + Web (:5200).
REM Copy this file (or a shortcut to it) into your Windows Startup folder to
REM auto-start the stack on logon:
REM   %APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup
call "%~dp0run-pg.cmd"
start "SEO-API" /min "%~dp0run-api.cmd"
start "SEO-Web" /min "%~dp0run-web.cmd"
echo SEO stack starting. API: http://127.0.0.1:8000  Web: http://localhost:5200
