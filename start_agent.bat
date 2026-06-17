@echo off
setlocal enabledelayedexpansion

:: Check for virtual environment and activate it if present
if exist "%~dp0.venv\Scripts\activate.bat" (
    call "%~dp0.venv\Scripts\activate.bat"
)

:: Forward all arguments to the runner script
python "%~dp0src\run_agent.py" %*
