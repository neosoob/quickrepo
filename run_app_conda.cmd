@echo off
setlocal

cd /d "%~dp0"

call conda activate quickrepo
if errorlevel 1 (
    echo Failed to activate conda environment: quickrepo
    pause
    exit /b 1
)

python app.py
set "EXIT_CODE=%ERRORLEVEL%"

if not "%EXIT_CODE%"=="0" (
    echo.
    echo app.py exited with code %EXIT_CODE%.
    pause
)

exit /b %EXIT_CODE%
