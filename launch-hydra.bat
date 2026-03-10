@echo off
cd /d "%~dp0"
call npx electron .
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to launch HYDRA
    pause
)
