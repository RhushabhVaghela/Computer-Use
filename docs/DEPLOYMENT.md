# Deployment Guide: Universal Open Interpreter Computer-Use MCP Server

This guide provides instructions for deploying and running the Universal Open Interpreter Computer-Use MCP Server in development, testing, and production environments.

---

## Prerequisites

- **Operating System**: Windows 10/11 (fully supported with DPI-awareness and native UI automation), Linux, or macOS.
- **Python**: Python 3.10 to 3.13 (Python 3.13 tested).
- **Permissions**: Standard user permissions. Administrative elevation is optional but recommended if controlling system-level window controls.

---

## 1. Installation & Environment Setup

### Step 1: Clone the Repository & Configure Directory
Ensure you have both the `Computer-Use` repository and the `open-interpreter` dependency repository available.

### Step 2: Create a Virtual Environment
We recommend using a dedicated virtual environment:
```bash
python -m venv computer_use_env
computer_use_env\Scripts\activate
```

### Step 3: Install Dependencies
Install dependencies from `pyproject.toml` including optional OS-specific modules:
```bash
# On Windows:
pip install -e .[win32]

# On Linux/macOS:
pip install -e .
```

Alternatively, you can install via `requirements.txt`:
```bash
pip install -r requirements.txt
```

---

## 2. Configuration (`.env`)

Create a `.env` file in the root directory. You can copy the template from `.env.example`:
```bash
copy .env.example .env
```

### Key Configuration Parameters:

| Environment Variable | Description | Recommended Value (Production) |
|---|---|---|
| `OI_PATH` | Absolute path to local `open-interpreter` directory | `D:\Agents-and-other-repos\open-interpreter` |
| `ALLOW_UNSAFE_COMMANDS` | Bypass denylist check for shell commands | `False` |
| `RISKY_ACTION_ENABLED` | Enable mouse click and keyboard emulation tools | `True` (if GUI control required) |
| `COMPUTER_ACTION_RATE_LIMIT` | Max GUI actions permitted per minute | `60` |
| `ENABLE_AUDIT_LOG` | Write actions to `logs/computer_actions.log` | `True` |
| `MPLBACKEND` | Headless Matplotlib rendering backend | `Agg` |

---

## 3. Running the Server

The server supports three different Model Context Protocol (MCP) transport modes.

### A. Stdio Mode (Default for CLI clients/desktop integrations)
Used by tools like Claude Desktop or other client orchestrators.
```bash
python src/server.py --stdio
```

### B. SSE Mode (Server-Sent Events)
Used for web clients or external tooling integrations.
```bash
python src/server.py --sse --host 127.0.0.1 --port 8000
```

### C. Streamable HTTP Mode
Optimized for LobeHub or streaming HTTP consumers.
```bash
python src/server.py --http --host 127.0.0.1 --port 8000
```

---

## 4. Running the Voice WebSocket Server

The server includes a low-latency WebSocket Voice Server for real-time speech interaction:
```bash
python src/voice_server.py
```
This starts a WebSocket server listening on `ws://127.0.0.1:8086`. 

By default, the voice server can operate in one of three pipelines, controlled via `.env`:

### A. PersonaPlex WebSocket Mode (Mode A, Recommended for Web UI)
This mode connects to a locally hosted Moshi server running PersonaPlex. Bidirectional audio is proxied between the client UI and the Moshi server, bypassing standard ASR/TTS steps and saving up to ~2.4GB VRAM.
Configure the following in `.env`:
```ini
PERSONAPLEX_MODE=websocket
PERSONAPLEX_URL=ws://localhost:8998/api/chat
```

### B. PersonaPlex Subprocess Mode (Mode B, For Native Windows/Terminal)
This mode spawns the pre-compiled native `moshi-sts.exe` executable inside the server process. Audio capture/playback are handled directly by the host soundcard via the C++ binary. The Python server listens to the stdout stream, extract transcripts, and triggers background VLM actions.
Configure the following in `.env`:
```ini
PERSONAPLEX_MODE=subprocess
PERSONAPLEX_BINARY=moshi-sts.exe
PERSONAPLEX_MODEL_PATH=models/personaplex-7b-v1-q4_k.gguf
```

### C. Standard STT-LLM-TTS Pipeline (PersonaPlex Disabled)
To use the traditional modular pipeline (Faster-Whisper/Qwen3-ASR for translation and Kokoro/Edge-TTS/Qwen3-TTS for playback), disable PersonaPlex:
```ini
PERSONAPLEX_MODE=none
ASR_ENGINE=qwen3     # or whisper
TTS_ENGINE=qwen3     # or kokoro, edge-tts, etc.
```

---

## 5. Production Service Deployment

### A. Windows: Deploy as a Service (via NSSM)
To run the server continuously in the background on Windows, use **NSSM (Non-Sucking Service Manager)**:

1. Download NSSM from [nssm.cc](https://nssm.cc/).
2. Run `nssm install oi-computer-use-mcp`.
3. Set the following parameters:
   - **Path**: `D:\Agents-and-other-repos\Computer-Use\computer_use_env\Scripts\python.exe`
   - **Startup directory**: `D:\Agents-and-other-repos\Computer-Use`
   - **Arguments**: `src/server.py --http --port 8000`
4. Go to the **Environment** tab and insert any `.env` parameters if they are not picked up from the directory.
5. Click **Install service** and start it using `net start oi-computer-use-mcp`.

### B. Linux: Deploy as a Systemd Service
Create `/etc/systemd/system/oi-computer-use.service`:

```ini
[Unit]
Description=Open Interpreter Computer-Use MCP Server
After=network.target

[Service]
Type=simple
User=mcpuser
WorkingDirectory=/opt/Computer-Use
ExecStart=/opt/Computer-Use/computer_use_env/bin/python src/server.py --http --host 127.0.0.1 --port 8000
Restart=on-failure
EnvironmentFile=/opt/Computer-Use/.env

[Install]
WantedBy=multi-user.target
```

Enable and start the service:
```bash
sudo systemctl daemon-reload
sudo systemctl enable oi-computer-use
sudo systemctl start oi-computer-use
```

---

## 6. Auditing & Monitoring

- **Application Logs**: Written to `logs/mcp_server.log`. Tracks server startup, connection handshakes, and errors.
- **Security Audit Logs**: When `ENABLE_AUDIT_LOG=True`, all interactive actions (clicks, keyboard input, commands run) are logged to `logs/computer_actions.log` with details on action parameters, target coordinates, and thinking descriptions.
