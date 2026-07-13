@echo off
echo Killing Windows processes...
taskkill /f /im llama-server.exe 2>nul
taskkill /f /im python.exe 2>nul
taskkill /f /im python3.exe 2>nul
echo Killing WSL processes...
wsl -d Ubuntu -e bash -c "pkill -f llama-server; pkill -f python; pkill -f vllm"
echo All requested processes have been killed.
pause
