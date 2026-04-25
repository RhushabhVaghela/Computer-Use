import asyncio
import json
import os
import sys
import time
import requests
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client


async def call_local_llm_stream(messages, tools, session: ClientSession):
    url = os.environ.get("OPENAI_COMPAT_URL", "http://localhost:1234/v1/chat/completions")
    model = os.environ.get("LM_STUDIO_MODEL", "openai/qwen-3.5-9b")
    payload = {
        "model": model,
        "messages": messages,
        "tools": tools,
        "tool_choice": "auto",
        "temperature": 0.0,
        "stream": True  # Streaming enabled for live thoughts!
    }
    
    loop = asyncio.get_running_loop()
    
    def _do_stream():
        try:
            r = requests.post(url, json=payload, stream=True, timeout=120)
            r.raise_for_status()
        except Exception as e:
            print(f"\n[STREAM ERROR] Connection failed: {e}")
            return "", {}
            
        full_content = ""
        tool_calls_dict = {}
        last_update = time.time()
        
        for line in r.iter_lines():
            if not line: continue
            decoded = line.decode('utf-8')
            if decoded.startswith("data: "):
                data_str = decoded[6:]
                if data_str.strip() == "[DONE]": break
                try:
                    chunk = json.loads(data_str)
                    if not chunk.get("choices"): continue
                    delta = chunk["choices"][0].get("delta", {})
                    
                    # 1. Intercept Text Thoughts and Push to Overlay
                    if "content" in delta and delta["content"]:
                        full_content += delta["content"]
                        print(delta["content"], end="", flush=True)
                        
                        now = time.time()
                        if now - last_update > 0.4: # Update UI smoothly
                            display_text = full_content.replace("\n", " ").strip()[-50:]
                            asyncio.run_coroutine_threadsafe(
                                session.call_tool("update_thought", {"thought": display_text}),
                                loop
                            )
                            last_update = now
                            
                    # 2. Rebuild Tool Calls flawlessly
                    if "tool_calls" in delta:
                        for tc in delta["tool_calls"]:
                            idx = tc.get("index", 0)
                            if idx not in tool_calls_dict:
                                tool_calls_dict[idx] = {
                                    "id": tc.get("id", f"call_local_{idx}_{int(time.time())}"), 
                                    "type": "function", 
                                    "function": {"name": "", "arguments": ""}
                                }
                            elif tc.get("id"):
                                tool_calls_dict[idx]["id"] = tc["id"]
                                
                            fn = tc.get("function", {})
                            if "name" in fn and fn["name"]:
                                tool_calls_dict[idx]["function"]["name"] += fn["name"]
                                # Show tool preparation in the overlay
                                asyncio.run_coroutine_threadsafe(
                                    session.call_tool("update_thought", {"thought": f"Preparing {tool_calls_dict[idx]['function']['name']}..."}),
                                    loop
                                )
                                
                            if "arguments" in fn and fn["arguments"]:
                                tool_calls_dict[idx]["function"]["arguments"] += fn["arguments"]
                except Exception as e:
                    pass
                    
        print() # Add newline in terminal when stream finishes
        return full_content, tool_calls_dict

    full_content, tool_calls_dict = await loop.run_in_executor(None, _do_stream)
    
    # Construct final OpenAI-compatible message
    final_message = {"role": "assistant"}
    if full_content:
        final_message["content"] = full_content
    else:
        final_message["content"] = ""
        
    if tool_calls_dict:
        final_message["tool_calls"] = [v for k, v in sorted(tool_calls_dict.items())]
        
    return final_message


def _tool_content(res):
    """Extracts text and image content blocks from the MCP tool response."""
    if not res or not getattr(res, "content", None):
        return ""
    
    blocks = []
    has_image = False
    
    for c in res.content:
        c_type = getattr(c, "type", None)
        if c_type == "text":
            blocks.append({"type": "text", "text": getattr(c, "text", "")})
        elif c_type == "image":
            has_image = True
            mime = getattr(c, "mimeType", "image/png")
            data = getattr(c, "data", "")
            blocks.append({
                "type": "image_url",
                "image_url": {"url": f"data:{mime};base64,{data}"}
            })
            
    if not has_image:
        return "\n".join([b["text"] for b in blocks if b["type"] == "text"]).strip()
        
    return blocks


def _blocked(msg: str) -> dict:
    fallback_hint = (
        " You MUST fall back to using GUI tools: call `read_screen_ui` then use the "
        "`computer` tool (mouse/keyboard) to achieve your goal. For example, press the 'win' key and type the app name."
    )
    return {"role": "tool", "content": msg + fallback_hint}


def _is_writey_shell(cmd: str) -> bool:
    s = (cmd or "").lower()
    return any(
        x in s
        for x in (
            ">", "out-file", "set-content", "add-content", "invoke-webrequest",
            "curl ", "wget ", "bitsadmin", "certutil", "copy ", "move ", "del ",
            "remove-item", "mkdir", "md ",
        )
    )


def _is_disallowed_shell(cmd: str) -> bool:
    s = (cmd or "").lower().strip()
    if s.startswith("start notepad") or s in ("start notepad.exe", "start notepad"):
        return False
    if s.startswith("start calc") or s in ("start calc.exe", "start calc"):
        return False
    if s.startswith("taskkill "):
        return False
    return True


def _to_openai_tools(mcp_tools):
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


def _extract_tool_calls(message: dict) -> list[dict]:
    tcs = message.get("tool_calls") or []
    out = []
    for tc in tcs:
        fn = (tc.get("function") or {})
        name = fn.get("name")
        args = fn.get("arguments") or "{}"
        try:
            # Fix broken JSON arguments from local streaming models
            if isinstance(args, str) and args.strip().endswith('"') and not args.strip().endswith('}'):
                args += '}'
            args_obj = json.loads(args) if isinstance(args, str) else (args or {})
        except Exception:
            args_obj = {}
        if name:
            out.append({"id": tc.get("id") or "", "name": name, "arguments": args_obj})
    return out


def _msg_has_final_answer(message: dict) -> bool:
    c = message.get("content")
    return isinstance(c, str) and c.strip() != ""


async def run(prompt: str) -> int:
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    python = os.path.join(root, ".venv", "Scripts", "python.exe")
    if not os.path.exists(python):
        python = sys.executable

    # You can read an env var or arg here to decide which server script to launch,
    # but for now, it launches hybrid_server if available, or falls back.
    server_script = "hybrid_server.py" if "--hybrid" in sys.argv else "server.py"
    
    server_params = StdioServerParameters(
        command=python,
        args=[os.path.join(root, "src", server_script), "--stdio"],
        env=os.environ.copy(),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = await session.list_tools()
            openai_tools = _to_openai_tools(tools.tools)

            # --- DYNAMIC BROWSER INJECTION ---
            has_bu_tools = any(t.name.startswith("bu_") for t in tools.tools)
            
            if has_bu_tools:
                browser_instructions = (
                    "Browser Handoff (HYBRID MODE):\n"
                    "- You are connected to the advanced browser-use backend.\n"
                    "- You MUST use `bu_browser_navigate` to open URLs.\n"
                    "- Read the page using `bu_browser_get_state`.\n"
                    "- EXCLUSIVELY use `bu_browser_click`, `bu_browser_type`, and `bu_browser_scroll` for web elements."
                )
            else:
                browser_instructions = (
                    "Browser Handoff (LOCAL MODE):\n"
                    "- You are connected directly to the local Windows desktop browser.\n"
                    "- You MUST use `browser_action` to open URLs and launch the browser.\n"
                    "- Read the page using `browser_use_dom`.\n"
                    "- Once you have the DOM tree, you MUST use the local `computer` tool passing the index [idx] (e.g., action='left_click', text='<idx>') to interact with web elements."
                )

            system_prompt = f"You are a careful tool-using assistant.\n\n{browser_instructions}"
            messages = [{"role": "system", "content": system_prompt}, {"role": "user", "content": prompt}]
            # ----------------------------------

            max_turns = int(os.environ.get("MCP_LLM_MAX_TURNS", "60"))
            for _ in range(max_turns):
                # Using the streaming LLM call so the overlay is fed live data!
                msg = await call_local_llm_stream(messages, openai_tools, session)
                messages.append(msg)

                tool_calls = _extract_tool_calls(msg)
                if not tool_calls and _msg_has_final_answer(msg):
                    return 0
                if not tool_calls:
                    return 0

                for tc in tool_calls:
                    name = tc["name"]
                    args = tc["arguments"] or {}

                    if name == "bash":
                        cmd = str(args.get("command") or "")
                        if _is_writey_shell(cmd) or _is_disallowed_shell(cmd):
                            messages.append(_blocked(f"Blocked bash command: {cmd}"))
                            continue

                    if name == "rename_file":
                        messages.append(_blocked("Blocked rename_file in this runner."))
                        continue

                    res = await session.call_tool(name, args)
                    content = _tool_content(res)
                    messages.append({"role": "tool", "tool_call_id": tc.get("id") or "", "content": content})
                    time.sleep(float(os.environ.get("MCP_LLM_TOOL_DELAY_S", "0.0")))

                    if name == "terminate_task":
                        print("\n[CLIENT]: Task terminated by agent. Exiting loop.")
                        return 0

    return 0


if __name__ == "__main__":
    if len(sys.argv) > 1:
        p = " ".join(sys.argv[1:])
    else:
        p = "Say hello, then list the available tools and stop."
    raise SystemExit(asyncio.run(run(p)))