@echo off
setlocal enabledelayedexpansion

echo ============================================================
echo   Open Interpreter Computer-Use MCP Server - Setup
echo ============================================================
echo.

set "PROJECT_DIR=%~dp0.."
cd /d "%PROJECT_DIR%"

:: --------------------------------------------------------
:: Step 1: Create virtual environment
:: --------------------------------------------------------
if not exist ".venv" (
    echo [1/4] Creating virtual environment...
    python -m venv .venv
    if errorlevel 1 (
        echo ERROR: Failed to create virtual environment.
        echo Make sure Python 3.11+ is installed and in PATH.
        pause
        exit /b 1
    )
) else (
    echo [1/4] Virtual environment already exists.
)

call .venv\Scripts\activate

:: --------------------------------------------------------
:: Step 2: Install dependencies
:: --------------------------------------------------------
echo [2/4] Installing dependencies...
pip install -r requirements.txt -q
if errorlevel 1 (
    echo ERROR: Failed to install dependencies.
    pause
    exit /b 1
)

:: --------------------------------------------------------
:: Step 3: Relax Open Interpreter constraints
:: --------------------------------------------------------
:: Default
set "OI_PATH=d:\Agents-and-other-repos\open-interpreter"

:: Read from .env if it exists
if exist ".env" (
    for /f "usebackq tokens=1,2 delims==" %%a in (".env") do (
        set "key=%%a"
        set "val=%%b"
        :: Strip quotes from val
        set "val=!val:"=!"
        
        if "!key!"=="OI_PATH_WIN" (
            set "OI_PATH=!val!"
        ) else if "!key!"=="OI_PATH" (
            :: Only set if not already set by OI_PATH_WIN
            if not defined OI_PATH_SET_BY_WIN (
                set "OI_PATH=!val!"
            )
        )
        
        if "!key!"=="OI_PATH_WIN" set "OI_PATH_SET_BY_WIN=1"
    )
)

echo.
echo [3/4] Relaxing Python version constraints in pyproject.toml...
echo       Target: "!OI_PATH!"

:: Check if OI directory exists
if not exist "!OI_PATH!" (
    echo ERROR: Open Interpreter not found at !OI_PATH!
    echo Please set OI_PATH in your .env file.
    pause
    exit /b 1
)

set "PYPROJECT=!OI_PATH!\pyproject.toml"
if exist "!PYPROJECT!" (
    :: Write a temp PowerShell script to avoid cmd escaping issues with spaces in paths
    > "%TEMP%\fix_pyproject.ps1" (
        echo $f = Get-Content -Raw -LiteralPath '!PYPROJECT!'
        echo $f = $f -replace 'python = ">=3\.9,<3\.13"', 'python = ">=3.9"'
        echo $f = $f -replace 'tiktoken = "\^0\.7\.0"', 'tiktoken = ">=0.8.0"'
        echo $f = $f -replace 'starlette = "\^0\.37\.2"', 'starlette = ">=0.37.2"'
        echo Set-Content -LiteralPath '!PYPROJECT!' -Value $f -NoNewline
    )
    powershell -ExecutionPolicy Bypass -File "%TEMP%\fix_pyproject.ps1"
    del "%TEMP%\fix_pyproject.ps1" 2>nul
    echo       Done.
)

:: --------------------------------------------------------
:: Step 4: Install Open Interpreter
:: --------------------------------------------------------
echo.
echo [4/5] Installing Open Interpreter core dependencies...

:: Ensure build backend tools exist (for pyproject.toml)
pip install "setuptools" "poetry-core" -q

:: Fix certifi if it was installed by conda (no RECORD file)
pip install --force-reinstall --no-deps certifi -q 2>nul

:: Editable install of your local Open Interpreter repo
pip install -e "!OI_PATH![os]" -q
if errorlevel 1 (
    echo.
    echo ERROR: Failed to install Open Interpreter dependencies.
    pause
    exit /b 1
)
echo       Open Interpreter installed successfully.

:: --------------------------------------------------------
:: Step 5: Install Playwright
:: --------------------------------------------------------
echo.
echo [5/5] Installing Playwright browsers for DOM analysis...
playwright install chromium
if errorlevel 1 (
    echo WARNING: Playwright installation failed. Browser DOM tools may not work.
)

echo.
echo ============================================================
echo   Setup complete! Start the server with:
echo.
echo     scripts\\start.bat --stdio
echo.
echo   New Features:
echo     - Coordinate accuracy fixed (DPI alignment)
echo     - Hierarchical UI Tree (read_screen_ui)
echo     - Browser-use DOM integration (browser_use_dom)
echo.
echo   Browser Integration:
echo     Agent can launch browsers correctly via 'browser_action'.
echo     To use already open browser, restart it with:
echo        chrome.exe --remote-debugging-port=9222
echo ============================================================
echo.
pause
