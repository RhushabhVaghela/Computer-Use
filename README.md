# Open Interpreter Computer-Use MCP Server

A standalone **Model Context Protocol (MCP)** server that exposes **Open Interpreter computer-use capabilities** to MCP clients such as Claude Desktop, OpenFang, MCP Inspector, and other compatible hosts.

This project is designed for **real desktop automation**, not just browser scripting. It combines:

- desktop UI scanning
- mouse / keyboard control
- screenshots
- shell execution
- browser launch + DOM extraction
- optional deep browser automation through a separate `browser-use` integration

***

## Why this project exists

Most MCP integrations stop at filesystem or shell tools. This repository goes further by giving an agent a practical **computer-use surface**:

- inspect what is visible on screen
- reason over UI elements
- click, type, drag, and scroll
- launch and inspect browsers
- combine desktop actions with browser DOM workflows

It is especially useful when you want an MCP client to automate:

- desktop applications
- mixed browser + desktop workflows
- repetitive UI tasks
- agentic research and execution loops
- human-visible, interactive automation instead of headless-only scripts

***

## Operating modes

The repository currently provides two primary runtime modes.

| Mode     | Entry point            | Best for                                                     | Notes                                                |
| -------- | ---------------------- | ------------------------------------------------------------ | ---------------------------------------------------- |
| Standard | `src/server.py`        | Desktop automation, screenshots, shell, lightweight browser support | Simplest setup path                                  |
| Hybrid   | `src/hybrid_server.py` | Mixed desktop + richer browser workflows                     | Adds delegated `browser-use` tools via separate venv |

***

## Feature matrix

| Capability                       | Standard mode | Hybrid mode | Notes                              |
| -------------------------------- | ------------: | ----------: | ---------------------------------- |
| MCP over stdio                   |           Yes |         Yes | Best for Claude Desktop / OpenFang |
| MCP over SSE                     |           Yes |         Yes | Legacy-friendly transport          |
| MCP over HTTP                    |           Yes |         Yes | For HTTP-capable MCP clients       |
| Desktop screenshots              |           Yes |         Yes | Through `computer`                 |
| Mouse control                    |           Yes |         Yes | Move, click, drag                  |
| Keyboard input                   |           Yes |         Yes | Type and key actions               |
| Scrolling                        |           Yes |         Yes | Desktop interaction                |
| Desktop UI tree scanning         |           Yes |         Yes | Through `read_screen_ui`           |
| Shell / command execution        |           Yes |         Yes | Through `bash`                     |
| File rename utility              |           Yes |         Yes | Through `rename_file`              |
| Agent loop termination tool      |           Yes |         Yes | Through `terminate_task`           |
| Browser launch helper            |           Yes |         Yes | Through `browser_action`           |
| Browser DOM extraction           |           Yes |         Yes | Through `browser_use_dom`          |
| Delegated `browser-use` tools    |            No |         Yes | `bu_*` tools only in hybrid mode   |
| Separate browser automation venv |            No |         Yes | Reduces dependency conflicts       |

***

## Architecture

At a high level, the system looks like this:

```text
MCP Client
  ├─ Claude Desktop
  ├─ OpenFang
  ├─ MCP Inspector
  └─ Other MCP hosts
          |
          v
+-----------------------------------+
| Open Interpreter Computer-Use MCP |
|                                   |
|  Standard server (`src/server.py`) |
|   ├─ computer                      |
|   ├─ read_screen_ui                |
|   ├─ bash                          |
|   ├─ browser_action                |
|   ├─ browser_use_dom               |
|   ├─ rename_file                   |
|   └─ terminate_task                |
|                                   |
|  Hybrid server (`src/hybrid_server.py`) |
|   ├─ all standard tools            |
|   └─ bu_* delegated browser tools  |
+-----------------------------------+
          |
          +--> Open Interpreter local clone
          +--> Desktop UI / input automation
          +--> Browser remote debugging / DOM extraction
          +--> Optional browser-use subprocess in separate venv
```

### Core components

| Path                       | Purpose                                                      |
| -------------------------- | ------------------------------------------------------------ |
| `src/server.py`            | Main MCP server for standard computer-use mode               |
| `src/hybrid_server.py`     | Hybrid MCP server that layers delegated browser-use tools on top |
| `src/ui_elements.py`       | UI element discovery / representation utilities              |
| `src/overlay.py`           | Visual overlay for interaction feedback                      |
| `scripts/setup.bat`        | Windows setup helper                                         |
| `scripts/setup.sh`         | Shell setup helper                                           |
| `scripts/start.bat`        | Windows launch helper                                        |
| `scripts/start.sh`         | Shell launch helper                                          |
| `tests/`                   | Smoke tests, coordinate checks, and verification scripts     |
| `computer-use-finetuning/` | Separate training / experimentation area, not the core MCP runtime |

***

## Tools exposed

### Standard mode tools

| Tool              | Purpose                                           |
| ----------------- | ------------------------------------------------- |
| `computer`        | Mouse, keyboard, scroll, cursor, drag, screenshot |
| `read_screen_ui`  | Hierarchical UI scan of visible desktop elements  |
| `bash`            | Shell / code execution                            |
| `rename_file`     | Rename file operations                            |
| `terminate_task`  | Explicit task termination signal                  |
| `browser_action`  | Launch or focus supported browsers                |
| `browser_use_dom` | Extract browser DOM state for agent reasoning     |

### `computer` action surface

| Category   | Actions                                                      |
| ---------- | ------------------------------------------------------------ |
| Mouse      | `mouse_move`, `left_click`, `right_click`, `double_click`, `middle_click`, `drag` |
| Keyboard   | `type`, `key`                                                |
| Navigation | `scroll`                                                     |
| Utility    | `cursor_position`, `screenshot`                              |

### Hybrid-only additions

Hybrid mode exposes all standard tools plus delegated browser tools prefixed with `bu_*`, including patterns such as:

- `bu_browser_navigate`
- `bu_browser_get_state`
- `bu_browser_click`
- `bu_browser_type`
- `bu_browser_scroll`
- `bu_browser_extract_content`
- browser tab and session helpers exposed by the delegated browser-use process

***

## Transports

Both runtime modes support the same transport flags.

| Flag      | Use case                                                     |
| --------- | ------------------------------------------------------------ |
| `--stdio` | Preferred for Claude Desktop, OpenFang, and most local MCP integrations |
| `--sse`   | Useful for legacy SSE-based clients                          |
| `--http`  | Useful for streamable HTTP MCP clients                       |

***

## Platform support

This repository is currently **Windows-first** in setup ergonomics and documentation.

### Current state

- Batch setup and start scripts are included for Windows
- Shell setup and start scripts are also present
- Environment variables support platform-specific Open Interpreter paths via `OI_PATH_WIN` and `OI_PATH_LINUX`
- Browser launch and UI automation assumptions are most mature on Windows

### Practical guidance

- If you want the smoothest path, start on Windows first
- If you are experimenting from WSL or Linux, validate the Open Interpreter path resolution carefully
- Treat non-Windows usage as possible but worth testing end to end in your own environment

***

## Quick start

### Windows setup

```bat
git clone https://github.com/RhushabhVaghela/Computer-Use.git
cd Computer-Use
scripts\setup.bat
copy .env.example .env
```

Start the standard server:

```bat
scripts\start.bat --stdio
```

### Hybrid setup

Install `browser-use` in a separate virtual environment. Do **not** mix it into the main environment unless you intentionally want to manage dependency conflicts yourself.

```bat
python -m venv ..\browser-use\.venv
..\browser-use\.venv\Scripts\python.exe -m pip install -U pip
..\browser-use\.venv\Scripts\python.exe -m pip install -r requirements.browser-use.txt
scripts\start.bat --hybrid --stdio
```

### Shell-based setup

If you prefer shell scripts, review and adapt:

```bash
./scripts/setup.sh
./scripts/start.sh --stdio
```

***

## MCP client configuration

### Claude Desktop / local stdio

```json
{
  "mcpServers": {
    "computer-use": {
      "command": "D:/path/to/Computer-Use/.venv/Scripts/python.exe",
      "args": [
        "D:/path/to/Computer-Use/src/server.py",
        "--stdio"
      ],
      "env": {
        "MCP_AUTO_SCAN_ON_CHANGE": "1"
      }
    }
  }
}
```

### Hybrid configuration

```json
{
  "mcpServers": {
    "computer-use-hybrid": {
      "command": "D:/path/to/Computer-Use/.venv/Scripts/python.exe",
      "args": [
        "D:/path/to/Computer-Use/src/hybrid_server.py",
        "--stdio"
      ]
    }
  }
}
```

### HTTP example

If you want to run the server over HTTP instead of stdio:

```bash
python src/server.py --http
```

Then point your MCP-capable client at the configured host and port.

***

## Example workflows

### 1. Browser-assisted desktop workflow

Use this when a task starts in the browser and finishes in a desktop app.

1. Launch a browser with `browser_action`
2. Extract page structure with `browser_use_dom`
3. Click or type using `computer`
4. Switch to the target desktop application
5. Scan visible controls with `read_screen_ui`
6. Continue interaction with `computer`

### 2. Desktop-only workflow

Use this for local application automation.

1. Call `read_screen_ui`
2. Inspect the returned hierarchy / indices
3. Use `computer` to click or type into the intended control
4. Capture a screenshot if validation is needed

### 3. Hybrid browser workflow

Use this when browser interactions need deeper DOM-aware primitives.

1. Start `src/hybrid_server.py`
2. Navigate with `bu_browser_navigate`
3. Inspect browser state with `bu_browser_get_state`
4. Use `bu_*` tools for browser-native actions
5. Fall back to `computer` when you need OS-level interaction

***

## Environment variables

The `.env.example` file already documents the current runtime knobs. The most important ones are grouped below.

### Core

| Variable           | Purpose                                          |
| ------------------ | ------------------------------------------------ |
| `OI_PATH`          | Primary path to the local Open Interpreter clone |
| `OI_PATH_WIN`      | Windows-specific override                        |
| `OI_PATH_LINUX`    | Linux-specific override                          |
| `HOST`             | Server bind host                                 |
| `PORT`             | Server port                                      |
| `MCP_TOOL_TIMEOUT` | Tool timeout in milliseconds                     |

### Overlay / input tuning

| Variable                  | Purpose                       |
| ------------------------- | ----------------------------- |
| `MCP_MOVE_DURATION_MS`    | Smooth mouse move duration    |
| `MCP_OVERLAY_MIN_HOLD_MS` | Minimum overlay hold time     |
| `MCP_OVERLAY_FADE_MS`     | Overlay fade timing           |
| `MCP_TYPE_INTERVAL_SEC`   | Per-character typing interval |

### Verification / scanning

| Variable                            | Purpose                                |
| ----------------------------------- | -------------------------------------- |
| `MCP_AUTO_SCAN_ALWAYS`              | Force scan after every computer action |
| `MCP_AUTO_SCAN_ON_CHANGE`           | Scan when the screen changes           |
| `MCP_AUTO_SCAN_MAX_ELEMENTS`        | Limit returned UI elements             |
| `MCP_UI_SCAN_BROWSER_ELEMENT_LIMIT` | Browser scan element cap               |
| `MCP_UI_SCAN_BROWSER_MAX_DEPTH`     | Browser scan depth cap                 |
| `MCP_UI_SCAN_BROWSER_ACTIVE_ONLY`   | Restrict browser scan scope            |

### Hybrid mode

| Variable               | Purpose                                                      |
| ---------------------- | ------------------------------------------------------------ |
| `BROWSER_USE_PYTHON`   | Override Python executable for delegated browser-use process |
| `BROWSER_USE_HEADLESS` | Control browser-use headless behavior                        |

***

## Supported browsers

The current project documentation describes browser launch / DOM extraction flows around:

- Google Chrome
- Microsoft Edge
- Brave
- Perplexity Comet
- Firefox

Browser support is most useful when remote debugging and DOM extraction are part of the workflow.

***

## Repository structure

```text
.
├── README.md
├── .env.example
├── requirements.txt
├── requirements.browser-use.txt
├── src/
│   ├── server.py
│   ├── hybrid_server.py
│   ├── ui_elements.py
│   ├── overlay.py
│   └── ...
├── scripts/
│   ├── setup.bat
│   ├── setup.sh
│   ├── start.bat
│   └── start.sh
├── tests/
│   ├── test_accuracy.py
│   ├── test_mcp_coordinates.py
│   ├── test_mcp_full_smoke.py
│   ├── verify_tools.py
│   └── verify_hybrid_tools.py
├── screenshots/
├── artifacts/
├── platforms/
│   └── openfang/
└── computer-use-finetuning/
```

***

## Local VLM Inference Optimization (llama.cpp)

Using desktop frontends like LM Studio for high-frequency agent actions can introduce unnecessary latency due to GUI overhead. Running `llama-server` directly from the command line is highly recommended for maximizing performance.

### RTX 5080 (16GB VRAM) Setup & Tuning

For cards like the NVIDIA RTX 5080 (16GB VRAM), we can fit the entire weights of models like `google/gemma-4-12b-qat` or `Qwen2-VL-7B` into VRAM for maximum speed.

1. **Download llama.cpp Server:**
   * Get the latest pre-built Windows CUDA binary package from the official [llama.cpp releases](https://github.com/ggerganov/llama.cpp/releases) page. Ensure you download the release compiled with CUDA support (e.g., `cudart-llama-bin-win-cuXX.X-x64.zip`).

2. **Acquire GGUF and Projector Files:**
   * Download your VLM GGUF file (e.g. `gemma-4-12b-qat-Q4_K_M.gguf`).
   * Download the matching multimodal projector file (e.g. `mmproj-model-f16.gguf`).

3. **Start the High-Performance Server:**
   Run the following command in command prompt or powershell:
   ```cmd
   llama-server.exe -m path/to/gemma-4-12b-qat-Q4_K_M.gguf --mmproj path/to/mmproj-model-f16.gguf -ngl 99 -c 8192 --host 127.0.0.1 --port 12345 --threads 8
   ```
   * **Key Parameters Explained:**
     * `-ngl 99` (`--n-gpu-layers 99`): Offloads all 99 model layers onto the RTX 5080's VRAM. Prefill and token generation will run purely on the GPU.
     * `-c 8192` (`--ctx-size 8192`): Restricts context to 8KB which is ideal for holding 1-2 turns of visual screenshots plus agent history.
     * `--threads 8`: Sets execution threads matching physical processor cores for optimal text token processing.

4. **Run the Agent Client:**
   Direct the agent client to target the high-performance local server instance:
   ```cmd
   python src/run_agent.py --provider local --api-base http://127.0.0.1:12345/v1 --model google/gemma-4-12b-qat --prompt "Launch Notepad and write a greeting"
   ```

***

## Stress Testing Suite

To stress-test coordinate clicking, multi-step browser DOM extraction, taskbar restoration, and agent self-correction under focus-loss, we have a multi-scenario benchmark tool.

### Scenarios
1. **Scenario 1 (Simple Notepad Flow):** Launches Notepad, inputs text, saves file in the temp directory, and closes.
2. **Scenario 2 (Dense Browser Scrape & Modal):** Opens a local visual dashboard, clicks to open a modal, dismisses the modal, navigates to the database tab, scans a dense service grid, extracts a critical service name, writes it to a file, and closes Chrome.
3. **Scenario 3 (Visual Focus Restoration):** Launches Notepad, begins typing. Mid-execution, the suite programmatically minimizes the Notepad window. The agent must visually detect the focus loss, click the taskbar icon to restore the window, append the completion phrase, save, and exit.

### Running the Suite
Execute the following to run all scenarios:
```cmd
python tests/stress_test_suite.py --provider local --api-base http://127.0.0.1:12345/v1 --model google/gemma-4-12b-qat
```

To run a single scenario (e.g. Scenario 2):
```cmd
python tests/stress_test_suite.py --provider local --api-base http://127.0.0.1:12345/v1 --model google/gemma-4-12b-qat --scenarios 2
```

Metrics, turns taken, latency numbers, and success codes are written to [logs/stress_test_report.json](file:///d:/Agents-and-other-repos/Computer-Use/logs/stress_test_report.json).

***

## Development and verification

### Tests currently present

- `tests/test_accuracy.py`
- `tests/test_mcp_coordinates.py`
- `tests/test_mcp_full_smoke.py`
- `tests/verify_tools.py`
- `tests/verify_hybrid_tools.py`

### Run tests

```bash
pytest -q
```

### Suggested maintainer workflow

When changing tools or protocol behavior:

1. update runtime code
2. verify standard mode tools
3. verify hybrid mode tools
4. re-check setup scripts
5. update README in the same commit

***

## Recommendations for future improvement

These are the highest-value README and project improvements based on the current visible repo structure.

### Documentation improvements

- Add a **Requirements** section listing Python version, OS assumptions, and Open Interpreter prerequisite clearly
- Add a **Troubleshooting** section for common issues such as path resolution, browser debugging ports, missing Open Interpreter clone, or hybrid venv misconfiguration
- Add **real screenshots / GIFs** showing desktop scanning, overlay feedback, and browser + desktop workflows
- Add a short **Security / Safety** section, because this project gives agents direct input-control capability
- Add a proper **License** section once a license is chosen

### Product / developer experience improvements

- Add a **tool schema summary** for each MCP tool with argument examples
- Add a **compatibility matrix** for supported MCP clients
- Add a **transport behavior note** explaining when to prefer stdio vs HTTP vs SSE
- Add explicit **non-goals** so users understand this is not a cloud sandbox or VM orchestration framework
- Add structured **release notes / changelog** once the interface stabilizes

### Architecture improvements

- Separate the runtime server docs from the `computer-use-finetuning/` research material more explicitly
- Consider adding an `ARCHITECTURE.md` that documents data flow between MCP transport, UI scanning, browser DOM extraction, overlay rendering, and delegated browser-use subprocesses
- Consider defining a stable compatibility layer for tool names and arguments so future changes do not break existing MCP client setups

***

## Positioning

A simple way to position this repository:

> **An MCP-first computer-use server for Open Interpreter, with optional hybrid browser automation.**

That description is more precise than calling it a generic browser automation tool, and it highlights the repository's strongest differentiator: **desktop + browser workflows exposed cleanly to MCP clients**.

***

## Security note

This project can control the mouse, keyboard, desktop UI, browser sessions, and shell execution. Treat it as a powerful local automation surface.

Recommended safety practices:

- run it only in trusted environments
- avoid exposing HTTP mode broadly without network controls
- keep API keys in environment variables, not source files
- validate what an MCP client is allowed to do before attaching it to this server

***

## License

No license is clearly documented in the currently visible repository root. Add one if you want other developers to know how they can use, modify, and redistribute the project.

Common options:

- MIT for maximal simplicity
- Apache-2.0 for explicit patent language
- GPL for strong copyleft

***

## Contributing

Issues and pull requests are welcome.

If you change any of the following, update the README in the same PR:

- tool names
- tool arguments
- startup scripts
- environment variables
- supported transports
- supported browser integrations
- platform expectations

***

## TL;DR

If you want the shortest path:

- use `src/server.py` for desktop-first automation
- use `src/hybrid_server.py` when you need richer browser-use flows
- keep `browser-use` in its own virtual environment
- document changes aggressively as the tool surface evolves
