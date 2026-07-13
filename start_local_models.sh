#!/bin/bash

echo "========================================================"
echo "  Starting Local Models (Voice Mode)"
echo "========================================================"

# Start Llama Server in the background
echo "[1/2] Starting llama-server on port 8080 (Gemma-4-12B-it-qat)..."
llama-server -m "/mnt/c/Users/Rhushabh/.lmstudio/models/unsloth/gemma-4-12B-it-qat-GGUF/gemma-4-12B-it-qat-UD-Q4_K_XL.gguf" --mmproj "/mnt/c/Users/Rhushabh/.lmstudio/models/unsloth/gemma-4-12B-it-qat-GGUF/mmproj-F32.gguf" --port 8080 -c 8192 -ngl 99 &
LLM_PID=$!

# Start TTS (sgl-omni) in the background via WSL
echo "[2/2] Starting sgl-omni on port 8095 in WSL (Higgs-Audio-v3-TTS)..."
wsl -d Ubuntu bash -ic 'cd ~/sglang-omni && source .venv/bin/activate && sgl-omni serve --model-path /mnt/c/Users/Rhushabh/Documents/HuggingFace/Reza2kn/Higgs-Audio-v3-TTS-4bit-NVFP4 --host 0.0.0.0 --port 8095' &
TTS_PID=$!

echo
echo "All servers are running in the background."
echo "PIDs: LLM=$LLM_PID"
echo "You can now return to the Unified Launcher and select Voice Mode."
echo "========================================================"

# Keep the script running and trap Ctrl+C to close background processes cleanly
trap "echo -e '\nStopping servers...'; kill $LLM_PID $OV_PID $TTS_PID; exit" SIGINT SIGTERM
wait