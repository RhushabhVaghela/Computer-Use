import asyncio
import sys
import mcp_complex_prompt_llm as runner

def main() -> int:
    # Pass --hybrid to the runner if it was provided to this script
    if "--hybrid" in sys.argv:
        sys.argv.append("--hybrid")

    prompt = """
You are controlling my Windows desktop via MCP tools.

Hard constraints (do not violate):
- Do NOT create, rename, move, delete, download, or save any files.
- Do NOT use rename_file at all.
- Avoid bash except for launching apps (start notepad/calc) or taskkill. Never use echo/type/copy/move/etc.
- Keep actions minimal: no redundant repeated clicks/scrolls. If an action does nothing twice, change strategy.
- THE BROWSER RULE: `read_screen_ui` CANNOT see inside web browsers. If you are interacting with Chrome, Edge, or the web, you MUST call `browser_use_dom` to get the webpage layout, then use the desktop `computer` tool to click the [idx] provided by the DOM scan.

Error Recovery (Bash to GUI Fallback):
- If a `bash` command is blocked, fails, or does not achieve the expected result (e.g., an app doesn't open), you MUST immediately abandon `bash`.
- To fall back to manual GUI control: Call `read_screen_ui`, then use the `computer` tool. You can use `action="key"` and `text="win"` to open Start, `action="type"` to search, and `action="key"` with `text="enter"` to launch.
- The system will automatically return the new UI tree [AUTO UI SCAN] after every successful mouse click or keyboard action. 
- You do NOT need to manually call `read_screen_ui` unless you are completely lost. Use the automatically provided [idx] elements to plan your next `computer` tool click.
- If you need to click an icon on the Windows Desktop wallpaper, DO NOT try to find it in the background. Use the `computer` tool with `action="key"` and `text="win+d"` to minimize all apps and make the Desktop the active window.

Task (complex multi-app flow):
1) Open Notepad.
2) Create a small formatted note:
   Title line: "MCP Complex Test"
   Then 6 bullet lines numbered 1-6, each containing a different short word: alpha, beta, gamma, delta, epsilon, zeta.
3) Use keyboard only to: Select all, Copy to clipboard, Move cursor to end, Insert a new line: "Clipboard copy done."
4) Open Calculator (Windows calculator).
5) Compute: (19 * 23) + 7
6) Return to Notepad and type the result on a new line as: "Calc result: <number>"
7) Open a browser and navigate to the Wikipedia page for "Fibonacci number".
8) Wait for page load, read the DOM, then scroll down ~3 times.
9) In the SAME browser session, navigate to "https://example.com".
10) Return to Notepad and type: "Browser navigation done."
11) Close Calculator and Notepad WITHOUT saving anything.

Throughout:
- Refer to your System Instructions on how to handle the browser handoff.
- Use desktop tools for non-browser actions.
- Call read_screen_ui immediately before any desktop mouse action.
""".strip()

    asyncio.run(runner.run(prompt))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())