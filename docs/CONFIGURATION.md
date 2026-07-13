# Configuration Guide - Ultimate Computer-Use MCP Server

Complete reference for all environment variables and configuration options.

---

## 📋 Table of Contents

1. [Required Configuration](#required-configuration)
2. [Screenshot Capture](#screenshot-capture)
3. [Health Monitoring](#health-monitoring)
4. [Mouse & Keyboard](#mouse--keyboard)
5. [UI Scanning](#ui-scanning)
6. [Browser Configuration](#browser-configuration)
7. [Security Settings](#security-settings)
8. [Local ML Models](#local-ml-models)
9. [Voice Pipeline](#voice-pipeline)
10. [Production Recommendations](#production-recommendations)

---

## Required Configuration

### `OI_PATH`
**Path to Open Interpreter installation**

```env
OI_PATH="D:/Agents-and-other-repos/open-interpreter"
```

**Platform-specific overrides:**
```env
OI_PATH_WIN="C:/Users/YourName/open-interpreter"
OI_PATH_LINUX="/home/user/open-interpreter"
```

**Validation:**
- Must point to directory containing `interpreter/` module
- Validated at server startup
- Server will not start without valid path

---

## Screenshot Capture (NEW!)

### `SCREENSHOT_BACKEND`
**Preferred screenshot capture backend**

```env
SCREENSHOT_BACKEND=auto
```

**Options:**
- `auto` (default) - Automatic selection (DXGI → MSS → PIL)
- `dxgi` - DirectX 11 (requires `dxcam`)
- `mss_gdi` - MSS GDI capture
- `pil_grab` - PIL ImageGrab (slowest)

**Recommendation:** Use `auto` for best compatibility.

---

### `SCREENSHOT_CACHE_ENABLED`
**Enable screenshot caching to prevent redundant captures**

```env
SCREENSHOT_CACHE_ENABLED=true
```

**Options:**
- `true` (default) - Cache enabled
- `false` - Disable caching

**Benefit:** Prevents multiple captures within TTL window.

---

### `SCREENSHOT_CACHE_TTL`
**Screenshot cache time-to-live in seconds**

```env
SCREENSHOT_CACHE_TTL=0.1
```

**Default:** `0.1` (100 milliseconds)  
**Range:** `0.01` - `1.0` seconds

**Recommendation:** Keep at 0.1s for balance of freshness and performance.

---

### `SCREENSHOT_MAX_RETRIES`
**Number of retry attempts on capture failure**

```env
SCREENSHOT_MAX_RETRIES=3
```

**Default:** `3`  
**Range:** `1` - `10`

**Behavior:** Automatic retry with exponential backoff.

---

### `SCREENSHOT_RETRY_BASE_DELAY`
**Initial retry delay in seconds (exponential backoff)**

```env
SCREENSHOT_RETRY_BASE_DELAY=0.1
```

**Default:** `0.1` (100ms)  
**Backoff:** Delay doubles each attempt (100ms → 200ms → 400ms)

---

### `SCREENSHOT_RETRY_MAX_DELAY`
**Maximum retry delay cap**

```env
SCREENSHOT_RETRY_MAX_DELAY=2.0
```

**Default:** `2.0` (2 seconds)  
**Purpose:** Prevents excessive waiting on persistent failures

---

## Health Monitoring (NEW!)

### `HEALTH_MONITOR_ENABLED`
**Enable real-time health monitoring**

```env
HEALTH_MONITOR_ENABLED=true
```

**Options:**
- `true` (default) - Monitoring enabled
- `false` - Disable monitoring

**Recommendation:** Keep enabled for production.

---

### `HEALTH_MONITOR_INTERVAL`
**Background health check interval in seconds**

```env
HEALTH_MONITOR_INTERVAL=60
```

**Default:** `60`  
**Range:** `10` - `300`

**Behavior:** Logs warnings when status is not "healthy".

---

## Mouse & Keyboard

### `MCP_MOVE_DURATION_MS`
**Smooth mouse movement duration in milliseconds**

```env
MCP_MOVE_DURATION_MS=150
```

**Default:** `150`  
**Range:** `50` - `1000`

**Effect:**
- Lower = faster, less smooth
- Higher = slower, smoother animation

---

### `MCP_TYPE_INTERVAL_SEC`
**Per-character typing interval in seconds**

```env
MCP_TYPE_INTERVAL_SEC=0.02
```

**Default:** `0.02` (20ms per character)  
**Range:** `0.001` - `0.5`

**Adjustment:**
- Increase if characters are dropped
- Decrease for faster typing (if reliable)

---

### `MCP_OVERLAY_MIN_HOLD_MS`
**Minimum time to hold overlay text visible**

```env
MCP_OVERLAY_MIN_HOLD_MS=450
```

**Default:** `450`  
**Range:** `100` - `2000`

---

### `MCP_OVERLAY_FADE_MS`
**Overlay fade-in animation duration**

```env
MCP_OVERLAY_FADE_MS=260
```

**Default:** `260`  
**Range:** `50` - `1000`

---

## UI Scanning

### `MCP_AUTO_SCAN_ON_CHANGE`
**Automatically scan UI after screen changes**

```env
MCP_AUTO_SCAN_ON_CHANGE=1
```

**Options:**
- `1` (default) - Scan when screen hash changes
- `0` - Disable auto-scan

**Recommendation:** Keep enabled for reliability.

---

### `MCP_AUTO_SCAN_ALWAYS`
**Scan UI after EVERY action (slower but more reliable)**

```env
MCP_AUTO_SCAN_ALWAYS=0
```

**Options:**
- `1` - Always scan after actions
- `0` (default) - Only scan on change

**Trade-off:** More reliable but 2-3x slower.

---

### `MCP_AUTO_SCAN_MAX_ELEMENTS`
**Maximum UI elements to return in auto-scan**

```env
MCP_AUTO_SCAN_MAX_ELEMENTS=60
```

**Default:** `60`  
**Range:** `10` - `500`

**Adjustment:**
- Increase for complex UIs
- Decrease for faster scans

---

### `MCP_UI_SCAN_BROWSER_ELEMENT_LIMIT`
**Maximum browser DOM elements to extract**

```env
MCP_UI_SCAN_BROWSER_ELEMENT_LIMIT=80
```

**Default:** `80`  
**Range:** `10` - `500`

---

### `MCP_UI_SCAN_BROWSER_MAX_DEPTH`
**Maximum DOM tree depth for browser scans**

```env
MCP_UI_SCAN_BROWSER_MAX_DEPTH=3
```

**Default:** `3`  
**Range:** `1` - `10`

**Benefit:** Limits scan time for deep DOMs.

---

### `MCP_UI_SCAN_BROWSER_ACTIVE_ONLY`
**Restrict browser scan to active window**

```env
MCP_UI_SCAN_BROWSER_ACTIVE_ONLY=true
```

**Options:**
- `true` (default) - Scan only active browser
- `false` - Scan all browser windows

---

## Browser Configuration

### `BROWSER_CDP_PORT`
**Chrome DevTools Protocol port**

```env
BROWSER_CDP_PORT=9222
```

**Default:** `9222`  
**Range:** `1024` - `65535`

**Note:** Browser must be launched with `--remote-debugging-port=9222`

---

### `browser_use` Settings (Hybrid Mode)

```env
# Python executable for browser-use
BROWSER_USE_PYTHON=

# Run in headless mode
BROWSER_USE_HEADLESS=false

# Logging level
BROWSER_USE_LOGGING_LEVEL=warning

# Setup logging
BROWSER_USE_SETUP_LOGGING=false

# Startup timeout (seconds)
HYBRID_BU_START_TIMEOUT_S=25.0

# Call timeout (seconds)
HYBRID_BU_CALL_TIMEOUT_S=25.0

# Error log path
HYBRID_BU_ERRLOG_PATH=

# Debug mode
HYBRID_DEBUG=0
```

---

## Security Settings

### `ALLOW_UNSAFE_COMMANDS`
**Bypass command denylist (DANGEROUS)**

```env
ALLOW_UNSAFE_COMMANDS=false
```

**Options:**
- `false` (default) - Enforce denylist
- `true` - Allow all commands (trusted environments only)

**⚠️ Warning:** Only set to `true` in isolated/VM environments.

---

### `RISKY_ACTION_ENABLED`
**Enable mouse/keyboard actions without confirmation**

```env
RISKY_ACTION_ENABLED=true
```

**Options:**
- `true` (default) - Actions execute immediately
- `false` - Actions require user confirmation

**Use case:** Set to `false` in shared/production environments.

---

### `COMPUTER_ACTION_RATE_LIMIT`
**Maximum computer actions per minute (0 = unlimited)**

```env
COMPUTER_ACTION_RATE_LIMIT=60
```

**Default:** `60`  
**Range:** `0` - `1000`

**Purpose:** Prevents runaway automation and abuse.

---

## Local ML Models

### `use_llama_server`
**Use local llama-server for LLM processing**

```env
USE_LLAMA_SERVER=true
```

**Options:**
- `true` (default) - Use local llama-server
- `false` - Use cloud API

---

### `llama_server_api_base`
**API base URL for llama-server**

```env
LLAMA_SERVER_API_BASE=http://127.0.0.1:8080/v1
```

**Default:** `http://127.0.0.1:8080/v1`

---

### `llama_server_model`
**Model identifier for llama-server**

```env
LLAMA_SERVER_MODEL=openai/gemma-4-12B
```

**Default:** `openai/gemma-4-12B`

---

### `asr_engine`
**Speech-to-text engine**

```env
ASR_ENGINE=whisper_turbo
```

**Options:**
- `whisper_turbo` (default) - Fast, good quality
- `whisper_base` - Slower, better quality
- `qwen-asr` - Qwen ASR (requires separate setup)

---

### `tts_engine`
**Text-to-speech engine**

```env
TTS_ENGINE=higgs
```

**Options:**
- `higgs` (default) - Higgs TTS
- `qwen3` - Qwen TTS
- `edge` - Edge TTS
- `kokoro` - Kokoro TTS

---

## Voice Pipeline (NEW!)

### PersonaPlex (Moshi) Settings

```env
# Integration mode
PERSONAPLEX_MODE=websocket

# WebSocket URL
PERSONAPLEX_URL=ws://localhost:8998/api/chat

# Binary path (subprocess mode)
PERSONAPLEX_BINARY=moshi\bin\personaplex.exe

# Model path
PERSONAPLEX_MODEL_PATH=models/personaplex-7b-v1-q4_k.gguf

# System prompt
PERSONAPLEX_PROMPT=You are a wise and friendly teacher.

# Temperature
PERSONAPLEX_TEMPERATURE=0.7
```

---

## Server Configuration

### `HOST` & `PORT`
**Server bind address and port**

```env
HOST=0.0.0.0
PORT=8000
```

**Defaults:**
- `HOST`: `0.0.0.0` (all interfaces)
- `PORT`: `8000`

---

### `mcp_tool_timeout`
**Default tool execution timeout in milliseconds**

```env
MCP_TOOL_TIMEOUT=60000
```

**Default:** `60000` (60 seconds)  
**Range:** `1000` - `300000`

---

### `mcp_screenshot_scaling`
**Enable screenshot scaling**

```env
MCP_SCREENSHOT_SCALING=true
```

**Options:**
- `true` (default) - Scale screenshots for efficiency
- `false` - Full resolution captures

---

### `mcp_max_screenshot_width` / `mcp_max_screenshot_height`
**Maximum dimensions for scaled screenshots**

```env
MCP_MAX_SCREENSHOT_WIDTH=1366
MCP_MAX_SCREENSHOT_HEIGHT=768
```

**Defaults:**
- Width: `1366`
- Height: `768`

---

## Production Recommendations

### Development Environment
```env
ALLOW_UNSAFE_COMMANDS=true
RISKY_ACTION_ENABLED=true
HEALTH_MONITOR_INTERVAL=60
SCREENSHOT_BACKEND=auto
```

### Production Environment
```env
ALLOW_UNSAFE_COMMANDS=false
RISKY_ACTION_ENABLED=false
COMPUTER_ACTION_RATE_LIMIT=60
HEALTH_MONITOR_INTERVAL=30
SCREENSHOT_CACHE_ENABLED=true
SCREENSHOT_BACKEND=dxgi  # If dxcam installed
```

### RDP/VM Environment
```env
SCREENSHOT_BACKEND=dxgi  # Required for RDP
SCREENSHOT_MAX_RETRIES=5  # Extra retries
SCREENSHOT_RETRY_BASE_DELAY=0.2
HEALTH_MONITOR_ENABLED=true
```

### High-Performance Setup
```env
SCREENSHOT_BACKEND=dxgi
SCREENSHOT_CACHE_TTL=0.05  # Aggressive caching
MCP_AUTO_SCAN_ALWAYS=0  # Only on change
MCP_AUTO_SCAN_MAX_ELEMENTS=40  # Faster scans
HEALTH_MONITOR_INTERVAL=120  # Less frequent checks
```

---

## Quick Reference Card

| Category | Key Variable | Recommended Value |
|----------|--------------|-------------------|
| **Required** | `OI_PATH` | Your OI path |
| **Screenshot** | `SCREENSHOT_BACKEND` | `auto` or `dxgi` |
| **Cache** | `SCREENSHOT_CACHE_ENABLED` | `true` |
| **Retry** | `SCREENSHOT_MAX_RETRIES` | `3` |
| **Health** | `HEALTH_MONITOR_ENABLED` | `true` |
| **Security** | `ALLOW_UNSAFE_COMMANDS` | `false` (prod) |
| **Rate Limit** | `COMPUTER_ACTION_RATE_LIMIT` | `60` |
| **Typing** | `MCP_TYPE_INTERVAL_SEC` | `0.02` |
| **Mouse** | `MCP_MOVE_DURATION_MS` | `150` |

---

For more details, see:
- [README.md](../README.md) - Quick start and features
- [HEALTH_MONITORING.md](HEALTH_MONITORING.md) - Monitoring guide
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues