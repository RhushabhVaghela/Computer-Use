@echo off
setlocal enabledelayedexpansion

set "PROJECT_DIR=%~dp0.."
cd /d "%PROJECT_DIR%"

:: Activate venv
if not exist ".venv" (
    echo [ERROR]: Virtual environment not found. Please run scripts\setup.bat first.
    pause
    exit /b 1
)
call .venv\Scripts\activate

:: Check for arguments
set "ARGS=%*"
if "%ARGS%"=="" (
    echo [INFO]: No transport specified, defaulting to stdio mode.
    set "ARGS=--stdio"
)

:: Check for hybrid flag
set "SERVER_SCRIPT=src\server.py"
echo %ARGS% | findstr /i "--hybrid" >nul
if %errorlevel% == 0 (
    set "SERVER_SCRIPT=src\hybrid_server.py"
    :: Remove --hybrid from args to avoid passing it to FastMCP
    set "ARGS=!ARGS:--hybrid=!"
)

echo.
echo ============================================================
echo   OI Computer-Use Server Launching
echo   Mode: %SERVER_SCRIPT%
echo   Args: %ARGS%
echo ============================================================
echo.

python %SERVER_SCRIPT% %ARGS%

if %errorlevel% neq 0 (
    echo.
    echo [ERROR]: Server stopped with exit code %errorlevel%
    pause
)
