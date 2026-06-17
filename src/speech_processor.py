import os
import sys
import numpy as np
import logging
import urllib.request
from typing import Optional, List
import torch

# Configure logging
logger = logging.getLogger("speech-processor")

# Try importing dependencies
try:
    from faster_whisper import WhisperModel
except ImportError:
    logger.warning("faster-whisper not installed. ASR will not be functional.")
    WhisperModel = None

try:
    from kokoro_onnx import Kokoro
except ImportError:
    logger.warning("kokoro-onnx not installed. TTS will not be functional.")
    Kokoro = None


class ASRProcessor:
    """
    Handles local speech recognition using faster-whisper (large-v3-turbo).
    Runs on CUDA GPU for extremely fast, low-latency transcription.
    """
    def __init__(self, model_size: str = "base.en", device: str = "cuda"):
        self.model_size = model_size
        self.device = device  # Try forcing CUDA directly for faster_whisper
        self.model = None
        
        if WhisperModel:
            logger.info(f"Initializing Whisper model '{self.model_size}' on '{self.device}'...")
            # Run float16 on GPU, float32 or int8 on CPU
            compute_type = "float16" if self.device == "cuda" else "int8"
            try:
                self.model = WhisperModel(self.model_size, device=self.device, compute_type=compute_type)
                logger.info("Whisper model loaded successfully.")
            except Exception as e:
                logger.error(f"Error loading Whisper model on {self.device}: {e}. Falling back to CPU.")
                self.device = "cpu"
                self.model = WhisperModel(self.model_size, device=self.device, compute_type="int8")
                logger.info("Whisper CPU fallback model loaded successfully.")
        else:
            logger.error("WhisperModel is not available.")

    def transcribe(self, audio_data: np.ndarray, sample_rate: int = 16000) -> str:
        """
        Transcribes float32 numpy array audio data.
        """
        if not self.model:
            return ""
        
        try:
            # transcribe returns generator of (segments, info)
            segments, info = self.model.transcribe(audio_data, beam_size=1, language="en")
            text = " ".join([seg.text for seg in segments]).strip()
            return text
        except Exception as e:
            logger.error(f"Error transcribing audio: {e}")
            return ""


class VADDetector:
    """
    A pure-python RMS (Root Mean Square) energy-based Voice Activity Detector.
    Requires no native binaries or compiling steps, ensuring high reliability on Windows.
    """
    def __init__(self, threshold_db: float = -35.0, silence_duration_sec: float = 0.6, sample_rate: int = 16000):
        self.threshold = 10 ** (threshold_db / 20)  # Convert dB to amplitude
        self.silence_duration_frames = int(silence_duration_sec * sample_rate)
        
        self.speech_buffer = []
        self.is_speaking = False
        self.silence_counter = 0

    def process_chunk(self, pcm_bytes: bytes) -> Optional[np.ndarray]:
        """
        Processes a PCM audio chunk. 
        Returns full spoken utterance numpy array when speech ends, otherwise None.
        """
        # Convert bytes to float32 numpy array
        chunk = np.frombuffer(pcm_bytes, dtype=np.int16).astype(np.float32) / 32768.0
        if len(chunk) == 0:
            return None

        # Compute RMS energy
        rms = np.sqrt(np.mean(chunk**2) + 1e-10)
        
        if rms > self.threshold:
            if not self.is_speaking:
                self.is_speaking = True
                logger.info("Speech detected...")
            self.silence_counter = 0
            self.speech_buffer.append(chunk)
        else:
            if self.is_speaking:
                self.silence_counter += len(chunk)
                self.speech_buffer.append(chunk)
                
                if self.silence_counter >= self.silence_duration_frames:
                    # Speech ended
                    self.is_speaking = False
                    logger.info("Speech finished.")
                    full_utterance = np.concatenate(self.speech_buffer)
                    self.speech_buffer = []
                    self.silence_counter = 0
                    return full_utterance
        return None


class TTSProcessor:
    """
    Handles local speech synthesis using Kokoro-82M ONNX runner.
    Downloads the model files automatically if not present.
    """
    HF_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    HF_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

    def __init__(self, model_dir: str = "models/kokoro", default_voice: str = "af_bella"):
        self.model_dir = model_dir
        self.default_voice = default_voice
        self.kokoro = None
        
        os.makedirs(model_dir, exist_ok=True)
        
        self.model_path = os.path.join(model_dir, "kokoro-v1.0.onnx")
        self.voices_path = os.path.join(model_dir, "voices-v1.0.bin")
        
        self._ensure_files()
        
        if Kokoro:
            logger.info("Initializing Kokoro ONNX engine...")
            try:
                # Initialize kokoro-onnx with downloaded files
                self.kokoro = Kokoro(self.model_path, self.voices_path)
                logger.info("Kokoro ONNX engine initialized successfully.")
            except Exception as e:
                logger.error(f"Error initializing Kokoro: {e}")
        else:
            logger.error("Kokoro class is not available.")

    def _ensure_files(self):
        """Downloads the ONNX weights and voice binaries from HF if missing."""
        def download_file(url, path):
            logger.info(f"Downloading {url} to {path}...")
            try:
                # Track progress
                def progress(count, block_size, total_size):
                    percent = int(count * block_size * 100 / total_size)
                    sys.stderr.write(f"\rDownloading... {percent}%")
                    sys.stderr.flush()
                
                urllib.request.urlretrieve(url, path, reporthook=progress)
                sys.stderr.write("\n")
                logger.info("Download completed successfully.")
            except Exception as e:
                logger.error(f"Failed to download file: {e}")
                raise e

        if not os.path.exists(self.model_path):
            download_file(self.HF_MODEL_URL, self.model_path)
            
        if not os.path.exists(self.voices_path):
            download_file(self.HF_VOICES_URL, self.voices_path)

    def synthesize(self, text: str, voice: str = None) -> Optional[tuple]:
        """
        Synthesizes text into audio.
        Returns:
            (audio_samples: np.ndarray, sample_rate: int) or None
        """
        if not self.kokoro:
            logger.error("Kokoro TTS is not loaded.")
            return None
            
        voice_name = voice or self.default_voice
        try:
            logger.info(f"Synthesizing text: '{text}' using voice '{voice_name}'...")
            samples, sr = self.kokoro.create(text, voice=voice_name, speed=1.0, lang="en-us")
            return samples, sr
        except Exception as e:
            logger.error(f"Error in TTS synthesis: {e}")
            return None

    async def synthesize_stream(self, text: str, voice: str = None):
        import struct
        voice_name = voice or self.default_voice
        
        if not self.kokoro:
            return
            
        try:
            # Yield audio chunks dynamically as Kokoro streams them
            async for samples, sr in self.kokoro.create_stream(text, voice=voice_name, speed=1.0, lang="en-us"):
                int16_audio = (samples * 32767.0).astype(np.int16)
                pcm_bytes = int16_audio.tobytes()
                
                # Standard WAV header per chunk so browser decodeAudioData can parse it
                channels = 1
                byte_rate = sr * channels * 2
                block_align = channels * 2
                
                header = b'RIFF' + struct.pack('<I', 36 + len(pcm_bytes)) + b'WAVE'
                header += b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, sr, byte_rate, block_align, 16)
                header += b'data' + struct.pack('<I', len(pcm_bytes))
                
                yield header + pcm_bytes
        except Exception as e:
            logger.error(f"Error in Kokoro TTS streaming: {e}")


class EdgeTTSProcessor:
    """
    Ultra-fast online TTS using Microsoft Edge's Read Aloud API.
    Does not require local GPU/CPU resources for inference.
    """
    def __init__(self, default_voice: str = "en-US-AndrewNeural"):
        self.default_voice = default_voice
        try:
            import edge_tts
            self.edge_tts = edge_tts
            logger.info("EdgeTTSProcessor initialized successfully.")
        except ImportError:
            logger.error("edge-tts not installed. Cannot use EdgeTTSProcessor.")
            self.edge_tts = None

    async def synthesize_stream(self, text: str, voice: str = None):
        """
        Synthesizes text into raw MP3 audio bytes asynchronously and yields chunks dynamically.
        """
        if not self.edge_tts:
            logger.error("edge-tts is not loaded.")
            return
            
        voice_name = voice or self.default_voice
        try:
            logger.info(f"Synthesizing text via Edge-TTS: '{text}' using voice '{voice_name}'...")
            communicate = self.edge_tts.Communicate(text, voice_name)
            async for chunk in communicate.stream():
                if chunk["type"] == "audio":
                    yield chunk["data"]
        except Exception as e:
            logger.error(f"Error in Edge-TTS synthesis: {e}")

class KittenTTSProcessor:
    """
    Ultra-fast local TTS using KittenTTS ONNX.
    """
    def __init__(self, model_id: str = "KittenML/kitten-tts-mini-0.8", default_voice: str = "Jasper"):
        self.default_voice = default_voice
        try:
            from kittentts import KittenTTS
            self.model = KittenTTS(model_id)
            logger.info("KittenTTSProcessor initialized successfully.")
        except ImportError:
            logger.error("kittentts not installed. Cannot use KittenTTSProcessor.")
            self.model = None

    async def synthesize_stream(self, text: str, voice: str = None):
        import struct
        import asyncio
        import numpy as np
        
        if not self.model:
            logger.error("KittenTTS is not loaded.")
            return
            
        voice_name = voice or self.default_voice
        try:
            logger.info(f"Synthesizing text via KittenTTS: '{text}' using voice '{voice_name}'...")
            # Generate audio synchronously using a thread to avoid blocking the event loop
            audio = await asyncio.to_thread(self.model.generate, text, voice=voice_name)
            
            # audio is a numpy float array. Convert to 16-bit PCM
            int16_audio = (audio * 32767.0).astype(np.int16)
            pcm_bytes = int16_audio.tobytes()
            
            sr = 24000
            channels = 1
            byte_rate = sr * channels * 2
            block_align = channels * 2
            
            header = b'RIFF' + struct.pack('<I', 36 + len(pcm_bytes)) + b'WAVE'
            header += b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, sr, byte_rate, block_align, 16)
            header += b'data' + struct.pack('<I', len(pcm_bytes))
            
            # Chunk the output slightly to simulate streaming, or just send the whole file
            # Since KittenTTS is fast, yielding the full WAV in one go is fine!
            chunk_size = 8192
            full_data = header + pcm_bytes
            for i in range(0, len(full_data), chunk_size):
                yield full_data[i:i+chunk_size]
            
        except Exception as e:
            logger.error(f"Error in KittenTTS synthesis: {e}")

class SupertonicTTSProcessor:
    """
    Local TTS using Supertone Supertonic-3
    """
    def __init__(self, default_voice: str = "F1"):
        self.default_voice = default_voice
        try:
            from supertonic import TTS
            # auto_download=True will download the ~400MB model on first run
            self.model = TTS(auto_download=True)
            logger.info("SupertonicTTSProcessor initialized successfully.")
        except ImportError:
            logger.error("supertonic not installed. Cannot use SupertonicTTSProcessor.")
            self.model = None

    async def synthesize_stream(self, text: str, voice: str = None):
        import struct
        import asyncio
        import numpy as np
        
        if not self.model:
            logger.error("Supertonic is not loaded.")
            return
            
        voice_name = voice or self.default_voice
        try:
            logger.info(f"Synthesizing text via Supertonic: '{text}' using voice '{voice_name}'...")
            
            # The model requires the style object
            style = self.model.get_voice_style(voice_name=voice_name)
            
            # Generate audio synchronously using a thread to avoid blocking the event loop
            audio, _ = await asyncio.to_thread(self.model.synthesize, text, voice_style=style, lang="en")
            
            # audio is usually a numpy float array
            int16_audio = (audio * 32767.0).astype(np.int16)
            pcm_bytes = int16_audio.tobytes()
            
            sr = getattr(self.model, 'sample_rate', 24000) # Try to get native sample rate, fallback to 24k
            channels = 1
            byte_rate = sr * channels * 2
            block_align = channels * 2
            
            header = b'RIFF' + struct.pack('<I', 36 + len(pcm_bytes)) + b'WAVE'
            header += b'fmt ' + struct.pack('<IHHIIHH', 16, 1, channels, sr, byte_rate, block_align, 16)
            header += b'data' + struct.pack('<I', len(pcm_bytes))
            
            chunk_size = 8192
            full_data = header + pcm_bytes
            for i in range(0, len(full_data), chunk_size):
                yield full_data[i:i+chunk_size]
            
        except Exception as e:
            logger.error(f"Error in Supertonic synthesis: {e}")


