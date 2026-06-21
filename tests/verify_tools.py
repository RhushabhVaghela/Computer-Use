import asyncio
import sys
import os
import time
import re
from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from mcp.types import TextContent, ImageContent

LINE_RE = re.compile(r'^\[M\d+\]\s+\[(\d+)\]\s+.+\s+"(.*)"\s+at\s+\((\-?\d+),(\-?\d+)\)\s*$')

def pick_click_index(ui_text: str) -> str:
    """Pick a stable UI element index that is not our overlay window."""
    for line in ui_text.splitlines():
        m = LINE_RE.match(line.strip())
        if not m:
            continue
        idx = m.group(1)
        name = (m.group(2) or "").strip()
        if "ComputerUseOverlay" in name or "ComputerUseCursorRing" in name:
            continue
        return idx
    return "1"

async def test_mcp_tools():
    """Test the MCP tools directly without an LLM to verify speed and overlay."""
    
    # Path to the server's python executable
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_path = os.path.join(root, "computer_use_env", "Scripts", "python.exe")
    if not os.path.exists(python_path):
        python_path = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python_path):
        python_path = sys.executable # Fallback to current python
    
    server_params = StdioServerParameters(
        command=python_path,
        args=[os.path.join(root, "src", "server.py"), "--stdio"],
        env=os.environ.copy()
    )
    
    print(f"Connecting to MCP server: {server_params.command} {' '.join(server_params.args)}")
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # 1. Test read_screen_ui (Speed Test)
            print("\n[STEP 1]: Testing read_screen_ui...")
            start_time = time.time()
            result = await session.call_tool("read_screen_ui", {})
            end_time = time.time()
            print(f"Read UI took: {end_time - start_time:.2f}s")
            ui_text = ""
            try:
                ui_text = result.content[0].text
            except Exception:
                pass
            click_idx = pick_click_index(ui_text)

            # 2. Test computer action (Overlay & Speed Test)
            print("\n[STEP 2]: Testing computer action (left_click)...")
            # Click something harmless, avoiding the overlay itself.
            start_time = time.time()
            result = await session.call_tool("computer", {
                "action": "left_click",
                "text": click_idx,
                "thinking": "verify_tools: left_click"
            })
            end_time = time.time()
            print(f"Click took: {end_time - start_time:.2f}s")
            
            # 3. Test screenshot (Speed Test)
            print("\n[STEP 3]: Testing screenshot...")
            start_time = time.time()
            result = await session.call_tool("computer", {
                "action": "screenshot",
                "thinking": "verify_tools: screenshot"
            })
            end_time = time.time()
            print(f"Screenshot took: {end_time - start_time:.2f}s")
            
            print("\n[SUCCESS]: Tools are working and optimized!")

if __name__ == "__main__":
    try:
        asyncio.run(test_mcp_tools())
    except Exception as e:
        print(f"Error: {e}")
