import os
import sys
import json
import asyncio
import logging
import base64
from io import BytesIO
from PIL import Image
import numpy as np
import websockets
from websockets.server import ServerConnection
from websockets.server import serve



# Add parent path to import src modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from run_agent import call_openai_compatible, get_mcp_params, to_openai_tools, format_tool_content_for_role, prune_message_history
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from speech_processor import (
    ASRProcessor, VADDetector, TTSProcessor, EdgeTTSProcessor, 
    KittenTTSProcessor, SupertonicTTSProcessor, Qwen3ASRProcessor, Qwen3TTSProcessor
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stderr)]
)
logger = logging.getLogger("voice-server")

# Global toggle to use native multimodal VLM audio input instead of Whisper
# Global toggle to use native multimodal VLM audio input instead of Whisper
USE_NATIVE_AUDIO = False

class LowLatencyVoiceServer:
    def __init__(self, host: str = "0.0.0.0", port: int = 8086, api_base: str = None, vlm_model_name: str = None):
        self.host = host
        self.port = port
        self.api_base = os.environ.get("VLM_API_BASE", api_base or "http://127.0.0.1:8080/v1")
        self.vlm_model_name = os.environ.get("VLM_MODEL_NAME", vlm_model_name or "gpt-4o")
        
        # Determine engines from environment variables
        asr_engine = os.environ.get("ASR_ENGINE", "qwen3").lower()
        tts_engine = os.environ.get("TTS_ENGINE", "qwen3").lower()
        
        # ASR Initialization
        if asr_engine == "qwen3":
            qwen3_asr_model = os.environ.get("QWEN3_ASR_MODEL", "Qwen/Qwen3-ASR-0.6B")
            qwen3_asr_endpoint = os.environ.get("QWEN3_ASR_ENDPOINT", None)
            self.asr = Qwen3ASRProcessor(model_size_or_name=qwen3_asr_model, remote_url=qwen3_asr_endpoint)
        else:
            self.asr = ASRProcessor(model_size="large-v3-turbo")
            
        self.vad = VADDetector()
        
        # TTS Initialization
        if tts_engine == "qwen3":
            qwen3_tts_model = os.environ.get("QWEN3_TTS_MODEL", "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
            qwen3_tts_endpoint = os.environ.get("QWEN3_TTS_ENDPOINT", None)
            self.tts = Qwen3TTSProcessor(model_name=qwen3_tts_model, remote_url=qwen3_tts_endpoint)
        elif tts_engine == "kokoro":
            self.tts = TTSProcessor()
        elif tts_engine == "edge-tts":
            self.tts = EdgeTTSProcessor()
        elif tts_engine == "kittentts":
            self.tts = KittenTTSProcessor()
        else:
            self.tts = SupertonicTTSProcessor()
        
        # Shared states
        self.latest_frame_b64: Optional[str] = None
        self.active_session: Optional[ClientSession] = None
        self.mcp_tools = []
        self.conversation_history = []
        self.system_prompt = ""
        self.is_processing = False
        self.current_vlm_task = None

    async def run(self):
        server_params = get_mcp_params(hybrid=False)
        server_params.env["MCP_COORD_GRID"] = "1000"
        logger.info("Connecting to MCP tool server...")
        
        self.system_prompt = (
            "You are a real-time conversational voice assistant and a desktop control agent.\n"
            "You observe the user's desktop screen and respond to their speech instructions.\n"
            "Ensure you keep your spoken replies extremely concise, clear, and friendly.\n"
            "CRITICAL LATENCY INSTRUCTION: YOU ARE RUNNING IN A ZERO-LATENCY MODE. DO NOT output any internal monologue, thought process, numbered lists, or step-by-step analysis in your response. "
            "YOUR ENTIRE TEXT RESPONSE MUST BE A SINGLE, SHORT, SPOKEN SENTENCE. If you are waiting for a command, say 'I am ready.'\n"
            "CRITICAL CONVERSATIONAL INSTRUCTION: If the user asks you a conversational question (like 'How are you?'), answer them conversationally! DO NOT blindly type their question into the screen's text boxes!\n"
            "To interact with screen elements, use the 'computer' or 'read_screen_ui' tools.\n"
            "COORDINATES: You MUST output coordinates on a normalized 1000x1000 grid, where [0, 0] is top-left and [1000, 1000] is bottom-right. E.g. [500, 500] is the center. I will scale them to pixels for you.\n"
            "KEYS: When using the 'key' action, YOU MUST USE EXACT ENGLISH PYAUTOGUI KEY NAMES (e.g., 'win+d', 'enter', 'ctrl+s', 'alt+tab'). NEVER use non-English or translated key names (like '윈도우 키').\n"
            "ACTIVE WINDOW & FOCUS MONITORING:\n"
            "- Monitor the `[Active Window]` metadata in the tool results.\n"
            "- If the target window becomes minimized or loses focus, click its taskbar icon or use 'alt+tab' to restore it before typing or clicking."
        )
        
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                self.active_session = session
                
                mcp_tools_list = await session.list_tools()
                self.mcp_tools = to_openai_tools(mcp_tools_list.tools)
                logger.info(f"Connected to MCP server. {len(self.mcp_tools)} tools registered.")
                
                logger.info(f"Starting low-latency WebSocket Voice Server on ws://{self.host}:{self.port}...")
                async with websockets.serve(self.handler, self.host, self.port):
                    await asyncio.Future()  # run forever

    async def telemetry_loop(self, history: list, websocket: ServerConnection):
        """Monitors system changes and injects passive telemetry into the history."""
        if not pyautogui or not win32gui:
            return
            
        # Hide PyAutoGUI fail-safe to prevent accidental crashes during passive monitoring
        pyautogui.FAILSAFE = False
            
        last_mouse = pyautogui.position()
        try:
            last_window = win32gui.GetWindowText(win32gui.GetForegroundWindow())
        except Exception:
            last_window = ""
            
        last_frame_np = None
        last_frame_b64 = None
            
        while True:
            await asyncio.sleep(1.0) # Poll every 1 second
            try:
                current_mouse = pyautogui.position()
                try:
                    current_window = win32gui.GetWindowText(win32gui.GetForegroundWindow())
                except Exception:
                    current_window = ""
                
                events = []
                
                # Active window change
                if current_window != last_window and current_window.strip():
                    events.append(f"Active window changed to: '{current_window}'")
                    last_window = current_window
                    
                # Mouse movement (threshold 20 pixels to ignore micro-jitters)
                if abs(current_mouse.x - last_mouse.x) > 20 or abs(current_mouse.y - last_mouse.y) > 20:
                    events.append(f"Mouse manually moved to ({current_mouse.x}, {current_mouse.y})")
                    last_mouse = current_mouse
                    
                # Visual screen change (MSE diff)
                if self.latest_frame_b64 and self.latest_frame_b64 != last_frame_b64:
                    try:
                        img_data = base64.b64decode(self.latest_frame_b64)
                        img = Image.open(BytesIO(img_data)).convert('L')
                        img_np = np.array(img).astype(np.float32)
                        
                        if last_frame_np is not None:
                            mse = np.mean((img_np - last_frame_np) ** 2)
                            # MSE > 200 usually indicates a notable visual change (scroll, new UI, etc.)
                            if mse > 200:
                                events.append(f"Screen visually updated (diff magnitude: {mse:.1f})")
                        last_frame_np = img_np
                        last_frame_b64 = self.latest_frame_b64
                    except Exception as e:
                        logger.error(f"Frame diff error: {e}")
                    
                if events:
                    event_text = " | ".join(events)
                    logger.info(f"Telemetry Event: {event_text}")
                    
                    if not self.is_processing:
                        # Direct realtime infusion
                        telemetry_prompt = f"[System Telemetry Update]: {event_text}. (Only speak or act if this requires immediate attention, otherwise just observe silently)."
                        has_visual_change = any("visually updated" in e for e in events)
                        # Do not interrupt active tasks for passive telemetry
                        asyncio.create_task(self.run_vlm_cycle(websocket, telemetry_prompt, history, is_telemetry=True, include_image=has_visual_change))
                    else:
                        # Prevent consecutive telemetry spam by combining lines
                        if history and history[-1].get("role") == "system" and "[System Telemetry]:" in history[-1].get("content", ""):
                            history[-1]["content"] += f"\n[System Telemetry]: {event_text}"
                        else:
                            history.append({
                                "role": "system",
                                "content": f"[System Telemetry]: {event_text}"
                            })
            except Exception as e:
                logger.error(f"Telemetry loop error: {e}")

    async def handler(self, websocket: ServerConnection):
        logger.info(f"Client connected: {websocket.remote_address}")
        
        # Connection-specific history
        history = [{"role": "system", "content": self.system_prompt}]
        
        # Start passive continuous monitoring pipeline
        telemetry_task = asyncio.create_task(self.telemetry_loop(history, websocket))
        
        try:
            async for message in websocket:
                if isinstance(message, bytes):
                    # Check magic bytes for frame vs audio
                    # Frame starting signature: JPEG starts with 0xFFD8
                    if len(message) > 4 and message[:2] == b'\xff\xd8':
                        # JPEG frame
                        self.latest_frame_b64 = base64.b64encode(message).decode('utf-8')
                    else:
                        # Treat as PCM 16-bit 16kHz audio chunk
                        spoken_utterance = self.vad.process_chunk(message)
                        if spoken_utterance is not None:
                            # User finished speaking
                            logger.info("Speech segment complete.")
                            
                            audio_b64 = None
                            transcript = ""
                            
                            if USE_NATIVE_AUDIO:
                                logger.info("Formatting raw audio for native VLM processing...")
                                # spoken_utterance is float32. Convert back to int16 PCM
                                int16_audio = (spoken_utterance * 32768.0).astype(np.int16)
                                pcm_bytes = int16_audio.tobytes()
                                wav_data = self.create_wav_header(len(pcm_bytes), 16000) + pcm_bytes
                                audio_b64 = base64.b64encode(wav_data).decode('utf-8')
                                transcript = "[User Audio Segment Provided]"
                            else:
                                logger.info("Transcribing using Whisper fallback...")
                                transcript = self.asr.transcribe(spoken_utterance)
                                logger.info(f"Transcription result: '{transcript}'")
                            
                            if transcript.strip() or audio_b64:
                                # Start VLM cycle immediately with raw audio
                                if self.current_vlm_task and not self.current_vlm_task.done():
                                    logger.info("Interrupting previous VLM task due to new voice input...")
                                    self.current_vlm_task.cancel()
                                    self.is_processing = False
                                
                                self.current_vlm_task = asyncio.create_task(self.run_vlm_cycle(websocket, transcript, history, audio_b64=audio_b64))
                                
                                # Process actual transcription for UI feedback without blocking
                                if USE_NATIVE_AUDIO:
                                    async def background_transcribe(audio_chunk, ws):
                                        try:
                                            # Run blocking transcription in thread
                                            real_transcript = await asyncio.to_thread(self.asr.transcribe, audio_chunk)
                                            if real_transcript.strip():
                                                await ws.send(json.dumps({
                                                    "type": "transcript",
                                                    "text": real_transcript
                                                }))
                                        except Exception as err:
                                            logger.error(f"Background transcription failed: {err}")
                                            
                                    asyncio.create_task(background_transcribe(spoken_utterance, websocket))
                                else:
                                    await websocket.send(json.dumps({
                                        "type": "transcript",
                                        "text": transcript
                                    }))
                else:
                    try:
                        data = json.loads(message)
                        msg_type = data.get("type")
                        if msg_type == "text_prompt":
                            text = data.get("text")
                            logger.info(f"Received text prompt override: '{text}'")
                            if self.current_vlm_task and not self.current_vlm_task.done():
                                self.current_vlm_task.cancel()
                                self.is_processing = False
                            self.current_vlm_task = asyncio.create_task(self.run_vlm_cycle(websocket, text, history))
                        elif msg_type == "set_voice":
                            voice = data.get("voice")
                            if voice:
                                logger.info(f"Setting TTS default voice to: '{voice}'")
                                self.tts.default_voice = voice
                    except Exception as e:
                        logger.error(f"Error handling text message: {e}")
        finally:
            telemetry_task.cancel()

    async def run_vlm_cycle(self, websocket: ServerConnection, user_text: str, history: list, audio_b64: str = None, is_telemetry: bool = False, include_image: bool = True):
        """Executes a single reasoning/thinking step with the VLM, triggering tools and TTS."""
        if self.is_processing:
            logger.info("Skipping VLM cycle, already processing.")
            return
            
        self.is_processing = True
        
        # Determine actual screen dimensions dynamically if possible (hardcoded for user's primary monitor 2560x1600)
        SCREEN_W, SCREEN_H = 2560, 1600
        
        logger.info(f"VLM cycle triggered. Prompt: '{user_text}'")
        
        # Prepare multimodal query message
        query_content = []
        if user_text:
            query_content.append({"type": "text", "text": user_text})
            
        if audio_b64:
            query_content.append({
                "type": "input_audio",
                "input_audio": {
                    "data": audio_b64,
                    "format": "wav"
                }
            })
            
        if self.latest_frame_b64 and include_image:
            query_content.append({
                "type": "image_url",
                "image_url": {"url": f"data:image/jpeg;base64,{self.latest_frame_b64}"}
            })
            
        history.append({
            "role": "user",
            "content": query_content
        })
        
        # Prune history to prevent context overflow from repeated screenshots
        prune_message_history(history)
        
        # Call VLM
        try:
            await websocket.send(json.dumps({
                "type": "status",
                "text": "Thinking..."
            }))
            
            response = await call_openai_compatible(
                api_key=None,
                api_base=self.api_base,
                model=self.vlm_model_name,
                system_prompt=self.system_prompt,
                messages=history,
                tools=self.mcp_tools,
                force_fallback=False  # Allow native generation for much faster responses
            )
            
            spoken_text = response.get("content") or ""
            reasoning = response.get("thought") or spoken_text
            tool_calls = response.get("tool_calls") or []
            
            logger.info(f"VLM Response thought: '{reasoning}' | Spoken: '{spoken_text}'")
            
            # Send thought to client ONLY if it differs from spoken text to avoid duplication
            if reasoning and reasoning.strip() != spoken_text.strip():
                await websocket.send(json.dumps({
                    "type": "thought",
                    "text": reasoning
                }))
            
            # Append response to history
            history.append(response)
            
            any_action_taken = bool(tool_calls)
            
            # 1. Synthesize text response and stream back immediately
            if spoken_text and not is_telemetry:
                # Strip out any numbered lists or newlines if the model accidentally outputted reasoning
                clean_spoken_text = spoken_text.split('\n')[0].strip()
                if len(clean_spoken_text) > 150:
                    clean_spoken_text = clean_spoken_text[:147] + "..."
                    
                logger.info(f"Synthesizing TTS for: '{clean_spoken_text}'")
                
                # Send text response
                await websocket.send(json.dumps({
                    "type": "text_response",
                    "text": clean_spoken_text
                }))
                
                try:
                    mp3_bytes = bytearray()
                    async for chunk in self.tts.synthesize_stream(clean_spoken_text):
                        mp3_bytes.extend(chunk)
                    
                    if mp3_bytes:
                        await websocket.send(bytes(mp3_bytes))
                        logger.info("Sent TTS audio stream to client.")
                except Exception as e:
                    logger.error(f"TTS Streaming failed: {e}")
            elif any_action_taken and not is_telemetry:
                # The model chose to execute an action without speaking to save latency.
                # Provide a brief audio acknowledgment so the user knows it's working.
                fallback_text = "Okay."
                logger.info(f"Synthesizing TTS fallback for action: '{fallback_text}'")
                
                await websocket.send(json.dumps({
                    "type": "text_response",
                    "text": fallback_text
                }))
                
                try:
                    mp3_bytes = bytearray()
                    async for chunk in self.tts.synthesize_stream(fallback_text):
                        mp3_bytes.extend(chunk)
                    
                    if mp3_bytes:
                        await websocket.send(bytes(mp3_bytes))
                        logger.info("Sent TTS fallback audio stream to client.")
                except Exception as e:
                    logger.error(f"TTS Fallback Streaming failed: {e}")
            
            # 2. Handle Tool Calls
            requires_verification = False
            if any_action_taken:
                for tc in tool_calls:
                    fn = tc["function"]
                    name = fn["name"]
                    args = json.loads(fn["arguments"])
                    tc_id = tc["id"]
                    
                    # Intercept coordinates to scale them
                    if name == "computer" and "coordinate" in args and isinstance(args["coordinate"], list) and len(args["coordinate"]) == 2:
                        raw_x, raw_y = args["coordinate"]
                        import pyautogui
                        screen_w, screen_h = pyautogui.size()
                        
                        # server.py expects coordinates in the SCALED screenshot dimension (out_w x out_h)
                        # We must compute out_w, out_h exactly as server.py does to prevent double scaling.
                        ratio = screen_w / screen_h if screen_h > 0 else 1.0
                        out_w, out_h = screen_w, screen_h
                        for tw, th in [(1024, 768), (1280, 800), (1366, 768)]:
                            if abs((tw / th) - ratio) < 0.02 and tw < screen_w:
                                out_w, out_h = tw, th
                                break
                        else:
                            max_w, max_h = 1366, 768
                            scale_factor = min(max_w / screen_w, max_h / screen_h, 1.0)
                            out_w = max(1, round(screen_w * scale_factor))
                            out_h = max(1, round(screen_h * scale_factor))
                        
                        # Scale 1000x1000 normalized grid to out_w x out_h
                        scaled_x = int((raw_x / 1000.0) * out_w)
                        scaled_y = int((raw_y / 1000.0) * out_h)
                        logger.info(f"Scaling coordinates [{raw_x}, {raw_y}] -> [{scaled_x}, {scaled_y}] for intermediate bounds {out_w}x{out_h} (Desktop: {screen_w}x{screen_h})")
                        args["coordinate"] = [scaled_x, scaled_y]
                    
                    if name == "computer":
                        requires_verification = True
                    
                    if "thinking" in args and args["thinking"]:
                        await websocket.send(json.dumps({
                            "type": "thought",
                            "text": args["thinking"]
                        }))
                    
                    await websocket.send(json.dumps({
                        "type": "action",
                        "text": f"Executing tool: {name}..."
                    }))
                    
                    logger.info(f"Executing local VLM tool call: {name}({args})")
                    try:
                        res = await self.active_session.call_tool(name, args)
                        formatted_content = format_tool_content_for_role(res, "local", text_only=False)
                        
                        # Handle tool completion in history
                        if isinstance(formatted_content, list):
                            text_part = next((item["text"] for item in formatted_content if item["type"] == "text"), "Action complete.")
                            
                            # Fallback Mechanism: If WebRTC stream is active, we strip the redundant mss screenshot 
                            # to save 10 seconds of LLM prompt evaluation latency.
                            if self.latest_frame_b64:
                                formatted_content = [{"type": "text", "text": text_part}]
                            else:
                                # WebRTC is off, fallback to using the mss screenshot from the tool
                                pass
                                
                            img_part = next((item["image_url"]["url"] for item in formatted_content if item["type"] == "image_url"), None)
                            
                            if img_part and "," in img_part:
                                # Only update our internal tracker if we are falling back to mss
                                self.latest_frame_b64 = img_part.split(",")[1]
                                
                            history.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": name,
                                "content": text_part
                            })
                            history.append({
                                "role": "user",
                                "content": formatted_content
                            })
                        else:
                            history.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": name,
                                "content": formatted_content
                            })
                            
                        # If a tool ran, trigger another VLM turn to verify and reply
                        await websocket.send(json.dumps({
                            "type": "status",
                            "text": f"Tool {name} executed. Re-evaluating screen..."
                        }))
                    except Exception as err:
                        logger.error(f"Error executing tool {name}: {err}")
                        history.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": name,
                            "content": f"Error: {err}"
                        })
                        
        except asyncio.CancelledError:
            logger.info("VLM cycle cancelled by interruption.")
            raise
        except Exception as e:
            logger.error(f"Error calling local VLM: {e}")
            try:
                await websocket.send(json.dumps({
                    "type": "status",
                    "text": f"Error: {e}"
                }))
            except Exception:
                pass
        finally:
            if self.current_vlm_task == asyncio.current_task():
                self.is_processing = False
            
        # Recursive verification turn ONLY if an action was taken that wasn't just observing
        if not is_telemetry and any_action_taken and requires_verification:
            # We wait 1 second to let UI stabilize before grabbing the screenshot for the next turn
            await asyncio.sleep(1.0)
            self.current_vlm_task = asyncio.create_task(self.run_vlm_cycle(websocket, "[System Verification Turn]", history))
        elif not is_telemetry:
            # If we are done processing and no verification is needed, tell the UI to unlock the mic
            try:
                await websocket.send(json.dumps({
                    "type": "status",
                    "text": "Connected"
                }))
            except Exception:
                pass

    @staticmethod
    def create_wav_header(data_size: int, sample_rate: int, channels: int = 1, bits_per_sample: int = 16) -> bytes:
        """Helper to create a standard 44-byte WAV header."""
        header = bytearray(44)
        # RIFF
        header[0:4] = b'RIFF'
        header[4:8] = (data_size + 36).to_bytes(4, 'little')
        # WAVE
        header[8:12] = b'WAVE'
        # fmt 
        header[12:16] = b'fmt '
        header[16:20] = (16).to_bytes(4, 'little') # Subchunk1Size
        header[20:22] = (1).to_bytes(2, 'little')   # AudioFormat (1 = PCM)
        header[22:24] = (channels).to_bytes(2, 'little')
        header[24:28] = (sample_rate).to_bytes(4, 'little')
        header[28:32] = (sample_rate * channels * bits_per_sample // 8).to_bytes(4, 'little') # ByteRate
        header[32:34] = (channels * bits_per_sample // 8).to_bytes(2, 'little')             # BlockAlign
        header[34:36] = (bits_per_sample).to_bytes(2, 'little')
        # data
        header[36:40] = b'data'
        header[40:44] = (data_size).to_bytes(4, 'little')
        return bytes(header)

if __name__ == "__main__":
    server = LowLatencyVoiceServer()
    try:
        asyncio.run(server.run())
    except KeyboardInterrupt:
        logger.info("Voice server terminated.")
