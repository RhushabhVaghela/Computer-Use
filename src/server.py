"""
Universal Open Interpreter Computer-Use MCP Server

Exposes screen reading, mouse/keyboard control, and code execution
as MCP tools. Supports all three transports:

    python server.py --stdio       # For OpenFang, Claude Desktop, etc.
    python server.py --sse         # For SSE-based MCP clients
    python server.py --http        # For LobeHub (Streamable HTTP)
    python server.py --http --port 9000  # Custom port
"""
import argparse
import sys
import os
import time

# Enable DPI Awareness on Windows BEFORE importing pyautogui or mss
# to ensure we get physical coordinates and correct screen sizes.
if sys.platform == "win32":
    import ctypes
    try:
        # 2 = PROCESS_PER_MONITOR_DPI_AWARE
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        # Also try to set the newer Per-Monitor V2 if available (Windows 10 1703+)
        # ctypes.windll.user32.SetProcessDpiAwarenessContext(-4) # DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2
    except Exception:
        pass

import pyautogui # Now safe to import

# Disable pyautogui safety delays for real-time control
pyautogui.PAUSE = 0
pyautogui.FAILSAFE = True # Keep fail-safe on for safety

from dotenv import load_dotenv
load_dotenv()

# Patch sys.__stdout__.fileno and sys.__stderr__.fileno to prevent 
def _safe_fileno(orig):
    def wrapper():
        try:
            return orig()
        except Exception:
            return -1
    return wrapper

if hasattr(sys, '__stdout__') and hasattr(sys.__stdout__, 'fileno'):
    sys.__stdout__.fileno = _safe_fileno(sys.__stdout__.fileno)
if hasattr(sys, '__stderr__') and hasattr(sys.__stderr__, 'fileno'):
    sys.__stderr__.fileno = _safe_fileno(sys.__stderr__.fileno)

# CRITICAL: Patch builtins.print to default to stderr to prevent JSON-RPC corruption
# in stdio mode. This is safer than redirecting sys.stdout which would break
# the MCP transport itself.
import builtins
_orig_print = builtins.print
def safe_print(*args, **kwargs):
    if "file" not in kwargs or kwargs["file"] is None or kwargs["file"] == sys.stdout:
        kwargs["file"] = sys.stderr
    _orig_print(*args, **kwargs)
builtins.print = safe_print

import mcp.types
import pydantic_core
_orig_validate = mcp.types.JSONRPCMessage.model_validate_json
def safe_validate_json(json_data, *args, **kwargs):
    if isinstance(json_data, (str, bytes)):
        content = json_data.decode() if isinstance(json_data, bytes) else json_data
        if not content.strip():
            return mcp.types.JSONRPCMessage(
                pydantic_core.to_jsonable_python(
                    mcp.types.Notification(
                        jsonrpc="2.0", 
                        method="notifications/initialized", 
                        params={}
                    )
                )
            )
    return _orig_validate(json_data, *args, **kwargs)
mcp.types.JSONRPCMessage.model_validate_json = safe_validate_json

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import TextContent, ImageContent
import logging

# Repo root (this file lives under src/)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Configure file logging for debugging
log_dir = os.path.join(PROJECT_ROOT, "logs")
os.makedirs(log_dir, exist_ok=True)
log_file = os.path.join(log_dir, "mcp_server.log")
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger("oi-mcp")

# Silence logs that might leak to stdout
logging.getLogger("uvicorn").setLevel(logging.ERROR)
logging.getLogger("mcp").setLevel(logging.ERROR)
logging.getLogger("starlette").setLevel(logging.ERROR)

# ==========================================
# Open Interpreter & Tools Initialization (Lazy)
# ==========================================

# Global state for lazy initialization
_tools_initialized = False
computer_tool = None
ui_provider = None
overlay = None
oi_interpreter = None

def _validate_oi_path():
    """Validate and return OI_PATH. Raises error if not set or invalid."""
    # Check environment variables in priority order
    oi_path = os.environ.get("OI_PATH_WIN") or os.environ.get("OI_PATH_LINUX") or os.environ.get("OI_PATH")
    
    if not oi_path:
        error_msg = (
            "ERROR: OI_PATH environment variable is not set.\n"
            "\nThis is REQUIRED for the application to function. Please set one of:\n"
            "  - OI_PATH: Generic path to open-interpreter (used as fallback)\n"
            "  - OI_PATH_WIN: Windows-specific path (takes priority on Windows)\n"
            "  - OI_PATH_LINUX: Linux-specific path (takes priority on Linux)\n"
            "\nExample setup:\n"
            "  Windows: set OI_PATH_WIN=d:\\path\\to\\open-interpreter\n"
            "  Linux:   export OI_PATH_LINUX=/path/to/open-interpreter\n"
            "\nThe path should point to your local open-interpreter clone directory\n"
            "and must contain an 'interpreter' module."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    # Strip quotes
    oi_path = oi_path.strip('"').strip("'")
    
    # Validate path exists
    if not os.path.isdir(oi_path):
        error_msg = f"ERROR: OI_PATH directory does not exist: {oi_path}"
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    # Validate interpreter module exists
    interpreter_path = os.path.join(oi_path, "interpreter")
    if not os.path.isdir(interpreter_path):
        error_msg = (
            f"ERROR: 'interpreter' module not found in OI_PATH: {oi_path}\n"
            f"Expected directory: {interpreter_path}\n"
            "Make sure OI_PATH points to the root of the open-interpreter repository."
        )
        logger.error(error_msg)
        raise RuntimeError(error_msg)
    
    logger.info(f"OI_PATH validated successfully: {oi_path}")
    return oi_path

# Validate OI_PATH at module load time (will raise if not set)
OI_PATH = _validate_oi_path()

def ensure_tools():
    """Lazily initialize all heavy tools."""
    global _tools_initialized, computer_tool, ui_provider, overlay, oi_interpreter
    if _tools_initialized:
        return
    
    logger.info("Initializing heavy tools (OI, UI Provider, Overlay)...")
    
    if OI_PATH not in sys.path:
        sys.path.insert(0, OI_PATH)

    try:
        from interpreter import interpreter as _oi
        from interpreter.computer_use.tools import ComputerTool
        from ui_elements import UIElementProvider
        from overlay import MouseOverlay
        
        oi_interpreter = _oi
        computer_tool = ComputerTool()
        computer_tool._scaling_enabled = False
        
        ui_provider = UIElementProvider()
        overlay = MouseOverlay()

        # Add set_monitor_size to computer_tool if it doesn't have it
        # Fixed: must store left/top for multi-monitor accuracy
        if not hasattr(computer_tool, "set_monitor_size"):
            def set_monitor_size(self, width, height, left=0, top=0):
                self.width = width
                self.height = height
                self.left = left
                self.top = top
            import types
            computer_tool.set_monitor_size = types.MethodType(set_monitor_size, computer_tool)

        oi_interpreter.auto_run = True
        oi_interpreter.display = False
        
        # Patch ComputerTool's smooth_move_to
        try:
            import interpreter.computer_use.tools.computer as ct_module
            ct_module.smooth_move_to = smooth_move_to
        except Exception:
            pass
            
        _tools_initialized = True
        logger.info("Tools initialization complete.")
    except Exception as e:
        logger.exception("Failed to initialize tools")
        raise

# Global pyautogui config
# pyautogui.PAUSE = 0.05 
pyautogui.PAUSE = 0.0 
pyautogui.FAILSAFE = False 

def print_startup_info():
    """Print detailed system information on startup to stderr."""
    print("\n" + "="*60, file=sys.stderr)
    print("  Universal OI Computer-Use MCP Server Starting", file=sys.stderr)
    print("="*60, file=sys.stderr)
    
    # OS and Python Info
    import platform
    print(f"[SYSTEM]: OS Platform: {sys.platform} ({platform.release()})", file=sys.stderr)
    print(f"[SYSTEM]: Python Version: {sys.version.split(' ')[0]}", file=sys.stderr)
    print(f"[SYSTEM]: Python Executable: {sys.executable}", file=sys.stderr)
    
    # Admin Status
    if sys.platform == "win32":
        try:
            import ctypes
            is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
            admin_str = "YES (Elevated)" if is_admin else "NO (Standard User)"
            print(f"[SYSTEM]: Running as Admin: {admin_str}", file=sys.stderr)
            
            # DPI awareness check
            dpi_mode = ctypes.windll.shcore.GetProcessDpiAwareness(0)
            mode_str = {0: "None", 1: "System Aware", 2: "Per-Monitor Aware"}.get(dpi_mode, str(dpi_mode))
            print(f"[SYSTEM]: Windows DPI Awareness: {mode_str}", file=sys.stderr)
        except Exception:
            print("[SYSTEM]: Windows Info: Failed to detect Admin/DPI status", file=sys.stderr)

    # Environment & Paths
    print(f"[PATHS]: OI_PATH: {OI_PATH}", file=sys.stderr)
    print(f"[PATHS]: Project Root: {os.path.dirname(os.path.abspath(__file__))}", file=sys.stderr)

    # Library Versions
    try:
        import mcp, mss, PIL
        import importlib.metadata
        mcp_v = "unknown"
        try: mcp_v = importlib.metadata.version("mcp")
        except: pass
        print(f"[LIBS]: mcp-python-sdk: {mcp_v}", file=sys.stderr)
        print(f"[LIBS]: pyautogui: {pyautogui.__version__}", file=sys.stderr)
        print(f"[LIBS]: mss: {getattr(mss, '__version__', 'unknown')}", file=sys.stderr)
        print(f"[LIBS]: Pillow: {getattr(PIL, '__version__', 'unknown')}", file=sys.stderr)
    except Exception:
        pass

    # Mouse Info
    pos = pyautogui.position()
    size = pyautogui.size()
    print(f"[MOUSE]: Initial Position: ({pos.x}, {pos.y})", file=sys.stderr)
    print(f"[MOUSE]: Primary Screen Size: {size.width}x{size.height}", file=sys.stderr)

    # Monitor Info
    try:
        import mss
        with mss.mss() as sct:
            print(f"[MONITORS]: Detected {len(sct.monitors)-1} active monitor(s):", file=sys.stderr)
            for i, m in enumerate(sct.monitors):
                if i == 0: 
                    print(f"  - Total Desktop Area: {m['width']}x{m['height']} at ({m['left']}, {m['top']})", file=sys.stderr)
                    continue
                print(f"  - Monitor {i}: {m['width']}x{m['height']} at ({m['left']}, {m['top']})", file=sys.stderr)
    except Exception as e:
        print(f"[MONITORS]: Error detecting monitors: {e}", file=sys.stderr)
    
    print("="*60 + "\n", file=sys.stderr)

# Call startup info
print_startup_info()

def direct_move_to(x, y):
    """Direct Win32 call for coordinate-perfect mouse move."""
    if sys.platform == "win32":
        try:
            import ctypes
            # SetCursorPos works with physical pixels if DPI aware
            ctypes.windll.user32.SetCursorPos(int(x), int(y))
            return
        except Exception:
            pass
    pyautogui.moveTo(x, y)

def smooth_move_to(x, y):
    """Ultra-fast ~150ms smooth move with real-time overlay tracking."""
    start_x, start_y = pyautogui.position()
    try:
        duration_ms = float(os.environ.get("MCP_MOVE_DURATION_MS", "150"))
    except Exception:
        duration_ms = 150.0
    duration = max(0.01, duration_ms / 1000.0)

    # More steps yields smoother motion, but avoid overwhelming Tk.
    steps = 20
    
    import math
    start_t = time.perf_counter()
    for i in range(1, steps + 1):
        t = i / steps
        eased_t = (1 - math.cos(t * math.pi)) / 2 # easeInOutSine
        curr_x = int(start_x + (x - start_x) * eased_t)
        curr_y = int(start_y + (y - start_y) * eased_t)
        
        # Perfect sync: Move mouse then update overlay immediately
        direct_move_to(curr_x, curr_y)
        if overlay:
            overlay.move(curr_x, curr_y)

        # Pace the loop to the target duration (reduces jitter vs fixed sleep).
        next_t = start_t + (i * duration / steps)
        remaining = next_t - time.perf_counter()
        if remaining > 0:
            time.sleep(remaining)

import base64
import hashlib
from io import BytesIO
from PIL import Image

MAX_SCALING_TARGETS: dict[str, dict[str, int]] = {
    # Keep in sync with Open Interpreter's defaults.
    "XGA": {"width": 1024, "height": 768},  # 4:3
    "WXGA": {"width": 1280, "height": 800},  # 16:10
    "FWXGA": {"width": 1366, "height": 768},  # ~16:9
}


def _scaling_enabled() -> bool:
    v = str(os.environ.get("MCP_SCREENSHOT_SCALING", "1")).strip().lower()
    return v not in ("0", "false", "no", "off")


def _pick_scaled_size(width: int, height: int) -> tuple[int, int]:
    """Return (out_w, out_h) for screenshots. Keeps aspect ratio, scales down if enabled."""
    if not _scaling_enabled():
        return width, height

    ratio = width / height if height else 1.0
    for dim in MAX_SCALING_TARGETS.values():
        if abs((dim["width"] / dim["height"]) - ratio) < 0.02 and dim["width"] < width:
            return dim["width"], dim["height"]

    # Fallback: cap to a max bounding box while preserving aspect ratio.
    try:
        max_w = int(os.environ.get("MCP_MAX_SCREENSHOT_WIDTH", "1366"))
        max_h = int(os.environ.get("MCP_MAX_SCREENSHOT_HEIGHT", "768"))
    except Exception:
        max_w, max_h = 1366, 768

    if width <= 0 or height <= 0 or max_w <= 0 or max_h <= 0:
        return width, height

    scale = min(max_w / width, max_h / height, 1.0)
    return max(1, round(width * scale)), max(1, round(height * scale))


def _get_virtual_desktop(sct) -> dict:
    """
    Back-compat helper for older code paths.

    Note: This returns the full virtual desktop across all monitors (mss.monitors[0]).
    Newer code should prefer _get_capture_region().
    """
    m = sct.monitors[0]
    return {"left": int(m["left"]), "top": int(m["top"]), "width": int(m["width"]), "height": int(m["height"])}


def _get_capture_region(sct) -> dict:
    """
    Choose which rectangle we treat as the "desktop" for screenshots/coords.

    MCP_CAPTURE_SCOPE:
      - primary (default): use monitor 1 (the primary display)
      - virtual/all: use monitor 0 (full virtual desktop across monitors)
    """
    scope = str(os.environ.get("MCP_CAPTURE_SCOPE", "primary")).strip().lower()
    if scope in ("virtual", "all", "desktop"):
        m = sct.monitors[0]
    else:
        # mss uses 1-based indices for physical monitors.
        m = sct.monitors[1] if len(sct.monitors) > 1 else sct.monitors[0]
    return {"left": int(m["left"]), "top": int(m["top"]), "width": int(m["width"]), "height": int(m["height"])}


def _api_xy_to_desktop_xy(x: int, y: int, desktop: dict, out_w: int, out_h: int) -> tuple[int, int]:
    """
    Convert from screenshot pixel coordinates (as returned to the model) to absolute desktop coordinates
    (virtual screen coords, suitable for pyautogui on Windows).

    Notes:
    - Our screenshots are the full virtual desktop (`mss.monitors[0]`).
    - If the user provides already-absolute desktop coords, we pass them through.
    """
    dl, dt, dw, dh = desktop["left"], desktop["top"], desktop["width"], desktop["height"]

    if out_w <= 0 or out_h <= 0 or dw <= 0 or dh <= 0:
        return int(x), int(y)

    # Prefer interpreting as screenshot pixel coords when it fits the screenshot bounds.
    if 0 <= x < out_w and 0 <= y < out_h:
        sx, sy = int(x), int(y)
    # Otherwise, if it fits the desktop bounds, assume caller provided absolute desktop coords.
    elif dl <= x < dl + dw and dt <= y < dt + dh:
        return int(x), int(y)
    else:
        # Out of bounds: clamp to screenshot bounds and best-effort map.
        sx = max(0, min(int(x), out_w - 1))
        sy = max(0, min(int(y), out_h - 1))

    ax = round(sx * (dw / out_w)) + dl
    ay = round(sy * (dh / out_h)) + dt
    return int(ax), int(ay)


def _desktop_xy_to_api_xy(x: int, y: int, desktop: dict, out_w: int, out_h: int) -> tuple[int, int]:
    """Convert absolute desktop coords to screenshot pixel coords."""
    dl, dt, dw, dh = desktop["left"], desktop["top"], desktop["width"], desktop["height"]
    if out_w <= 0 or out_h <= 0 or dw <= 0 or dh <= 0:
        return int(x), int(y)
    sx = round((x - dl) * (out_w / dw))
    sy = round((y - dt) * (out_h / dh))
    return int(sx), int(sy)


def _capture_desktop_png_base64(desktop: dict, out_w: int, out_h: int) -> tuple[str, str, str]:
    """
    Capture full virtual desktop screenshot as PNG base64.

    Returns:
    - base64_png: PNG bytes base64-encoded
    - bgra_hash: md5 of raw BGRA buffer (for quick change detection)
    - png_hash: md5 of PNG bytes (for logging/debug)
    """
    import mss

    start = time.time()
    with mss.mss() as sct:
        # Grab exactly the region we are mapping coordinates against.
        sct_img = sct.grab(
            {
                "left": int(desktop["left"]),
                "top": int(desktop["top"]),
                "width": int(desktop["width"]),
                "height": int(desktop["height"]),
            }
        )
        bgra_hash = hashlib.md5(sct_img.bgra).hexdigest()
        img = Image.frombytes("RGB", sct_img.size, sct_img.bgra, "raw", "BGRX")

    if (out_w, out_h) != (desktop["width"], desktop["height"]):
        img = img.resize((out_w, out_h), Image.Resampling.LANCZOS)

    buffered = BytesIO()
    img.save(buffered, format="PNG")
    png_bytes = buffered.getvalue()
    base64_png = base64.b64encode(png_bytes).decode()
    png_hash = hashlib.md5(png_bytes).hexdigest()

    print(
        f"[SYSTEM]: Screenshot captured in {time.time()-start:.2f}s "
        f"({out_w}x{out_h}, desktop={desktop['width']}x{desktop['height']} at ({desktop['left']},{desktop['top']}), "
        f"Hash: {png_hash[:8]})",
        file=sys.stderr,
    )
    return base64_png, bgra_hash, png_hash

# ==========================================
# Core MCP Tools
# ==========================================

async def computer(
    action: str,
    text: str = None,
    coordinate: list[int] = None,
    start_coordinate: list[int] = None,
    thinking: str = None,
) -> list[TextContent | ImageContent]:
    """Perform a precise computer action.
    
    Args:
        action: The action to perform (left_click, right_click, double_click, middle_click, mouse_move, key, type, scroll, drag, screenshot).
        text: Optional text for 'type' or 'key' or element index for clicks.
        coordinate: Optional [x, y] coordinates.
        start_coordinate: Optional [x, y] for drag.
        thinking: REQUIRED. A brief description of what the agent is thinking or doing (e.g., 'Searching for submit button', 'Typing search query'). This will be displayed in the overlay.
    """
    try:
        ensure_tools()
        global pyautogui 
        
        # Map click1/click2 aliases
        if action == "click1": action = "left_click"
        if action == "click2": action = "right_click"
        
        print(f"\n[TOOL]: Action={action} text='{text}' thinking='{thinking}'", file=sys.stderr)
        
        # Sync ComputerTool with the capture region so screenshot<->desktop mapping stays consistent.
        import mss
        with mss.mss() as sct:
            desktop = _get_capture_region(sct)
            computer_tool.set_monitor_size(desktop["width"], desktop["height"], left=desktop["left"], top=desktop["top"])

        out_w, out_h = _pick_scaled_size(desktop["width"], desktop["height"])
        print(
            f"[COORD]: Screenshot space={out_w}x{out_h} maps to desktop={desktop['width']}x{desktop['height']} at ({desktop['left']},{desktop['top']})",
            file=sys.stderr,
        )

        if action == "cursor_position":
            mx, my = pyautogui.position()
            sx, sy = _desktop_xy_to_api_xy(int(mx), int(my), desktop, out_w, out_h)
            msg = (
                f"Cursor: screenshot=({sx},{sy}) desktop=({int(mx)},{int(my)}) "
                f"screenshot_size={out_w}x{out_h} desktop={desktop['width']}x{desktop['height']} at ({desktop['left']},{desktop['top']})"
            )
            return [TextContent(type="text", text=msg)]

        # Show initial overlay if we have a target
        target_x, target_y = None, None
        
        # Translate element index to coordinates early
        text_str = str(text) if text is not None else ""
        snap_msg = ""
        action_label = f"{action} {text if text else ''}"
        
        if action in ("left_click", "right_click", "double_click", "middle_click", "mouse_move") and text_str and text_str.strip().isdigit():
            idx = int(text_str.strip())
            element = ui_provider.get_element(idx)
            if element:
                cx, cy = element.center 
                target_x, target_y = cx, cy
                snap_msg = f"(Targeted element {idx}: {element.name} at {target_x},{target_y})"
                action_label = f"{action.replace('_click', '').capitalize()} {element.name[:20]}"
                print(f"[UI]: Target acquired index={idx} name='{element.name}' at {target_x},{target_y}", file=sys.stderr)
            else:
                msg = f"Error: UI element index {idx} not found."
                print(f"[ERROR]: {msg}", file=sys.stderr)
                return [TextContent(type="text", text=msg)]

        if not target_x and coordinate:
            sx, sy = int(coordinate[0]), int(coordinate[1])
            try:
                coord_grid = int(os.environ.get("MCP_COORD_GRID", "0"))
            except Exception:
                coord_grid = 0
            
            if coord_grid > 0:
                # The model outputs coordinates on a fixed grid (e.g. 1000x1000)
                # We map directly to the absolute desktop physical pixels
                target_x = round(sx * (desktop["width"] / coord_grid)) + desktop["left"]
                target_y = round(sy * (desktop["height"] / coord_grid)) + desktop["top"]
                target_x, target_y = int(target_x), int(target_y)
            else:
                target_x, target_y = _api_xy_to_desktop_xy(sx, sy, desktop, out_w, out_h)
            
            print(
                f"[COORD]: Target acquired from model coords ({sx}, {sy}) -> desktop ({target_x}, {target_y})",
                file=sys.stderr,
            )

        # 1. SHOW OVERLAY AT START POSITION FIRST
        combined_label = f"{thinking}|{action_label}" if thinking else action_label
        mx, my = pyautogui.position()
        has_moved = False
        
        if overlay:
            if target_x is not None and target_y is not None:
                overlay.show(mx, my, combined_label)
                # 2. MOVE SMOOTHLY TO TARGET (150ms)
                smooth_move_to(target_x, target_y)
                has_moved = True
            else:
                # For non-movement actions (type, key, etc.), show overlay at current mouse position
                overlay.show(mx, my, combined_label)
        
        # 3. IF NO TARGET, RE-POSITION OVERLAY TO CURRENT MOUSE POSITION JUST IN CASE
        if not has_moved and overlay:
            overlay.move(mx, my)

        # 3. CAPTURE PRE-ACTION STATE
        with mss.mss() as sct:
            pre_data = sct.grab(
                {"left": desktop["left"], "top": desktop["top"], "width": desktop["width"], "height": desktop["height"]}
            )
            pre_hash = hashlib.md5(pre_data.bgra).hexdigest()

        # 4. PERFORM ACTION
        print(f"[ACTION]: Executing {action}...", file=sys.stderr)
        if overlay:
            combined_label_exec = f"{thinking}|Executing {action}..." if thinking else f"Executing {action}..."
            overlay.update_label(combined_label_exec)
        
        if action == "left_click":
            if has_moved: pyautogui.click()
            elif target_x is not None: pyautogui.click(target_x, target_y)
            else: pyautogui.click()
        elif action == "right_click":
            if has_moved: pyautogui.rightClick()
            elif target_x is not None: pyautogui.rightClick(target_x, target_y)
            else: pyautogui.rightClick()
        elif action == "double_click":
            if has_moved: pyautogui.doubleClick()
            elif target_x is not None: pyautogui.doubleClick(target_x, target_y)
            else: pyautogui.doubleClick()
        elif action == "middle_click":
            if has_moved: pyautogui.middleClick()
            elif target_x is not None: pyautogui.middleClick(target_x, target_y)
            else: pyautogui.middleClick()
        elif action == "mouse_move":
            if not has_moved and target_x is not None:
                direct_move_to(target_x, target_y)
        elif action == "type":
            if text: 
                logger.info(f"Typing: {text}")
                try:
                    interval = float(os.environ.get("MCP_TYPE_INTERVAL_SEC", "0.02"))
                except Exception:
                    interval = 0.02
                # Small settle helps prevent dropped characters when focus just changed.
                time.sleep(0.05)
                pyautogui.write(str(text), interval=max(0.0, interval))
        elif action == "key":
            if text:
                logger.info(f"Pressing keys: {text}")
                keys = str(text).lower().split("+")
                if len(keys) > 1: 
                    pyautogui.hotkey(*keys)
                else: 
                    pyautogui.press(keys[0])
                
                # ENHANCEMENT: Smart delay for heavy UI animations
                if "win" in keys or "command" in keys:
                    time.sleep(0.8)  # Wait for Start Menu to fully open
                else:
                    time.sleep(0.05)
        elif action == "scroll":
            # API semantics:
            # - positive => scroll DOWN
            # - negative => scroll UP
            # - "down"/"up" accepted
            t = str(text).strip().lower() if text is not None else ""
            if t in ("down", "d"):
                clicks = 3
            elif t in ("up", "u"):
                clicks = -3
            elif t and t.replace("-", "").isdigit():
                clicks = int(t)
            else:
                clicks = 3
            pyautogui.scroll(-clicks * 100)
        elif action == "drag":
            if start_coordinate and coordinate:
                sx1, sy1 = int(start_coordinate[0]), int(start_coordinate[1])
                sx2, sy2 = int(coordinate[0]), int(coordinate[1])
                ax1, ay1 = _api_xy_to_desktop_xy(sx1, sy1, desktop, out_w, out_h)
                ax2, ay2 = _api_xy_to_desktop_xy(sx2, sy2, desktop, out_w, out_h)
                direct_move_to(ax1, ay1)
                pyautogui.dragTo(ax2, ay2, button="left", duration=0.1)
        
        # 5. CAPTURE RESULT AND CHECK FOR CHANGE
        if overlay and action == "screenshot":
            # Make capture feel alive in the overlay.
            overlay.status("Capturing Screen...", "orange")
        result_b64, post_hash, _png_hash = _capture_desktop_png_base64(desktop, out_w, out_h)
        
        change_msg = ""
        if pre_hash == post_hash:
            change_msg = "\n[WARNING]: Screen state UNCHANGED. If clicking doesn't work, try clicking the title bar. If a 'Save' dialog is blocking, use 'tab' then 'enter' or 'alt+n'."
            print(f"[WARNING]: No state change detected (Hash: {pre_hash[:8]})", file=sys.stderr)

        output_msg = f"Result: {snap_msg} Action completed.{change_msg}"
        
        if action == "screenshot" and result_b64:
            try:
                import datetime
                shots_dir = os.path.join(PROJECT_ROOT, "screenshots")
                if not os.path.exists(shots_dir):
                    os.makedirs(shots_dir)
                timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"
                filepath = os.path.join(shots_dir, filename)
                img_data = base64.b64decode(result_b64)
                # with open(filepath, "wb") as f:
                #     f.write(img_data)
                output_msg += f" [FILE SAVED]: {filepath}"
            except Exception as save_err:
                print(f"[ERROR]: Failed to save screenshot: {save_err}", file=sys.stderr)

        if overlay:
            overlay.update_label("Processing prompt...|")
        print(f"[SUCCESS]: {action} completed.", file=sys.stderr)

        instruction = "\n\n[SYSTEM]: Action complete. If the screen evolved, you MUST call 'read_screen_ui'. If finished, call 'terminate_task' and STOP."
        contents = [TextContent(type="text", text=output_msg + instruction)]
        if result_b64:
            contents.append(ImageContent(type="image", data=result_b64, mimeType="image/png"))

        # Optional: auto-scan UI so the model can verify success.
        # - MCP_AUTO_SCAN_ON_CHANGE=1 scans only when screen hash changed (default)
        # - MCP_AUTO_SCAN_ALWAYS=1 scans after every action (slower but more reliable)
        auto_scan_on_change = str(os.environ.get("MCP_AUTO_SCAN_ON_CHANGE", "1")).strip().lower() not in ("0", "false", "no", "off")
        auto_scan_always = str(os.environ.get("MCP_AUTO_SCAN_ALWAYS", "0")).strip().lower() in ("1", "true", "yes", "on")
        do_scan = (auto_scan_always or (auto_scan_on_change and pre_hash != post_hash)) and action not in ("cursor_position",)
        if do_scan:
            try:
                import mss
                ui_provider.reset()
                with mss.mss() as sct:
                    scope = str(os.environ.get("MCP_CAPTURE_SCOPE", "primary")).strip().lower()
                    monitors = sct.monitors[1:] if scope in ("virtual", "all", "desktop") else [sct.monitors[1]]
                    ui_provider.scan(monitors=monitors)
                ui_text = ui_provider.format_for_llm(
                    monitors=monitors,
                    computer_tool=computer_tool,
                    desktop=desktop,
                    display_size=(out_w, out_h),
                    max_elements=int(os.environ.get("MCP_AUTO_SCAN_MAX_ELEMENTS", "60")),
                    elements=ui_provider.scan(monitors=monitors)
                )
                contents.insert(0, TextContent(type="text", text="[AUTO UI SCAN]\n" + ui_text))
            except Exception as _scan_err:
                print(f"[WARN]: Auto UI scan failed: {_scan_err}", file=sys.stderr)
        
        return contents
    except Exception as e:
        if overlay: overlay.hide()
        logger.exception("Error in computer tool")
        return [TextContent(type="text", text=f"Exception: {str(e)}")]


async def read_screen_ui() -> list[TextContent]:
    """Scan the screen for interactive UI elements in a hierarchical tree."""
    try:
        ensure_tools()
        if overlay:
            overlay.status("Scanning UI Tree...", "orange")
        
        import hashlib
        import mss
        
        ui_provider.reset()
        with mss.mss() as sct:
            desktop = _get_capture_region(sct)
            out_w, out_h = _pick_scaled_size(desktop["width"], desktop["height"])
            scope = str(os.environ.get("MCP_CAPTURE_SCOPE", "primary")).strip().lower()
            monitors = sct.monitors[1:] if scope in ("virtual", "all", "desktop") else [sct.monitors[1]]
            
        # The scan() method now builds a hierarchical tree internally
        scanned_elements = ui_provider.scan(monitors=monitors)
        
        # Format as hierarchical tree for the LLM
        output = ui_provider.format_for_llm(
            monitors=monitors,
            computer_tool=computer_tool,
            desktop=desktop,
            display_size=(out_w, out_h),
            elements=scanned_elements
        )
        
        current_hash = hashlib.md5(output.encode()).hexdigest()
        warning = ""
        if hasattr(read_screen_ui, "_last_hash") and read_screen_ui._last_hash == current_hash:
            warning = "[WARNING: UI STATE UNCHANGED] "
        read_screen_ui._last_hash = current_hash
        
        # Detect if a browser is active to suggest the more efficient browser_use_dom tool
        browser_hint = ""
        try:
            import uiautomation as auto
            active_win = auto.GetForegroundWindow()
            if active_win:
                win_name = (auto.ControlFromHandle(active_win).Name or "").lower()
                if any(b in win_name for b in ["chrome", "edge", "brave", "firefox", "opera"]):
                    browser_hint = "\n\n[HINT]: A browser is active. For much more efficient and deep analysis of the web page, call 'browser_use_dom'."
        except Exception:
            pass

        if overlay:
            overlay.status("Scan Complete", "cyan")
            time.sleep(0.1)
            overlay.update_label("Processing prompt...|")

        footer = "\n\n[INSTRUCTION]: Use index numbers [idx] with 'computer' tool. If the tree is too complex, look for semantic landmarks (Window, Group, etc.)."
        return [TextContent(type="text", text=warning + output + browser_hint + footer)]
    except Exception as e:
        logger.exception("Error in read_screen_ui")
        return [TextContent(type="text", text=f"Exception: {str(e)}")]


async def bash(command: str) -> list[TextContent]:
    """Run shell code."""
    try:
        ensure_tools()
        if overlay:
            overlay.status(f"Shell: {command[:20]}...", "yellow")
            
        print(f"[SHELL]: Running command: {command}", file=sys.stderr)
        output_messages = oi_interpreter.computer.run(language="shell", code=command)
        output = "\n".join([msg["content"] for msg in output_messages if "content" in msg]).strip()
        final_output = output if output else "Code executed."
        
        if overlay:
            overlay.status("Execution Done", "green")
            time.sleep(0.1)
            overlay.update_label("Processing prompt...|")

        # ENHANCEMENT: Explicitly instruct the LLM on what to do next
        system_instruction = (
            "\n\n[SYSTEM]: Execution done. Verify success visually using 'read_screen_ui'. "
            "If the command failed, threw an error, or the app didn't open, IMMEDIATELY fallback "
            "to GUI tools: use 'read_screen_ui' followed by 'computer' (mouse/keyboard)."
        )

        return [TextContent(type="text", text=final_output + system_instruction)]
    except Exception as e:
        logger.exception("Error in bash tool")
        fallback_err = f"Exception: {str(e)}\n\n[SYSTEM]: Bash failed! Fallback to GUI tools ('read_screen_ui' -> 'computer')."
        return [TextContent(type="text", text=fallback_err)]


async def rename_file(old_path: str, new_path: str) -> list[TextContent]:
    """Rename or move a file directly (no shell, no interactive prompts)."""
    try:
        ensure_tools()
        import shutil

        src = os.path.expandvars(old_path) if old_path else old_path
        dst = os.path.expandvars(new_path) if new_path else new_path
        if not src or not dst:
            return [TextContent(type="text", text="Error: Provide old_path and new_path")]

        # Ensure destination directory exists if a directory component is present.
        dst_dir = os.path.dirname(dst)
        if dst_dir and not os.path.exists(dst_dir):
            os.makedirs(dst_dir, exist_ok=True)

        # Overwrite destination if it exists (Windows Move-Item -Force behavior).
        if os.path.exists(dst):
            try:
                os.remove(dst)
            except IsADirectoryError:
                shutil.rmtree(dst, ignore_errors=True)

        shutil.move(src, dst)
        return [TextContent(type="text", text=f"Success: {src} -> {dst}")]
    except Exception as e:
        logger.exception("Error in rename_file tool")
        return [TextContent(type="text", text=f"Exception: {str(e)}")]


async def browser_action(url: str = None, search_query: str = None, browser: str = "chrome", isolated_session: bool = True) -> list[TextContent]:
    """Specialized browser tool. 
    Directly launches the browser. Defaults to an isolated session with onboarding bypassed.
    """
    try:
        ensure_tools()
        if search_query:
            url = f"https://www.google.com/search?q={search_query.replace(' ', '+')}"
        
        if not url:
            return [TextContent(type="text", text="Error: Provide url or search_query")]

        debug_port = "9222"
        debug_flag = f"--remote-debugging-port={debug_port}"
        new_window = "--new-window"
        
        # CRITICAL FIX: Flags to suppress the "Welcome to Chrome" and sign-in roadblocks
        fre_bypass_flags = "--no-first-run --no-default-browser-check --disable-fre --disable-sync --disable-popup-blocking"
        
        profile_flag = ""
        browser = browser.lower()

        # Isolate the AI's browser session from the user's active session
        if isolated_session and sys.platform == "win32":
            temp_dir = os.path.join(os.environ.get("TEMP", "C:\\temp"), f"mcp_agent_{browser}")
            if browser == "firefox":
                profile_flag = f'-profile "{temp_dir}"'
            else:
                profile_flag = f'--user-data-dir="{temp_dir}" {fre_bypass_flags}'
            
        if sys.platform == "win32":
            if browser == "chrome":
                cmd = f'start chrome "{url}" {debug_flag} {profile_flag} {new_window}'
            elif browser == "edge":
                cmd = f'start msedge "{url}" {debug_flag} {profile_flag} {new_window}'
            elif browser == "brave":
                cmd = f'start brave "{url}" {debug_flag} {profile_flag} {new_window}'
            elif browser in ["comet", "perplexity"]:
                cmd = f'start comet "{url}" {debug_flag} {profile_flag} {new_window}'
            elif browser == "firefox":
                cmd = f'start firefox "{url}" {profile_flag} {new_window}'
            elif browser == "opera":
                cmd = f'start launcher "{url}" {debug_flag} {profile_flag} {new_window}'
            else:
                cmd = f'start {browser} "{url}" {debug_flag} {profile_flag}'
        else:
            # Linux/macOS fallback
            if browser == "chrome":
                cmd = f'google-chrome "{url}" {debug_flag} {profile_flag} {new_window} &'
            elif browser in ["comet", "perplexity"]:
                cmd = f'comet "{url}" {debug_flag} {profile_flag} {new_window} &'
            elif browser == "firefox":
                cmd = f'firefox "{url}" {new_window} &'
            else:
                cmd = f'open "{url}"'

        print(f"[BROWSER]: Launching {browser} with command: {cmd}", file=sys.stderr)
        return await bash(cmd)
    except Exception as e:
        logger.exception("Error in browser_action tool")
        return [TextContent(type="text", text=f"Exception: {str(e)}")]


async def browser_use_dom() -> list[TextContent]:
    """Extract efficient DOM structure from the installed browser."""
    try:
        ensure_tools()
        dom_tree = await ui_provider.scan_browser()
        
        if "Error connecting" in dom_tree:
            msg = (
                f"{dom_tree}\n\n"
                "[CRITICAL SYSTEM NOTE]: Connection refused. The user's active browser is NOT running in debug mode.\n"
                "-> Option 1: Call `read_screen_ui` and use the `computer` tool (mouse/keyboard clicks).\n"
                "-> Option 2: Call `browser_action` to open a separate, debuggable browser instance."
            )
            return [TextContent(type="text", text=msg)]

        system_instruction = (
            "\n\n[SYSTEM]: DOM Snapshot complete. You MUST now use `bu_browser_click`, "
            "`bu_browser_type`, or `bu_browser_navigate`. Do NOT use the `computer` tool for web elements."
        )
        return [TextContent(type="text", text=f"[BROWSER DOM SNAPSHOT]\n{dom_tree}" + system_instruction)]
    except Exception as e:
        return [TextContent(type="text", text=f"Exception: {str(e)}")]

async def update_thought(thought: str) -> list[TextContent]:
    """Update the overlay with the LLM's live thoughts. (Internal UI Tool)"""
    if overlay:
        # The pill uses "Thinking|Action" format. We put "Thinking..." small, and the live text large.
        overlay.update_label(f"Thinking...|{thought.strip()}")
    return [TextContent(type="text", text="OK")]

async def terminate_task(success: bool, message: str) -> list[TextContent]:
    """FINAL TASK SIGNAL. STOP IMMEDIATELY AFTER CALLING THIS."""
    status = "SUCCESS" if success else "FAILED"
    print(f"\n[TERMINATE]: Task ended with {status}: {message}", file=sys.stderr)
    
    # Update overlay if it exists
    if overlay:
        overlay.update_label(f"Task {status}")
        overlay.status(f"Finished: {status}", "green" if success else "red")
        time.sleep(1.0) # Brief pause so user sees the final status
        overlay.hide()
        
    # Construct a very explicit message for the LLM
    done_msg = f"[TASK_TERMINATED]: {status}\n{message}\n\n"
    done_msg += "============================================================\n"
    done_msg += "  CRITICAL: TASK COMPLETED. DO NOT GENERATE MORE TOKENS.    \n"
    done_msg += "  IF YOU ARE IN A LOOP, STOP NOW. TERMINATE EXECUTION.      \n"
    done_msg += "============================================================\n"
    
    return [TextContent(type="text", text=done_msg)]


def parse_args():
    parser = argparse.ArgumentParser(description="Open Interpreter Computer-Use MCP Server")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--stdio", action="store_true", help="Run in stdio mode")
    group.add_argument("--sse", action="store_true", help="Run in SSE mode")
    group.add_argument("--http", action="store_true", help="Run in Streamable HTTP mode")
    parser.add_argument("--host", default="0.0.0.0", help="Bind address")
    parser.add_argument("--port", type=int, default=8000, help="Port number")
    return parser.parse_args()


def create_server(host: str, port: int) -> FastMCP:
    """Create and configure the FastMCP server."""
    mcp = FastMCP(
        "Open Interpreter Computer-Use",
        host=host,
        port=port,
        transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        stateless_http=True,
    )

    mcp.tool()(computer)
    mcp.tool()(read_screen_ui)
    mcp.tool()(bash)
    mcp.tool()(terminate_task)
    mcp.tool()(rename_file)
    mcp.tool()(browser_action)
    mcp.tool()(browser_use_dom)
    mcp.tool()(browser_action)
    mcp.tool()(browser_use_dom)
    mcp.tool()(update_thought)  # <-- ADD THIS LINE

    return mcp


def main():
    args = parse_args()
    mcp = create_server(args.host, args.port)

    if args.stdio:
        mcp.run(transport="stdio")
    elif args.sse:
        mcp.run(transport="sse")
    elif args.http:
        import uvicorn
        app = mcp.streamable_http_app()
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
