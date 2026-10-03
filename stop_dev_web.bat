@echo off
setlocal
cd /d "%~dp0"
uv run python scripts\dev_web.py --stop
endlocal
