import asyncio
import os
import re
import sys
import time

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


CURSOR_META_RE = re.compile(r"screenshot_size=(\d+)x(\d+)")
CURSOR_POS_RE = re.compile(r"Cursor:\s+screenshot=\((\-?\d+),(\-?\d+)\)")
UI_LINE_RE = re.compile(r'^\[M\d+\]\s+\[(\d+)\]\s+.+\s+at\s+\((-?\d+),(-?\d+)\)\s*$')


def _repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _extract_sizes(cursor_text: str) -> tuple[int, int] | None:
    m = CURSOR_META_RE.search(cursor_text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def _extract_cursor(cursor_text: str) -> tuple[int, int] | None:
    m = CURSOR_POS_RE.search(cursor_text or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


async def _tool_text(res) -> str:
    if not res or not getattr(res, "content", None):
        return ""
    parts = []
    for c in res.content:
        t = getattr(c, "text", None)
        if t:
            parts.append(t)
    return "\n".join(parts).strip()


async def _cursor_info(session: ClientSession) -> str:
    res = await session.call_tool("computer", {"action": "cursor_position", "thinking": "accuracy: cursor_position"})
    return await _tool_text(res)


async def main() -> int:
    root = _repo_root()
    venv_py = os.path.join(root, ".venv", "Scripts", "python.exe")
    python = venv_py if os.path.exists(venv_py) else sys.executable

    server_params = StdioServerParameters(
        command=python,
        args=[os.path.join(root, "src", "server.py"), "--stdio"],
        env=os.environ.copy(),
    )

    # Configurable knobs.
    n = int(os.environ.get("MCP_ACCURACY_SAMPLES", "10"))
    tol = int(os.environ.get("MCP_ACCURACY_TOL_PX", "6"))
    settle_ms = int(os.environ.get("MCP_ACCURACY_SETTLE_MS", "60"))

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # Determine screenshot dimensions from cursor_position metadata.
            info = await _cursor_info(session)
            sizes = _extract_sizes(info)
            if not sizes:
                print(f"FAIL: Could not parse screenshot_size from cursor_position output:\n{info}")
                return 2
            sw, sh = sizes
            print(f"screenshot_size={sw}x{sh} samples={n} tol={tol}px settle={settle_ms}ms")

            # Prefer points derived from UI element coordinates returned by read_screen_ui.
            ui = await session.call_tool("read_screen_ui", {})
            ui_text = await _tool_text(ui)
            points: list[tuple[int, int]] = []
            for line in (ui_text or "").splitlines():
                m = UI_LINE_RE.match(line.strip())
                if not m:
                    continue
                x = int(m.group(2))
                y = int(m.group(3))
                if 0 <= x < sw and 0 <= y < sh:
                    points.append((x, y))
                if len(points) >= n:
                    break

            if not points:
                print("FAIL: read_screen_ui returned no usable points to test.")
                return 2

            worst = (0, 0, 0, 0)  # dx, dy, x, y
            failures = 0
            for i, (x, y) in enumerate(points, start=1):
                await session.call_tool(
                    "computer",
                    {"action": "mouse_move", "coordinate": [x, y], "thinking": f"accuracy: move {i}/{n}"},
                )
                await asyncio.sleep(settle_ms / 1000.0)
                info2 = await _cursor_info(session)
                cur = _extract_cursor(info2)
                if not cur:
                    print(f"FAIL: Could not parse cursor screenshot position:\n{info2}")
                    return 3
                sx, sy = cur
                dx = abs(sx - x)
                dy = abs(sy - y)
                if dx > worst[0] or dy > worst[1]:
                    worst = (dx, dy, x, y)
                ok = dx <= tol and dy <= tol
                if not ok:
                    failures += 1
                print(f"{'PASS' if ok else 'FAIL'} {i:02d}: target=({x},{y}) read=({sx},{sy}) delta=({dx},{dy})")

            if failures:
                dx, dy, x, y = worst
                print(f"\nFAIL: {failures}/{n} points exceeded tolerance. Worst delta=({dx},{dy}) at target=({x},{y}).")
                return 1

            dx, dy, x, y = worst
            print(f"\nPASS: all {n} points within tolerance. Worst delta=({dx},{dy}).")
            return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
