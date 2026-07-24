@echo off
setlocal
set "CHENGSI_HOME=%CHENGSI_HOME%"
if not defined CHENGSI_HOME set "CHENGSI_HOME=%~dp0"
if not exist "%CHENGSI_HOME%\.venv\Scripts\python.exe" (
    echo Chengsi is not installed at "%CHENGSI_HOME%".
    echo Run setup_and_run.bat first.
    exit /b 1
)
cd /d "%CHENGSI_HOME%"
"%CHENGSI_HOME%\.venv\Scripts\python.exe" main.py %*
