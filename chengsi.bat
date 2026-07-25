@echo off
setlocal
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "VENV_PYTHON=%ROOT%\.venv\Scripts\python.exe"
if not exist "%VENV_PYTHON%" (
    echo Chengsi is not installed at "%ROOT%".
    echo Run setup_and_run.bat --setup first.
    exit /b 1
)
cd /d "%ROOT%"
"%VENV_PYTHON%" "%ROOT%\main.py" %*
