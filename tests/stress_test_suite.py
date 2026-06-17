import argparse
import asyncio
import json
import os
import sys
import time
import traceback
from typing import Any, Dict, List, Optional

# Add the src folder to path to import run_agent utilities
sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src"))

from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client
import mcp.types as mcp_types

# Import the unified client elements
from run_agent import (
    call_anthropic,
    call_openai_compatible,
    call_gemini,
    format_tool_content_for_role,
    to_openai_tools,
    get_mcp_params
)

# Configuration & Temp files setup
TEMP_DIR = os.environ.get("TEMP") or os.environ.get("TMP") or "C:\\Windows\\Temp"
SCEN1_OUT = os.path.join(TEMP_DIR, "mcp_scen1_done.txt")
SCEN2_OUT = os.path.join(TEMP_DIR, "mcp_scen2_done.txt")
SCEN3_OUT = os.path.join(TEMP_DIR, "mcp_scen3_done.txt")

DASHBOARD_PATH = os.path.abspath(os.path.join(os.path.dirname(__file__), "mock_dashboard.html"))

# Ensure paths use double backslashes for Windows shell execution compatibility
SCEN1_OUT_ESC = SCEN1_OUT.replace("\\", "\\\\")
SCEN2_OUT_ESC = SCEN2_OUT.replace("\\", "\\\\")
SCEN3_OUT_ESC = SCEN3_OUT.replace("\\", "\\\\")
DASHBOARD_PATH_ESC = DASHBOARD_PATH.replace("\\", "\\\\")


async def run_scenario_loop(
    scenario_id: int,
    prompt: str,
    session: ClientSession,
    provider: str,
    model: str,
    api_key: str,
    api_base: str,
    max_turns: int,
    text_only: bool,
    system_prompt: str,
    tools: List[Dict[str, Any]],
    interference_task: Optional[asyncio.Task] = None,
    force_fallback: bool = False
) -> Dict[str, Any]:
    """Runs a single scenario agent loop, collecting timings and turn metrics."""
    messages = [{"role": "user", "content": prompt}]
    turns_data = []
    success = False
    error_msg = ""
    start_time = time.time()
    
    print(f"\n==================================================")
    print(f"  RUNNING SCENARIO {scenario_id}: Max Turns={max_turns}")
    print(f"  Prompt: {prompt}")
    print(f"==================================================")
    last_sig = None
    rep_count = 0
    loop_warning_to_inject = None
    
    for turn in range(1, max_turns + 1):
        turn_start = time.time()
        print(f"\n[Turn {turn}/{max_turns}]: Calling VLM...")
        
        # 1. API Call with timing and transient error retries
        api_start = time.time()
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
                break  # Success!
            except Exception as api_err:
                err_str = str(api_err).lower()
                is_transient = any(phrase in err_str for phrase in [
                    "503", "429", "500", "502", "504", "rate limit", 
                    "service unavailable", "overloaded", "temporarily unavailable",
                    "quota exceeded", "demand"
                ])
                if is_transient and attempt < max_retries - 1:
                    print(f"[API WARN]: VLM call failed: {api_err}. Retrying in {retry_delay}s (attempt {attempt + 1}/{max_retries})...")
                    await asyncio.sleep(retry_delay)
                    retry_delay *= 2
                else:
                    print(f"❌ VLM API error after {attempt + 1} attempts: {api_err}")
                    error_msg = f"API Error: {api_err}"
                    break
                    
        if not response_msg:
            break
            
        api_duration = time.time() - api_start
        thought = response_msg.get("content") or ""
        tool_calls = response_msg.get("tool_calls") or []
        
        print(f"🤖 Thought ({api_duration:.2f}s): {thought[:150]}...")
        for tc in tool_calls:
            print(f"🛠️  Action: {tc['function']['name']}({tc['function']['arguments']})")
            
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
        
        # Track metrics for this turn
        turn_metric = {
            "turn": turn,
            "vlm_latency_sec": round(api_duration, 2),
            "thought": thought,
            "actions": [tc["function"]["name"] for tc in tool_calls]
        }
        
        if not tool_calls:
            print("[SCENARIO]: No more tools called. Terminating turn loop.")
            success = True
            break
            
        # 2. Execute Actions
        actions_execution_start = time.time()
        for tc in tool_calls:
            name = tc["function"]["name"]
            args = json.loads(tc["function"]["arguments"])
            tc_id = tc["id"]
            
            try:
                # Update visual overlay if active
                try:
                    await session.call_tool("update_thought", {"thought": f"Turn {turn}: {name}"})
                except Exception:
                    pass
                    
                res = await session.call_tool(name, args)
                formatted_content = format_tool_content_for_role(res, provider, text_only)
                
                # Check for termination
                if name == "terminate_task":
                    print(f"🏁 Terminated by agent: {args.get('message')}")
                    success = args.get("success", True)
                    error_msg = args.get("message", "")
                    
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

                # Format message content based on provider expectations
                if provider in ("openai", "local") and isinstance(formatted_content, list):
                    text_part = next((item["text"] for item in formatted_content if item["type"] == "text"), "Action complete.")
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "name": name,
                        "content": text_part
                    })
                    messages.append({
                        "role": "user",
                        "content": formatted_content
                    })
                elif provider == "gemini" and isinstance(formatted_content, list):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "name": name,
                        "content": formatted_content
                    })
                else:
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tc_id,
                        "name": name,
                        "content": formatted_content
                    })
            except Exception as tool_err:
                print(f"❌ Error executing tool {name}: {tool_err}")
                messages.append({
                    "role": "tool",
                    "tool_call_id": tc_id,
                    "name": name,
                    "content": f"Error: {tool_err}"
                })
                
        turn_metric["execution_latency_sec"] = round(time.time() - actions_execution_start, 2)
        turns_data.append(turn_metric)
        
        if name == "terminate_task":
            break
            
        # Pacing delay between turns
        pacing = 3.0 if provider in ("gemini", "anthropic", "openai") else 0.5
        await asyncio.sleep(pacing)
        
    duration = time.time() - start_time
    
    # Cancel interference if it's still running
    if interference_task and not interference_task.done():
        interference_task.cancel()
        
    return {
        "scenario_id": scenario_id,
        "success": success,
        "total_turns": len(turns_data),
        "total_duration_sec": round(duration, 2),
        "avg_vlm_latency_sec": round(sum(t["vlm_latency_sec"] for t in turns_data) / len(turns_data), 2) if turns_data else 0,
        "turns": turns_data,
        "error_msg": error_msg
    }


async def minimize_notepad_interference(delay_sec: float):
    """Wait for a short duration and then programmatically minimize Notepad windows."""
    await asyncio.sleep(delay_sec)
    print("\n[STRESS TEST INTERFERENCE]: Triggering focus loss - Minimizing Notepad...")
    if sys.platform == "win32":
        try:
            import win32gui
            import win32con
            
            def enum_handler(hwnd, lparam):
                class_name = win32gui.GetClassName(hwnd)
                if "Notepad" in class_name:
                    # SW_MINIMIZE minimizes the window
                    win32gui.ShowWindow(hwnd, win32con.SW_MINIMIZE)
                    print(f"[STRESS TEST INTERFERENCE]: Minimized Notepad Window HWND={hwnd}")
                return True
                
            win32gui.EnumWindows(enum_handler, None)
        except Exception as e:
            print(f"[STRESS TEST INTERFERENCE] Error: {e}")
    else:
        print("[STRESS TEST INTERFERENCE]: Minimizing is only supported on Windows.")


async def verify_scenario_1() -> bool:
    """Verifies that Scenario 1 outputs exist and are correct."""
    if not os.path.exists(SCEN1_OUT):
        print("Verification Fail: Scenario 1 output file does not exist.")
        return False
    with open(SCEN1_OUT, "r", encoding="utf-8") as f:
        content = f.read().strip()
    
    ok = "STRESS_TEST_SCENARIO_1_SUCCESS" in content
    if ok:
        print("Verification Pass: Scenario 1 file found and content matched.")
        try:
            os.remove(SCEN1_OUT)
        except Exception:
            pass
        return True
    else:
        print(f"Verification Fail: Scenario 1 content mismatch. Found: '{content}'")
        return False


async def verify_scenario_2() -> bool:
    """Verifies that Scenario 2 outputs exist and are correct."""
    if not os.path.exists(SCEN2_OUT):
        print("Verification Fail: Scenario 2 output file does not exist.")
        return False
    with open(SCEN2_OUT, "r", encoding="utf-8") as f:
        content = f.read().strip()
        
    # Expecting: Auth-Gateway-Service
    ok = "Auth-Gateway-Service" in content
    if ok:
        print("Verification Pass: Scenario 2 file found and content matched.")
        try:
            os.remove(SCEN2_OUT)
        except Exception:
            pass
        return True
    else:
        print(f"Verification Fail: Scenario 2 content mismatch. Found: '{content}'")
        return False


async def verify_scenario_3() -> bool:
    """Verifies that Scenario 3 outputs exist and are correct."""
    if not os.path.exists(SCEN3_OUT):
        print("Verification Fail: Scenario 3 output file does not exist.")
        return False
    with open(SCEN3_OUT, "r", encoding="utf-8") as f:
        content = f.read().strip()
        
    has_start = "Starting Scenario 3 typing..." in content
    has_end = "Scenario 3 Completed successfully!" in content
    
    if has_start and has_end:
        print("Verification Pass: Scenario 3 file found and self-correction input verified.")
        try:
            os.remove(SCEN3_OUT)
        except Exception:
            pass
        return True
    else:
        print(f"Verification Fail: Scenario 3 contents. Start={has_start}, End={has_end}. Found: '{content}'")
        return False


async def run_suite(
    provider: str,
    model: str,
    api_key: str,
    api_base: str,
    scenarios_list: List[int],
    max_turns: int,
    text_only: bool,
    hybrid: bool,
    force_fallback: bool = False
):
    server_params = get_mcp_params(hybrid)
    results = []
    
    print(f"\n==================================================")
    print(f"  STARTING STRESS TEST SUITE")
    print(f"  Provider={provider} Model={model} Hybrid={hybrid}")
    print(f"==================================================")
    
    # 0. Clean up any stale files from previous runs
    for path in (SCEN1_OUT, SCEN2_OUT, SCEN3_OUT):
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass
                
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # List available tools
            mcp_tools_list = await session.list_tools()
            tools = to_openai_tools(mcp_tools_list.tools)
            
            # Construct instructions based on mode
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
            
            # --- SCENARIO 1 ---
            if 1 in scenarios_list:
                prompt_1 = (
                    f"Open Notepad, type the text 'STRESS_TEST_SCENARIO_1_SUCCESS' in the editor, "
                    f"save the file to path '{SCEN1_OUT_ESC}', and then close Notepad completely."
                )
                res_1 = await run_scenario_loop(
                    1, prompt_1, session, provider, model, api_key, api_base, max_turns, text_only, system_prompt, tools, force_fallback=force_fallback
                )
                verified = await verify_scenario_1()
                res_1["verified"] = verified
                res_1["success"] = res_1["success"] and verified
                results.append(res_1)
                
            # --- SCENARIO 2 ---
            if 2 in scenarios_list:
                prompt_2 = (
                    f"Open the local HTML file at '{DASHBOARD_PATH_ESC}' in the Chrome browser. "
                    f"First, click the red button 'Run Integrity Check' which will open a critical status verification overlay modal. "
                    f"Visually locate the modal's top-right 'X' close button or the grey 'Cancel' button, and click it to dismiss the modal. "
                    f"Next, click on the 'Database' tab menu on the sidebar to view the database table. "
                    f"Find the device/service row with ID '#1026' which is marked as 'critical'. "
                    f"Identify its 'Device / Service Name' (the second column in that row). "
                    f"Save that exact service name to the file '{SCEN2_OUT_ESC}', and then close the Chrome browser window."
                )
                res_2 = await run_scenario_loop(
                    2, prompt_2, session, provider, model, api_key, api_base, max_turns, text_only, system_prompt, tools, force_fallback=force_fallback
                )
                verified = await verify_scenario_2()
                res_2["verified"] = verified
                res_2["success"] = res_2["success"] and verified
                results.append(res_2)
                
            # --- SCENARIO 3 ---
            if 3 in scenarios_list:
                prompt_3 = (
                    f"Open Notepad. Type exactly the text 'Starting Scenario 3 typing...' in the editor. "
                    f"Save the file to path '{SCEN3_OUT_ESC}'. "
                    f"Keep Notepad open. Note: If the Notepad window gets minimized or loses focus, click on the Notepad application icon on the Windows taskbar "
                    f"to restore/focus it. Then, append the text 'Scenario 3 Completed successfully!' to the file, save the file again, and close Notepad."
                )
                
                # Launch background task to trigger focus loss (minimize notepad) after 8 seconds
                interference_task = asyncio.create_task(minimize_notepad_interference(8.0))
                
                res_3 = await run_scenario_loop(
                    3, prompt_3, session, provider, model, api_key, api_base, max_turns, text_only, system_prompt, tools, interference_task, force_fallback=force_fallback
                )
                verified = await verify_scenario_3()
                res_3["verified"] = verified
                res_3["success"] = res_3["success"] and verified
                results.append(res_3)

    # 4. Generate report
    report = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "provider": provider,
        "model": model,
        "hybrid": hybrid,
        "text_only": text_only,
        "results": results
    }
    
    logs_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "logs")
    os.makedirs(logs_dir, exist_ok=True)
    report_file = os.path.join(logs_dir, "stress_test_report.json")
    
    with open(report_file, "w", encoding="utf-8") as rf:
        json.dump(report, rf, indent=2)
        
    print(f"\n==================================================")
    print(f"  STRESS TEST SUITE COMPLETE")
    print(f"  Report written to: {report_file}")
    for r in results:
        status = "PASSED" if r["success"] else "FAILED"
        print(f"  Scenario {r['scenario_id']}: {status} in {r['total_turns']} turns ({r['total_duration_sec']}s)")
    print(f"==================================================")


def main():
    parser = argparse.ArgumentParser(description="MCP Computer-Use Stress Test Suite Controller")
    parser.add_argument(
        "--provider",
        choices=["gemini", "anthropic", "openai", "local"],
        default="local",
        help="Model provider (gemini, anthropic, openai, local)"
    )
    parser.add_argument(
        "--model",
        default="google/gemma-4-12b-qat",
        help="Model name/identifier override"
    )
    parser.add_argument(
        "--api-base",
        default="http://127.0.0.1:12345/v1",
        help="Base URL for local OpenAI compatible server"
    )
    parser.add_argument(
        "--scenarios",
        default="all",
        help="Scenarios to run, e.g. '1,2' or 'all'"
    )
    parser.add_argument(
        "--max-turns",
        type=int,
        default=25,
        help="Max agent loop turns per scenario"
    )
    parser.add_argument(
        "--text-only",
        action="store_true",
        help="Disable image screenshots (only text accessibility queries)"
    )
    parser.add_argument(
        "--force-fallback",
        action="store_true",
        help="Force text JSON prompting fallback instead of native tool calls (recommended for local models)"
    )
    parser.add_argument(
        "--hybrid",
        action="store_true",
        help="Enable browser-use delegated tools"
    )
    args = parser.parse_args()
    
    api_key = ""
    if args.provider == "gemini":
        api_key = os.environ.get("GEMINI_API_KEY") or ""
        if not api_key:
            print("ERROR: GEMINI_API_KEY not found in environment.")
            sys.exit(1)
    elif args.provider == "anthropic":
        api_key = os.environ.get("ANTHROPIC_API_KEY") or ""
        if not api_key:
            print("ERROR: ANTHROPIC_API_KEY not found in environment.")
            sys.exit(1)
    elif args.provider == "openai":
        api_key = os.environ.get("OPENAI_API_KEY") or ""
        if not api_key:
            print("ERROR: OPENAI_API_KEY not found in environment.")
            sys.exit(1)
            
    if args.scenarios == "all":
        scenarios_list = [1, 2, 3]
    else:
        scenarios_list = [int(s.strip()) for s in args.scenarios.split(",") if s.strip()]
        
    try:
        asyncio.run(run_suite(
            provider=args.provider,
            model=args.model,
            api_key=api_key,
            api_base=args.api_base,
            scenarios_list=scenarios_list,
            max_turns=args.max_turns,
            text_only=args.text_only,
            hybrid=args.hybrid,
            force_fallback=args.force_fallback
        ))
    except KeyboardInterrupt:
        print("\n[STRESS TEST SUITE]: Interrupted by user.")
    except Exception as e:
        print(f"\n[STRESS TEST SUITE ERROR]: {e}")
        traceback.print_exc()

if __name__ == "__main__":
    main()
