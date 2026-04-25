import argparse
import json
import random
import uuid
import os
import time
import logging
import requests
import shutil

# --- Path Discovery Helper ---
def get_base_path():
    # Priority: Env var (OI_MCP_PATH) > Directory of current script
    path = os.environ.get("OI_MCP_PATH")
    if path:
        return path.strip('"\'')
    # Default to repo root (two levels up from scripts/dataset_manager.py)
    return os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))

BASE_DIR = get_base_path()
# ----------------------------

from colorama import init, Fore, Style
from tabulate import tabulate
from rich.console import Console
from rich.json import JSON
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn, TimeElapsedColumn, TimeRemainingColumn

# Initialize colorama and rich
init(autoreset=True)
console = Console()

# Configure logging
logging.basicConfig(
    filename='generation.log',
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s'
)

# ---------------------------------------------------------------------------
# CORE HELPERS
# ---------------------------------------------------------------------------
def create_example(messages):
    return json.dumps({"messages": messages})

def sys_prompt():
    return {
        "role": "system",
        "content": "You are a capable AI assistant that can control the user's computer using the provided tools. You can perform precise actions using `computer`, read the screen UI using `read_screen_ui`, execute code using `bash`, and use specialized tools like `browser_action` and `rename_file`. Always include a `thinking` field in `computer` calls to explain your actions. When a task is complete or failed, you MUST call `terminate_task` to signal the end of the conversation."
    }

def user(text): return {"role": "user", "content": text}
def assistant_msg(text): return {"role": "assistant", "content": text}
def call_tool(id, name, args):
    if isinstance(args, dict): args = json.dumps(args)
    return {"id": id, "type": "function", "function": {"name": name, "arguments": args}}
def assistant_tool(calls, text=None):
    msg = {"role": "assistant", "tool_calls": calls}
    if text: msg["content"] = text
    return msg
def tool_result(id, text): return {"role": "tool", "tool_call_id": id, "content": text}

# --- VLM specific helpers ---
def user_with_image(text, mock_image_b64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNk+M9QDwADhgGAWjR9awAAAABJRU5ErkJggg=="):
    return {"role": "user", "content": [{"type": "image_url", "image_url": {"url": f"data:image/png;base64,{mock_image_b64}"}}, {"type": "text", "text": text}]}

def tool_result_with_image(id, text, mock_image_b64="iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQAAAABJRU5ErkJggg=="):
    return {"role": "tool", "tool_call_id": id, "content": [{"type": "text", "text": text}, {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{mock_image_b64}"}}]}
# ---------------------------------------------------------------------------
# 1. GENERATE SEEDS (Manual Gold Standard + Basic Actions)
# ---------------------------------------------------------------------------
def get_manual_seeds():
    dataset = []

    # --- TIER 1 & 2: BASIC PERCEPTIONS & ACTIONS ---
    dataset.append([sys_prompt(), user("Type 'Hello World' on the keyboard."), assistant_tool([call_tool("call_1", "computer", {"action": "type", "text": "Hello World", "thinking": "Typing 'Hello World' on the user's keyboard."})]), tool_result("call_1", "Result: Typed 'Hello World'"), assistant_tool([call_tool("call_done_1", "terminate_task", {"success": True, "message": "I have successfully typed 'Hello World'."})])])
    dataset.append([sys_prompt(), user("Hit enter."), assistant_tool([call_tool("call_2", "computer", {"action": "key", "text": "enter", "thinking": "Pressing the enter key."})]), tool_result("call_2", "Result: Pressed 'enter'"), assistant_tool([call_tool("call_done_2", "terminate_task", {"success": True, "message": "I pressed the enter key."})])])
    dataset.append([sys_prompt(), user("Save the current document."), assistant_tool([call_tool("call_3", "computer", {"action": "key", "text": "ctrl+s", "thinking": "Saving the document using Ctrl+S shortcut."})]), tool_result("call_3", "Result: Pressed 'ctrl+s'"), assistant_tool([call_tool("call_done_3", "terminate_task", {"success": True, "message": "I pressed Ctrl+S to save the document."})])])
    dataset.append([sys_prompt(), user("Click at coordinate 500, 500."), assistant_tool([call_tool("call_4", "computer", {"action": "left_click", "coordinate": [500, 500], "thinking": "Clicking at the specified coordinates (500, 500)."})]), tool_result("call_4", "Result: Clicked at (500, 500)"), assistant_tool([call_tool("call_done_4", "terminate_task", {"success": True, "message": "I clicked at the coordinates (500, 500)."})])])
    dataset.append([sys_prompt(), user("Right click in the center of the screen (960, 540)."), assistant_tool([call_tool("call_5", "computer", {"action": "right_click", "coordinate": [960, 540], "thinking": "Performing a right-click at the center of the screen (960, 540)."})]), tool_result("call_5", "Result: Right clicked at (960, 540)"), assistant_tool([call_tool("call_done_5", "terminate_task", {"success": True, "message": "I right-clicked at (960, 540)."})])])
    dataset.append([sys_prompt(), user("Open the file located at 100, 200 by double clicking it."), assistant_tool([call_tool("call_6", "computer", {"action": "double_click", "coordinate": [100, 200], "thinking": "Double-clicking at (100, 200) to open the file."})]), tool_result("call_6", "Result: Double clicked at (100, 200)"), assistant_tool([call_tool("call_done_6", "terminate_task", {"success": True, "message": "I double-clicked the file to open it."})])])
    dataset.append([sys_prompt(), user("Drag the window from 100,100 to 500,500."), assistant_tool([call_tool("call_7", "computer", {"action": "drag", "start_coordinate": [100, 100], "coordinate": [500, 500], "thinking": "Dragging the window from (100, 100) to (500, 500)."})]), tool_result("call_7", "Result: Dragged from (100, 100) to (500, 500)"), assistant_tool([call_tool("call_done_7", "terminate_task", {"success": True, "message": "I dragged the item from (100, 100) to (500, 500)."})])])
    dataset.append([sys_prompt(), user("Scroll down a bit."), assistant_tool([call_tool("call_9", "computer", {"action": "scroll", "text": "-10", "thinking": "Scrolling down by 10 units."})]), tool_result("call_9", "Result: Scrolled by -10 units"), assistant_tool([call_tool("call_done_9", "terminate_task", {"success": True, "message": "I scrolled down."})])])
    dataset.append([sys_prompt(), user("Scroll up to the top."), assistant_tool([call_tool("call_10", "computer", {"action": "scroll", "text": "20", "thinking": "Scrolling up to the top."})]), tool_result("call_10", "Result: Scrolled by 20 units"), assistant_tool([call_tool("call_done_10", "terminate_task", {"success": True, "message": "I scrolled up."})])])
    dataset.append([sys_prompt(), user("Hover over the icon at 300, 400 to see its tooltip."), assistant_tool([call_tool("call_11", "computer", {"action": "mouse_move", "coordinate": [300, 400], "thinking": "Moving the mouse to (300, 400) to hover over the icon."})]), tool_result("call_11", "Result: Mouse moved to (300, 400)"), assistant_tool([call_tool("call_done_11", "terminate_task", {"success": True, "message": "I moved the mouse over the icon."})])])
    dataset.append([sys_prompt(), user("Click the 'Submit' button."), assistant_tool([call_tool("call_12", "read_screen_ui", {})]), tool_result("call_12", "[M1] [1] Edit \"Search\" at (500, 50)\n[M1] [2] Button \"Submit\" at (500, 100)"), assistant_tool([call_tool("call_13", "computer", {"action": "left_click", "coordinate": [500, 100], "thinking": "I found the Submit button at coordinates (500, 100) and will click it."})]), tool_result("call_13", "Result: Clicked at (500, 100)"), assistant_tool([call_tool("call_done_13", "terminate_task", {"success": True, "message": "I clicked the Submit button."})])])
    dataset.append([sys_prompt(), user("Open Google Chrome."), assistant_tool([call_tool("call_14", "read_screen_ui", {})]), tool_result("call_14", "[M1] [1] ListItem \"Recycle Bin\" at (50, 50)\n[M1] [2] ListItem \"Google Chrome\" at (50, 150)"), assistant_tool([call_tool("call_15", "computer", {"action": "double_click", "coordinate": [50, 150], "thinking": "Double-clicking the Google Chrome icon at (50, 150) to open the browser."})]), tool_result("call_15", "Result: Double clicked at (50, 150)"), assistant_tool([call_tool("call_done_15", "terminate_task", {"success": True, "message": "I double-clicked Google Chrome to open it."})])])
    dataset.append([sys_prompt(), user("Click 'Advanced Settings' at the bottom of the page."), assistant_tool([call_tool("call_16", "read_screen_ui", {})]), tool_result("call_16", "[M1] [1] Text \"General Settings\" at (100, 100)\n[M1] [2] Text \"Network\" at (100, 200)"), assistant_tool([call_tool("call_17", "computer", {"action": "scroll", "text": "-20", "thinking": "I don't see the 'Advanced Settings' button. I will scroll down to find it."})], "I don't see it on the current screen. I'll scroll down."), tool_result("call_17", "Result: Scrolled by -20 units"), assistant_tool([call_tool("call_18", "read_screen_ui", {})]), tool_result("call_18", "[M1] [8] Text \"Security\" at (100, 800)\n[M1] [9] Button \"Advanced Settings\" at (100, 900)"), assistant_tool([call_tool("call_19", "computer", {"action": "left_click", "coordinate": [100, 900], "thinking": "Found the 'Advanced Settings' button at (100, 900). Clicking it now."})]), tool_result("call_19", "Result: Clicked at (100, 900)"), assistant_tool([call_tool("call_done_19", "terminate_task", {"success": True, "message": "I found 'Advanced Settings' after scrolling and clicked it."})])])
    dataset.append([sys_prompt(), user("What error message is showing on the screen right now?"), assistant_tool([call_tool("call_20", "read_screen_ui", {})]), tool_result("call_20", "[M1] [1] Window \"Error\" at (500, 500)\n[M1] [2] Text \"Connection timed out. Error code 504.\" at (520, 550)\n[M1] [3] Button \"OK\" at (520, 600)"), assistant_tool([call_tool("call_done_20", "terminate_task", {"success": True, "message": "The screen shows an error message: \"Connection timed out. Error code 504.\""})])])
    dataset.append([sys_prompt(), user("Fill out the login form. Username 'admin', password '1234'."), assistant_tool([call_tool("call_21", "read_screen_ui", {})]), tool_result("call_21", "[M1] [1] Edit \"Username\" at (400, 300)\n[M1] [2] Edit \"Password\" at (400, 400)\n[M1] [3] Button \"Login\" at (400, 500)"), assistant_tool([call_tool("call_22", "computer", {"action": "left_click", "coordinate": [400, 300], "thinking": "Clicking the Username field."}), call_tool("call_23", "computer", {"action": "type", "text": "admin", "thinking": "Typing 'admin' into the username field."}), call_tool("call_24", "computer", {"action": "left_click", "coordinate": [400, 400], "thinking": "Clicking the Password field."}), call_tool("call_25", "computer", {"action": "type", "text": "1234", "thinking": "Typing '1234' into the password field."}), call_tool("call_26", "computer", {"action": "left_click", "coordinate": [400, 500], "thinking": "Clicking the Login button."})], "I see the form. I'll click the username field, type 'admin', then click the password field, type '1234', and click Login."), tool_result("call_22", "Result: Clicked"), tool_result("call_23", "Result: Typed"), tool_result("call_24", "Result: Clicked"), tool_result("call_25", "Result: Typed"), tool_result("call_26", "Result: Clicked"), assistant_tool([call_tool("call_done_26", "terminate_task", {"success": True, "message": "I have filled out the login form and clicked Login."})])])
    dataset.append([sys_prompt(), user("Click the start menu on the second monitor."), assistant_tool([call_tool("call_27", "read_screen_ui", {})]), tool_result("call_27", "[M1] [1] Button \"Start\" at (20, 1060)\n[M2] [2] Button \"Start\" at (1940, 1060)"), assistant_tool([call_tool("call_28", "computer", {"action": "left_click", "coordinate": [1940, 1060], "thinking": "Clicking the Start button on the second monitor (M2)."})]), tool_result("call_28", "Result: Clicked at (1940, 1060)"), assistant_tool([call_tool("call_done_28", "terminate_task", {"success": True, "message": "I clicked the Start button on monitor 2."})])])
    dataset.append([sys_prompt(), user("Close that annoying popup advertisement."), assistant_tool([call_tool("call_29", "read_screen_ui", {})]), tool_result("call_29", "[M1] [1] Window \"Special Offer!\" at (600, 400)\n[M1] [2] Button \"Close\" at (900, 420)\n[M1] [3] Text \"Buy now\" at (700, 500)"), assistant_tool([call_tool("call_30", "computer", {"action": "left_click", "coordinate": [900, 420], "thinking": "I found the close button for the popup and will click it to dismiss the advertisement."})]), tool_result("call_30", "Result: Clicked at (900, 420)"), assistant_tool([call_tool("call_done_30", "terminate_task", {"success": True, "message": "I found the close button for the popup and clicked it."})])])
    dataset.append([sys_prompt(), user("Uncheck the 'Subscribe to newsletter' box."), assistant_tool([call_tool("call_31", "read_screen_ui", {})]), tool_result("call_31", "[M1] [1] CheckBox \"Subscribe to newsletter\" at (300, 600)"), assistant_tool([call_tool("call_32", "computer", {"action": "left_click", "coordinate": [300, 600], "thinking": "Clicking the checkbox to uncheck the newsletter subscription."})]), tool_result("call_32", "Result: Clicked at (300, 600)"), assistant_tool([call_tool("call_done_32", "terminate_task", {"success": True, "message": "I've unchecked the newsletter subscription box."})])])
    dataset.append([sys_prompt(), user("Drag the image into the folder."), assistant_tool([call_tool("call_33", "read_screen_ui", {})]), tool_result("call_33", "[M1] [1] Image \"photo.jpg\" at (200, 200)\n[M1] [2] Folder \"Vacation\" at (800, 200)"), assistant_tool([call_tool("call_34", "computer", {"action": "drag", "start_coordinate": [200, 200], "coordinate": [800, 200], "thinking": "I will drag the image 'photo.jpg' from its current location to the 'Vacation' folder."})]), tool_result("call_34", "Result: Dragged from (200, 200) to (800, 200)"), assistant_tool([call_tool("call_done_34", "terminate_task", {"success": True, "message": "I dragged the image 'photo.jpg' into the 'Vacation' folder."})])])
    
    # --- TIER 3: CODE ENVIRONMENTS ---
    dataset.append([sys_prompt(), user("Calculate the square root of 256 using python."), assistant_tool([call_tool("call_37", "bash", {"command": "python -c \"import math; print(math.sqrt(256))\""})]), tool_result("call_37", "16.0\n"), assistant_tool([call_tool("call_done_37", "terminate_task", {"success": True, "message": "The square root of 256 is 16.0."})])])
    dataset.append([sys_prompt(), user("Get the current bitcoin price in USD using python."), assistant_tool([call_tool("call_40", "bash", {"command": "python -c \"import requests; res=requests.get('https://api.coindesk.com/v1/bpi/currentprice.json').json(); print(res['bpi']['USD']['rate_float'])\""})]), tool_result("call_40", "64230.15\n"), assistant_tool([call_tool("call_done_40", "terminate_task", {"success": True, "message": "The current price of Bitcoin is roughly $64,230.15 USD."})])])
    dataset.append([sys_prompt(), user("Read the first 3 lines of 'data.csv' in my Documents."), assistant_tool([call_tool("call_42", "bash", {"command": "head -n 3 ~/Documents/data.csv"})]), tool_result("call_42", "id,name,age\n1,Alice,30\n2,Bob,25\n"), assistant_tool([call_tool("call_done_42", "terminate_task", {"success": True, "message": "Here are the first three lines of your CSV file:\n`id,name,age`\n`1,Alice,30`\n`2,Bob,25`"})])])
    dataset.append([sys_prompt(), user("Run this in JS: console.log(Array.from({length: 5}, (_, i) => i * 2))"), assistant_tool([call_tool("call_43", "bash", {"command": "node -e \"console.log(Array.from({length: 5}, (_, i) => i * 2))\""})]), tool_result("call_43", "[ 0, 2, 4, 6, 8 ]\n"), assistant_tool([call_tool("call_done_43", "terminate_task", {"success": True, "message": "The output is `[ 0, 2, 4, 6, 8 ]`."})])])
    dataset.append([sys_prompt(), user("Kill the notepad process."), assistant_tool([call_tool("call_44", "bash", {"command": "Stop-Process -Name 'notepad' -Force"})]), tool_result("call_44", ""), assistant_tool([call_tool("call_done_44", "terminate_task", {"success": True, "message": "I have forcefully terminated the Notepad process."})])])
    dataset.append([sys_prompt(), user("List all PDF files in the Downloads folder."), assistant_tool([call_tool("call_45", "bash", {"command": "ls ~/Downloads/*.pdf"})]), tool_result("call_45", "/Users/usr/Downloads/report.pdf\n/Users/usr/Downloads/invoice.pdf\n"), assistant_tool([call_tool("call_done_45", "terminate_task", {"success": True, "message": "I found the following PDF files in your Downloads folder: \n- `report.pdf`\n- `invoice.pdf`"})])])

    # --- TIER 4: GOLD REASONING EXAMPLES ---
    dataset.append([sys_prompt(), user("Download the latest Python 3.12 installer for Windows."), assistant_tool([call_tool("call_01", "browser_action", {"url": "https://www.python.org/downloads/", "browser": "chrome"})], "I'll open Chrome and navigate to the Python downloads page."), tool_result("call_01", "Launched browser"), assistant_tool([call_tool("call_02", "read_screen_ui", {})], "I'll read the screen to find the download link for Windows."), tool_result("call_02", "[M1] [1] Text \"Download Python 3.12.2\" at (500, 300)\n[M1] [2] Link \"Windows installer (64-bit)\" at (500, 350)"), assistant_tool([call_tool("call_03", "computer", {"action": "left_click", "coordinate": [500, 350], "thinking": "Found the Windows installer link. Clicking to start the download."})]), tool_result("call_03", "Result: Clicked at (500, 350)"), assistant_tool([call_tool("call_done_03", "terminate_task", {"success": True, "message": "I have navigated to the Python website and initiated the download for the 64-bit Windows installer."})])])
    dataset.append([sys_prompt(), user("Extract all the email addresses from contact.txt on my desktop."), assistant_tool([call_tool("call_06", "bash", {"command": "python -c \"import re, os; text = open(os.path.expanduser('~/Desktop/contact.txt'), 'r').read(); print(re.findall(r'[\\w\\.-]+@[\\w\\.-]+', text))\""})]), tool_result("call_06", "FileNotFoundError: [Errno 2] No such file or directory: 'C:\\\\Users\\\\User\\\\Desktop\\\\contact.txt'"), assistant_tool([call_tool("call_07", "bash", {"command": "Get-ChildItem -Path ~/Desktop -Filter '*contact*' -Recurse"})], "I couldn't find 'contact.txt' exactly on the desktop. I'll search for any file containing 'contact' on the desktop."), tool_result("call_07", "Directory: C:\\Users\\User\\Desktop\\Important\n\nName\n----\ncontacts_list.txt\n"), assistant_tool([call_tool("call_08", "bash", {"command": "python -c \"import re, os; text = open(os.path.expanduser('~/Desktop/Important/contacts_list.txt'), 'r').read(); print(re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}', text))\""})], "Ah, the file is named 'contacts_list.txt' and it's inside an 'Important' folder. I will extract the emails from there."), tool_result("call_08", "['admin@example.com', 'support@lobehub.com']\n"), assistant_tool([call_tool("call_done_08", "terminate_task", {"success": True, "message": "I found the following email addresses in `contacts_list.txt`: `admin@example.com` and `support@lobehub.com`"})])])
    dataset.append([sys_prompt(), user("My computer is running really slow and the fans are loud. Fix it."), assistant_tool([call_tool("call_20", "bash", {"command": "Get-Process | Sort-Object CPU -Descending | Select-Object -First 3 Name, CPU, Id"})], "Let's check which processes are consuming the most CPU right now."), tool_result("call_20", "Name         CPU        Id\n----         ---        --\nffmpeg       145.2      9021\nchrome       12.4       5044\nexplorer     4.1        3011\n"), assistant_tool([call_tool("call_21", "bash", {"command": "Stop-Process -Id 9021 -Force"})], "There is an FFmpeg process (ID 9021) consuming an abnormally high amount of CPU. I'll terminate it to restore performance."), tool_result("call_21", ""), assistant_tool([call_tool("call_done_21", "terminate_task", {"success": True, "message": "I found a rogue `ffmpeg` process maxing out your CPU and terminated it. Your computer should cool down and become responsive again."})])])
    dataset.append([sys_prompt(), user("Get the current weather for New York. Use python."), assistant_tool([call_tool("call_22", "bash", {"command": "python -c \"import requests; print(requests.get('https://wttr.in/NewYork?format=3').text)\""})]), tool_result("call_22", "requests.exceptions.ConnectionError: HTTPSConnectionPool(host='wttr.in', port=443): Max retries exceeded"), assistant_tool([call_tool("call_23", "bash", {"command": "python -c \"import json, urllib.request; req = urllib.request.Request('https://api.weather.gov/points/40.7128,-74.0060', headers={'User-Agent': 'my-app'}); data = json.loads(urllib.request.urlopen(req).read().decode()); print('Weather URL:', data['properties']['forecast'])\""})], "The `wttr.in` service seems down or timed out. I'll try using the official US weather.gov API as a fallback."), tool_result("call_23", "Weather URL: https://api.weather.gov/gridpoints/OKX/32,34/forecast\n"), assistant_tool([call_tool("call_24", "bash", {"command": "python -c \"import urllib.request, json; req = urllib.request.Request('https://api.weather.gov/gridpoints/OKX/32,34/forecast', headers={'User-Agent': 'my-app'}); data = json.loads(urllib.request.urlopen(req).read().decode()); print(data['properties']['periods'][0]['detailedForecast'])\""})]), tool_result("call_24", "Mostly clear, with a low around 65. West wind 5 to 10 mph.\n"), assistant_tool([call_tool("call_done_24", "terminate_task", {"success": True, "message": "The weather in New York is currently mostly clear, with a low around 65°F and a west wind of 5 to 10 mph."})])])
    dataset.append([sys_prompt(), user("I messed up my last commit. Can you undo it but keep my changes in the working directory? I'm in the 'my-project' folder on Desktop."), assistant_tool([call_tool("call_25", "bash", {"command": "cd ~/Desktop/my-project && git log -n 2 --oneline"})], "I'll first verify the recent commit history in your project."), tool_result("call_25", "a1b2c3d (HEAD -> main) Oops bad commit\ne4f5g6h Added new feature\n"), assistant_tool([call_tool("call_26", "bash", {"command": "cd ~/Desktop/my-project && git reset --soft HEAD~1 && git status -s"})], "I see the bad commit. I will use `git reset --soft HEAD~1` to undo the commit while retaining the file changes in your staging area."), tool_result("call_26", "M  src/main.py\nA  src/utils.py\n"), assistant_tool([call_tool("call_done_26", "terminate_task", {"success": True, "message": "I have successfully undone the commit 'a1b2c3d'. Your changes to `src/main.py` and `src/utils.py` are preserved in your working directory and staged, ready for you to adjust and recommit."})])])

    return dataset

# ---------------------------------------------------------------------------
# 2. GENERATE API (GEMINI & LOCAL LLMS)
# ---------------------------------------------------------------------------
def generate_api_dataset(api_key, count, api_base, model_name, batch_size=14, output_file="dataset.jsonl"):
    mode = "openai" if api_base else "gemini"
    
    if mode == "openai":
        try:
            from openai import OpenAI
            client = OpenAI(base_url=api_base, api_key=api_key or "local-key")
            model_name = model_name or "qwen2.5"
            print(f"Using Local LLM API endpoint: {api_base} with model {model_name}")
        except ImportError:
            print("ERROR: Run `pip install openai` to use local API generation.")
            return []
    else:
        if not api_key:
            print("ERROR: Gemini API key required. Pass it with --api-key or use --api-base for local.")
            return []
        
        # We use standard requests to explicitly avoid hidden google-genai 429 infinite backoff loops
        client = None 
        model_name = model_name or "gemini-3-pro-preview"
        print(f"Using Google Gemini REST API with model {model_name}")

    seeds = get_manual_seeds()
    dataset = []
    
    SYSTEM_PROMPT = """You are an expert AI dataset generator. Your job is to create synthetic fine-tuning examples that teach an LLM how to use computer-control tools natively. 
The tools available are EXACTLY: 
1. `computer`: Perform a precise computer action. Arguments: {"action": "left_click|right_click|double_click|middle_click|mouse_move|key|type|scroll|drag|screenshot", "coordinate": [x, y], "start_coordinate": [x, y], "text": "string", "thinking": "REQUIRED string"}.
2. `read_screen_ui`: Scan the screen for interactive UI elements in a hierarchical tree. Arguments: {}.
3. `bash`: Run shell code. Arguments: {"command": "string"}.
4. `terminate_task`: FINAL TASK SIGNAL. STOP IMMEDIATELY AFTER CALLING THIS. Arguments: {"success": bool, "message": "string"}.
5. `rename_file`: Rename or move a file directly. Arguments: {"old_path": "string", "new_path": "string"}.
6. `browser_action`: Specialized browser tool. Arguments: {"url": "string", "search_query": "string", "browser": "chrome|edge|firefox|brave|comet|perplexity"}.
7. `browser_use_dom`: Extract efficient DOM structure from browser. Arguments: {}.

CRITICAL GEOMETRY RULES:
1. THINKING FIELD: Every single `computer` tool call MUST include the `thinking` field explaining what the agent is doing (e.g., 'Searching for submit button', 'Typing search query').
2. STRICT ALTERNATION: You MUST strictly alternate between `assistant` and `tool` roles. An `assistant` message with `tool_calls` MUST be immediately followed by a `tool` message containing the result. NEVER output two consecutive `assistant` messages. If you need to make parallel tool calls, group them inside the `tool_calls` array of a SINGLE `assistant` message.
3. CONVERSATION CLOSURE: Every conversation array MUST end with a `terminate_task` tool call from the assistant. NEVER end a conversation mid-tool-call or with a plain text message.
4. INJECT REALISM: Purposefully simulate realistic tool failures in ~25% of the scenarios (e.g., a `bash` command returning "command not found", or an incorrect file path). The `assistant` MUST gracefully read the failure from the `tool` message, apologize or reason through it, and retry successfully.
5. MAXIMUM CONCISENESS: A single synthetic conversation should NEVER exceed 8 messages total. Solve the user's computer-use problem elegantly in 1 to 3 tool calls. Do not overcomplicate the scenario.

Always output your response as EXACTLY ONE perfectly formatted JSON array representing a list of conversations. Do NOT output markdown blocks."""
    print(f"Calling API to generate {count} items...")
    
    successful = 0
    batch_size = min(batch_size, count)
    total_tokens_approx = 0

    start_time = time.time()

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        task_id = progress.add_task("[cyan]Generating Dataset", total=count)

        while successful < count:
            prompt = f"Generate {batch_size} highly distinct, creative, and complex multi-turn computer use scenarios. Output ONLY a JSON array containing exactly {batch_size} conversation arrays. Format: [ [turn1, turn2...], [turn1, turn2...] ]."
        
            # Build prompt history dynamically based on API type
            if mode == "gemini":
                contents = [{"role": "user", "parts": [{"text": "You must strictly output raw JSON without markdown blocks."}]}]
                for seed in random.sample(seeds, min(2, len(seeds))):
                    contents.append({"role": "user", "parts": [{"text": "Create a high-reasoning example."}]})
                    contents.append({"role": "model", "parts": [{"text": json.dumps(seed)}]})
                contents.append({"role": "user", "parts": [{"text": prompt}]})
            else:
                contents = [
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": "You must strictly output raw JSON without markdown blocks."}
                ]
                for seed in random.sample(seeds, min(2, len(seeds))):
                    contents.append({"role": "user", "content": "Create a high-reasoning example."})
                    contents.append({"role": "assistant", "content": json.dumps(seed)})
                contents.append({"role": "user", "content": prompt})

            batch_start_time = time.time()
            try:
                if mode == "gemini":
                    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model_name}:streamGenerateContent?alt=sse&key={api_key}"
                    headers = {'Content-Type': 'application/json'}
                    payload = {
                        "contents": contents,
                        "systemInstruction": {"role": "user", "parts": [{"text": SYSTEM_PROMPT}]},
                        "generationConfig": {"temperature": 0.8}
                    }
                    response = requests.post(url, headers=headers, json=payload, stream=True, timeout=120)
                    if response.status_code != 200:
                        raise Exception(f"HTTP {response.status_code}: {response.text}")
                    
                    chunk_iterator = response.iter_lines()
                else:
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=contents,
                        temperature=0.8,
                        max_tokens=4000,
                        stop=["<|im_end|>", "<|endoftext|>"],
                        stream=True
                    )
                    chunk_iterator = response

                content = ""
                reported_count = 0
                batch_success_count = 0
                sample_start_time = time.time()
                
                import json_repair
                
                try:
                    for chunk in chunk_iterator:
                        chunk_text = ""
                        if mode == "gemini":
                            if chunk:
                                line = chunk.decode('utf-8')
                                if line.startswith("data: "):
                                    try:
                                        data_json = json.loads(line[6:])
                                        chunk_text = data_json['candidates'][0]['content']['parts'][0]['text']
                                    except:
                                        pass
                        else:
                            if chunk.choices and chunk.choices[0].delta.content:
                                chunk_text = chunk.choices[0].delta.content
                                
                        if chunk_text:
                            content += chunk_text
                            total_tokens_approx += len(chunk_text) // 4
                            
                            # Periodically try to extract finished examples from the streaming buffer
                            if "]" in chunk_text or "}" in chunk_text:
                                parsed = json_repair.loads(content)
                                if isinstance(parsed, dict) and 'messages' in parsed:
                                    parsed = parsed['messages']
                                    
                                if isinstance(parsed, list):
                                    # We only trust items BEFORE the last item as fully complete dynamically
                                    fully_completed_items = parsed[:-1]
                                    
                                    while reported_count < len(fully_completed_items) and successful < count:
                                        ex = fully_completed_items[reported_count]
                                        if isinstance(ex, list) and len(ex) > 2:
                                            dataset.append(ex)
                                            successful += 1
                                            batch_success_count += 1
                                            progress.update(task_id, advance=1)
                                            
                                            tool_count = sum(1 for msg in ex if isinstance(msg, dict) and msg.get("tool_calls"))
                                            response_count = sum(1 for msg in ex if isinstance(msg, dict) and msg.get("content") and msg.get("role") == "assistant" and not msg.get("tool_calls"))
                                            total_turns = len(ex)
                                            
                                            sample_chars = len(json.dumps(ex))
                                            sample_tokens = sample_chars // 4
                                            sample_time = time.time() - sample_start_time
                                            progress.console.print(
                                                f"[bold green]✅ Sample {successful}/{count}:[/bold green] "
                                                f"[cyan]{total_turns} messages[/cyan] ("
                                                f"[magenta]{tool_count} tool actions[/magenta], "
                                                f"[blue]{response_count} AI thoughts[/blue]) | "
                                                f"[yellow]~{sample_tokens} tokens[/yellow] | "
                                                f"[dim]{sample_time:.1f}s[/dim]"
                                            )
                                            # Write to file instantly!
                                            with open(output_file, "a", encoding="utf-8") as f:
                                                f.write(create_example(ex) + "\n")
                                                
                                            sample_start_time = time.time()
                                        reported_count += 1
                                        
                                        if successful >= count:
                                            break
                                            
                                # Early exit if the stream hallucinates past the required batch size seamlessly
                                if reported_count >= batch_size:
                                    break
                                        
                        if successful >= count:
                            break
                finally:
                    if mode == "openai":
                        response.close()
                    elif mode == "gemini":
                        response.close()

                # Process any remaining items (the very last item in the valid stream)
                parsed = json_repair.loads(content)
                if isinstance(parsed, dict) and 'messages' in parsed:
                    parsed = parsed['messages']
                if isinstance(parsed, list):
                    while reported_count < len(parsed) and successful < count:
                        ex = parsed[reported_count]
                        if isinstance(ex, list) and len(ex) > 2:
                            dataset.append(ex)
                            successful += 1
                            batch_success_count += 1
                            progress.update(task_id, advance=1)
                            
                            tool_count = sum(1 for msg in ex if isinstance(msg, dict) and msg.get("tool_calls"))
                            response_count = sum(1 for msg in ex if isinstance(msg, dict) and msg.get("content") and msg.get("role") == "assistant" and not msg.get("tool_calls"))
                            total_turns = len(ex)
                            
                            sample_chars = len(json.dumps(ex))
                            sample_tokens = sample_chars // 4
                            sample_time = time.time() - sample_start_time
                            progress.console.print(
                                f"[bold green]✅ Sample {successful}/{count}:[/bold green] "
                                f"[cyan]{total_turns} messages[/cyan] ("
                                f"[magenta]{tool_count} tool actions[/magenta], "
                                f"[blue]{response_count} AI thoughts[/blue]) | "
                                f"[yellow]~{sample_tokens} tokens[/yellow] | "
                                f"[dim]{sample_time:.1f}s[/dim]"
                            )
                            # Write to file instantly!
                            with open(output_file, "a", encoding="utf-8") as f:
                                f.write(create_example(ex) + "\n")
                                
                            sample_start_time = time.time()
                        reported_count += 1
                
                batch_elapsed = time.time() - batch_start_time
                logging.info(f"Batch completed in {batch_elapsed:.2f}s. New examples: {batch_success_count}")
                time.sleep(2)

            except KeyboardInterrupt:
                progress.console.print(f"\n[bold yellow]⚠️ Generation cancelled by user. Force exiting...[/bold yellow]")
                logging.warning("User triggered KeyboardInterrupt. Cancelling generation.")
                os._exit(1)
            except Exception as e:
                batch_elapsed = time.time() - batch_start_time
                err_msg = str(e)
            
                logging.error(f"API Batch failed after {batch_elapsed:.2f}s: {err_msg}")
            
                # Use strict markup=True only on the label, and inject the raw string bypassing rich parsing
                progress.console.print(f"[bold red]❌ Failed batch after {batch_elapsed:.1f}s:[/bold red] {err_msg}", markup=True)
                
                # Auto-terminate on fatal HTTP errors (Bad Request, Unauthorized, Forbidden, Not Found)
                if any(fatal_err in err_msg for fatal_err in ["HTTP 400", "HTTP 401", "HTTP 403", "HTTP 404"]):
                    progress.console.print(f"\n[bold red]🛑 Fatal API Configuration Error detected (e.g., Wrong Model Name, Invalid API Key). Terminating to prevent infinite wait loop.[/bold red]")
                    os._exit(1)
                    
                time.sleep(2)
            
    total_time = time.time() - start_time
    avg_speed = successful / total_time if total_time > 0 else 0
    avg_tokens = (total_tokens_approx / successful) if successful > 0 else 0
    
    print(f"\n{Fore.GREEN}{Style.BRIGHT}✅ API GENERATION COMPLETE!{Style.RESET_ALL}")
    table = [
        ["Total Generated", f"{successful} examples"],
        ["Target Goal", f"{count} examples"],
        ["Total Elapsed Time", f"{total_time:.2f} seconds"],
        ["Average Batch Speed", f"{avg_speed:.2f} examples/sec"],
        ["Approx Tokens Generated", f"~{total_tokens_approx} tokens"],
        ["Avg Tokens Per Example", f"~{int(avg_tokens)} tokens"],
        ["Detailed Logs", "generation.log"],
        ["Output File", "See CLI --out argument"]
    ]
    print(tabulate(table, tablefmt="fancy_grid"))
    logging.info(f"Generation Session Complete. Synthesized {successful} examples in {total_time:.2f}s.")
    
    return dataset

# ---------------------------------------------------------------------------
# 3. GENERATE VLM (Local Algorithmic Multimodal)
# ---------------------------------------------------------------------------
def generate_vlm_dataset(count):
    dataset = []
    print(f"\n{Fore.CYAN}{Style.BRIGHT}👁️ INITIALIZING VLM ALGORITHMIC SYNTHESIS{Style.RESET_ALL}")
    print(f"{Fore.WHITE}Target Generations: {count}{Style.RESET_ALL}\n")
    start_time = time.time()
    
    # 1. Vision Direct Click
    for i in range(count // 3):
        x, y = random.randint(100, 1920), random.randint(100, 1080)
        target = random.choice(["Login", "Submit", "Cancel", "Search icon", "Settings gear", "Windows Start button"])
        tid = f"call_{uuid.uuid4().hex[:8]}"
        
        dataset.append([sys_prompt(), user_with_image(f"Click the '{target}' button on this screen."), assistant_tool([call_tool(tid, "computer", {"action": "left_click", "coordinate": [x, y]})], f"Based on the screenshot, the '{target}' button is located at {x}, {y}. I will click it."), tool_result(tid, "Result: Clicked"), assistant_msg(f"I clicked the '{target}' button.")])
        if (i+1) % 100 == 0: print(f"{Fore.YELLOW}[Phase 1/3]{Style.RESET_ALL} 🖱️ Direct Click logic: {i+1}/{count//3} examples...")

    # 2. Vision + UI Tree Integration
    for i in range(count // 3):
        target = random.choice(["Archive", "Delete", "Forward", "Reply"])
        x, y = random.randint(100, 1920), random.randint(100, 1080)
        tid1, tid2 = f"call_{uuid.uuid4().hex[:8]}", f"call_{uuid.uuid4().hex[:8]}"
        
        dataset.append([sys_prompt(), user_with_image(f"Please hit the '{target}' button in the top right menu."), assistant_tool([call_tool(tid1, "read_screen_ui", {})], "I can see the menu in the screenshot, but I'll pull the accessibility tree to get the exact clickable coordinate."), tool_result_with_image(tid1, f"[M1] [1] Button \"{target}\" at ({x}, {y})"), assistant_tool([call_tool(tid2, "computer", {"action": "left_click", "coordinate": [x, y]})], "Found it."), tool_result(tid2, "Result: Clicked"), assistant_msg(f"Done.")])
        if (i+1) % 100 == 0: print(f"{Fore.YELLOW}[Phase 2/3]{Style.RESET_ALL} 🌳 UI Tree integration: {i+1}/{count//3} examples...")

    # 3. Vision Visual Feedback Loop
    remainder = count - (count // 3) * 2
    for i in range(remainder):
        target_app = random.choice(["Chrome", "Spotify", "Terminal", "VS Code"])
        tid1, tid2 = f"call_{uuid.uuid4().hex[:8]}", f"call_{uuid.uuid4().hex[:8]}"
        
        dataset.append([sys_prompt(), user(f"Open {target_app}"), assistant_tool([call_tool(tid1, "computer", {"action": "key", "text": "win"})], "Opening the start menu."), tool_result_with_image(tid1, "Result: Pressed 'win'"), assistant_tool([call_tool(tid2, "computer", {"action": "type", "text": target_app}), call_tool(f"call_{uuid.uuid4().hex[:8]}", "computer", {"action": "key", "text": "enter"})], f"I see the Start menu opened. Now typing '{target_app}' and hitting enter."), tool_result_with_image(tid2, "Result: Typed and Pressed enter"), assistant_msg(f"Based on the final screen, {target_app} has successfully launched.")])
        if (i+1) % 100 == 0: print(f"{Fore.YELLOW}[Phase 3/3]{Style.RESET_ALL} 🔄 Visual Feedback loop: {i+1}/{remainder} examples...")

    random.shuffle(dataset)
    total_time = time.time() - start_time
    
    print(f"\n{Fore.GREEN}{Style.BRIGHT}✅ VLM SYNTHESIS COMPLETE!{Style.RESET_ALL}")
    table = [
        ["Total Generated", f"{len(dataset)} examples"],
        ["Total Time", f"{total_time:.5f} seconds"],
        ["Algorithmic Speed", f"{len(dataset)/total_time:.2f} examples/sec"]
    ]
    print(tabulate(table, tablefmt="fancy_grid"))
    
    return dataset

# ---------------------------------------------------------------------------
# 4. DATASET NORMALIZATION (fix_jsonl logic)
# ---------------------------------------------------------------------------
def normalize_dataset(file_path):
    """Standardizes dataset to OpenAI schema and consistency."""
    import shutil
    
    if not os.path.exists(file_path):
        console.print(f"[bold red]Error:[/bold red] File not found: {file_path}")
        return False
        
    backup_path = f"{file_path}.bak"
    console.print(f"[yellow]Backing up {file_path} to {backup_path}...[/yellow]")
    shutil.copy2(file_path, backup_path)
    
    valid_lines = []
    console.print(f"[cyan]Normalizing {file_path}...[/cyan]")
    
    with open(file_path, 'r', encoding='utf-8') as f_in:
        for i, line in enumerate(f_in):
            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue
                
            # Standardize messages
            for msg in data.get("messages", []):
                if "tool_calls" in msg:
                    for tc in msg["tool_calls"]:
                        # Extract name and arguments
                        if "function" in tc:
                            name = tc["function"].get("name", "unknown")
                            args = tc["function"].get("arguments", "{}")
                        else:
                            name = tc.get("name", "unknown")
                            args = tc.get("arguments", "{}")
                        
                        if not isinstance(args, str):
                            args = json.dumps(args)
                            
                        tc_id = tc.get("id")
                        if not tc_id:
                            tc_id = f"call_{str(uuid.uuid4())[:8]}"
                        
                        # Replace with standard OpenAI format
                        tc.clear()
                        tc["id"] = tc_id
                        tc["type"] = "function"
                        tc["function"] = {
                            "name": name,
                            "arguments": args
                        }
                        
            valid_lines.append(json.dumps(data) + "\n")
    
    with open(file_path, 'w', encoding='utf-8') as f_out:
        f_out.writelines(valid_lines)
    
    console.print("[green]✅ Normalization complete.[/green]")
    
    try:
        from datasets import load_dataset
        ds = load_dataset("json", data_files=file_path, split="train")
        console.print(f"[green]✅ Successfully loaded {len(ds)} examples with datasets library![/green]")
        return True
    except Exception as e:
        console.print(f"[bold red]❌ Failed to verify with datasets library:[/bold red] {e}")
        return False

# ---------------------------------------------------------------------------
# MAIN CLI
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Unified Computer-Use Dataset & Environment Manager")
    parser.add_argument("mode", choices=["seeds", "api", "vlm", "normalize"], help="What action to perform")
    parser.add_argument("--out", default=os.path.join(BASE_DIR, "computer-use-finetuning", "scripts", "dataset.jsonl"), help="Output JSONL file path")
    parser.add_argument("--file", default="", help="File to normalize (if mode is 'normalize')")
    parser.add_argument("--count", type=int, default=1000, help="Number of examples (for api/vlm)")
    parser.add_argument("--api-key", default="", help="Gemini API Key (for api mode)")
    parser.add_argument("--api-base", default="", help="Local LLM Base URL (e.g., http://localhost:11434/v1 for Ollama)")
    parser.add_argument("--model", default="", help="Model name (e.g., qwen2.5, gemini-2.5-flash)")
    parser.add_argument("--batch-size", default=14, type=int, help="Number of examples per API call")
    
    args = parser.parse_args()

    if args.mode == "seeds":
        data = get_manual_seeds()
        with open(args.out, "a", encoding="utf-8") as f:
            for example in data:
                f.write(create_example(example) + "\n")
        console.print(f"[green]✅ Generated {len(data)} gold-standard seeds to {args.out}[/green]")
        # Auto-normalize
        normalize_dataset(args.out)
        
    elif args.mode == "api":
        generate_api_dataset(args.api_key, args.count, args.api_base, args.model, args.batch_size, args.out)
        # Auto-normalize after generation
        console.print("\n[yellow]Auto-normalizing generated dataset...[/yellow]")
        normalize_dataset(args.out)
        
    elif args.mode == "vlm":
        data = generate_vlm_dataset(args.count)
        with open(args.out, "a", encoding="utf-8") as f:
            for example in data:
                f.write(create_example(example) + "\n")
        console.print(f"[green]✅ Generated {len(data)} VLM-algorithmic examples to {args.out}[/green]")
        # Auto-normalize
        normalize_dataset(args.out)

    elif args.mode == "normalize":
        normalize_dataset(args.file or args.out)
