import os
import sys
import torch
import struct
import json
import numpy as np
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response
from pydantic import BaseModel

# Safe import
try:
    from qwen_tts import Qwen3TTSModel
except ImportError:
    Qwen3TTSModel = None

from contextlib import asynccontextmanager

# Global model container
model = None

def load_model():
    global model
    model_name = os.environ.get("QWEN3_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-CustomVoice")
    print(f"Loading Qwen3 TTS Model '{model_name}' on GPU...")
    if Qwen3TTSModel is None:
        print("qwen-tts not installed in this environment.")
        return
    
    try:
        model = Qwen3TTSModel.from_pretrained(
            model_name,
            device_map="cuda:0" if torch.cuda.is_available() else "cpu",
            dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
        )
        speakers = model.get_supported_speakers()
        print(f"Qwen3 TTS Model loaded successfully. Supported speakers: {speakers}")
    except Exception as e:
        print(f"Failed to load Qwen3 TTS model: {e}")

@asynccontextmanager
async def lifespan(app: FastAPI):
    load_model()
    yield

app = FastAPI(title="Qwen3 TTS Bridge Server", lifespan=lifespan)

class TTSRequest(BaseModel):
    model: str
    input: str
    voice: str = "vivian"
    response_format: str = "wav"

@app.post("/v1/audio/speech")
@app.post("/audio/speech")
def speech(req: TTSRequest):
    global model
    if model is None:
        raise HTTPException(status_code=500, detail="TTS model not loaded.")
        
    try:
        voice_name = req.voice
        text = req.input
        
        # Try generate_custom_voice first (works with CustomVoice models)
        if hasattr(model, "generate_custom_voice"):
            try:
                wavs, sr = model.generate_custom_voice(text, speaker=voice_name)
            except (ValueError, TypeError) as e:
                # Fallback: if speaker isn't valid, use generate_voice_design
                if hasattr(model, "generate_voice_design"):
                    instruct = f"A clear, natural {voice_name} voice speaking at a moderate pace."
                    wavs, sr = model.generate_voice_design(text, instruct=instruct)
                else:
                    raise
        elif hasattr(model, "generate_voice_design"):
            instruct = f"A clear, natural {voice_name} voice speaking at a moderate pace."
            wavs, sr = model.generate_voice_design(text, instruct=instruct)
        else:
            raise HTTPException(status_code=500, detail="No valid generation method found on TTS model.")
            
        audio = wavs[0]
        if isinstance(audio, torch.Tensor):
            audio = audio.cpu().numpy()
            
        int16_audio = (audio * 32767.0).astype(np.int16)
        pcm_bytes = int16_audio.tobytes()
        
        # Create WAV header
        channels = 1
        byte_rate = sr * channels * 2
        block_align = channels * 2
        
        header = b'RIFF' + struct.pack('<I', 36 + len(pcm_bytes)) + b'WAVE'
        header += b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, sr, byte_rate, block_align, 16)
        header += b'data' + struct.pack('<I', len(pcm_bytes))
        
        wav_data = header + pcm_bytes
        return Response(content=wav_data, media_type="audio/wav")
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"TTS synthesis error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=9001)
