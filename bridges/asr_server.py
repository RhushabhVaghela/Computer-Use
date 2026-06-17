import os
import sys
import torch
from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from pydantic import BaseModel

try:
    from qwen_asr import Qwen3ASRModel
except ImportError:
    Qwen3ASRModel = None

from contextlib import asynccontextmanager

# Global model container
asr_model = None

def load_model():
    global asr_model
    model_name = os.environ.get("QWEN3_ASR_MODEL", "Qwen/Qwen3-ASR-0.6B")
    print(f"Loading Qwen3 ASR Model '{model_name}' on GPU (if CUDA available)...")
    if Qwen3ASRModel is None:
        print("qwen-asr not installed in this environment.")
        return
        
    try:
        device_str = "cuda" if torch.cuda.is_available() else "cpu"
        dtype_val = torch.bfloat16 if torch.cuda.is_available() else torch.float32
        
        # Qwen3ASRModel.from_pretrained forwards kwargs to AutoModelForSpeechSeq2Seq
        asr_model = Qwen3ASRModel.from_pretrained(
            model_name,
            device_map=device_str,
            dtype=dtype_val
        )
        print(f"Qwen3 ASR Model loaded successfully on '{device_str}'.")
    except Exception as e:
        print(f"Failed to load Qwen3 ASR model: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield

app = FastAPI(title="Qwen3 ASR Bridge Server", lifespan=lifespan)

@app.post("/v1/audio/transcriptions")
@app.post("/audio/transcriptions")
async def transcribe(file: UploadFile = File(...), model: str = Form(None)):
    global asr_model
    if asr_model is None:
        raise HTTPException(status_code=500, detail="ASR model not loaded.")
        
    try:
        os.makedirs("scratch", exist_ok=True)
        temp_wav = f"scratch/temp_asr_bridge_{os.getpid()}.wav"
        contents = await file.read()
        with open(temp_wav, "wb") as f:
            f.write(contents)
            
        transcription_list = asr_model.transcribe(temp_wav)
        result_text = transcription_list[0].text if transcription_list else ""
        
        try:
            os.remove(temp_wav)
        except Exception:
            pass
            
        return {"text": result_text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ASR transcription error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9002)
