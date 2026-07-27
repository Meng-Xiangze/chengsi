@echo off
setlocal EnableExtensions EnableDelayedExpansion
cd /d "%~dp0"
set "ROOT=%~dp0"
set "ROOT=%ROOT:~0,-1%"
set "VENV_PYTHON=%ROOT%\.venv\Scripts\python.exe"
set "NEEDS_SETUP=0"
set "BOOTSTRAP_PYTHON="
set "BOOTSTRAP_PYTHON_IS_PATH=0"
set "APP_ARGS=%*"

if /i "%~1"=="--setup" (
    set "NEEDS_SETUP=1"
    set "APP_ARGS="
)
if not exist "%VENV_PYTHON%" set "NEEDS_SETUP=1"
if exist "%VENV_PYTHON%" "%VENV_PYTHON%" -m pip --version >nul 2>nul
if errorlevel 1 set "NEEDS_SETUP=1"
if "%NEEDS_SETUP%"=="0" "%VENV_PYTHON%" -c "import requests, yaml, webview, PIL, ddgs, bs4, win32clipboard, win32con" >nul 2>nul
if errorlevel 1 set "NEEDS_SETUP=1"
if exist "%ROOT%\.venv\pyvenv.cfg" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%ROOT%\.venv\pyvenv.cfg") do (
        if /i "%%A"=="executable " (
            set "CFG_EXECUTABLE=%%B"
            set "CFG_EXECUTABLE=!CFG_EXECUTABLE:~1!"
            if not exist "!CFG_EXECUTABLE!" set "NEEDS_SETUP=1"
        )
    )
)

if "%NEEDS_SETUP%"=="1" call :setup
if errorlevel 1 goto :error

call :check_webview2
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
call "%ROOT%\chengsi.bat" %APP_ARGS%
if errorlevel 1 goto :error
exit /b 0

:setup
if exist "%ROOT%\.venv" if not exist "%ROOT%\.venv\pyvenv.cfg" (
    rmdir /s /q "%ROOT%\.venv"
)
if exist "%ROOT%\.venv\pyvenv.cfg" (
    for /f "usebackq tokens=1,* delims==" %%A in ("%ROOT%\.venv\pyvenv.cfg") do (
        if /i "%%A"=="executable " (
            set "CFG_EXECUTABLE=%%B"
            set "CFG_EXECUTABLE=!CFG_EXECUTABLE:~1!"
            if not exist "!CFG_EXECUTABLE!" (
                echo Removing virtual environment created on another computer...
                rmdir /s /q "%ROOT%\.venv"
            )
        )
    )
)
if defined CHENGSI_PYTHON (
    if not exist "%CHENGSI_PYTHON%" (
        echo CHENGSI_PYTHON does not point to an existing Python executable:
        echo "%CHENGSI_PYTHON%"
        exit /b 1
    )
    set "BOOTSTRAP_PYTHON=%CHENGSI_PYTHON%"
    set "BOOTSTRAP_PYTHON_IS_PATH=1"
) else (
    where py >nul 2>nul
    if not errorlevel 1 (
        set "BOOTSTRAP_PYTHON=py -3"
    ) else (
        where python >nul 2>nul
        if errorlevel 1 (
            echo Python 3.10 or newer is required.
            echo Download it from https://www.python.org/downloads/
            exit /b 1
        )
        set "BOOTSTRAP_PYTHON=python"
    )
)

if not exist "%ROOT%\.venv\Scripts\python.exe" (
    echo Creating virtual environment...
    if "%BOOTSTRAP_PYTHON_IS_PATH%"=="1" (
        "%BOOTSTRAP_PYTHON%" -m venv "%ROOT%\.venv"
    ) else (
        %BOOTSTRAP_PYTHON% -m venv "%ROOT%\.venv"
    )
    if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -m pip --version >nul 2>nul
if errorlevel 1 (
    echo Restoring pip in the virtual environment...
    "%VENV_PYTHON%" -m ensurepip --upgrade
    if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -c "import sys; raise SystemExit(0 if sys.version_info >= (3, 10) else 1)"
if errorlevel 1 (
    echo Python 3.10 or newer is required for this environment.
    exit /b 1
)

echo Installing dependencies...
"%VENV_PYTHON%" -m pip install -r "%ROOT%\requirements.txt"
if errorlevel 1 (
    echo Standard HTTPS installation failed. Retrying with PyPI certificate checks bypassed...
    "%VENV_PYTHON%" -m pip install -r "%ROOT%\requirements.txt" --trusted-host pypi.org --trusted-host files.pythonhosted.org
    if errorlevel 1 exit /b 1
)

"%VENV_PYTHON%" -c "import requests, yaml, webview, PIL, ddgs, bs4, win32clipboard, win32con"
if errorlevel 1 (
    echo Dependency verification failed. Some required packages are still unavailable.
    exit /b 1
)
exit /b 0

:check_webview2
call :detect_webview2
if "%WEBVIEW2_FOUND%"=="1" exit /b 0

echo Microsoft Edge WebView2 Runtime is required for the Chengsi interface.
echo Attempting installation with winget...
where winget >nul 2>nul
if not errorlevel 1 winget install --id Microsoft.EdgeWebView2Runtime --exact --silent --accept-package-agreements --accept-source-agreements
call :detect_webview2
if "%WEBVIEW2_FOUND%"=="1" exit /b 0

echo winget did not install WebView2. Downloading the official Evergreen x64 installer...
set "WEBVIEW2_INSTALLER=%TEMP%\MicrosoftEdgeWebView2Runtime.exe"
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ProgressPreference='SilentlyContinue'; Invoke-WebRequest -UseBasicParsing -Uri 'https://go.microsoft.com/fwlink/?linkid=2124703' -OutFile $env:WEBVIEW2_INSTALLER"
if exist "%WEBVIEW2_INSTALLER%" "%WEBVIEW2_INSTALLER%" /silent /install
call :detect_webview2
if "%WEBVIEW2_FOUND%"=="1" exit /b 0

echo WebView2 Runtime installation failed or was blocked.
echo Install it from: https://developer.microsoft.com/microsoft-edge/webview2/
exit /b 1

:detect_webview2
set "WEBVIEW2_FOUND=0"
for %%K in ("HKLM\SOFTWARE\Microsoft\EdgeUpdate\Clients" "HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients" "HKCU\Software\Microsoft\EdgeUpdate\Clients") do (
    reg query %%K /s /f pv 2>nul | findstr /i "pv" >nul
    if not errorlevel 1 set "WEBVIEW2_FOUND=1"
)
for %%P in ("%ProgramFiles%\Microsoft\EdgeWebView\Application" "%ProgramFiles(x86)%\Microsoft\EdgeWebView\Application" "%LOCALAPPDATA%\Microsoft\EdgeWebView\Application") do (
    if exist "%%~P" dir /s /b "%%~P\msedgewebview2.exe" 2>nul | findstr /i "msedgewebview2.exe" >nul
    if not errorlevel 1 set "WEBVIEW2_FOUND=1"
)
exit /b 0

:error
echo.
echo Chengsi startup failed. Review the message above.
pause
exit /b 1
