#!/bin/bash
set -e

echo "===================================================="
echo " Setting up vLLM-Omni in WSL for Higgs Audio V3 TTS"
echo "===================================================="

# 1. Provide the missing custom architecture files to your local model directory
MODEL_DIR="/mnt/c/Users/Rhushabh/Documents/HuggingFace/Reza2kn/Higgs-Audio-v3-TTS-4bit-NVFP4"
echo "[1/4] Downloading missing architecture files to model directory..."
wget -q -nc -O "$MODEL_DIR/configuration_higgs.py" "https://huggingface.co/bosonai/higgs-audio-v3-tts-4b/resolve/main/configuration_higgs.py" || echo "configuration_higgs.py already exists."
wget -q -nc -O "$MODEL_DIR/modeling_higgs.py" "https://huggingface.co/bosonai/higgs-audio-v3-tts-4b/resolve/main/modeling_higgs.py" || echo "modeling_higgs.py already exists."

# 2. Setup project-local uv environment
echo "[2/4] Verifying Python environment (uv)..."

ENV_DIR="$HOME/wsl_env"
echo "Creating uv virtual environment at $ENV_DIR..."
uv venv --python 3.12 "$ENV_DIR"

echo "Activating virtual environment..."
source "$ENV_DIR/bin/activate"

# 3. Install nvcc / CUDA toolkit if necessary for building extensions
echo "[3/4] Checking CUDA compiler (nvcc)..."
if ! command -v nvcc &> /dev/null
then
    echo "nvcc not found. Installing nvidia-cuda-toolkit..."
    sudo apt update
    sudo apt install -y nvidia-cuda-toolkit
fi

# 4. Install vLLM and vLLM-Omni
echo "[4/4] Compiling and installing vLLM and vLLM-Omni using uv (This may take a while)..."
uv pip install vllm
uv pip install git+https://github.com/vllm-project/vllm-omni.git

echo ""
echo "===================================================="
echo " Setup Complete! "
echo " You can now close this WSL window."
echo " Use 'start_local_models.bat' in Windows to launch the servers."
echo "===================================================="
