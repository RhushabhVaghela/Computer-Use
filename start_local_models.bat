@echo off
echo ========================================================
echo   Starting Local Models (Voice Mode)
echo ========================================================

:: Start LLM (llama-server) in a new window
echo [1/2] Starting llama-server on port 8080 (Gemma 4 12B)...
start "LLM - llama-server" cmd /k llama-server -m "C:\Users\Rhushabh\.lmstudio\models\unsloth\gemma-4-12B-it-qat-GGUF\gemma-4-12B-it-qat-UD-Q4_K_XL.gguf" --mmproj "C:\Users\Rhushabh\.lmstudio\models\unsloth\gemma-4-12B-it-qat-GGUF\mmproj-F32.gguf" --port 8080 -c 8192 -ngl 99


:: Start TTS (sgl-omni) in a new window via WSL
echo [2/2] Starting sgl-omni on port 8095 in WSL (Higgs-Audio-v3-TTS)...
start "TTS - WSL sgl-omni" wsl -d Ubuntu bash -ic "cd ~/sglang-omni && source .venv/bin/activate && sgl-omni serve --model-path /mnt/c/Users/Rhushabh/Documents/HuggingFace/Reza2kn/Higgs-Audio-v3-TTS-4bit-NVFP4 --host 0.0.0.0 --port 8095 --disable-cuda-graph --mem-fraction-static 0.6; exec bash"

echo.
echo All servers have been launched in separate windows!
echo You can now return to the Unified Launcher and select Voice Mode.
echo ========================================================
pause