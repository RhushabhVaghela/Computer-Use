import asyncio
import time
import numpy as np
import sounddevice as sd

from speech_processor import ASRProcessor
from speech_processor import HiggsTTSProcessor as _HiggsTTSProcessor
from speech_processor import VADDetector

class AudioRecorder:
    def __init__(self, sample_rate=16000):
        self.sample_rate = sample_rate
        self.vad = VADDetector(sample_rate=sample_rate)

    def record_until_silence(self) -> np.ndarray:
        print("Listening...")
        q = []
        def callback(indata, frames, time_info, status):
            q.append(indata.copy())

        utterance = None
        with sd.InputStream(samplerate=self.sample_rate, channels=1, dtype='int16', callback=callback):
            while True:
                if q:
                    chunk = q.pop(0)
                    pcm_bytes = chunk.tobytes()
                    utterance = self.vad.process_chunk(pcm_bytes)
                    if utterance is not None:
                        break
                else:
                    time.sleep(0.01)
        return utterance

class WhisperASR:
    def __init__(self, model_size="turbo"):
        # map "turbo" to "large-v3-turbo"
        if model_size == "turbo":
            model_size = "large-v3-turbo"
        self.processor = ASRProcessor(model_size=model_size)

    def transcribe(self, audio_data: np.ndarray) -> str:
        return self.processor.transcribe(audio_data)

class HiggsTTS:
    def __init__(self, model_path=None):
        # We use the provided model_path as the model name since vllm-omni uses the exact path as the model ID
        if model_path is None:
            model_path = "/mnt/c/Users/Rhushabh/Documents/HuggingFace/Reza2kn/Higgs-Audio-v3-TTS-4bit-NVFP4"
        self.processor = _HiggsTTSProcessor(model_name=model_path)

    def speak(self, text: str):
        async def _speak():
            stream = sd.OutputStream(samplerate=24000, channels=1, dtype='int16')
            stream.start()
            try:
                async for chunk in self.processor.synthesize_stream(text):
                    # Strip 44 byte RIFF header
                    if len(chunk) > 44:
                        pcm_bytes = chunk[44:]
                        audio_data = np.frombuffer(pcm_bytes, dtype=np.int16)
                        stream.write(audio_data)
            finally:
                stream.stop()
                stream.close()

        loop = asyncio.get_event_loop()
        if loop.is_running():
            # Schedule in the background (will play while VLM thinks or after)
            loop.create_task(_speak())
        else:
            asyncio.run(_speak())
