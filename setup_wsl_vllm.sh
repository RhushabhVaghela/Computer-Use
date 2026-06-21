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

# 2. Check for python/conda
echo "[2/4] Verifying Python environment..."
if ! command -v conda &> /dev/null
then
    echo "Conda not found. Setting up a standard python venv..."
    sudo apt update
    sudo apt install -y python3.10-venv python3-pip git
    python3 -m venv ~/vllm_env
    source ~/vllm_env/bin/activate
else
    echo "Conda found. Creating 'vllm-omni' environment..."
    conda create -n vllm-omni python=3.10 -y || true
    # Conda activate in bash scripts requires sourcing the profile
    source $(conda info --base)/etc/profile.d/conda.sh
    conda activate vllm-omni
fi

# 3. Install nvcc / CUDA toolkit if necessary for building extensions
echo "[3/4] Checking CUDA compiler (nvcc)..."
if ! command -v nvcc &> /dev/null
then
    echo "nvcc not found. Installing nvidia-cuda-toolkit..."
    sudo apt install -y nvidia-cuda-toolkit
fi

# 4. Install vLLM-Omni
echo "[4/4] Compiling and installing vLLM-Omni from source (This may take 15-20 minutes)..."
pip install --upgrade pip
pip install git+https://github.com/vllm-project/vllm-omni.git

echo ""
echo "===================================================="
echo " Setup Complete! "
echo " You can now close this WSL window."
echo " Use 'start_local_models.bat' in Windows to launch the servers."
echo "===================================================="
