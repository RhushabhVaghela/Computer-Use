@echo off
echo Starting Local AI Models...
echo.

:: Start LLM (llama-server) in a new window
echo [1/2] Starting llama-server on port 8080 (Gemma 4 12B)...
start "LLM - llama-server" cmd /k "llama-server -m "C:\Users\Rhushabh\.lmstudio\models\unsloth\gemma-4-12B-it-qat-GGUF\gemma-4-12B-it-qat-UD-Q4_K_XL.gguf" --mmproj "C:\Users\Rhushabh\.lmstudio\models\unsloth\gemma-4-12B-it-qat-GGUF\mmproj-F32.gguf" -p 8080 -c 8192"

:: Start TTS (vllm-omni) in a new window
echo [2/2] Starting vllm-omni on port 8095 (Higgs-Audio-v3-TTS)...
start "TTS - vllm-omni" cmd /k "vllm-omni serve "C:\Users\Rhushabh\Documents\HuggingFace\Reza2kn\Higgs-Audio-v3-TTS-4bit-NVFP4" --host 0.0.0.0 --port 8095 --trust-remote-code --omni"

echo.
echo Both servers have been launched in separate windows!
echo Keep those windows open while running the Computer-Use agent.
pause
