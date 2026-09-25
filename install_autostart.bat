@echo off
setlocal
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_autostart.ps1"
if errorlevel 1 (
    echo.
    echo [Error] 执行失败，错误代码 %errorlevel%
)
endlocal
pause
