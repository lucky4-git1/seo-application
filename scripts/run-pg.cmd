@echo off
REM Start the local SEO Postgres cluster (port 5434) — used by the SEO-PG scheduled task.
"C:\Program Files\PostgreSQL\18\bin\pg_ctl.exe" -D "%LOCALAPPDATA%\seo-app\pgdata" -l "%LOCALAPPDATA%\seo-app\logs\pg.log" -w start
