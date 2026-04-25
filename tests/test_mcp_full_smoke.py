import asyncio
import os
import re
import sys
import time
import uuid

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession


LINE_RE = re.compile(
    r'^\[M\d+\]\s+\[(\d+)\]\s+([A-Za-z0-9_]+)\s+"(.*)"\s+at\s+\((\-?\d+),(\-?\d+)\)\s*$'
)
CURSOR_META_RE = re.compile(r"screenshot_size=(\d+)x(\d+)")


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


def _pick_editish_point(ui_text: str) -> tuple[int, int] | None:
    """
    Pick a likely-safe point to click/type into.
    We prefer an EditControl; otherwise any WindowControl/PaneControl not on the taskbar region.
    """
    candidates: list[tuple[int, int, int, str, str]] = []
    for line in ui_text.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        _idx = int(m.group(1))
        ctype = m.group(2)
        name = m.group(3)
        x = int(m.group(4))
        y = int(m.group(5))

        # Basic sanity: ignore obvious taskbar-ish y values only if huge (we don't know height yet).
        candidates.append((_idx, x, y, ctype, name))

    # Prefer edit controls first.
    for idx, x, y, ctype, _name in candidates:
        if ctype == "EditControl":
            return x, y

    # Then window/pane controls.
    for idx, x, y, ctype, _name in candidates:
        if ctype in ("WindowControl", "PaneControl"):
            return x, y

    return candidates[0][1:3] if candidates else None


def _clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(v, hi))


async def _call(session: ClientSession, name: str, args: dict) -> tuple[bool, str, object]:
    try:
        res = await session.call_tool(name, args)
        # Best-effort text extraction.
        text = ""
        if getattr(res, "content", None):
            parts = []
            for c in res.content:
                t = getattr(c, "text", None)
                if t:
                    parts.append(t)
            text = "\n".join(parts).strip()
        return True, text, res
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", None


async def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    venv_py = os.path.join(root, ".venv", "Scripts", "python.exe")
    python = venv_py if os.path.exists(venv_py) else sys.executable

    server_params = StdioServerParameters(
        command=python,
        args=[os.path.join(root, "src", "server.py"), "--stdio"],
        env=os.environ.copy(),
    )

    steps: list[tuple[str, bool, str]] = []

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 1) bash: create+rename a file in %TEMP%.
            token = uuid.uuid4().hex[:8]
            src_name = rf"%TEMP%\mcp_smoke_src_{token}.txt"
            dst_name = rf"%TEMP%\mcp_smoke_dst_{token}.txt"
            ok, txt, _ = await _call(
                session,
                "bash",
                {"command": f'echo mcp_smoke_test> "{src_name}"'},
            )
            steps.append(("bash:create_temp_file", ok, txt[:200]))

            ok, txt, _ = await _call(
                session,
                "rename_file",
                {
                    "old_path": src_name,
                    "new_path": dst_name,
                },
            )
            steps.append(("rename_file", ok, txt[:200]))

            # 2) Launch Notepad (safe target for input actions).
            ok, txt, _ = await _call(session, "bash", {"command": "start notepad.exe"})
            steps.append(("bash:launch_notepad", ok, txt[:200]))
            await asyncio.sleep(1.0)

            # 3) read_screen_ui + choose a click point (screenshot coords).
            ok, ui_txt, _ = await _call(session, "read_screen_ui", {})
            steps.append(("read_screen_ui", ok, ui_txt.splitlines()[0][:200] if ui_txt else ""))

            pt = _pick_editish_point(ui_txt if ok else "")
            if not pt:
                # Fallback: use cursor_position metadata to click screen center.
                ok2, pos_txt, _ = await _call(session, "computer", {"action": "cursor_position", "thinking": "metadata"})
                steps.append(("computer:cursor_position(meta)", ok2, pos_txt[:200]))
                m = CURSOR_META_RE.search(pos_txt or "")
                if not m:
                    steps.append(("pick_point", False, "Could not derive screenshot size"))
                    pt = (500, 300)
                    sw, sh = 1000, 800
                else:
                    sw, sh = int(m.group(1)), int(m.group(2))
                    pt = (sw // 2, sh // 2)
            else:
                # We still want screenshot size for clamping offsets; pull it from cursor_position.
                ok2, pos_txt, _ = await _call(session, "computer", {"action": "cursor_position", "thinking": "metadata"})
                steps.append(("computer:cursor_position(meta)", ok2, pos_txt[:200]))
                m = CURSOR_META_RE.search(pos_txt or "")
                if m:
                    sw, sh = int(m.group(1)), int(m.group(2))
                else:
                    sw, sh = 1366, 768

            x, y = pt
            x = _clamp(x, 5, sw - 6)
            y = _clamp(y, 5, sh - 6)
            steps.append(("pick_point", True, f"screenshot=({x},{y}) size={sw}x{sh}"))

            # 4) Exercise computer actions.
            ok, txt, _ = await _call(
                session,
                "computer",
                {"action": "mouse_move", "coordinate": [x, y], "thinking": "smoke: mouse_move"},
            )
            steps.append(("computer:mouse_move", ok, txt[:200]))

            ok, txt, _ = await _call(
                session,
                "computer",
                {"action": "left_click", "coordinate": [x, y], "thinking": "smoke: left_click"},
            )
            steps.append(("computer:left_click", ok, txt[:200]))

            ok, txt, _ = await _call(
                session,
                "computer",
                {"action": "type", "text": f"MCP full smoke test {_now()}\nline2: quick brown fox\nline3: 12345\n"},
            )
            steps.append(("computer:type", ok, txt[:200]))

            ok, txt, _ = await _call(session, "computer", {"action": "key", "text": "ctrl+a"})
            steps.append(("computer:key(ctrl+a)", ok, txt[:200]))

            ok, txt, _ = await _call(session, "computer", {"action": "key", "text": "right"})
            steps.append(("computer:key(right)", ok, txt[:200]))

            ok, txt, _ = await _call(
                session,
                "computer",
                {"action": "double_click", "coordinate": [x, y], "thinking": "smoke: double_click"},
            )
            steps.append(("computer:double_click", ok, txt[:200]))

            ok, txt, _ = await _call(
                session,
                "computer",
                {"action": "right_click", "coordinate": [x, y], "thinking": "smoke: right_click"},
            )
            steps.append(("computer:right_click", ok, txt[:200]))

            ok, txt, _ = await _call(session, "computer", {"action": "key", "text": "escape"})
            steps.append(("computer:key(escape)", ok, txt[:200]))

            ok, txt, _ = await _call(session, "computer", {"action": "scroll", "text": "3"})
            steps.append(("computer:scroll(down)", ok, txt[:200]))

            ok, txt, _ = await _call(session, "computer", {"action": "scroll", "text": "-3"})
            steps.append(("computer:scroll(up)", ok, txt[:200]))

            x2 = _clamp(x + 200, 5, sw - 6)
            y2 = _clamp(y + 5, 5, sh - 6)
            ok, txt, _ = await _call(
                session,
                "computer",
                {
                    "action": "drag",
                    "start_coordinate": [x, y],
                    "coordinate": [x2, y2],
                    "thinking": "smoke: drag selection",
                },
            )
            steps.append(("computer:drag", ok, txt[:200]))

            ok, txt, _ = await _call(
                session,
                "computer",
                {"action": "middle_click", "coordinate": [x, y], "thinking": "smoke: middle_click"},
            )
            steps.append(("computer:middle_click", ok, txt[:200]))

            ok, txt, res = await _call(session, "computer", {"action": "screenshot", "thinking": "smoke: screenshot"})
            has_image = False
            if res and getattr(res, "content", None):
                for c in res.content:
                    if getattr(c, "type", None) == "image" and getattr(c, "data", None):
                        has_image = True
                        break
            steps.append(("computer:screenshot", ok and has_image, (txt[:200] if txt else "image_ok" if has_image else "no_image")))

            ok, pos_txt, _ = await _call(session, "computer", {"action": "cursor_position", "thinking": "smoke: cursor_position"})
            steps.append(("computer:cursor_position", ok, pos_txt[:200]))

            # 5) browser_action: open a search (will open Chrome).
            ok, txt, _ = await _call(
                session,
                "browser_action",
                {"search_query": f"mcp smoke test {_now()}"},
            )
            steps.append(("browser_action", ok, txt[:200]))

            # 6) terminate_task tool (just to ensure it responds).
            ok, txt, _ = await _call(
                session,
                "terminate_task",
                {"success": True, "message": "MCP full smoke test complete"},
            )
            steps.append(("terminate_task", ok, txt[:200]))

            # 7) cleanup: close Notepad forcibly to avoid save prompts.
            ok, txt, _ = await _call(session, "bash", {"command": "taskkill /im notepad.exe /f"})
            steps.append(("bash:taskkill_notepad", ok, txt[:200]))

    failed = [s for s in steps if not s[1]]
    for name, ok, detail in steps:
        print(f"{'PASS' if ok else 'FAIL'} {name}: {detail}")

    if failed:
        print(f"\nFAILED {len(failed)}/{len(steps)} steps.")
        return 1

    print(f"\nOK: all {len(steps)} steps passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
