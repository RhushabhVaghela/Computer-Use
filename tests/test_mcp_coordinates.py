import asyncio
import os
import re
import sys

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession


LINE_RE = re.compile(r"^\[M\d+\]\s+\[(\d+)\]\s+.+\s+at\s+\((\-?\d+),(\-?\d+)\).*$")
CURSOR_RE = re.compile(r"Cursor:\s+screenshot=\((\-?\d+),(\-?\d+)\)\s+desktop=\((\-?\d+),(\-?\d+)\)")


def _pick_first_element(text: str) -> tuple[int, int, int] | None:
    for line in text.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        idx = int(m.group(1))
        x = int(m.group(2))
        y = int(m.group(3))
        return idx, x, y
    return None


async def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_py = os.path.join(root, "computer_use_env", "Scripts", "python.exe")
    if not os.path.exists(venv_py):
        venv_py = os.path.join(root, ".venv", "Scripts", "python.exe")
    python = venv_py if os.path.exists(venv_py) else sys.executable

    server_params = StdioServerParameters(
        command=python,
        args=[os.path.join(root, "src", "server.py"), "--stdio"],
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            ui = await session.call_tool("read_screen_ui", {})
            ui_text = ui.content[0].text if ui and ui.content else ""
            pick = _pick_first_element(ui_text)
            if not pick:
                print("Failed to find any UI element line to test against.")
                return 2

            idx, x, y = pick
            print(f"Testing move to element idx={idx} at screenshot=({x},{y})")

            # Move mouse to the reported screenshot coordinate.
            await session.call_tool(
                "computer",
                {
                    "action": "mouse_move",
                    "coordinate": [x, y],
                    "thinking": "Testing coordinate mapping via MCP",
                },
            )

            pos = await session.call_tool(
                "computer",
                {
                    "action": "cursor_position",
                    "thinking": "Read back cursor position",
                },
            )
            pos_text = pos.content[0].text if pos and pos.content else ""
            m = CURSOR_RE.search(pos_text)
            if not m:
                print(f"Failed to parse cursor position: {pos_text!r}")
                return 3

            sx = int(m.group(1))
            sy = int(m.group(2))
            dx = abs(sx - x)
            dy = abs(sy - y)
            print(f"Cursor readback: screenshot=({sx},{sy}) delta=({dx},{dy})")

            tol = 5
            if dx <= tol and dy <= tol:
                print("PASS: Coordinate mapping looks consistent.")
                return 0

            print("FAIL: Coordinate mapping mismatch beyond tolerance.")
            return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
