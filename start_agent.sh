#!/bin/bash

echo "========================================================"
echo "  Computer-Use Agent Unified Launcher"
echo "========================================================"

# Check for virtual environment and activate it if present
if [ -f "./.venv/bin/activate" ]; then
    source "./.venv/bin/activate"
elif [ -f "./windows_env/Scripts/activate" ]; then
    source "./windows_env/Scripts/activate"
fi

# If arguments are passed, bypass the menu and run directly
if [ "$#" -gt 0 ]; then
    python src/run_agent.py "$@"
    exit 0
fi

# Interactive menu if no arguments are passed
echo ""
echo "Select a mode to run:"
echo "[1] Voice Mode (Local Llama-Server on Port 8080)"
echo "[2] Text Mode  (Custom Prompt)"
echo ""
read -p "Enter choice (1 or 2): " mode

if [ "$mode" == "1" ]; then
    echo ""
    echo "Starting Voice Agent..."
    python src/run_agent.py --provider local --api-base "http://127.0.0.1:8080/v1" --voice --force-fallback
elif [ "$mode" == "2" ]; then
    echo ""
    read -p "Enter your prompt for the agent: " user_prompt
    echo ""
    echo "Select Provider:"
    echo "[1] Local"
    echo "[2] Anthropic (Claude)"
    echo "[3] OpenAI"
    echo "[4] Gemini"
    read -p "Enter provider choice (1-4): " prov_choice
    
    prov="local"
    if [ "$prov_choice" == "1" ]; then prov="local"; fi
    if [ "$prov_choice" == "2" ]; then prov="anthropic"; fi
    if [ "$prov_choice" == "3" ]; then prov="openai"; fi
    if [ "$prov_choice" == "4" ]; then prov="gemini"; fi
    
    echo ""
    echo "Starting Text Agent with provider [$prov]..."
    python src/run_agent.py --provider "$prov" --prompt "$user_prompt"
else
    echo "Invalid choice. Exiting."
fi
