"""
MCP Client Test for Computer-Use MCP Server

This script tests the MCP server by:
1. Starting the server in stdio mode
2. Listing all available tools
3. Running simple tasks (cursor_position, screenshot)
4. Running complex tasks (read_screen_ui, bash commands)
"""
import asyncio
import os
import sys
import json
import time
import base64
from io import BytesIO

# Ensure PYTHONPATH doesn't contaminate from Hermes agent venv
os.environ.pop("PYTHONPATH", None)

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession
from PIL import Image
from mcp.types import TextContent, ImageContent

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV_PYTHON = os.path.join(ROOT, ".venv", "Scripts", "python.exe")

def log(msg):
    """Print to stderr so it doesn't interfere with MCP JSON-RPC."""
    print(f"[CLIENT] {msg}", file=sys.stderr, flush=True)

async def main():
    results = {
        "simple_tests": {},
        "complex_tests": {},
        "summary": {}
    }

    server_params = StdioServerParameters(
        command=VENV_PYTHON,
        args=[os.path.join(ROOT, "src", "server.py"), "--stdio"],
        env=os.environ.copy(),
    )

    log("=" * 60)
    log("Computer-Use MCP Server Test Client")
    log("=" * 60)

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            log("Session initialized!")

            # =========================================
            # TEST 1: List all available tools
            # =========================================
            log("\n--- TEST 1: List All Tools ---")
            tools_result = await session.list_tools()
            tool_names = [t.name for t in tools_result.tools]
            tool_descs = {t.name: t.description[:100] for t in tools_result.tools}
            log(f"Available tools ({len(tool_names)}): {tool_names}")
            results["simple_tests"]["list_tools"] = {
                "status": "PASS",
                "tools": tool_names,
                "tool_descriptions": tool_descs,
                "count": len(tool_names)
            }

            # =========================================
            # TEST 2: Simple - Cursor Position
            # =========================================
            log("\n--- TEST 2: Get Cursor Position ---")
            start = time.time()
            res = await session.call_tool("computer", {
                "action": "cursor_position",
                "thinking": "test: get cursor position"
            })
            elapsed = time.time() - start
            cursor_text = res.content[0].text if res and res.content else ""
            log(f"Cursor position: {cursor_text[:200]}")
            log(f"Completed in {elapsed:.2f}s")
            results["simple_tests"]["cursor_position"] = {
                "elapsed_sec": round(elapsed, 3),
                "output": cursor_text[:300],
                "status": "PASS" if cursor_text else "FAIL"
            }

            # =========================================
            # TEST 3: Simple - Screenshot
            # =========================================
            log("\n--- TEST 3: Take Screenshot ---")
            start = time.time()
            res = await session.call_tool("computer", {
                "action": "screenshot",
                "thinking": "test: take screenshot"
            })
            elapsed = time.time() - start
            has_image = False
            screenshot_info = ""
            if res and res.content:
                for c in res.content:
                    if getattr(c, "type", None) == "image" and getattr(c, "data", None):
                        has_image = True
                        # Decode and check image properties
                        img_data = base64.b64decode(c.data)
                        img = Image.open(BytesIO(img_data)) if has_image else None
                        screenshot_info = f"Image: {len(img_data)} bytes"
                        if img:
                            screenshot_info += f", {img.size[0]}x{img.size[1]} {img.format}"
                            # Save to test screenshots dir
                            test_dir = os.path.join(ROOT, "test_screenshots")
                            os.makedirs(test_dir, exist_ok=True)
                            ts = time.strftime("%Y%m%d_%H%M%S")
                            img.save(os.path.join(test_dir, f"screenshot_{ts}.png"))
                            screenshot_info += f" -> saved to test_screenshots/"
                text_parts = [c.text for c in res.content if getattr(c, "type", None) == "text"]
                if text_parts:
                    screenshot_info += f" | Text: {text_parts[0][:200]}"
            log(f"Screenshot result: {screenshot_info}")
            log(f"Completed in {elapsed:.2f}s")
            results["simple_tests"]["screenshot"] = {
                "elapsed_sec": round(elapsed, 3),
                "has_image": has_image,
                "info": screenshot_info,
                "status": "PASS" if has_image else "FAIL"
            }

            # =========================================
            # TEST 4: Complex - Read Screen UI
            # =========================================
            log("\n--- TEST 4: Read Screen UI ---")
            start = time.time()
            res = await session.call_tool("read_screen_ui", {})
            elapsed = time.time() - start
            ui_text = res.content[0].text if res and res.content else ""
            lines = ui_text.strip().split("\n") if ui_text else []
            log(f"UI scan returned {len(lines)} lines in {elapsed:.2f}s")
            log(f"First 5 lines: {lines[:5]}")
            results["complex_tests"]["read_screen_ui"] = {
                "elapsed_sec": round(elapsed, 3),
                "line_count": len(lines),
                "first_lines": lines[:5],
                "status": "PASS" if len(lines) > 0 else "FAIL"
            }

            # =========================================
            # TEST 5: Complex - Bash: Create a file
            # =========================================
            log("\n--- TEST 5: Bash - Create test file ---")
            test_filename = os.path.join(os.environ.get("TEMP", "/tmp"), f"mcp_test_{int(time.time())}.txt")
            start = time.time()
            res = await session.call_tool("bash", {
                "command": f'echo "MCP test file created at {time.strftime("%Y-%m-%d %H:%M:%S")}" > "{test_filename}"'
            })
            elapsed = time.time() - start
            bash_text = res.content[0].text if res and res.content else ""
            log(f"Bash create file: {bash_text[:200]}")
            log(f"Completed in {elapsed:.2f}s")

            # Verify the file was created
            file_exists = os.path.exists(test_filename)
            log(f"File exists: {file_exists}")
            results["complex_tests"]["bash_create_file"] = {
                "elapsed_sec": round(elapsed, 3),
                "file_created": file_exists,
                "output": bash_text[:300],
                "status": "PASS" if file_exists else "FAIL"
            }

            # =========================================
            # TEST 6: Complex - Bash: Read the file back
            # =========================================
            log("\n--- TEST 6: Bash - Read file back ---")
            start = time.time()
            res = await session.call_tool("bash", {
                "command": f'type "{test_filename}"'
            })
            elapsed = time.time() - start
            bash_text = res.content[0].text if res and res.content else ""
            log(f"Bash read file: {bash_text[:200]}")
            log(f"Completed in {elapsed:.2f}s")
            results["complex_tests"]["bash_read_file"] = {
                "elapsed_sec": round(elapsed, 3),
                "output": bash_text[:300],
                "status": "PASS" if file_exists and "MCP test file" in bash_text else "FAIL"
            }

            # =========================================
            # TEST 7: Complex - Bash: List directory contents
            # =========================================
            log("\n--- TEST 7: Bash - List directory ---")
            start = time.time()
            res = await session.call_tool("bash", {
                "command": f'dir "{ROOT}" /b'
            })
            elapsed = time.time() - start
            bash_text = res.content[0].text if res and res.content else ""
            dir_lines = bash_text.strip().split("\n") if bash_text else []
            log(f"Bash dir listing: {len(dir_lines)} entries in {elapsed:.2f}s")
            log(f"First 10 entries: {dir_lines[:10]}")
            results["complex_tests"]["bash_list_dir"] = {
                "elapsed_sec": round(elapsed, 3),
                "entry_count": len(dir_lines),
                "entries": dir_lines[:10],
                "status": "PASS" if len(dir_lines) > 0 else "FAIL"
            }

            # =========================================
            # TEST 8: Complex - Multi-step: Mouse move + click
            # =========================================
            log("\n--- TEST 8: Multi-step - Move mouse + click ---")
            # First get cursor position to know starting point
            res_pos = await session.call_tool("computer", {
                "action": "cursor_position",
                "thinking": "pre-move: get position"
            })
            pos_text = res_pos.content[0].text if res_pos and res_pos.content else ""
            import re
            m = re.search(r"desktop=\((\d+),(\d+)\)", pos_text)
            start_pos = (500, 300)  # safe default
            if m:
                start_pos = (int(m.group(1)), int(m.group(2)))
            log(f"Starting cursor at: {start_pos}")

            # Move mouse to a specific coordinate
            target_x, target_y = 100, 100
            start = time.time()
            res = await session.call_tool("computer", {
                "action": "mouse_move",
                "coordinate": [target_x, target_y],
                "thinking": "test: move mouse to corner"
            })
            elapsed_move = time.time() - start
            log(f"Mouse move to ({target_x},{target_y}) in {elapsed_move:.2f}s")

            # Read cursor position back to verify
            res2 = await session.call_tool("computer", {
                "action": "cursor_position",
                "thinking": "post-move: verify position"
            })
            pos_text2 = res2.content[0].text if res2 and res2.content else ""
            log(f"New cursor position: {pos_text2[:200]}")

            m2 = re.search(r"desktop=\((\d+),(\d+)\)", pos_text2)
            end_pos = (int(m2.group(1)), int(m2.group(2))) if m2 else (0, 0)
            # Also extract screenshot coordinates for proper comparison
            ms = re.search(r"screenshot=\((\d+),(\d+)\)", pos_text2)
            end_screenshot = (int(ms.group(1)), int(ms.group(2))) if ms else (0, 0)
            # The target was in screenshot coordinates, so compare against screenshot coords
            delta = (abs(end_screenshot[0] - target_x), abs(end_screenshot[1] - target_y))
            log(f"Delta from target (screenshot coords): {delta}")

            results["complex_tests"]["mouse_move_click"] = {
                "elapsed_sec": round(elapsed_move, 3),
                "target": [target_x, target_y],
                "actual_screenshot": list(end_screenshot),
                "actual_desktop": list(end_pos),
                "delta": list(delta),
                "status": "PASS" if delta[0] <= 5 and delta[1] <= 5 else "FAIL"
            }

            # =========================================
            # TEST 9: Complex - Security: Command Denylist (C2)
            # =========================================
            log("\n--- TEST 9: Security - Command Denylist ---")
            start = time.time()
            res = await session.call_tool("bash", {
                "command": "rm -rf /"
            })
            elapsed = time.time() - start
            bash_text = res.content[0].text if res and res.content else ""
            log(f"Bash denylist test: {bash_text[:200]}")
            log(f"Completed in {elapsed:.2f}s")
            blocked = "ERROR: Command blocked" in bash_text or "blocked by security policy" in bash_text
            results["complex_tests"]["security_denylist"] = {
                "elapsed_sec": round(elapsed, 3),
                "command": "rm -rf /",
                "blocked": blocked,
                "output": bash_text[:300],
                "status": "PASS" if blocked else "FAIL"
            }

            # =========================================
            # TEST 10: Complex - Security: Safe command allowed
            # =========================================
            log("\n--- TEST 10: Security - Safe command allowed ---")
            start = time.time()
            res = await session.call_tool("bash", {
                "command": "echo security_test_passed"
            })
            elapsed = time.time() - start
            bash_text = res.content[0].text if res and res.content else ""
            log(f"Bash safe command: {bash_text[:200]}")
            log(f"Completed in {elapsed:.2f}s")
            allowed = "security_test_passed" in bash_text
            results["complex_tests"]["security_safe_command"] = {
                "elapsed_sec": round(elapsed, 3),
                "allowed": allowed,
                "output": bash_text[:300],
                "status": "PASS" if allowed else "FAIL"
            }

            # =========================================
            # TEST 11: Complex - Multi-step: UI element discovery + click
            # =========================================
            log("\n--- TEST 11: Multi-step - UI element discovery ---")
            start = time.time()
            res = await session.call_tool("read_screen_ui", {})
            elapsed = time.time() - start
            ui_text = res.content[0].text if res and res.content else ""
            lines = ui_text.strip().split("\n") if ui_text else []
            # Look for a UI element line like [M1] [5] <Pane name="Taskbar" at (683,751)>
            element_lines = [l for l in lines if "<" in l and "at (" in l]
            log(f"UI scan found {len(element_lines)} elements in {elapsed:.2f}s")
            log(f"Sample elements: {element_lines[:3]}")
            results["complex_tests"]["ui_element_discovery"] = {
                "elapsed_sec": round(elapsed, 3),
                "element_count": len(element_lines),
                "sample_elements": element_lines[:3],
                "status": "PASS" if len(element_lines) > 0 else "FAIL"
            }

            # =========================================
            # TEST 12: Multi-step: Scroll action
            # =========================================
            log("\n--- TEST 12: Multi-step - Scroll action ---")
            start = time.time()
            res = await session.call_tool("computer", {
                "action": "scroll",
                "text": "5",
                "thinking": "test: scroll down"
            })
            elapsed = time.time() - start
            scroll_text = res.content[0].text if res and res.content else ""
            log(f"Scroll result: {scroll_text[:200]}")
            log(f"Completed in {elapsed:.2f}s")
            results["complex_tests"]["scroll_action"] = {
                "elapsed_sec": round(elapsed, 3),
                "output": scroll_text[:300],
                "status": "PASS" if scroll_text else "FAIL"
            }

            # =========================================
            # TEST 13: Complex - Terminate task
            # =========================================
            log("\n--- TEST 9: Terminate task ---")
            res = await session.call_tool("terminate_task", {
                "success": True,
                "message": "MCP test suite completed"
            })
            term_text = res.content[0].text if res and res.content else ""
            log(f"Terminate result: {term_text[:200]}")
            results["complex_tests"]["terminate_task"] = {
                "output": term_text[:300],
                "status": "PASS" if "TASK_TERMINATED" in term_text else "FAIL"
            }

            # =========================================
            # SUMMARY
            # =========================================
            log("\n" + "=" * 60)
            log("TEST SUMMARY")
            log("=" * 60)

            all_tests = {}
            all_tests.update(results["simple_tests"])
            all_tests.update(results["complex_tests"])

            passed = sum(1 for t in all_tests.values() if t["status"] == "PASS")
            failed = sum(1 for t in all_tests.values() if t["status"] == "FAIL")

            for name, info in all_tests.items():
                status_icon = "✅" if info["status"] == "PASS" else "❌"
                log(f"  {status_icon} {name}: {info['status']}")

            log(f"\nTotal: {passed} passed, {failed} failed out of {len(all_tests)} tests")

            results["summary"] = {
                "total": len(all_tests),
                "passed": passed,
                "failed": failed,
                "all_tests": all_tests
            }

            # Save results to file
            results_file = os.path.join(ROOT, "test_results.json")
            with open(results_file, "w") as f:
                json.dump(results, f, indent=2, default=str)
            log(f"\nResults saved to: {results_file}")

    return results


if __name__ == "__main__":
    results = asyncio.run(main())
    passed = results["summary"]["passed"]
    failed = results["summary"]["failed"]
    print(f"\n=== FINAL: {passed} passed, {failed} failed ===", file=sys.stderr)
    sys.exit(0 if failed == 0 else 1)
