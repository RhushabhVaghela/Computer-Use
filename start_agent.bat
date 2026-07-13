@echo off
setlocal enabledelayedexpansion

echo ========================================================
echo   Computer-Use Agent Unified Launcher
echo ========================================================

:: Check for virtual environment and activate it if present
if exist "%~dp0windows_env\Scripts\activate.bat" (
    call "%~dp0windows_env\Scripts\activate.bat"
) else if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
)

:: If arguments are passed, bypass the menu and run directly
if not "%~1"=="" (
    python "%~dp0src\run_agent.py" %*
    goto :eof
)

:: Interactive menu if no arguments are passed
echo.
echo Select a mode to run:
echo [1] Voice Mode (Local Llama-Server on Port 8080)
echo [2] Text Mode  (Custom Prompt)
echo.
set /p mode="Enter choice (1 or 2): "

if "%mode%"=="1" (
    echo.
    echo Starting Real-Time Voice WebSocket Server...
    start "Realtime Voice Web UI" cmd /c "timeout /t 2 >nul && start """" "%~dp0tests\voice_client.html""
    python "%~dp0src\voice_server.py"
) else if "%mode%"=="2" (
    echo.
    set /p user_prompt="Enter your prompt for the agent: "
    echo.
    echo Select Provider:
    echo [1] Local
    echo [2] Anthropic (Claude)
    echo [3] OpenAI
    echo [4] Gemini
    set /p prov_choice="Enter provider choice (1-4): "
    
    if "!prov_choice!"=="1" set prov=local
    if "!prov_choice!"=="2" set prov=anthropic
    if "!prov_choice!"=="3" set prov=openai
    if "!prov_choice!"=="4" set prov=gemini
    
    if "!prov!"=="" set prov=local
    
    echo.
    echo Starting Text Agent with provider [!prov!]...
    python "%~dp0src\run_agent.py" --provider !prov! --prompt "!user_prompt!"
) else (
    echo Invalid choice. Exiting.
)
