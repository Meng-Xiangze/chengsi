@echo off
setlocal
cd /d "%~dp0"
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "VENV_PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "NEEDS_SETUP=0"

if /i "%~1"=="--setup" set "NEEDS_SETUP=1"
if not exist "%VENV_PYTHON%" set "NEEDS_SETUP=1"

if "%NEEDS_SETUP%"=="1" call :setup
if errorlevel 1 goto :error

if not exist "%ROOT%\config.json" (
    copy /y "%ROOT%\config.example.json" "%ROOT%\config.json" >nul
    if errorlevel 1 goto :error
    echo Created config.json from config.example.json.
)

rem Register this installation for the global launcher. Ollama owns its own startup.
powershell -NoProfile -ExecutionPolicy Bypass -Command "$root = [IO.Path]::GetFullPath('%ROOT%'); [Environment]::SetEnvironmentVariable('CHENGSI_HOME', $root, 'User'); $path = [Environment]::GetEnvironmentVariable('Path', 'User'); $parts = @($path -split ';' | Where-Object { $_ -and ($_.TrimEnd('\') -ine $root.TrimEnd('\')) }); $parts += $root; [Environment]::SetEnvironmentVariable('Path', (($parts | Select-Object -Unique) -join ';'), 'User')"
if errorlevel 1 goto :error

set "CHENGSI_HOME=%ROOT%"
set "PATH=%ROOT%;%PATH%"
echo Starting Chengsi...
"%VENV_PYTHON%" "%ROOT%\main.py"
if errorlevel 1 goto :error
exit /b 0

:setup
where py >nul 2>nul
if not errorlevel 1 (
    set "PYTHON=py -3"
) else (
    where python >nul 2>nul
    if errorlevel 1 (
        echo Python 3.10 or newer is required.
        echo Download it from https://www.python.org/downloads/
        exit /b 1
    )
    set "PYTHON=python"
)

if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo Creating virtual environment...
    %PYTHON% -m venv "%ROOT%\.venv"
    if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Python 3.10 or newer is required for this environment.
    exit /b 1
)

echo Installing dependencies...
"%VENV_PYTHON%" -m pip install -r "%ROOT%\requirements.txt"
if errorlevel 1 exit /b 1
exit /b 0

:error
echo.
echo Chengsi startup failed. Review the message above.
pause
exit /b 1
