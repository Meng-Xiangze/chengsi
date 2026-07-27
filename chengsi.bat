@echo off
setlocal EnableExtensions
cd /d "%~dp0"
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "VENV_PYTHON=%ROOT%\.venv\Scripts\python.exe"

if not exist "%VENV_PYTHON%" (
    echo Chengsi is not set up yet.
    echo Run "%ROOT%\setup_and_run.bat" first.
    exit /b 1
)

if not exist "%ROOT%\config.json" (
    echo Chengsi configuration is missing.
    echo Run "%ROOT%\setup_and_run.bat" to create it.
    exit /b 1
)

set "CHENGSI_HOME=%ROOT%"
"%VENV_PYTHON%" "%ROOT%\launcher.py" %*
exit /b %errorlevel%
