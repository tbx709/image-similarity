@echo off
rem Image similarity tool - Windows launcher (double-click to run)
setlocal
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

if not exist "%PY%" (
    echo [1/2] Creating virtual environment...
    python -m venv .venv || goto :err
    echo [2/2] Installing dependencies...
    "%PY%" -m pip install -r requirements.txt || goto :err
)

"%PY%" gui.py
if errorlevel 1 pause
exit /b 0

:err
echo.
echo Setup failed. Make sure Python 3.8 or newer is installed and in PATH:
echo   https://www.python.org/downloads/
pause
exit /b 1
