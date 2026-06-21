import asyncio
import os
import sys

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def main() -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python_path = os.path.join(root, "computer_use_env", "Scripts", "python.exe")
    if not os.path.exists(python_path):
        python_path = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python_path):
        python_path = sys.executable

    server_params = StdioServerParameters(
        command=python_path,
        args=[os.path.join(root, "src", "hybrid_server.py"), "--stdio"],
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            names = sorted([t.name for t in tools.tools])

            bu = [n for n in names if n.startswith("bu_")]
            cu = [n for n in names if not n.startswith("bu_")]

            print(f"Total tools: {len(names)}")
            print(f"Computer-use tools: {len(cu)}")
            print(f"Browser-use proxy tools (bu_*): {len(bu)}")
            print("bu_* sample:", ", ".join(bu[:12]))

            # Minimal end-to-end proxy smoke check.
            if "bu_browser_list_sessions" in names:
                res = await session.call_tool("bu_browser_list_sessions", {})
                txt = ""
                if res.content:
                    c0 = res.content[0]
                    txt = getattr(c0, "text", "") or ""
                print("bu_browser_list_sessions:", (txt[:200] + ("..." if len(txt) > 200 else "")) or str(res.content))

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
