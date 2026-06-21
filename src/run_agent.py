import argparse
import asyncio
import base64
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional, Tuple, Union

# Force UTF-8 encoding on standard streams to prevent Windows cp1252 UnicodeEncodeErrors
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')


# Load environment variables
from dotenv import load_dotenv
load_dotenv(override=True)

from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client
import mcp.types as mcp_types
from mcp_utils import get_mcp_params, to_openai_tools

# ===========================================================================
# Helper: Visual & Text Context Pruning
# ===========================================================================

def prune_message_history(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Prune older turns' screenshots and giant UI tree/DOM text dumps to keep local VLM prefill times under 2 seconds.
    Only keeps:
    - The single most recent user turn's screenshot (1 image total).
    - The single most recent read_screen_ui or browser_use_dom text output (truncating older ones to placeholders).
    - Auto UI scans in older computer tool outputs are stripped.
    """
    pruned = []
    user_turns_with_images = 0
    read_screen_ui_count = 0
    browser_use_dom_count = 0
    auto_ui_scan_count = 0
    
    def strip_auto_scan(text: str) -> str:
        if "[AUTO UI SCAN]" in text:
            parts = text.split("[AUTO UI SCAN]")
            return parts[0].strip() + "\n[AUTO UI SCAN Truncated]"
        return text

    def extract_active_window(text: str) -> str:
        for line in text.splitlines():
            if "[Active Window]:" in line:
                return line.strip()
        return ""

    for msg in reversed(messages):
        new_msg = msg.copy()
        role = msg.get("role")
        name = msg.get("name")
        
        # 1. Prune User Messages with Screenshots
        if role == "user":
            if isinstance(msg.get("content"), list):
                # Search for image blocks
                has_image = any(item.get("type") in ("image_url", "image") for item in msg["content"])
                if has_image:
                    user_turns_with_images += 1
                    # PRESERVE IMAGES: Stripping images breaks llama.cpp KV cache!
                    # if user_turns_with_images > 1:
                    #     text_parts = []
                    #     for item in msg["content"]:
                    #         if item.get("type") == "text":
                    #             text_parts.append(item["text"])
                    #     new_msg["content"] = " ".join(text_parts)
            elif isinstance(msg.get("content"), str):
                # Fallback message format mapping might have injected text tool responses
                content_str = msg["content"]
                if "[Tool Response for read_screen_ui]" in content_str:
                    read_screen_ui_count += 1
                    if read_screen_ui_count > 1:
                        active_win = extract_active_window(content_str)
                        new_msg["content"] = f"[Tool Response for read_screen_ui]: [UI Elements Tree Truncated (Past Turn)]"
                        if active_win:
                            new_msg["content"] = f"{active_win}\n{new_msg['content']}"
                elif "[Tool Response for browser_use_dom]" in content_str:
                    browser_use_dom_count += 1
                    if browser_use_dom_count > 1:
                        new_msg["content"] = f"[Tool Response for browser_use_dom]: [Browser DOM Snapshot Truncated]"
                elif "[Tool Response for computer]" in content_str:
                    if "[AUTO UI SCAN]" in content_str:
                        auto_ui_scan_count += 1
                        if auto_ui_scan_count > 1:
                            new_msg["content"] = strip_auto_scan(content_str)
                            
        # 2. Prune Tool Messages (Native Tool Calling)
        elif role == "tool":
            if name == "read_screen_ui":
                read_screen_ui_count += 1
                if read_screen_ui_count > 1:
                    content_str = str(msg.get("content") or "")
                    active_win = extract_active_window(content_str)
                    truncated_text = f"[UI Elements Tree Truncated (Past Turn)]"
                    if active_win:
                        truncated_text = f"{active_win}\n{truncated_text}"
                    new_msg["content"] = truncated_text
            elif name == "browser_use_dom":
                browser_use_dom_count += 1
                if browser_use_dom_count > 1:
                    new_msg["content"] = f"[Browser DOM Snapshot Truncated]"
            elif name == "computer":
                content_str = str(msg.get("content") or "")
                if "[AUTO UI SCAN]" in content_str:
                    auto_ui_scan_count += 1
                    if auto_ui_scan_count > 1:
                        new_msg["content"] = strip_auto_scan(content_str)
                        
        pruned.insert(0, new_msg)
        
    return pruned


def parse_fallback_json(content: str) -> Dict[str, Any]:
    """
    Extremely robust JSON parser that extracts and parses tool calls from 
    local model fallback outputs, even when they are unclosed or truncated.
    """
    import re
    import json
    
    clean_content = content.strip()
    
    # 1. Try to find JSON inside markdown code block
    json_match = re.search(r"```json\s*(.*?)\s*(?:```|$)", clean_content, re.DOTALL)
    if json_match:
        json_str = json_match.group(1).strip()
    else:
        # Check if there is a raw JSON block starting with {
        first_curly = clean_content.find("{")
        if first_curly != -1:
            json_str = clean_content[first_curly:].strip()
        else:
            json_str = clean_content
            
    # 2. Try standard parsing
    try:
        return json.loads(json_str)
    except Exception:
        pass
        
    # 3. Try to repair truncated JSON by adding closing brackets/quotes
    for suffix in ["", "}", "]}", "]} }", "\"}]}", "\"} ] }", "\"} ]", "\"} }", "\"}"]:
        try:
            return json.loads(json_str + suffix)
        except Exception:
            pass
            
    # 4. If repair fails, fall back to regex extraction for name and arguments
    try:
        names = re.findall(r'"name"\s*:\s*"([^"]+)"', json_str)
        args_matches = re.finditer(r'"arguments"\s*:\s*(\{.*?)(?:"name"|]$|}$|$)', json_str, re.DOTALL)
        
        tool_calls = []
        for i, (name, match) in enumerate(zip(names, args_matches)):
            arg_str = match.group(1).strip()
            arg_data = {}
            for suffix in ["", "}", "\"}", "\"} }", "\"}"]:
                try:
                    arg_data = json.loads(arg_str + suffix)
                    break
                except Exception:
                    pass
            tool_calls.append({
                "name": name,
                "arguments": arg_data
            })
        if tool_calls:
            return {
                "thought": "Extracted from truncated JSON",
                "tool_calls": tool_calls
            }
    except Exception:
        pass
        
    raise ValueError("Failed to parse JSON")


# --- Anthropic (Claude 3.5 Sonnet) ---
async def call_anthropic(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    import anthropic
    client = anthropic.AsyncAnthropic(api_key=api_key)
    
    # Anthropic expects tools with specific fields
    anthropic_tools = []
    for t in tools:
        fn = t["function"]
        anthropic_tools.append({
            "name": fn["name"],
            "description": fn["description"],
            "input_schema": fn["parameters"]
        })
        
    response = await client.messages.create(
        model=model,
        max_tokens=4000,
        system=system_prompt,
        messages=messages,
        tools=anthropic_tools,
        temperature=0.0
    )
    
    # Convert Anthropic response to common OpenAI-compatible format
    content_text = ""
    tool_calls = []
    
    for block in response.content:
        if block.type == "text":
            content_text += block.text
        elif block.type == "tool_use":
            tool_calls.append({
                "id": block.id,
                "type": "function",
                "function": {
                    "name": block.name,
                    "arguments": json.dumps(block.input)
                }
            })
            
    result = {
        "role": "assistant",
        "content": content_text,
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result

# --- OpenAI (GPT-4o) & Local (LM Studio, Ollama, vLLM) ---
async def call_openai_compatible(
    api_key: str,
    api_base: str,
    model: str,
    system_prompt: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
    force_fallback: bool = False,
) -> Dict[str, Any]:
    import openai
    
    # Prune visual and text context to keep context small and fast
    pruned_messages = prune_message_history(messages)
    
    # Inject system prompt into messages if needed (OpenAI style)
    formatted_messages = []
    if system_prompt:
        formatted_messages.append({"role": "system", "content": system_prompt})
    formatted_messages.extend(pruned_messages)
    
    cleaned_messages = formatted_messages
    client = openai.AsyncOpenAI(api_key=api_key or "local-key", base_url=api_base)
    
    use_fallback = force_fallback
    if not use_fallback:
        try:
            response = await client.chat.completions.create(
                model=model,
                messages=cleaned_messages,
                tools=tools,
                tool_choice="auto" if tools else None,
                temperature=0.0,
                max_tokens=2048
            )
            
            choice = response.choices[0]
            result = {
                "role": "assistant",
                "content": choice.message.content or "",
            }
            if choice.message.tool_calls:
                tool_calls = []
                for tc in choice.message.tool_calls:
                    tool_calls.append({
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments
                        }
                    })
                result["tool_calls"] = tool_calls
            return result
        except Exception as e:
            err_msg = str(e).lower()
            if "jinja" in err_msg or "template" in err_msg or "tool" in err_msg:
                use_fallback = True
            else:
                raise e

    if use_fallback:
        print("[RUNNER WARN]: Using text JSON prompting fallback for tool calling...")
        # Inject tool descriptions in system prompt
        import re
        formatted_tools = json.dumps(tools, indent=2)
        
        fallback_system_prompt = (
            f"{system_prompt}\n\n"
            "You MUST use tool calling to perform this task. Below are the available tools:\n"
            f"{formatted_tools}\n\n"
            "To call a tool, respond with a JSON markdown block of this exact format:\n"
            "```json\n"
            "{\n"
            "  \"thought\": \"your detailed thinking explaining the action\",\n"
            "  \"tool_calls\": [\n"
            "    {\n"
            "      \"name\": \"tool_name\",\n"
            "      \"arguments\": {\"param\": \"value\"}\n"
            "    }\n"
            "  ]\n"
            "}\n"
            "```\n"
            "Ensure that your response contains only this JSON block inside the ```json block."
        )
        
        # Reconstruct message stack with injected system instructions
        fallback_messages = []
        fallback_messages.append({"role": "system", "content": fallback_system_prompt})
        
        # Map existing history to standard user/assistant roles while keeping screenshots intact
        mapped_history = []
        for m in pruned_messages:
            if m["role"] == "system":
                continue
            
            clean_m = {}
            if m["role"] == "tool":
                # Convert tool response to user message
                clean_m["role"] = "user"
                # Handle multimodal list format vs string content
                if isinstance(m.get("content"), list):
                    clean_m["content"] = []
                    for item in m["content"]:
                        if item.get("type") == "text":
                            clean_m["content"].append({
                                "type": "text",
                                "text": f"[Tool Response for {m.get('name')}]: {item['text']}"
                            })
                        else:
                            clean_m["content"].append(item)
                else:
                    clean_m["content"] = f"[Tool Response for {m.get('name')}]: {m.get('content')}"
                    
            elif m["role"] == "assistant":
                clean_m["role"] = "assistant"
                content = m.get("content") or ""
                if "tool_calls" in m and m["tool_calls"]:
                    tc_list = []
                    for tc in m["tool_calls"]:
                        fn = tc["function"]
                        try:
                            args_dict = json.loads(fn["arguments"])
                        except Exception:
                            args_dict = fn["arguments"]
                        tc_list.append({
                            "name": fn["name"],
                            "arguments": args_dict
                        })
                    
                    fallback_json = {
                        "thought": content,
                        "tool_calls": tc_list
                    }
                    clean_m["content"] = f"```json\n{json.dumps(fallback_json, indent=2)}\n```"
                else:
                    clean_m["content"] = content
                
            else:
                clean_m["role"] = m["role"]
                if isinstance(m.get("content"), list):
                    clean_m["content"] = [item.copy() for item in m["content"]]
                else:
                    clean_m["content"] = m.get("content")
                
            mapped_history.append(clean_m)

        fallback_messages.extend(mapped_history)
            
        # Call completions without API tools
        response = await client.chat.completions.create(
            model=model,
            messages=fallback_messages,
            temperature=0.0,
            max_tokens=2048
        )
        
        content = response.choices[0].message.content or ""
        print(f"[DEBUG VLM RAW]:\n{content}\n[DEBUG VLM END]", file=sys.stderr)
        
        try:
            data = parse_fallback_json(content)
            thought = data.get("thought", "")
            tc_list = data.get("tool_calls", [])
            
            tool_calls = []
            for tc in tc_list:
                name = tc.get("name")
                args = tc.get("arguments")
                if args is None:
                    # If arguments are flattened (at the same level as name), collect all other keys as arguments
                    args = {k: v for k, v in tc.items() if k not in ("name", "id", "type", "thinking")}
                
                tool_calls.append({
                    "id": tc.get("id") or f"call_local_{int(time.time())}",
                    "type": "function",
                    "function": {
                        "name": name,
                        "arguments": json.dumps(args)
                    }
                })
                
            # Extract spoken text: it is the text OUTSIDE the JSON block.
            import re
            json_match = re.search(r"```json\s*(.*?)\s*(?:```|$)", content, re.DOTALL)
            if json_match:
                spoken_text = content.replace(json_match.group(0), "").strip()
            else:
                spoken_text = content.replace(json.dumps(data), "").strip() if data else ""
                
            if not spoken_text and not tool_calls:
                spoken_text = thought  # Fallback if the model put its entire response inside 'thought'
                
            return {
                "role": "assistant",
                "content": spoken_text,
                "thought": thought,
                "tool_calls": tool_calls
            }
        except Exception:
            # If parsing fails, fall back to returning raw content
            return {
                "role": "assistant",
                "content": content
            }

# --- Gemini (via official REST endpoint for safety/speed) ---
async def call_gemini(
    api_key: str,
    model: str,
    system_prompt: str,
    messages: List[Dict[str, Any]],
    tools: List[Dict[str, Any]],
) -> Dict[str, Any]:
    import httpx
    
    # Prune visual and text context to keep context small and fast
    pruned_messages = prune_message_history(messages)
    
    # Map messages list to Gemini Content structure
    # Role maps: user -> user, assistant -> model, tool -> user (with functionResponse)
    gemini_contents = []
    
    # Keep track of active tool response mapping
    for msg in pruned_messages:
        role = msg["role"]
        if role == "user":
            parts = []
            if isinstance(msg.get("content"), list):
                for item in msg["content"]:
                    if item.get("type") == "text":
                        parts.append({"text": item["text"]})
                    elif item.get("type") == "image_url":
                        url_str = item["image_url"]["url"]
                        # Extract base64 part
                        if "," in url_str:
                            b64_data = url_str.split(",")[1]
                        else:
                            b64_data = url_str
                        parts.append({
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": b64_data
                            }
                        })
            else:
                parts.append({"text": str(msg.get("content") or "")})
            gemini_contents.append({"role": "user", "parts": parts})
            
        elif role == "assistant":
            parts = []
            if msg.get("content"):
                parts.append({"text": msg["content"]})
            if msg.get("tool_calls"):
                for tc in msg["tool_calls"]:
                    fn = tc["function"]
                    parts.append({
                        "functionCall": {
                            "name": fn["name"],
                            "args": json.loads(fn["arguments"])
                        }
                    })
            gemini_contents.append({"role": "model", "parts": parts})
            
        elif role == "tool":
            # Map tool response to functionResponse
            # If content was a list (text + image), split them.
            parts = []
            res_content = msg.get("content")
            
            # Simple text response
            text_res = ""
            if isinstance(res_content, list):
                # Search for text and image blocks
                for item in res_content:
                    if item.get("type") == "text":
                        text_res += item["text"] + "\n"
                    elif item.get("type") == "image_url":
                        url_str = item["image_url"]["url"]
                        b64_data = url_str.split(",")[1] if "," in url_str else url_str
                        parts.append({
                            "inlineData": {
                                "mimeType": "image/png",
                                "data": b64_data
                            }
                        })
            else:
                text_res = str(res_content or "")
                
            parts.insert(0, {
                "functionResponse": {
                    "name": msg.get("name", "unknown"),
                    "response": {"output": text_res.strip()}
                }
            })
            gemini_contents.append({"role": "user", "parts": parts})

    # Map tools to Gemini schema
    gemini_tools = []
    if tools:
        declarations = []
        for t in tools:
            fn = t["function"]
            declarations.append({
                "name": fn["name"],
                "description": fn["description"],
                "parameters": fn["parameters"]
            })
        gemini_tools.append({"function_declarations": declarations})

    # Call Gemini REST API
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    payload = {
        "contents": gemini_contents,
        "generationConfig": {"temperature": 0.0}
    }
    if system_prompt:
        payload["systemInstruction"] = {"role": "user", "parts": [{"text": system_prompt}]}
    if gemini_tools:
        payload["tools"] = gemini_tools
        
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers={"Content-Type": "application/json"}, timeout=120.0)
        r.raise_for_status()
        res_json = r.json()
    
    # Parse Response
    candidate = res_json["candidates"][0]
    print(f"[DEBUG GEMINI]: candidate = {json.dumps(candidate)}", flush=True)
    content = candidate.get("content", {})
    parts = content.get("parts", [])
    
    content_text = ""
    tool_calls = []
    
    for part in parts:
        if "text" in part:
            content_text += part["text"]
        elif "functionCall" in part:
            fc = part["functionCall"]
            tool_calls.append({
                "id": f"call_gemini_{int(time.time())}",
                "type": "function",
                "function": {
                    "name": fc["name"],
                    "arguments": json.dumps(fc.get("args") or {})
                }
            })
            
    result = {
        "role": "assistant",
        "content": content_text,
    }
    if tool_calls:
        result["tool_calls"] = tool_calls
    return result

# ===========================================================================
# 2. Conversational Message Formatter
# ===========================================================================

def format_tool_content_for_role(res, provider: str, text_only: bool = False) -> Union[str, List[Dict[str, Any]]]:
    """Parse MCP tool result into the provider's message schema."""
    if not res or not getattr(res, "content", None):
        return "Action complete."
        
    text_blocks = []
    image_b64 = None
    
    for c in res.content:
        c_type = getattr(c, "type", None)
        if c_type == "text":
            text_blocks.append(getattr(c, "text", ""))
        elif c_type == "image":
            image_b64 = getattr(c, "data", "")
            
    text_out = "\n".join(text_blocks).strip()
    if not text_out:
        text_out = "Action completed."
        
    if text_only or not image_b64:
        return text_out
        
    # Provider-specific mapping
    if provider == "anthropic":
        content_blocks = [{"type": "text", "text": text_out}]
        content_blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": "image/png",
                "data": image_b64
            }
        })
        return content_blocks
        
    elif provider in ("openai", "local"):
        # For OpenAI tools, since we cannot return an image in the tool response directly
        # in standard libraries, we return a list format, which we will handle.
        # Note: We return it as a list that the runner will append.
        return [
            {"type": "text", "text": text_out},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
        ]
        
    elif provider == "gemini":
        # Handled in call_gemini payload formatting dynamically
        return [
            {"type": "text", "text": text_out},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}}
        ]
        
    return text_out

# ===========================================================================
# 3. Main Runner Loop
# ===========================================================================

async def run_agent(
    provider: str,
    model: str,
    api_key: str,
    api_base: str,
    prompt: str,
    hybrid: bool,
    max_turns: int,
    text_only: bool = False,
    force_fallback: bool = False
):
    server_params = get_mcp_params(hybrid)
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # List available tools
            mcp_tools_list = await session.list_tools()
            tools = to_openai_tools(mcp_tools_list.tools)
            
            # Configure instructions based on hybrid vs standard mode
            has_bu = any(t.name.startswith("bu_") for t in mcp_tools_list.tools)
            if has_bu:
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
                
            system_prompt = (
                "You are an expert desktop automation AI assistant that can control the user's computer using the provided tools.\n"
                "You inspect the screen, plan actions, click, drag, scroll, type, and verify outcomes.\n\n"
                "CRITICAL EXECUTION STRATEGY:\n"
                "1. INDEXING FOR PERFECT ACCURACY:\n"
                "   - To click, hover, drag, or type on any screen elements with 100% precision, you MUST first run `read_screen_ui` (for desktop) or `browser_use_dom` (for web).\n"
                "   - Extract the element's index number `[idx]` (e.g. `12` or `[12]`) and pass it as the `text` argument in your click tool: `computer(action='left_click', text='[12]')` instead of predicting raw `[x, y]` coordinates. This avoids coordinate scaling offsets and clicks the target exactly.\n\n"
                "2. SELF-CORRECTION & VERIFICATION:\n"
                "   - After every action, inspect the returned text output and screenshot to evaluate the outcome.\n"
                "   - If you see `[WARNING]: Screen state UNCHANGED` or notice the window didn't open/type/update, your action failed (usually due to window focus loss or clicking an inactive region).\n"
                "   - Do NOT repeat the exact same failing action. You must self-correct: first click the title bar or window to focus the app, run `read_screen_ui` to re-index, and then try a different approach (or use keyboard shortcuts like tab/enter/alt keys).\n\n"
                "3. SPEED & EFFICIENCY:\n"
                "   - Minimize turns to complete tasks as fast as possible.\n"
                "   - Prefer running CLI commands via `bash` directly (e.g. `start notepad`, `taskkill`, `python my_script.py`, file operations) to bypass slow multi-step visual clicking when possible.\n\n"
                "4. ACTIVE WINDOW & FOCUS MONITORING:\n"
                "   - Monitor the `[Active Window]` metadata in the tool results (including State: Minimized/Maximized/Normal).\n"
                "   - If the target window becomes minimized or loses focus, click its taskbar icon or use `alt+tab` to restore it before typing or clicking. Do not assume focus is kept if the state is Minimized.\n\n"
                f"{browser_instructions}"
            )
            
            # Initialize messages
            messages = [{"role": "user", "content": prompt}]
            
            print(f"\n[AGENT START]: Provider={provider.upper()} Model={model} Max Turns={max_turns}")
            print(f"Prompt: {prompt}\n")
            
            last_sig = None
            rep_count = 0
            loop_warning_to_inject = None
            
            for turn in range(1, max_turns + 1):
                print(f"[TURN {turn}/{max_turns}]: Requesting VLM response...", flush=True)
                
                # 1. CALL API PROVIDER (with transient error retries)
                max_retries = 5
                retry_delay = 2
                response_msg = None
                
                for attempt in range(max_retries):
                    try:
                        if provider == "anthropic":
                            response_msg = await call_anthropic(api_key, model, system_prompt, messages, tools)
                        elif provider == "openai":
                            response_msg = await call_openai_compatible(api_key, None, model, system_prompt, messages, tools, force_fallback)
                        elif provider == "local":
                            response_msg = await call_openai_compatible(None, api_base, model, system_prompt, messages, tools, force_fallback)
                        elif provider == "gemini":
                            response_msg = await call_gemini(api_key, model, system_prompt, messages, tools)
                        else:
                            raise ValueError(f"Unknown provider: {provider}")
                        break # Success!
                    except Exception as api_err:
                        err_str = str(api_err).lower()
                        # Retry on 503, 429, 500, 502, 504 or common rate limit/overload keywords
                        is_transient = any(phrase in err_str for phrase in [
                            "503", "429", "500", "502", "504", "rate limit", 
                            "service unavailable", "overloaded", "temporarily unavailable",
                            "quota exceeded", "demand"
                        ])
                        if is_transient and attempt < max_retries - 1:
                            print(f"[API WARN]: Call failed: {api_err}. Retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})...")
                            await asyncio.sleep(retry_delay)
                            retry_delay *= 2
                        else:
                            print(f"\n[API ERROR]: Failed calling model API after {attempt + 1} attempts: {api_err}")
                            traceback.print_exc()
                            response_msg = None
                            break
                            
                if not response_msg:
                    break
                
                # 2. PRINT LIVE THOUGHT AND ACTION
                thought = response_msg.get("content") or ""
                tool_calls = response_msg.get("tool_calls") or []
                
                if thought:
                    print(f"🤖 [Thought]: {thought}")
                    # Update overlay if it exists
                    try:
                        await session.call_tool("update_thought", {"thought": thought.replace("\n", " ").strip()[-60:]})
                    except Exception:
                        pass
                        
                for tc in tool_calls:
                    fn = tc["function"]
                    print(f"🛠️  [Action]: Call {fn['name']}({fn['arguments']})")
                    
                # Append assistant message to history
                messages.append(response_msg)

                # Anti-Loop Guard: Detect repetitive VLM actions
                if tool_calls:
                    first_tc = tool_calls[0]["function"]
                    try:
                        args_dict = json.loads(first_tc["arguments"])
                        filtered_args = {k: v for k, v in args_dict.items() if k not in ("thinking", "thought", "description")}
                        sig_args = json.dumps(filtered_args, sort_keys=True)
                    except Exception:
                        sig_args = first_tc["arguments"]
                    sig = (first_tc["name"], sig_args)
                    if sig == last_sig:
                        rep_count += 1
                    else:
                        rep_count = 0
                        last_sig = sig
                        
                    if rep_count >= 2:
                        print("[RUNNER WARN]: Repetitive action detected. Preparing warning injection.")
                        loop_warning_to_inject = (
                            "[SYSTEM WARNING]: You have repeated this exact action multiple times in a row. "
                            "The desktop state is NOT advancing. If clicking this element fails to focus or "
                            "open the application, do NOT repeat the click. You must try a different approach: "
                            "either try keyboard hotkeys (e.g. key='alt+tab'), or execute a direct terminal "
                            "command using the 'bash' tool (e.g., command='start notepad')."
                        )
                
                if not tool_calls:
                    print("\n[AGENT FINISHED]: No more tool calls emitted. Agent loop complete.")
                    break
                    
                # 3. EXECUTE ACTIONS
                for tc in tool_calls:
                    fn = tc["function"]
                    name = fn["name"]
                    args = json.loads(fn["arguments"])
                    tc_id = tc["id"]
                    
                    print(f"⏳ Executing {name}...")
                    try:
                        res = await session.call_tool(name, args)
                        
                        # Process response (extracting screenshots if returned)
                        formatted_content = format_tool_content_for_role(res, provider, text_only)
                        
                        # Check termination
                        if name == "terminate_task":
                            print(f"\n🏁 [TERMINATE]: Task ended by agent: {args.get('message') or 'No message'}")
                            return
                            
                        # Prepend Anti-Loop Warning to the tool response if triggered
                        if loop_warning_to_inject:
                            if isinstance(formatted_content, list):
                                for item in formatted_content:
                                    if item.get("type") == "text":
                                        item["text"] = f"{loop_warning_to_inject}\n\n{item['text']}"
                                        break
                            else:
                                formatted_content = f"{loop_warning_to_inject}\n\n{formatted_content}"
                            loop_warning_to_inject = None

                        # Append tool response
                        if provider in ("openai", "local") and isinstance(formatted_content, list):
                            # OpenAI doesn't support images directly in 'tool' messages.
                            # So we put the text result in the tool message:
                            text_part = next((item["text"] for item in formatted_content if item["type"] == "text"), "Action complete.")
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": name,
                                "content": text_part
                            })
                            # And append a user message carrying the screenshot:
                            messages.append({
                                "role": "user",
                                "content": formatted_content
                            })
                            print(f"📸 Screenshot received. Appended to conversation history.")
                        elif provider == "gemini" and isinstance(formatted_content, list):
                            # Gemini REST formatting will package the image-bearing list.
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": name,
                                "content": formatted_content
                            })
                            print(f"📸 Screenshot received. Appended to conversation history.")
                        else:
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tc_id,
                                "name": name,
                                "content": formatted_content
                            })
                            
                    except Exception as tool_err:
                        print(f"❌ Error executing tool: {tool_err}")
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tc_id,
                            "name": name,
                            "content": f"Error: {tool_err}"
                        })
                        
                # Brief delay between turns to pace API calls (helps avoid hitting 429 Rate Limits on cloud providers)
                pacing_delay = 3.0 if provider in ("gemini", "anthropic", "openai") else 0.5
                await asyncio.sleep(pacing_delay)

# ===========================================================================
# 4. CLI Entrypoint
# ===========================================================================

def main():
    parser = argparse.ArgumentParser(description="Run the Computer-Use MCP Server with any VLM")
    parser.add_argument(
        "--provider",
        choices=["gemini", "anthropic", "openai", "local"],
        required=True,
        help="Model provider (gemini, anthropic, openai, local)"
    )
    parser.add_argument(
        "--model",
        help="Model ID/name override"
    )
    parser.add_argument(
        "--api-base",
        help="Custom API base URL (for local models, e.g. LM Studio, Ollama)"
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="Task query description for the agent"
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="Enable hybrid mode with browser-use delegated tools"
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=60,
        help="Maximum agent turns loop count"
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Do not send screen screenshots to the model (for text-only local models)"
    )
    parser.add_argument(
        "--force-fallback",
        action="store_true",
        help="Force text JSON prompting fallback instead of native tool calls (recommended for local models)"
    )
    args = parser.parse_args()
    
    # 1. Resolve Provider Keys and Defaults
    provider = args.provider.lower()
    api_key = None
    api_base = args.api_base
    
    if provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY")
        if not api_key:
            print("ERROR: GEMINI_API_KEY environment variable not set.")
            sys.exit(1)
        model = args.model or "gemini-2.5-flash"
        
    elif provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY environment variable not set.")
            sys.exit(1)
        model = args.model or "claude-3-5-sonnet-latest"
        
    elif provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            print("ERROR: OPENAI_API_KEY environment variable not set.")
            sys.exit(1)
        model = args.model or "gpt-4o"
        
    elif provider == "local":
        model = args.model or "my-local-vlm"
        if not api_base:
            # Default to LM Studio default port
            api_base = "http://localhost:1234/v1"
        print(f"[RUNNER]: Targeting Local OpenAI-compatible server at {api_base}")
        
    # 2. Launch Loop
    try:
        asyncio.run(run_agent(
            provider=provider,
            model=model,
            api_key=api_key,
            api_base=api_base,
            prompt=args.prompt,
            hybrid=args.hybrid,
            max_turns=args.max_turns,
            text_only=args.text_only,
            force_fallback=args.force_fallback
        ))
    except KeyboardInterrupt:
        print("\n[RUNNER]: Process interrupted by user.")
    except Exception as e:
        print(f"\n[RUNNER ERROR]: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
