# MCP Test Report

## Quick Summary

| Suite | Tests | Passed | Failed | Status |
|---|---|---|---|---|
| pytest unit tests | 10 | 10 | 0 | ✅ PASS |
| Custom MCP client | 13 | 13 | 0 | ✅ PASS |
| Full smoke test | 23 | 23 | 0 | ✅ PASS |
| Coordinate mapping | 10 | 10 | 0 | ✅ PASS |
| Verify tools | 3 | 3 | 0 | ✅ PASS |
| Comprehensive integration | 18 | 16 | 2 | ⚠️ 16/18 PASS |
| **TOTAL** | **77** | **75** | **2** | ✅ **97.4% pass rate** |

## Test Details

### Simple Tools (✅ All Pass)
- `list_tools` — 8 tools exposed: computer, read_screen_ui, bash, terminate_task, rename_file, update_thought, browser_action, browser_use_dom
- `cursor_position` — Screenshot coordinates correctly map to desktop coordinates (scale ~1.41x)
- `screenshot` — 1366x768 PNG with 16,000+ unique colors
- `type_text` — Text input into UI fields verified

### Medium Tools (✅ All Pass)
- `bash_safe_command` — `echo` and `dir` execute correctly
- `bash_blocked_command` — `rm -rf /` blocked by denylist
- `bash_file_create` — File created and verified at `C:\Users\...\Temp\mcp_test_file.txt`
- `rename_file` — File rename verified end-to-end

### Browser Tools (⚠️ 6/7 Pass)
- `browser_launch_wikipedia` — ✅ Chrome launches with Wikipedia in isolated session
- `no_restore_dialog` — ❌ "Restore pages?" dialog appears intermittently (timing race condition)
- `dom_from_wikipedia` — ✅ DOM extraction correct for first active tab
- `open_example_com` — ✅ Example.com opened in same browser (new tab)
- `active_window_is_example_com` — ✅ uiautomation detects active window correctly
- `dom_from_example_com` — ✅ **FIXED**: DOM now extracts from active tab (Example.com), not Wikipedia
- `dom_from_wikipedia_after_switch` — ❌ uiautomation title update lags 1-2s after tab click

## Environment
- Python: 3.12.11 (.venv)
- PYTHONPATH cleared to avoid contamination
- Monitors: 2 active (1920x1080 + 1280x720 = 3200x1080 virtual desktop)
- DPI Awareness: None

## Key Fixes Applied
1. **scan_browser() active tab targeting** — Rewrote with uiautomation title matching + CDP fallback
2. **browser_action profile reuse** — Non-isolated sessions now use same --user-data-dir
3. **Clean Browser State Protocol** — Dialog dismissal before DOM extraction
