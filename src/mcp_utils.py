import os
import sys
from typing import Any, Dict, List
from mcp.client.stdio import StdioServerParameters

def get_mcp_params(hybrid: bool) -> StdioServerParameters:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python):
        python = sys.executable
        
    script = "hybrid_server.py" if hybrid else "server.py"
    print(f"[RUNNER]: Launching MCP Server: {script} via {python}")
    
    return StdioServerParameters(
        command=python,
        args=[os.path.join(root, "src", script), "--stdio"],
        env=os.environ.copy()
    )

def to_openai_tools(mcp_tools) -> List[Dict[str, Any]]:
    out = []
    for t in mcp_tools:
        params = t.inputSchema or {"type": "object", "properties": {}}
        out.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": params,
            },
        })
    return out
