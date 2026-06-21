import os
import io
import queue
import wave
import time
import threading
import sounddevice as sd
import soundfile as sf
import numpy as np
from faster_whisper import WhisperModel
import sys

# Optional Higgs TTS (imported dynamically or wrapped in try/except)
try:
    import torch
    from transformers import AutoModelForCausalLM, AutoTokenizer
    HAS_TRANSFORMERS = True
except ImportError:
    HAS_TRANSFORMERS = False

class AudioRecorder:
    def __init__(self, sample_rate=16000, channels=1, silence_threshold=0.01, silence_duration=1.5):
        self.sample_rate = sample_rate
        self.channels = channels
        self.silence_threshold = silence_threshold
        self.silence_duration = silence_duration
        
    def record_until_silence(self) -> np.ndarray:
        """Records audio from the mic until silence is detected, returns numpy float32 array."""
        print("[Mic] Listening... (speak now)")
        audio_data = []
        silence_start_time = None
        
        # We process in small chunks (e.g., 0.1s)
        chunk_size = int(self.sample_rate * 0.1)
        
        with sd.InputStream(samplerate=self.sample_rate, channels=self.channels, dtype='float32') as stream:
            while True:
                chunk, _ = stream.read(chunk_size)
                audio_data.append(chunk)
                
                # Check for silence using RMS volume
                rms = np.sqrt(np.mean(chunk**2))
                if rms < self.silence_threshold:
                    if silence_start_time is None:
                        silence_start_time = time.time()
                    elif time.time() - silence_start_time > self.silence_duration:
                        # Only stop if we actually recorded some non-silence beforehand
                        if len(audio_data) > (self.silence_duration / 0.1) + 2:
                            break
                else:
                    silence_start_time = None

        print("[Mic] Stopped listening.")
        return np.concatenate(audio_data, axis=0).flatten()


class WhisperASR:
    def __init__(self, model_size="turbo"):
        print(f"[ASR] Loading Whisper {model_size}...")
        self.model = WhisperModel(model_size, device="auto", compute_type="default")
        print("[ASR] Whisper loaded.")
        
    def transcribe(self, audio_array: np.ndarray, sample_rate: int = 16000) -> str:
        # faster-whisper accepts numpy arrays directly (float32, 16kHz, mono)
        segments, info = self.model.transcribe(audio_array, beam_size=5, language="en")
        text = " ".join([segment.text for segment in segments]).strip()
        return text


class HiggsTTS:
    def __init__(self, model_path: str):
        if not HAS_TRANSFORMERS:
            raise ImportError("transformers and torch are required for HiggsTTS")
            
        print(f"[TTS] Loading Higgs TTS from {model_path}...")
        self.tokenizer = AutoTokenizer.from_pretrained(model_path, trust_remote_code=True)
        # For a 4B model, we use device_map="auto" to spread across GPU/CPU if needed
        self.model = AutoModelForCausalLM.from_pretrained(
            model_path, 
            device_map="auto", 
            trust_remote_code=True
        )
        print("[TTS] Higgs TTS loaded.")
        
    def speak(self, text: str):
        print(f"[TTS] Generating speech for: {text}")
        # Note: Higgs TTS API integration
        # Will implement generation block based on the specific model architecture 
        # (needs verification on how the Qwen3 multimodal accepts audio inputs/outputs)
        pass

