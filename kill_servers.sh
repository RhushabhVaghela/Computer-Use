#!/bin/bash
echo "Killing WSL/Linux processes..."
pkill -f llama-server
pkill -f python
pkill -f vllm
echo "Killing Windows processes..."
cmd.exe /c "taskkill /f /im llama-server.exe 2>nul"
cmd.exe /c "taskkill /f /im python.exe 2>nul"
cmd.exe /c "taskkill /f /im python3.exe 2>nul"
echo "All requested processes have been killed."
