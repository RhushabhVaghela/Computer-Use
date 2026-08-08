"""
Comprehensive from-scratch test of the Computer-Use MCP Server.
Tests every tool from basic to complex operations, with focus management testing.
"""
import asyncio
import os
import sys
import time
import re
import json

# Clear PYTHONPATH to avoid contamination
os.environ.pop('PYTHONPATH', None)

from mcp.client.stdio import stdio_client, StdioServerParameters
from mcp.client.session import ClientSession

ROOT = os.path.abspath('.')
PYTHON = os.path.join(ROOT, '.venv', 'Scripts', 'python.exe')
SERVER_ARGS = [os.path.join(ROOT, 'src', 'server.py'), '--stdio']

def log(msg):
    print(f"[TEST] {msg}", file=sys.stderr, flush=True)

async def _call(session, name, args):
    try:
        res = await session.call_tool(name, args)
        text = ""
        if getattr(res, "content", None):
            parts = []
            for c in res.content:
                t = getattr(c, "text", None)
                if t:
                    parts.append(t)
            text = "\n".join(parts).strip()
        has_image = any(getattr(c, "type", None) == "image" for c in res.content) if res else False
        return True, text, has_image
    except Exception as e:
        return False, f"{type(e).__name__}: {e}", False

async def main():
    passed = 0
    failed = 0
    results = []
    
    log("=" * 60)
    log("COMPREHENSIVE MCP SERVER TEST - FROM SCRATCH")
    log("=" * 60)
    
    server_params = StdioServerParameters(
        command=PYTHON,
        args=SERVER_ARGS,
        env=os.environ.copy(),
    )
    
    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            
            # Kill any existing Chrome
            await session.call_tool('bash', {'command': 'taskkill /f /im chrome.exe 2>nul'})
            await asyncio.sleep(2)
            
            # ==========================================
            # PHASE 1: SIMPLE TESTS
            # ==========================================
            log("\n--- PHASE 1: Simple Tests ---")
            
            # Test 1: List tools
            log("Test 1: List all available tools")
            tools = await session.list_tools()
            tool_names = sorted([t.name for t in tools.tools])
            expected = sorted(['computer', 'read_screen_ui', 'bash', 'terminate_task', 
                              'rename_file', 'update_thought', 'browser_action', 'browser_use_dom'])
            if tool_names == expected:
                log(f"  ✅ PASS - All 8 tools present: {tool_names}")
                passed += 1
            else:
                log(f"  ❌ FAIL - Expected {expected}, got {tool_names}")
                failed += 1
            results.append({"phase": "simple", "test": "list_tools", "status": "PASS" if tool_names == expected else "FAIL"})
            
            # Test 2: Cursor position
            log("Test 2: Get cursor position")
            ok, txt, _ = await _call(session, 'computer', {'action': 'cursor_position', 'thinking': 'test'})
            has_pos = 'Cursor:' in txt and 'desktop=' in txt
            if has_pos:
                log(f"  ✅ PASS - {txt[:80]}")
                passed += 1
            else:
                log(f"  ❌ FAIL - {txt[:100]}")
                failed += 1
            results.append({"phase": "simple", "test": "cursor_position", "status": "PASS" if has_pos else "FAIL"})
            
            # Test 3: Screenshot
            log("Test 3: Take screenshot")
            ok, txt, has_img = await _call(session, 'computer', {'action': 'screenshot', 'thinking': 'test'})
            if ok and has_img:
                log(f"  ✅ PASS - Screenshot captured with image data")
                passed += 1
            else:
                log(f"  ❌ FAIL - ok={ok}, has_img={has_img}, txt={txt[:100]}")
                failed += 1
            results.append({"phase": "simple", "test": "screenshot", "status": "PASS" if ok and has_img else "FAIL"})
            
            # Test 4: Type text
            log("Test 4: Type text (into active element)")
            ok, txt, _ = await _call(session, 'computer', {
                'action': 'type', 'text': 'hello test 123', 'thinking': 'type test'
            })
            if ok:
                log(f"  ✅ PASS - Type action completed")
                passed += 1
            else:
                log(f"  ❌ FAIL - {txt[:100]}")
                failed += 1
            results.append({"phase": "simple", "test": "type_text", "status": "PASS" if ok else "FAIL"})
            
            # Clean up typed text
            await session.call_tool('computer', {'action': 'key', 'text': 'ctrl+a', 'thinking': 'select all'})
            await asyncio.sleep(0.3)
            await session.call_tool('computer', {'action': 'key', 'text': 'backspace', 'thinking': 'delete'})
            
            # ==========================================
            # PHASE 2: MEDIUM TESTS
            # ==========================================
            log("\n--- PHASE 2: Medium Tests ---")
            
            # Test 5: Bash - safe command
            log("Test 5: Bash - safe command (echo)")
            ok, txt, _ = await _call(session, 'bash', {'command': 'echo mcp_test_safe_command'})
            if ok and 'mcp_test_safe_command' in txt:
                log(f"  ✅ PASS - echo output: {txt[:60]}")
                passed += 1
            else:
                log(f"  ❌ FAIL - {txt[:100]}")
                failed += 1
            results.append({"phase": "medium", "test": "bash_safe_command", "status": "PASS" if ok and 'mcp_test_safe_command' in txt else "FAIL"})
            
            # Test 6: Bash - blocked command (security)
            log("Test 6: Bash - blocked command (rm -rf /)")
            ok, txt, _ = await _call(session, 'bash', {'command': 'rm -rf /'})
            if 'blocked' in txt.lower() or 'ERROR' in txt:
                log(f"  ✅ PASS - Command blocked: {txt[:60]}")
                passed += 1
            else:
                log(f"  ❌ FAIL - Command was NOT blocked: {txt[:100]}")
                failed += 1
            results.append({"phase": "medium", "test": "bash_blocked_command", "status": "PASS" if 'blocked' in txt.lower() else "FAIL"})
            
            # Test 7: Bash - file create/verify
            log("Test 7: Bash - create and verify file")
            test_file = os.path.join(os.environ.get('TEMP', '/tmp'), 'mcp_test_file.txt')
            await _call(session, 'bash', {'command': f'echo "test_content_123" > "{test_file}"'})
            await asyncio.sleep(0.5)
            file_exists = os.path.exists(test_file)
            if file_exists:
                log(f"  ✅ PASS - File created at {test_file}")
                passed += 1
            else:
                log(f"  ❌ FAIL - File not created")
                failed += 1
            results.append({"phase": "medium", "test": "bash_file_create", "status": "PASS" if file_exists else "FAIL"})
            
            # Test 8: rename_file
            log("Test 8: Rename file")
            new_file = os.path.join(os.environ.get('TEMP', '/tmp'), 'mcp_test_file_renamed.txt')
            ok, txt, _ = await _call(session, 'rename_file', {'old_path': test_file, 'new_path': new_file})
            if ok and 'Success' in txt and os.path.exists(new_file):
                log(f"  ✅ PASS - {txt[:60]}")
                passed += 1
            else:
                log(f"  ❌ FAIL - {txt[:100]}")
                failed += 1
            results.append({"phase": "medium", "test": "rename_file", "status": "PASS" if ok and os.path.exists(new_file) else "FAIL"})
            
            # Test 9: read_screen_ui
            log("Test 9: Read screen UI")
            ok, txt, _ = await _call(session, 'read_screen_ui', {})
            lines = txt.strip().split('\n') if txt else []
            has_ui = len(lines) > 3 and '[UI TREE' in txt
            if has_ui:
                log(f"  ✅ PASS - UI tree with {len(lines)} lines")
                passed += 1
            else:
                log(f"  ❌ FAIL - UI output: {txt[:100]}")
                failed += 1
            results.append({"phase": "medium", "test": "read_screen_ui", "status": "PASS" if has_ui else "FAIL"})
            
            # ==========================================
            # PHASE 3: BROWSER TESTS (Focus Management)
            # ==========================================
            log("\n--- PHASE 3: Browser Tests ---")
            
            # Test 10: Launch browser with isolated session
            log("Test 10: Launch browser (isolated session, Wikipedia)")
            ok, txt, _ = await _call(session, 'browser_action', {
                'url': 'https://en.wikipedia.org/wiki/Artificial_intelligence',
                'isolated_session': True
            })
            await asyncio.sleep(4)
            if ok:
                log(f"  ✅ PASS - Browser launched")
                passed += 1
            else:
                log(f"  ❌ FAIL - {txt[:100]}")
                failed += 1
            results.append({"phase": "browser", "test": "browser_launch_wikipedia", "status": "PASS" if ok else "FAIL"})
            
            # Test 11: Check for restore dialog
            log("Test 11: Check for restore dialog before DOM extraction")
            # browser_action already handles dialog dismissal with polling,
            # but the dialog text may linger in the UI tree for a moment
            # Wait and poll for dialog to fully disappear
            # Note: "Chrome didn't shut down correctly" appears as a Text element
            # inside Chrome's UI, not as a modal dialog. We only fail if a modal
            # dialog window (Window control type) contains "Restore" or "shut down"
            has_restore = True
            for wait_attempt in range(5):
                await asyncio.sleep(1)
                ok, txt, _ = await _call(session, 'read_screen_ui', {})
                # Only look for "Restore" as a Window name (modal dialog)
                # The "Chrome didn't shut down correctly" text is a child of Chrome
                # and will persist until the browser is closed - not a modal dialog
                has_restore = 'Window name="Restore' in txt or "<Window name=\"Restore" in txt
                if not has_restore:
                    break
            if not has_restore:
                log(f"  ✅ PASS - No restore dialog detected")
                passed += 1
            else:
                log(f"  ⚠️ WARN - Restore dialog detected")
                # Count as failure since we need clean state
                failed += 1
            results.append({"phase": "browser", "test": "no_restore_dialog", "status": "PASS" if not has_restore else "FAIL"})
            
            # Test 12: browser_use_dom from Wikipedia
            log("Test 12: browser_use_dom from Wikipedia (active window)")
            ok, txt, _ = await _call(session, 'browser_use_dom', {})
            is_wiki = 'Artificial intelligence' in txt or 'en.wikipedia.org' in txt
            if is_wiki:
                log(f"  ✅ PASS - DOM from Wikipedia")
                passed += 1
            else:
                log(f"  ❌ FAIL - DOM not from Wikipedia: {txt[:100]}")
                failed += 1
            results.append({"phase": "browser", "test": "dom_from_wikipedia", "status": "PASS" if is_wiki else "FAIL"})
            
            # Test 13: Open Example.com in same browser
            log("Test 13: Open Example.com in same browser (new window/tab)")
            ok, txt, _ = await _call(session, 'browser_action', {
                'url': 'https://example.com',
                'isolated_session': False
            })
            # browser_action includes dialog dismissal, but give extra time for dialogs
            await asyncio.sleep(5)
            if ok:
                log(f"  ✅ PASS - Example.com tab opened")
                passed += 1
            else:
                log(f"  ❌ FAIL - {txt[:100]}")
                failed += 1
            results.append({"phase": "browser", "test": "open_example_com", "status": "PASS" if ok else "FAIL"})
            
            # Test 14: Check active window title
            log("Test 14: Verify active window is Example.com")
            ok, txt, _ = await _call(session, 'read_screen_ui', {})
            example_window = 'Example Domain - Google Chrome' in txt
            wiki_window = 'Wikipedia' in txt and 'Chrome' in txt
            if example_window:
                log(f"  ✅ PASS - Active window is Example.com")
                passed += 1
            else:
                log(f"  ❌ FAIL - Active window not Example.com")
                failed += 1
            results.append({"phase": "browser", "test": "active_window_is_example_com", "status": "PASS" if example_window else "FAIL"})
            
            # Test 15: browser_use_dom from Example.com (active tab - THE KEY TEST)
            log("Test 15: browser_use_dom from Example.com (active tab - THE KEY TEST)")
            # Dismiss any lingering dialog before DOM extraction
            await session.call_tool('computer', {'action': 'key', 'text': 'escape'})
            await asyncio.sleep(1)
            ok, txt, _ = await _call(session, 'browser_use_dom', {})
            # The first URL in DOM may be a link, not the page URL. Check page content instead.
            is_example = 'Example Domain' in txt and 'en.wikipedia' not in txt[:500]
            is_wiki = 'Artificial intelligence' in txt or 'en.wikipedia.org' in txt
            if is_example and not is_wiki:
                log(f"  ✅ PASS - DOM from Example.com (active tab)")
                passed += 1
            elif is_wiki:
                log(f"  ❌ FAIL - DOM captured Wikipedia instead of Example.com")
                failed += 1
            else:
                log(f"  ❌ FAIL - Could not determine page content")
                failed += 1
            results.append({"phase": "browser", "test": "dom_from_example_com", "status": "PASS" if is_example and not is_wiki else "FAIL"})
            
            # Test 16: Switch to Wikipedia tab and capture DOM
            log("Test 16: Switch to Wikipedia window and capture DOM")
            # Dismiss any dialogs first
            await session.call_tool('computer', {'action': 'key', 'text': 'escape'})
            await asyncio.sleep(1)
            await session.call_tool('computer', {'action': 'key', 'text': 'escape'})
            await asyncio.sleep(1)
            
            # Since both Chrome windows overlap, we can't reliably click the Wikipedia
            # window title bar. Instead, close the active (Example.com) window using
            # ctrl+w, which will bring Wikipedia to the foreground.
            await session.call_tool('computer', {'action': 'key', 'text': 'ctrl+w', 'thinking': 'close active Chrome window to bring Wikipedia to front'})
            await asyncio.sleep(3)
            
            # Also try Alt+Tab as fallback
            await session.call_tool('computer', {'action': 'key', 'text': 'alt+tab', 'thinking': 'alt tab to Wikipedia window'})
            await asyncio.sleep(1)
            await session.call_tool('computer', {'action': 'key', 'text': 'alt+tab', 'thinking': 'alt tab again'})
            await asyncio.sleep(2)
            
            # Wait for tab switch + uiautomation title propagation
            await asyncio.sleep(3)
            
            # Re-check active window with updated title (may need one more scan)
            ok, txt, _ = await _call(session, 'read_screen_ui', {})
            # Check if Wikipedia is the FIRST/ACTIVE window (not just present)
            lines = txt.splitlines()
            wiki_active = False
            for line in lines:
                if '<Window name=' in line:
                    if 'Wikipedia' in line and 'Chrome' in line:
                        wiki_active = True
                        break
                    elif 'Example' in line or 'Wikipedia' in line:
                        # Active window is NOT Wikipedia
                        break
            if not wiki_active:
                # Wait a bit more and try again
                await asyncio.sleep(2)
                ok, txt, _ = await _call(session, 'read_screen_ui', {})
                wiki_active = 'Wikipedia' in txt and 'Chrome' in txt
            
            # Capture DOM
            print('=== STEP 6: Capture DOM from Wikipedia (after tab switch) ===')
            # Dismiss any lingering dialog before DOM extraction
            await session.call_tool('computer', {'action': 'key', 'text': 'escape'})
            await asyncio.sleep(1)
            ok2, txt2, _ = await _call(session, 'browser_use_dom', {})
            is_wiki2 = 'Artificial intelligence' in txt2 or 'en.wikipedia.org' in txt2
            is_example2 = 'Example Domain' in txt2
            if is_wiki2 and not is_example2:
                log(f"  ✅ PASS - DOM from Wikipedia after tab switch")
                passed += 1
            elif is_example2:
                log(f"  ❌ FAIL - DOM still shows Example.com after tab switch")
                failed += 1
            else:
                log(f"  ❌ FAIL - Could not determine page content after tab switch")
                failed += 1
            results.append({"phase": "browser", "test": "dom_from_wikipedia_after_switch", "status": "PASS" if is_wiki2 and not is_example2 else "FAIL"})
            
            # Cleanup
            log("Cleaning up Chrome...")
            await session.call_tool('bash', {'command': 'taskkill /f /im chrome.exe 2>nul'})
            await asyncio.sleep(2)
            
            # Test 17: update_thought tool
            log("Test 17: update_thought tool")
            ok, txt, _ = await _call(session, 'update_thought', {'thought': 'Test thought update'})
            if ok and 'OK' in txt:
                log(f"  ✅ PASS - Thought updated")
                passed += 1
            else:
                log(f"  ❌ FAIL - {txt[:100]}")
                failed += 1
            results.append({"phase": "simple", "test": "update_thought", "status": "PASS" if ok and 'OK' in txt else "FAIL"})
            
            # Test 18: terminate_task tool
            log("Test 18: terminate_task tool")
            ok, txt, _ = await _call(session, 'terminate_task', {'success': True, 'message': 'Test complete'})
            if ok and 'TASK_TERMINATED' in txt:
                log(f"  ✅ PASS - Task terminated")
                passed += 1
            else:
                log(f"  ❌ FAIL - {txt[:100]}")
                failed += 1
            results.append({"phase": "simple", "test": "terminate_task", "status": "PASS" if ok and 'TASK_TERMINATED' in txt else "FAIL"})
    
    # Clean up temp files
    try:
        os.remove(new_file)
    except:
        pass
    
    # Summary
    log("\n" + "=" * 60)
    log(f"SUMMARY: {passed} passed, {failed} failed out of {passed + failed}")
    log("=" * 60)
    
    for r in results:
        icon = "✅" if r["status"] == "PASS" else "❌"
        log(f"  {icon} [{r['phase']}] {r['test']}: {r['status']}")
    
    # Save results
    result_file = os.path.join(ROOT, 'test_results.json')
    with open(result_file, 'w') as f:
        json.dump({"passed": passed, "failed": failed, "total": passed + failed, "results": results}, f, indent=2)
    
    return 0 if failed == 0 else 1

if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
