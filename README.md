# ⚡ Open Interpreter Computer-Use MCP Server

> A production-ready **Model Context Protocol (MCP)** server enabling **Open Interpreter** computer-use capabilities for MCP clients like Claude Desktop, OpenFang, MCP Inspector, and custom agent loops. Includes an interactive **Voice & Text Agent** powered by local VLM inference.

This project is built for **real-time desktop automation** and goes beyond simple browser scripting. It provides a full computer-use surface, combining UI scanning, mouse/keyboard control, screen processing, and Voice-driven interactions.

---

## ✨ Features

- **🗣️ Voice & Text Agent Modes**: Interact with the agent natively via voice (WebSocket, WebRTC) or terminal text using the new unified interactive menu.
- **👁️ Desktop UI Scanning & Computer Control**: Inspect screen elements, reason over them, and precisely click, drag, scroll, and type.
- **🌐 Hybrid Browser Automation**: Seamlessly combine native desktop automation with Playwright/Browser-Use DOM extraction.
- **⚡ Local VLM Optimization**: Built-in support for ultra-low latency execution via `llama.cpp` using models like `google/gemma-4-12b-qat` or `Qwen2-VL-7B`.
- **🎙️ Advanced Audio Pipeline**: Includes real-time Audio Recording, Whisper/Qwen-ASR for transcription, and Higgs/Qwen-TTS for synthesized voice responses.
- **🛡️ Secure Execution**: Tools for filesystem management, shell execution, task termination, and safety mechanisms.

---

## 🚀 Quick Start

### 1. Prerequisites
- **Python 3.11+**
- **Git**
- A local installation of [Open Interpreter](https://github.com/OpenInterpreter/open-interpreter) (Optional but recommended)
- **Windows** is currently the primary supported OS (with partial Linux/WSL support).

### 2. Installation

Clone the repository and run the setup script:

```bat
git clone https://github.com/RhushabhVaghela/Computer-Use.git
cd Computer-Use

# Run the automated setup
scripts\setup.bat

# Configure environments
copy .env.example .env
```

### 3. Launching the Agent

We provide a unified, interactive launcher for starting the agent in your preferred mode:

**On Windows:**
```bat
start_agent.bat
```
**On Linux / macOS:**
```bash
./start_agent.sh
```

**Interactive Menu Options:**
1. **Voice Agent (WebSocket/WebRTC):** Starts the real-time voice pipeline (ASR/TTS) and opens the Web UI.
2. **Text Agent (Terminal):** Starts the classic terminal-based VLM loop.
3. **Local Llama.cpp Server:** Launches a high-performance local VLM server.
4. **Hybrid / MCP Server:** Launches the standard/hybrid MCP server for Claude Desktop or OpenFang.

---

## 🏗️ Operating Modes & Architecture

### Server Modes
| Mode | Entry Point | Best For |
|---|---|---|
| **Standard MCP** | `src/server.py` | Connecting to Claude Desktop / OpenFang. Exposes basic `computer`, `bash`, and `browser` tools. |
| **Hybrid MCP** | `src/hybrid_server.py` | Complex workflows requiring deep DOM tree extraction via `browser-use`. |
| **Voice Agent** | `src/voice_server.py` | Real-time voice interaction with a frontend WebSocket client. |
| **Text Agent** | `src/run_agent.py` | Standalone terminal execution loop. |

### Tool Surface
- `computer`: Move, click, type, scroll, drag, screenshot.
- `read_screen_ui`: Hierarchical UI tree extraction for Windows UIAutomation.
- `bash`: Safe shell execution.
- `browser_action` / `browser_use_dom`: DOM extraction and browser launching.
- `bu_*` tools (Hybrid mode): Deep Playwright integration.

---

## 🎧 The Voice Pipeline

The Voice Agent leverages a specialized audio pipeline (`src/voice_pipeline.py`) designed for extremely low latency.
- **ASR (Speech-to-Text)**: Powered by `faster-whisper` (Main Env) or `Qwen-ASR` (Isolated Env).
- **TTS (Text-to-Speech)**: Powered by `Kokoro`, `Edge-TTS`, or `Qwen-TTS`.

*Note: Due to conflicting `transformers` version requirements between `Qwen-ASR` and `Qwen-TTS`, they are sandboxed into separate environments (`asr_env` and `tts_env`) if used.*

---

## 🧠 Local VLM Inference (llama.cpp)

For maximum performance, run local vision-language models (VLMs) directly.

1. **Download Llama.cpp:** Get the latest CUDA binaries from [ggerganov/llama.cpp](https://github.com/ggerganov/llama.cpp).
2. **Get the Models:** Download a VLM GGUF (e.g., `gemma-4-12b-qat-Q4_K_M.gguf`) and its projector (`mmproj-model-f16.gguf`).
3. **Start the Engine:** We provide automated scripts that handle booting `llama-server` for the LLM and `vllm-omni` in WSL for TTS. Run the following:
```bat
start_local_models.bat
```
*(On Linux/macOS, use `./start_local_models.sh` instead)*

4. **Connect the Agent:** Launch the Text or Voice Agent and specify the local provider (`http://127.0.0.1:12345/v1`).

---

## ⚙️ Configuration (.env)

Customize your agent by editing the `.env` file:
- `OI_PATH`: Path to your Open Interpreter installation.
- `MCP_AUTO_SCAN_ON_CHANGE`: Force UI scans upon screen updates (1 or 0).
- `MCP_MOVE_DURATION_MS`: Mouse movement smoothness.
- `HOST` & `PORT`: Server bindings (default `127.0.0.1:8086` for voice).

See `.env.example` for the full list of configurable options including security settings, screenshot configuration, UI scanning, browser settings, and PersonaPlex (Moshi) speech-to-speech.

---

## 🔌 MCP Client Setup

This server implements the **Model Context Protocol (MCP)** and can be connected to any MCP-compatible client (Claude Desktop, OpenFang, MCP Inspector, custom agents).

### 1. Transport Modes
The server supports three MCP transports via `src/server.py`:

| Mode | Command | Use Case |
|------|---------|----------|
| **Stdio** | `python src/server.py --stdio` | Claude Desktop, local CLI clients |
| **SSE** | `python src/server.py --sse --host 127.0.0.1 --port 8000` | Web clients, external tools |
| **Streamable HTTP** | `python src/server.py --http --host 127.0.0.1 --port 8000` | LobeHub, streaming HTTP consumers |

### 2. Claude Desktop Configuration
Add to your `claude_desktop_config.json`:

**Windows:** `%APPDATA%\Claude\claude_desktop_config.json`  
**macOS:** `~/Library/Application Support/Claude/claude_desktop_config.json`  
**Linux:** `~/.config/Claude/claude_desktop_config.json`

```json
{
  "mcpServers": {
    "computer-use": {
      "command": "python",
      "args": ["src/server.py", "--stdio"],
      "cwd": "D:/Agents-and-other-repos/Computer-Use",
      "env": {
        "OI_PATH": "D:/Agents-and-other-repos/open-interpreter"
      }
    }
  }
}
```

> **Tip:** Use the automated setup scripts (`scripts/setup.bat` or `scripts/setup.sh`) which handle virtual environment. For production, point `command` to your venv python (e.g., `.venv/Scripts/python.exe` on Windows).

### 3. OpenFang Integration
Use the provided bridge script which auto-injects MCP config:
```powershell
# Windows
platforms\openfang\bridge.ps1

# Linux/macOS
platforms\openfang\bridge.sh
```

### 4. MCP Inspector (Debugging)
```bash
npx @modelcontextprotocol/inspector python src/server.py --stdio
```

### 5. Available MCP Tools
Once connected, the following tools are exposed:

| Tool | Description |
|------|-------------|
| `computer` | Move, click, type, scroll, drag, screenshot |
| `read_screen_ui` | Hierarchical UI tree extraction (Windows UIAutomation) |
| `bash` | Safe shell execution |
| `browser_action` | Launch/control browser, navigate, extract content |
| `browser_use_dom` | Deep DOM extraction via Browser-Use |
| `bu_*` (Hybrid) | Extended Playwright tools (use `src/hybrid_server.py`) |

---


## 🛡️ Security & Recommendations

This MCP server gives agents direct control over your mouse, keyboard, shell, and filesystem. 
- **Use local Sandboxes/VMs** if running untrusted code.
- **Never expose the HTTP/WS ports** to the public internet without authentication.
- Monitor execution natively via the built-in screen overlay.

---

## 🤝 Contributing
Issues and Pull Requests are highly appreciated! Please ensure any modifications to tool schemas or startup logic are documented in your PR.

## 📄 License
This project is licensed under the **MIT License**.
