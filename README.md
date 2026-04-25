# Open Interpreter Computer-Use MCP Server

Standalone MCP server that exposes Open Interpreter computer-use capabilities (screen reading, mouse/keyboard control, and code execution) to MCP clients.

This repo supports two modes:
1. Computer-Use mode: `src/server.py` (desktop automation via UIAutomation + mouse/keyboard)
2. Hybrid mode: `src/hybrid_server.py` (adds `bu_*` browser DOM tools via `browser-use` in a separate venv)

## Quick Start (Windows)

```bat
cd oi-computer-use-mcp
scripts\setup.bat
copy .env.example .env
scripts\start.bat --stdio
```

Hybrid mode:

```bat
REM 1) Install browser-use into its own venv (required; do not install into this repo's venv)
python -m venv ..\browser-use\.venv
..\browser-use\.venv\Scripts\python.exe -m pip install -U pip
..\browser-use\.venv\Scripts\python.exe -m pip install -r requirements.browser-use.txt

REM 2) Start the hybrid server
scripts\start.bat --hybrid --stdio
```

## Supported Transports

Same flags for both `src/server.py` and `src/hybrid_server.py`:
- `--stdio` (Claude Desktop, OpenFang, MCP Inspector)
- `--sse` (legacy clients)
- `--http` (Streamable HTTP, e.g. LobeHub)

## Tools (Computer-Use Mode)

Computer-use tools are exposed as:
- `computer`: Precise mouse/keyboard control and screenshots.
- `read_screen_ui`: Hierarchical UI tree for the entire desktop.
- `bash`: Code and shell command execution.
- `rename_file`: Direct file operations.
- `terminate_task`: Final signal to end an agent loop.
- `browser_action`: Launch Chrome, Edge, Brave, Perplexity Comet, or Firefox with debugging enabled.
- `browser_use_dom`: Efficient DOM extraction from any running browser (CDP-based).

### `computer` actions

- Mouse: `mouse_move`, `left_click`, `right_click`, `double_click`, `middle_click`, `drag`
- Keyboard: `type`, `key`
- Scroll: `scroll` (positive = down, negative = up; also accepts `up`/`down`)
- Other: `cursor_position`, `screenshot`

Notes:
- `read_screen_ui` returns coordinates in screenshot pixels that match the image returned by `computer`.
- You can click by UI element index using `computer` with `text: "<index>"` for click actions.

## Hybrid Mode (Browser DOM + Desktop)

Hybrid mode exposes everything above plus browser DOM tools prefixed with `bu_*`:
- `bu_browser_navigate`
- `bu_browser_get_state`
- `bu_browser_click`
- `bu_browser_type`
- `bu_browser_scroll`
- `bu_browser_extract_content`
- plus tab/session helpers (`bu_browser_list_tabs`, etc.)

Hybrid mode runs `browser-use` out-of-process from `../browser-use/.venv` to avoid dependency conflicts with Open Interpreter.

## MCP Configuration (Claude Desktop / OpenFang)

Add this to your `claude_desktop_config.json` or equivalent MCP client configuration.

### Standard Mode
Best for general desktop automation and fast browser interactions.

```json
{
  "mcpServers": {
    "computer-use": {
      "command": "d:/Agents-and-other-repos/oi-computer-use-mcp/.venv/Scripts/python.exe",
      "args": ["d:/Agents-and-other-repos/oi-computer-use-mcp/src/server.py", "--stdio"],
      "env": {
        "MCP_AUTO_SCAN_ON_CHANGE": "1"
      }
    }
  }
}
```

### Hybrid Mode
Includes deep DOM tools from `browser-use`. Requires separate installation (see above).

```json
{
  "mcpServers": {
    "computer-use-hybrid": {
      "command": "d:/Agents-and-other-repos/oi-computer-use-mcp/.venv/Scripts/python.exe",
      "args": ["d:/Agents-and-other-repos/oi-computer-use-mcp/src/hybrid_server.py", "--stdio"]
    }
  }
}
```

## Usage Guide

The agent can perform advanced multi-environment tasks using these tools.

### Web Browsing Workflow
1.  **Launch Browser**: Use `browser_action(url="https://google.com", browser="chrome")`. This starts Chrome, Edge, Brave, or Perplexity Comet with the `--remote-debugging-port=9222` flag.
2.  **Analyze DOM**: Use `browser_use_dom()`. This extracts a high-quality DOM tree with absolute desktop coordinates mapped for every button and link.
3.  **Interact**: Use `computer(action="left_click", text="<index>")` with the index from the DOM tree.

### Desktop UI Workflow
1.  **Scan Desktop**: Use `read_screen_ui()`. This generates a hierarchical tree of all visible windows (Excel, Word, VS Code, etc.).
2.  **Interact**: Use the provided index to click or type into specific UI elements without needing coordinates.

### Visual Feedback
The **Mouse Overlay** provides real-time feedback. When the AI moves the mouse or clicks, a modern pill-shaped overlay with a gradient background appears, displaying the AI's current "Thinking" status.

## Repo Layout

- `src/`: MCP servers + overlay + UI scanning code
- `tests/`: smoke tests and accuracy checks
- `scripts/`: setup/start scripts and LLM runner helpers
- `logs/`: server logs (default `logs/mcp_server.log`)

## Environment Variables

Core:
- `OI_PATH` (path to your `open-interpreter` clone). You can also use `OI_PATH_WIN` or `OI_PATH_LINUX` for platform-specific overrides.
- `HOST`, `PORT`
- `MCP_TOOL_TIMEOUT`

Verification / scanning:
- `MCP_AUTO_SCAN_ALWAYS` (set `1` to scan after every `computer` action)
- `MCP_AUTO_SCAN_ON_CHANGE` (default `1`)
- `MCP_AUTO_SCAN_MAX_ELEMENTS`
- `MCP_UI_SCAN_BROWSER_ELEMENT_LIMIT`, `MCP_UI_SCAN_BROWSER_MAX_DEPTH`, `MCP_UI_SCAN_BROWSER_ACTIVE_ONLY`

Overlay / input tuning:
- `MCP_MOVE_DURATION_MS`
- `MCP_OVERLAY_MIN_HOLD_MS`
- `MCP_OVERLAY_FADE_MS`
- `MCP_TYPE_INTERVAL_SEC`

Hybrid:
- `BROWSER_USE_PYTHON` (override python used to start browser-use MCP server)
- `BROWSER_USE_HEADLESS` (default profile is headless=false; keep `0` for visible browser)
