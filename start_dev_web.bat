@echo off
setlocal
cd /d "%~dp0"
if not exist "runtime" mkdir "runtime"

if "%~1"=="--log" (
    uv run python scripts\dev_web.py --no-reload-backend >> runtime\dev_web_service.log 2>&1
) else (
    uv run python scripts\dev_web.py --no-reload-backend %*
)
endlocal
