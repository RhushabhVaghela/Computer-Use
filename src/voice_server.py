import os
import sys
import json
import shutil
import asyncio
import logging
import base64
from io import BytesIO
from PIL import Image
import numpy as np
import websockets
from websockets.server import ServerConnection

try:
    import pyautogui
except ImportError:
    pyautogui = None

try:
    import win32gui
except ImportError:
    win32gui = None



# Add parent path to import src modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import CONFIG
from run_agent import call_openai_compatible, get_mcp_params, to_openai_tools, format_tool_content_for_role, prune_message_history
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
from speech_processor import (
    ASRProcessor, VADDetector, TTSProcessor, EdgeTTSProcessor, 
    KittenTTSProcessor, SupertonicTTSProcessor, Qwen3ASRProcessor, Qwen3TTSProcessor,
    HiggsTTSProcessor
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
        
        # Load PersonaPlex Settings
        pp_mode = os.environ.get("PERSONAPLEX_MODE", CONFIG.personaplex_mode).lower().strip()
        self.personaplex_mode = pp_mode if pp_mode not in ("", "none", "false") else None
        self.personaplex_url = os.environ.get("PERSONAPLEX_URL", CONFIG.personaplex_url)
        self.personaplex_binary = os.environ.get("PERSONAPLEX_BINARY", CONFIG.personaplex_binary)
        self.personaplex_model_path = os.environ.get("PERSONAPLEX_MODEL_PATH", CONFIG.personaplex_model_path)
        self.personaplex_user_prefix = os.environ.get("PERSONAPLEX_USER_PREFIX", "User:").strip()
        self.personaplex_voice = os.environ.get("PERSONAPLEX_VOICE", "NATF2").strip()
        self.personaplex_prompt = os.environ.get("PERSONAPLEX_PROMPT", CONFIG.personaplex_prompt).strip()
        try:
            self.personaplex_temperature = float(os.environ.get("PERSONAPLEX_TEMPERATURE", str(CONFIG.personaplex_temperature)))
        except (ValueError, TypeError):
            self.personaplex_temperature = 0.7
        
        # Determine engines from environment variables (fallback if PersonaPlex is disabled)
        asr_engine = os.environ.get("ASR_ENGINE", CONFIG.asr_engine).lower()
        tts_engine = os.environ.get("TTS_ENGINE", CONFIG.tts_engine).lower()
        
        self.asr = None
        self.tts = None
        self.vad = None
        
        if not self.personaplex_mode:
            logger.info("Initializing standard STT-LLM-TTS speech processors...")
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
            elif tts_engine == "higgs":
                self.tts = HiggsTTSProcessor()
            elif tts_engine == "kokoro":
                self.tts = TTSProcessor()
            elif tts_engine == "edge-tts":
                self.tts = EdgeTTSProcessor()
            elif tts_engine == "kittentts":
                self.tts = KittenTTSProcessor()
            else:
                self.tts = SupertonicTTSProcessor()
        else:
            logger.info(f"PersonaPlex enabled (mode={self.personaplex_mode}). Standard ASR/TTS processors bypassed to save memory.")
        
        # Shared states
        self.latest_frame_b64: Optional[str] = None
        self.active_session: Optional[ClientSession] = None
        self.mcp_tools = []
        self.conversation_history = []
        self.system_prompt = ""
        self.is_processing = False
        self.current_vlm_task = None
        self.is_muted = False
        self.auto_mute = False
        self.current_stream = "assistant"

    def set_hardware_mic_mute(self, mute: bool):
        if sys.platform != "win32":
            return
        try:
            import comtypes
            try:
                comtypes.CoInitialize()
            except Exception:
                pass
                
            from comtypes import GUID
            from comtypes.client import CreateObject
            from pycaw.pycaw import IAudioEndpointVolume, IMMDeviceEnumerator
            from ctypes import cast, POINTER
            from comtypes import CLSCTX_ALL
            
            CLSID_MMDeviceEnumerator = GUID("{BCDE0395-E52F-467C-8E3D-C4579291692E}")
            
            enumerator = CreateObject(CLSID_MMDeviceEnumerator, interface=IMMDeviceEnumerator)
            # eCapture = 1 (audio capture devices), DEVICE_STATE_ACTIVE = 1
            collection = enumerator.EnumAudioEndpoints(1, 1)
            count = collection.GetCount()
            
            for i in range(count):
                try:
                    device = collection.Item(i)
                    interface = device.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
                    volume = cast(interface, POINTER(IAudioEndpointVolume))
                    volume.SetMute(1 if mute else 0, None)
                    del volume
                    del interface
                    del device
                except Exception as dev_err:
                    logger.warning(f"Failed to set mute={mute} on capture device index {i}: {dev_err}")
            
            del collection
            del enumerator
            
            # Force garbage collection to clean up COM pointers while COM is still initialized
            import gc
            gc.collect()
            
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
                
            logger.info(f"Hardware microphones (count={count}) set to mute={mute}")
        except Exception as e:
            logger.warning(f"Could not set hardware microphone mute states: {e}")

    def sync_hardware_mic_state(self):
        if self.personaplex_mode != "subprocess":
            return
        if self.is_muted:
            self.set_hardware_mic_mute(True)
        elif self.auto_mute and self.current_stream == "assistant":
            self.set_hardware_mic_mute(True)
        else:
            self.set_hardware_mic_mute(False)

    async def ensure_model_downloaded(self, model_id: str, ws_client):
        """Checks if the model directory exists under models/. If not, downloads it and configures it."""
        # Resolve local path
        if model_id.startswith(("models/", "models\\", "./", ".\\", "/")) or os.path.isabs(model_id) or os.path.isdir(model_id):
            local_dir = os.path.abspath(model_id)
        else:
            local_dir = os.path.abspath(os.path.join("models", model_id))

        # Check for LiquidAI model architecture early
        if "liquid" in model_id.lower() or "lfm" in model_id.lower():
            raise ValueError(
                "LiquidAI hybrid LFM architecture is not supported by the local C++ runner (personaplex.exe)."
            )

        hf_config_file = os.path.join(local_dir, "config.json")
        config_file = os.path.join(local_dir, "personaplex-config.json")

        # Check if the folder contains a large model file (>100MB) with model weights extensions
        has_weights = False
        if os.path.exists(local_dir):
            try:
                for f in os.listdir(local_dir):
                    if f.endswith((".safetensors", ".gguf", ".bin")) and not "tokenizer" in f.lower() and not "mimi" in f.lower():
                        if os.path.getsize(os.path.join(local_dir, f)) > 100 * 1024 * 1024: # >100MB
                            has_weights = True
                            break
            except Exception:
                pass

        # Download from Hugging Face if config.json, personaplex-config.json, or weight files are missing
        if not os.path.exists(local_dir) or (not os.path.exists(config_file) and not os.path.exists(hf_config_file)) or not has_weights:
            if not "/" in model_id and not "\\" in model_id:
                logger.warning(f"Model simple path {model_id} specified but personaplex-config.json not found in {local_dir}")
                return local_dir

            logger.info(f"Model {model_id} not found locally or incomplete. Initiating Hugging Face download...")
            await ws_client.send(json.dumps({
                "type": "status",
                "text": f"Downloading model weights for {model_id} (up to 14GB)..."
            }))

            try:
                from huggingface_hub import snapshot_download
                
                # Run snapshot download in thread to avoid blocking main event loop
                await asyncio.to_thread(
                    snapshot_download,
                    repo_id=model_id,
                    local_dir=local_dir,
                    ignore_patterns=["*.git*", "*.md"],
                    max_workers=4
                )
                logger.info(f"Model {model_id} weights downloaded successfully.")
                await ws_client.send(json.dumps({
                    "type": "status",
                    "text": f"Weights downloaded. Configuring {model_id}..."
                }))
            except Exception as e:
                logger.error(f"Failed to download model {model_id}: {e}")
                await ws_client.send(json.dumps({
                    "type": "status",
                    "text": f"Error downloading weights: {e}"
                }))
                raise e

        # 1. Copy tokenizer_spm_32k_3.model if missing
        tok_src = os.path.abspath(os.path.join("models", "moshi-common", "tokenizer_spm_32k_3.model"))
        tok_dest = os.path.join(local_dir, "tokenizer_spm_32k_3.model")
        if os.path.exists(tok_src) and not os.path.exists(tok_dest):
            try:
                shutil.copy(tok_src, tok_dest)
            except Exception as e:
                logger.warning(f"Failed to copy tokenizer to {tok_dest}: {e}")

        # 2. Extract voices.tgz if it exists in local_dir
        tgz_path = os.path.join(local_dir, "voices.tgz")
        voices_dest = os.path.join(local_dir, "voices")
        if os.path.exists(tgz_path) and not os.path.exists(voices_dest):
            try:
                import tarfile
                logger.info(f"Extracting voices.tgz in {local_dir}...")
                with tarfile.open(tgz_path, "r:gz") as tar:
                    tar.extractall(path=local_dir)
                logger.info("voices.tgz extracted successfully.")
            except Exception as te:
                logger.warning(f"Failed to extract voices.tgz: {te}")

        # 3. Read HF config.json to detect shapes dynamically
        hf_config = {}
        if os.path.exists(hf_config_file):
            try:
                with open(hf_config_file, "r") as f_hf:
                    hf_config = json.load(f_hf)
            except Exception as ce:
                logger.warning(f"Failed to parse HF config.json at {hf_config_file}: {ce}")

        # Determine shapes
        dep_q = hf_config.get("dep_q", 16)
        n_q = hf_config.get("n_q", 16)
        dim = hf_config.get("dim", 4096)
        num_layers = hf_config.get("num_layers", 32)
        num_heads = hf_config.get("num_heads", 32)
        text_card = hf_config.get("text_card", 32000)
        hidden_scale = hf_config.get("hidden_scale", 4.125)
        
        # Decide model_type: if dep_q is 16, we can load voice embedding, so use "personaplex". Otherwise use "moshi".
        model_type = "personaplex" if dep_q >= 16 else "moshi"

        # Generate delays
        delays = hf_config.get("delays")
        if not delays:
            delays = [0, 0] + [1] * (n_q - 1)
            # If length is 17 (like standard Moshi/PersonaPlex), it has a 0 in the middle (index 9) for text codebook
            if n_q == 16:
                delays = [0, 0, 1, 1, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 1, 1]

        config_data = {
            "card": 2048,
            "n_q": n_q,
            "dep_q": dep_q,
            "delays": delays,
            "dim": dim,
            "text_card": text_card,
            "existing_text_padding_id": 3,
            "num_heads": num_heads,
            "num_layers": num_layers,
            "hidden_scale": hidden_scale,
            "causal": True,
            "layer_scale": None,
            "context": 3000,
            "max_period": 10000,
            "gating": "silu",
            "norm": "rms_norm_f32",
            "positional_embedding": "rope",
            "depformer_dim": 1024,
            "depformer_num_heads": 16,
            "depformer_num_layers": 6,
            "depformer_dim_feedforward": 4224,
            "depformer_multi_linear": True,
            "depformer_context": 8,
            "depformer_max_period": 10000,
            "depformer_gating": "silu",
            "depformer_pos_emb": "none",
            "depformer_weights_per_step": True,
            "conditioners": {},
            "cross_attention": False,
            "model_type": model_type,
            "tokenizer_name": "tokenizer_spm_32k_3.model",
            "mimi_name": "tokenizer-e351c8d8-checkpoint125.safetensors",
            "moshi_name": "model.safetensors"
        }

        # Override filenames if using standard personaplex-7b GGUF
        if "personaplex-7b-v1-q4_k" in local_dir:
            config_data["tokenizer_name"] = "../moshi-common/tokenizer_spm_32k_3.model"
            config_data["mimi_name"] = "../moshi-common/mimi-e351c8d8-125.gguf"
            config_data["moshi_name"] = "model-q4_k.gguf"

        # Write or overwrite personaplex-config.json
        try:
            with open(config_file, "w") as f_out:
                json.dump(config_data, f_out, indent=2)
            logger.info(f"Dynamically generated/verified config at {config_file}")
        except Exception as we:
            logger.warning(f"Failed to write personaplex-config.json: {we}")

        # 4. If model supports voice embeddings (dep_q == 16), copy voices directory from models/voices if missing
        if dep_q >= 16 and not os.path.exists(voices_dest):
            voices_src = os.path.abspath(os.path.join("models", "voices"))
            if os.path.exists(voices_src):
                try:
                    shutil.copytree(voices_src, voices_dest)
                    logger.info(f"Copied default voices to {voices_dest}")
                except Exception as ve:
                    logger.warning(f"Failed to copy voices directory: {ve}")

        return local_dir

    def build_subprocess_cmd(self, local_model_path: str) -> list:
        # Check if voice parameter should be omitted
        has_voice = True
        config_file = os.path.join(local_model_path, "personaplex-config.json")
        if os.path.exists(config_file):
            try:
                with open(config_file, "r") as f:
                    cfg = json.load(f)
                    if cfg.get("dep_q", 16) < 16 or cfg.get("model_type") == "moshi":
                        has_voice = False
            except Exception:
                pass
        
        cmd = [
            self.personaplex_binary,
            "-m", local_model_path,
            "-c", "2000",
            "-t", str(self.personaplex_temperature),
            "-p", self.personaplex_prompt
        ]
        if has_voice:
            cmd.extend(["-v", self.personaplex_voice])
        return cmd

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
        
        # Send config handshake to let client know if it should capture audio
        await websocket.send(json.dumps({
            "type": "config",
            "personaplex_mode": self.personaplex_mode or "none"
        }))
        
        # Connection-specific history
        history = [{"role": "system", "content": self.system_prompt}]
        
        # Start passive continuous monitoring pipeline
        telemetry_task = asyncio.create_task(self.telemetry_loop(history, websocket))
        
        proc = None
        moshi_ws = None
        moshi_proxy_task = None
        sts_stdout_task = None
        
        if self.personaplex_mode == "subprocess":
            logger.info("Spawning PersonaPlex (moshi-sts) subprocess...")
            try:
                local_model_path = await self.ensure_model_downloaded(self.personaplex_model_path, websocket)
            except Exception as e:
                logger.error(f"Could not load initial model: {e}")
                await websocket.send(json.dumps({
                    "type": "status",
                    "text": f"Error: {e}"
                }))
                return
            cmd = self.build_subprocess_cmd(local_model_path)
            try:
                await websocket.send(json.dumps({"type": "status", "text": "Starting model subprocess..."}))
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=None,  # Output directly to host console to prevent pipe buffer exhaustion & stuttering
                    stdin=asyncio.subprocess.PIPE
                )
                logger.info("PersonaPlex subprocess launched successfully.")
                
                # Start background task to read stdout in real-time
                async def read_sts_stdout(process, ws_client):
                    # Discard startup/loading logs until "ready" followed by newline
                    startup_line = ""
                    ready_received = False
                    try:
                        while not ready_received:
                            char_bytes = await process.stdout.read(1)
                            if not char_bytes:
                                break
                            char = char_bytes.decode('utf-8', errors='ignore')
                            sys.stdout.write(char)
                            sys.stdout.flush()
                            startup_line += char
                            if char == '\n':
                                clean_line = startup_line.strip()
                                if clean_line:
                                    try:
                                        await ws_client.send(json.dumps({
                                            "type": "status",
                                            "text": f"Model: {clean_line}"
                                        }))
                                    except Exception:
                                        pass
                                if "ready" in startup_line.lower():
                                    ready_received = True
                                    logger.info("PersonaPlex model loaded and ready. Beginning conversation feed.")
                                    self.current_stream = "user"
                                    self.sync_hardware_mic_state()
                                startup_line = ""
                                
                        if not ready_received:
                            exit_code = process.returncode if process.returncode is not None else await process.wait()
                            logger.error(f"PersonaPlex subprocess exited unexpectedly during startup with code {exit_code}")
                            await ws_client.send(json.dumps({
                                "type": "status",
                                "text": f"Error: Model failed to load (exit code {exit_code})."
                            }))
                            return
                    except Exception as err:
                        logger.error(f"Error reading startup logs: {err}")
                        
                    current_stream = "assistant"
                    self.current_stream = "assistant"
                    self.sync_hardware_mic_state()
                    user_buffer = ""
                    assistant_buffer = ""
                    last_char_time = asyncio.get_event_loop().time()
                    
                    # Background task to monitor user silence
                    async def check_silence_loop():
                        nonlocal user_buffer, last_char_time, current_stream
                        while True:
                            await asyncio.sleep(0.1)
                            if current_stream == "user" and user_buffer.strip():
                                elapsed = asyncio.get_event_loop().time() - last_char_time
                                if elapsed > 1.2:  # 1.2 seconds of silence / no new tokens
                                    user_text = user_buffer.strip()
                                    user_buffer = ""
                                    if self.is_muted:
                                        logger.info("Subprocess is muted. Discarding user speech segment.")
                                        continue
                                    logger.info(f"User finished speaking. Triggering VLM for: '{user_text}'")
                                    
                                    if self.current_vlm_task and not self.current_vlm_task.done():
                                        self.current_vlm_task.cancel()
                                        self.is_processing = False
                                    self.current_vlm_task = asyncio.create_task(
                                        self.run_vlm_cycle(ws_client, user_text, history)
                                    )
                                    
                    silence_task = asyncio.create_task(check_silence_loop())
                    
                    try:
                        while True:
                            char_bytes = await process.stdout.read(1)
                            if not char_bytes:
                                break
                            
                            last_char_time = asyncio.get_event_loop().time()
                            char = char_bytes.decode('utf-8', errors='ignore')
                            
                            # Print to server terminal stdout in real-time
                            sys.stdout.write(char)
                            sys.stdout.flush()
                            
                            if char == '|':
                                # Switch to user stream
                                current_stream = "user"
                                self.current_stream = "user"
                                self.sync_hardware_mic_state()
                                # Flush any assistant text to UI
                                if assistant_buffer.strip():
                                    await ws_client.send(json.dumps({
                                        "type": "transcript",
                                        "speaker": "assistant",
                                        "text": assistant_buffer.strip()
                                    }))
                                    assistant_buffer = ""
                                try:
                                    await ws_client.send(json.dumps({
                                        "type": "status",
                                        "text": "Connected"
                                    }))
                                except Exception:
                                    pass
                                continue
                            
                            if char == '\n':
                                # Reset stream status
                                current_stream = "assistant"
                                self.current_stream = "assistant"
                                self.sync_hardware_mic_state()
                                # Flush buffers
                                if assistant_buffer.strip():
                                    await ws_client.send(json.dumps({
                                        "type": "transcript",
                                        "speaker": "assistant",
                                        "text": assistant_buffer.strip()
                                    }))
                                    assistant_buffer = ""
                                if user_buffer.strip() and not self.is_muted:
                                    await ws_client.send(json.dumps({
                                        "type": "transcript",
                                        "speaker": "user",
                                        "text": user_buffer.strip()
                                    }))
                                user_buffer = ""
                                continue
                                
                            if current_stream == "user":
                                if self.is_muted:
                                    user_buffer = ""
                                    continue
                                user_buffer += char
                                # Periodically update UI with accumulated words
                                if char in (' ', '\r'):
                                    await ws_client.send(json.dumps({
                                        "type": "transcript",
                                        "speaker": "user",
                                        "text": user_buffer.strip()
                                    }))
                            else:
                                assistant_buffer += char
                                if char in (' ', '\r'):
                                    await ws_client.send(json.dumps({
                                        "type": "transcript",
                                        "speaker": "assistant",
                                        "text": assistant_buffer.strip()
                                    }))
                                    
                    except asyncio.CancelledError:
                        pass
                    except Exception as err:
                        logger.error(f"Error reading PersonaPlex stdout: {err}")
                    finally:
                        silence_task.cancel()
                
                sts_stdout_task = asyncio.create_task(read_sts_stdout(proc, websocket))
            except Exception as e:
                logger.error(f"Failed to spawn PersonaPlex subprocess: {e}")
                await websocket.send(json.dumps({"type": "status", "text": f"Error spawning PersonaPlex binary: {e}"}))
                
        elif self.personaplex_mode == "websocket":
            logger.info(f"Connecting to PersonaPlex WebSocket server at {self.personaplex_url}...")
            try:
                moshi_ws = await websockets.connect(self.personaplex_url)
                logger.info("Connected to PersonaPlex WebSocket server.")
                
                # Start proxy task from Moshi to Client
                async def proxy_moshi_to_client(m_ws, ws_client):
                    try:
                        import msgpack
                    except ImportError:
                        msgpack = None
                        
                    try:
                        async for msg in m_ws:
                            if isinstance(msg, bytes):
                                unpacked = None
                                if msgpack:
                                    try:
                                        unpacked = msgpack.unpackb(msg)
                                    except Exception:
                                        pass
                                
                                if isinstance(unpacked, dict):
                                    audio_chunk = unpacked.get("data")
                                    text_val = unpacked.get("text", "")
                                    speaker = unpacked.get("speaker", "")
                                    
                                    if audio_chunk:
                                        await ws_client.send(audio_chunk)
                                    if text_val:
                                        await ws_client.send(json.dumps({
                                            "type": "transcript",
                                            "speaker": speaker or "assistant",
                                            "text": text_val
                                        }))
                                        if speaker == "user":
                                            logger.info(f"Triggering VLM cycle for user command: '{text_val}'")
                                            if self.current_vlm_task and not self.current_vlm_task.done():
                                                self.current_vlm_task.cancel()
                                                self.is_processing = False
                                            self.current_vlm_task = asyncio.create_task(
                                                self.run_vlm_cycle(ws_client, text_val, history)
                                            )
                                else:
                                    await ws_client.send(msg)
                            else:
                                try:
                                    data = json.loads(msg)
                                    text_val = data.get("text", "")
                                    speaker = data.get("speaker", "")
                                    if text_val:
                                        await ws_client.send(json.dumps({
                                            "type": "transcript",
                                            "speaker": speaker or "assistant",
                                            "text": text_val
                                        }))
                                    else:
                                        await ws_client.send(msg)
                                    
                                    if text_val and speaker == "user":
                                        logger.info(f"Triggering VLM cycle for user command: '{text_val}'")
                                        if self.current_vlm_task and not self.current_vlm_task.done():
                                            self.current_vlm_task.cancel()
                                            self.is_processing = False
                                        self.current_vlm_task = asyncio.create_task(
                                            self.run_vlm_cycle(ws_client, text_val, history)
                                        )
                                except Exception:
                                    await ws_client.send(json.dumps({
                                        "type": "transcript",
                                        "speaker": "assistant",
                                        "text": str(msg)
                                    }))
                    except asyncio.CancelledError:
                        pass
                    except Exception as err:
                        logger.error(f"Error in Moshi to client proxy: {err}")
                
                moshi_proxy_task = asyncio.create_task(proxy_moshi_to_client(moshi_ws, websocket))
            except Exception as e:
                logger.error(f"Failed to connect to PersonaPlex WebSocket: {e}")
                await websocket.send(json.dumps({"type": "status", "text": f"Error connecting to PersonaPlex server: {e}"}))
        
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
                        if self.personaplex_mode == "websocket" and moshi_ws:
                            try:
                                import msgpack
                                payload = msgpack.packb({"type": "audio", "data": message})
                                await moshi_ws.send(payload)
                            except Exception:
                                await moshi_ws.send(message)
                        elif self.personaplex_mode == "subprocess":
                            # direct hardware mic capture by moshi-sts, ignore client audio
                            pass
                        else:
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
                                                        "speaker": "user",
                                                        "text": real_transcript
                                                    }))
                                            except Exception as err:
                                                logger.error(f"Background transcription failed: {err}")
                                                
                                        asyncio.create_task(background_transcribe(spoken_utterance, websocket))
                                    else:
                                        await websocket.send(json.dumps({
                                            "type": "transcript",
                                            "speaker": "user",
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
                                if self.tts:
                                    self.tts.default_voice = voice
                                
                                # Map custom frontend voice names to default names supported by personaplex.exe
                                mapped_voice = voice
                                if voice == "moshika":
                                    mapped_voice = "NATF2"
                                elif voice == "US Female":
                                    mapped_voice = "NATF2"
                                elif voice == "US Male":
                                    mapped_voice = "NATM0"
                                elif voice == "UK Female":
                                    mapped_voice = "NATF0"
                                elif voice == "UK Male":
                                    mapped_voice = "NATM1"
                                    
                                if self.personaplex_mode == "subprocess" and mapped_voice != self.personaplex_voice:
                                    logger.info(f"Re-spawning PersonaPlex with new voice: {mapped_voice} (original: {voice})")
                                    self.personaplex_voice = mapped_voice
                                    if proc:
                                        logger.info("Terminating running PersonaPlex process...")
                                        try:
                                            proc.terminate()
                                            await proc.wait()
                                        except Exception as pe:
                                            logger.warning(f"Error terminating child: {pe}")
                                    
                                    # Ensure the model is available locally
                                    try:
                                        local_model_path = await self.ensure_model_downloaded(self.personaplex_model_path, websocket)
                                    except Exception as e:
                                        logger.error(f"Failed to ensure model is downloaded: {e}")
                                        await websocket.send(json.dumps({
                                            "type": "status",
                                            "text": f"Error: {e}"
                                        }))
                                        continue
                                        
                                    cmd = self.build_subprocess_cmd(local_model_path)
                                    await websocket.send(json.dumps({"type": "status", "text": "Starting model subprocess..."}))
                                    proc = await asyncio.create_subprocess_exec(
                                        *cmd,
                                        stdout=asyncio.subprocess.PIPE,
                                        stderr=None,
                                        stdin=asyncio.subprocess.PIPE
                                    )
                                    logger.info(f"PersonaPlex subprocess re-spawned with voice {self.personaplex_voice}.")
                                    
                                    if sts_stdout_task:
                                        sts_stdout_task.cancel()
                                    sts_stdout_task = asyncio.create_task(read_sts_stdout(proc, websocket))
                        elif msg_type == "set_model":
                            model = data.get("model")
                            if model and self.personaplex_mode == "subprocess" and model != self.personaplex_model_path:
                                logger.info(f"Setting PersonaPlex model to: '{model}'")
                                
                                # Terminate current process first to free VRAM for loading the new model
                                if proc:
                                    logger.info("Terminating running PersonaPlex process for model change...")
                                    try:
                                        proc.terminate()
                                        await proc.wait()
                                    except Exception as pe:
                                        logger.warning(f"Error terminating child: {pe}")
                                
                                # Ensure model is downloaded and configured
                                try:
                                    local_model_path = await self.ensure_model_downloaded(model, websocket)
                                except Exception as e:
                                    logger.error(f"Failed to download/configure model: {e}")
                                    await websocket.send(json.dumps({
                                        "type": "status",
                                        "text": f"Error downloading model: {e}"
                                    }))
                                    continue
                                
                                self.personaplex_model_path = model
                                    
                                # Assign standard default voice profiles for the new models to avoid errors
                                if "moshika" in model.lower():
                                    self.personaplex_voice = "NATF2"
                                elif "liquid" in model.lower():
                                    self.personaplex_voice = "NATF2"
                                else:
                                    self.personaplex_voice = "NATF2"
                                    
                                cmd = self.build_subprocess_cmd(local_model_path)
                                await websocket.send(json.dumps({"type": "status", "text": "Starting model subprocess..."}))
                                proc = await asyncio.create_subprocess_exec(
                                    *cmd,
                                    stdout=asyncio.subprocess.PIPE,
                                    stderr=None,
                                    stdin=asyncio.subprocess.PIPE
                                )
                                logger.info(f"PersonaPlex subprocess re-spawned with model {local_model_path} and voice {self.personaplex_voice}.")
                                
                                if sts_stdout_task:
                                    sts_stdout_task.cancel()
                                sts_stdout_task = asyncio.create_task(read_sts_stdout(proc, websocket))
                        elif msg_type == "set_mute":
                            self.is_muted = data.get("muted", False)
                            logger.info(f"Subprocess mute state set to: {self.is_muted}")
                            self.sync_hardware_mic_state()
                        elif msg_type == "set_auto_mute":
                            self.auto_mute = data.get("enabled", False)
                            logger.info(f"Auto-mute state set to: {self.auto_mute}")
                            self.sync_hardware_mic_state()
                    except Exception as e:
                        logger.error(f"Error handling text message: {e}")
        finally:
            self.set_hardware_mic_mute(False) # Always restore mic state when connection ends
            telemetry_task.cancel()
            if moshi_proxy_task:
                moshi_proxy_task.cancel()
            if sts_stdout_task:
                sts_stdout_task.cancel()
            if moshi_ws:
                await moshi_ws.close()
            if proc:
                logger.info("Terminating PersonaPlex subprocess...")
                try:
                    proc.terminate()
                    await proc.wait()
                except Exception as e:
                    logger.warning(f"Error terminating PersonaPlex process: {e}")

    async def run_vlm_cycle(self, websocket: ServerConnection, user_text: str, history: list, audio_b64: str = None, is_telemetry: bool = False, include_image: bool = True, is_verification: bool = False):
        """Executes a single reasoning/thinking step with the VLM, triggering tools and TTS."""
        if not is_telemetry and not is_verification:
            if self.is_processing:
                logger.info("Skipping VLM cycle, already processing.")
                return
            self.is_processing = True
        

        
        # Query actual screen dimensions at runtime
        try:
            import pyautogui
            SCREEN_W, SCREEN_H = pyautogui.size()
            logger.info(f"Queried screen dimensions: {SCREEN_W}x{SCREEN_H}")
        except Exception as e:
            # Fallback with warning if query fails
            logger.warning(f"Failed to query screen dimensions: {e}. Using fallback 1920x1080")
            SCREEN_W, SCREEN_H = 1920, 1080
        
        # Allow override via environment variables (optional)
        try:
            if "VOICE_SCREEN_W" in os.environ:
                SCREEN_W = int(os.environ["VOICE_SCREEN_W"])
            if "VOICE_SCREEN_H" in os.environ:
                SCREEN_H = int(os.environ["VOICE_SCREEN_H"])
            if "VOICE_SCREEN_W" in os.environ or "VOICE_SCREEN_H" in os.environ:
                logger.info(f"Screen dimensions overridden via env vars: {SCREEN_W}x{SCREEN_H}")
        except (ValueError, TypeError) as e:
            logger.warning(f"Invalid VOICE_SCREEN_W/VOICE_SCREEN_H values: {e}")
        
        logger.info(f"VLM cycle triggered. Prompt: '{user_text}' | Screen: {SCREEN_W}x{SCREEN_H}")
        
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
        has_error_or_cancelled = True
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
                    
                logger.info(f"VLM Text Response: '{clean_spoken_text}'")
                
                # Send text response
                await websocket.send(json.dumps({
                    "type": "text_response",
                    "text": clean_spoken_text
                }))
                
                if not self.personaplex_mode:
                    logger.info(f"Synthesizing TTS for: '{clean_spoken_text}'")
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
                logger.info(f"VLM action fallback: '{fallback_text}'")
                
                await websocket.send(json.dumps({
                    "type": "text_response",
                    "text": fallback_text
                }))
                
                if not self.personaplex_mode:
                    logger.info(f"Synthesizing TTS fallback for action: '{fallback_text}'")
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
                        
            has_error_or_cancelled = False
        except asyncio.CancelledError:
            logger.info("VLM cycle cancelled by interruption.")
            raise
        except Exception as e:
            err_msg = str(e)
            if "Connection" in err_msg or "ConnectError" in err_msg or "all connection attempts failed" in err_msg:
                err_msg = f"Cannot connect to Reasoning VLM on {self.api_base}. Please ensure llama-server.exe or your OpenAI-compatible API is running."
            logger.error(f"Error calling local VLM: {err_msg}")
            try:
                await websocket.send(json.dumps({
                    "type": "status",
                    "text": f"VLM Error: {err_msg}"
                }))
            except Exception:
                pass
        finally:
            if has_error_or_cancelled:
                if self.current_vlm_task == asyncio.current_task() or self.current_vlm_task is None or self.current_vlm_task.done():
                    self.is_processing = False
                    if self.auto_mute and self.personaplex_mode == "subprocess":
                        self.sync_hardware_mic_state()
            
        # Recursive verification turn ONLY if an action was taken that wasn't just observing
        if not is_telemetry and any_action_taken and requires_verification:
            # We wait 1 second to let UI stabilize before grabbing the screenshot for the next turn
            await asyncio.sleep(1.0)
            self.current_vlm_task = asyncio.create_task(self.run_vlm_cycle(websocket, "[System Verification Turn]", history, is_verification=True))
        elif not is_telemetry:
            # If we are done processing and no verification is needed, tell the UI to unlock the mic
            self.is_processing = False
            if self.auto_mute and self.personaplex_mode == "subprocess":
                self.sync_hardware_mic_state()
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
