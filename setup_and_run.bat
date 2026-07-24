@echo off
setlocal
cd /d "%~dp0"

where py >nul 2>nul
if %errorlevel%==0 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 or newer is required.
        echo Download it from https://www.python.org/downloads/
        pause
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv .venv
    if errorlevel 1 goto :error
)

echo Installing dependencies...
".venv\Scripts\python.exe" -m pip install --upgrade pip
if errorlevel 1 goto :error
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :error

if not exist "config.json" (
    copy /y "config.example.json" "config.json" >nul
    echo Created config.json from config.example.json.
)

rem Register a per-user installation location and launcher command.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$root = (Get-Location).Path; [Environment]::SetEnvironmentVariable('CHENGSI_HOME', $root, 'User'); $path = [Environment]::GetEnvironmentVariable('Path', 'User'); $parts = @($path -split ';' | Where-Object { $_ -and ($_ -ne $root) }); if ($parts -notcontains $root) { $parts += $root }; [Environment]::SetEnvironmentVariable('Path', ($parts -join ';'), 'User'); Write-Host ('Registered Chengsi at ' + $root)"
if errorlevel 1 goto :error
set "CHENGSI_HOME=%cd%"
set "PATH=%CHENGSI_HOME%;%PATH%"

echo Starting Chengsi...
".venv\Scripts\python.exe" main.py
if errorlevel 1 goto :error
exit /b 0

:error
echo.
echo Setup or startup failed. Review the message above.
pause
exit /b 1
