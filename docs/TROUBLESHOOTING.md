# Troubleshooting Guide

Common issues and solutions for the Computer-Use MCP Server.

---

## 🖥️ Screenshot Issues

### BitBlt Error: "Windows graphics function failed"

**Symptom:**
```
ERROR: Windows graphics function failed (no error provided): BitBlt
```

**Cause:**
Windows GDI capture failing due to:
- RDP session limitations
- Graphics context stale
- Running in VM without proper drivers
- DPI awareness issues

**Solutions:**

#### 1. Install DirectX Capture (RECOMMENDED)
```bash
pip install dxcam numpy
```

This enables DXGI backend which works in RDP/VMs.

#### 2. Set Backend to DXGI
```env
SCREENSHOT_BACKEND=dxgi
```

#### 3. Restart the Server
Graphics context may be stale. Restart clears it.

#### 4. Check DPI Awareness
The server should be DPI-aware by default. If issues persist:
```python
import ctypes
ctypes.windll.shcore.SetProcessDpiAwareness(2)
```

#### 5. Use PIL Fallback
```env
SCREENSHOT_BACKEND=pil_grab
```

Slower but more compatible.

---

### Slow Screenshot Capture (>200ms)

**Symptom:**
Screenshots taking >200ms consistently

**Solutions:**

#### 1. Enable Caching
```env
SCREENSHOT_CACHE_ENABLED=true
SCREENSHOT_CACHE_TTL=0.1
```

Prevents redundant captures within 100ms window.

#### 2. Install DXGI
```bash
pip install dxcam numpy
```

DXGI is 40-60ms vs MSS 80-120ms.

#### 3. Reduce Resolution
```env
MCP_MAX_SCREENSHOT_WIDTH=1024
MCP_MAX_SCREENSHOT_HEIGHT=768
```

Smaller screenshots = faster capture + resize.

#### 4. Check System Load
High CPU usage can slow capture. Monitor with:
```python
from health_monitor import health_check_endpoint
health = health_check_endpoint()
print(f"CPU: {health['system']['cpu_percent']}%")
```

---

### Screenshots Not Capturing Full Desktop

**Symptom:**
Partial screen or wrong monitor captured

**Cause:**
Multi-monitor configuration not handled correctly.

**Solution:**

The server captures the virtual desktop (all monitors) by default. Check:

1. **Monitor Detection:**
```python
import mss
with mss.MSS() as sct:
    print(f"Monitors: {len(sct.monitors)}")
    for i, mon in enumerate(sct.monitors):
        print(f"  {i}: {mon['width']}x{mon['height']}")
```

2. **Capture Scope:**
```env
MCP_CAPTURE_SCOPE=virtual  # or 'primary' or 'all'
```

3. **Multi-Monitor Coordinates:**
Ensure `set_monitor_size()` includes left/top offset:
```python
computer_tool.set_monitor_size(width, height, left=monitor_left, top=monitor_top)
```

---

## 🔧 Tool Execution Failures

### Tool Success Rate < 80%

**Symptom:**
```json
{
  "tools": {
    "success_rate": 0.73
  }
}
```

**Diagnosis:**

1. **Check Error Logs:**
```python
from health_monitor import health_check_endpoint
health = health_check_endpoint()
print(f"Errors last hour: {health['tools']['errors_last_hour']}")
print(f"Recent errors: {health['recent_errors']}")
```

2. **Review Server Logs:**
```bash
cat logs/mcp_server.log | tail -50
```

3. **Breakdown by Tool:**
```python
monitor = get_health_monitor()
breakdown = monitor.get_tool_breakdown()
for tool, stats in breakdown.items():
    print(f"{tool}: {stats['success_rate']*100:.1f}%")
```

**Solutions:**

#### Computer Tool Failing
- Verify screen capture works
- Check UI scanning isn't timing out
- Reduce `MCP_AUTO_SCAN_MAX_ELEMENTS`

#### Bash Tool Failing
- Check command sandboxing
- Verify `ALLOW_UNSAFE_COMMANDS` setting
- Test commands manually first

#### Browser Tools Failing
- Verify browser is running with `--remote-debugging-port=9222`
- Check `BROWSER_CDP_PORT` matches
- Restart browser with clean profile

---

### UI Scanning Timeout

**Symptom:**
```
Tool 'read_screen_ui' exceeded timeout of 60s
```

**Solutions:**

#### 1. Reduce Max Elements
```env
MCP_AUTO_SCAN_MAX_ELEMENTS=40
```

#### 2. Increase Timeout
```env
MCP_TOOL_TIMEOUT=120000  # 120 seconds
```

#### 3. Disable Auto-Scan
```env
MCP_AUTO_SCAN_ON_CHANGE=0
```

#### 4. Check Active Window
Too many background windows being scanned. Close unnecessary apps.

#### 5. Browser Deep Scan
If scanning browser DOM, reduce depth:
```env
MCP_UI_SCAN_BROWSER_MAX_DEPTH=2
```

---

## 💾 Memory Issues

### Memory Usage > 90%

**Symptom:**
```json
{
  "status": "unhealthy",
  "system": {
    "memory_percent": 92.3
  }
}
```

**Immediate Action:**
Restart the server.

**Long-term Solutions:**

#### 1. Reduce Element Limit
```env
MCP_AUTO_SCAN_MAX_ELEMENTS=30
```

Fewer UI elements cached = less memory.

#### 2. Disable Auto-Scan-Always
```env
MCP_AUTO_SCAN_ALWAYS=0
```

Only scan on screen changes.

#### 3. Check for Memory Leaks
```python
import psutil
import time

proc = psutil.Process()
for _ in range(10):
    mem = proc.memory_info().rss / 1024 / 1024
    print(f"Memory: {mem:.1f}MB")
    time.sleep(60)
```

If steadily increasing, you have a leak.

#### 4. Schedule Restarts
Use a cron job or scheduled task:
```bash
# Windows Task Scheduler
schtasks /create /tn "Restart MCP" /tr "restart_mcp.bat" /sc daily /st 03:00
```

---

## 🔐 Security Issues

### Commands Blocked

**Symptom:**
```
ERROR: Command blocked by security policy: matched denylist pattern 'rm -rf'
```

**Solutions:**

#### 1. Check If Command Should Be Allowed
Review `COMMAND_DENYLIST` in `src/config.py`.

#### 2. Override (TRUSTED ENVIRONMENTS ONLY)
```env
ALLOW_UNSAFE_COMMANDS=true
```

**⚠️ Warning:** Only in isolated/VM environments!

#### 3. Use Alternative Approach
Instead of `rm -rf /tmp/*`:
```bash
# Safer alternative
for file in /tmp/*; do rm "$file"; done
```

---

### Rate Limit Exceeded

**Symptom:**
```
ERROR: Computer action rate limit exceeded (60 actions per minute)
```

**Solutions:**

#### 1. Increase Limit
```env
COMPUTER_ACTION_RATE_LIMIT=120
```

#### 2. Disable Limit (Trusted Only)
```env
COMPUTER_ACTION_RATE_LIMIT=0
```

#### 3. Code Review
Check your automation loop - 60/minute should be plenty. Add delays between actions.

---

## 🌐 Browser Issues

### Browser Not Detected

**Symptom:**
```
Error: No active browser context found on port 9222
```

**Solutions:**

#### 1. Launch Browser with CDP
```bash
# Chrome
chrome --remote-debugging-port=9222

# Edge
msedge --remote-debugging-port=9222
```

#### 2. Verify Port
Check `BROWSER_CDP_PORT` in `.env` matches browser port.

#### 3. Use browser_action Tool
```python
browser_action(search_query="test")
```

Opens a new isolated browser session.

#### 4. Check for Multiple Instances
Only one browser per profile. Close others or use isolated sessions.

---

### DOM Extraction Fails

**Symptom:**
```
Error connecting to browser: Connection refused
```

**Solutions:**

#### 1. Verify Browser Running
```python
import requests
try:
    resp = requests.get("http://localhost:9222/json/version", timeout=5)
    print(f"Browser: {resp.json()['Browser']}")
except:
    print("Not running or not accessible")
```

#### 2. Use Hybrid Mode
`src/hybrid_server.py` has better browser support than standard mode.

#### 3. Check Firewall
Port 9222 may be blocked. Allow it:
```bash
# Windows
netsh advfirewall firewall add rule name="CDP" dir=in action=allow protocol=TCP localport=9222
```

---

## 🎤 Voice Pipeline Issues

### ASR Not Working

**Symptom:**
Voice transcription fails or returns empty

**Solutions:**

#### 1. Check Microphone Access
```python
import sounddevice as sd
print(sd.query_devices())
```

Ensure default input device exists.

#### 2. Verify ASR Engine
```env
ASR_ENGINE=whisper_turbo
```

#### 3. Install Dependencies
```bash
pip install faster-whisper torch
```

#### 4. Test ASR Directly
```python
from faster_whisper import WhisperModel
model = WhisperModel("base")
segments, info = model.transcribe("test.wav")
for segment in segments:
    print(segment.text)
```

---

### TTS Not Working

**Symptom:**
Text-to-speech fails or silent

**Solutions:**

#### 1. Check TTS Engine
```env
TTS_ENGINE=higgs
```

#### 2. Verify Audio Output
```python
import sounddevice as sd
print(sd.query_devices())
```

#### 3. Test TTS Directly
Depends on engine. For Kokoro:
```python
from kokoro import generate
audio = generate("Hello world", voice='default')
```

---

## 🚀 Startup Issues

### Server Won't Start

**Symptom:**
Server exits immediately with error

**Common Causes:**

#### 1. Invalid OI_PATH
```
ERROR: OI_PATH directory does not exist: D:/wrong/path
```
**Fix:** Set correct path in `.env`

#### 2. Missing Interpreter Module
```
ERROR: 'interpreter' module not found in OI_PATH
```
**Fix:** Ensure OI_PATH points to Open Interpreter root.

#### 3. Port Already in Use
```
ERROR: Address already in use
```
**Fix:** Change port:
```env
PORT=8001
```

#### 4. Import Errors
```
ModuleNotFoundError: No module named 'xxx'
```
**Fix:** Install missing dependencies:
```bash
.venv\Scripts\activate
pip install -r requirements.txt
```

---

## 📊 Health Monitoring Issues

### Metrics Not Updating

**Symptom:**
Health endpoint returns stale data

**Solutions:**

#### 1. Verify psutil Installed
```bash
pip install psutil
```

#### 2. Check Health Monitor Enabled
```env
HEALTH_MONITOR_ENABLED=true
```

#### 3. Test Manually
```python
from health_monitor import get_health_monitor
monitor = get_health_monitor()
metrics = monitor.get_metrics()
print(f"CPU: {metrics.cpu_percent}%")
```

---

## 🐛 Known Issues

### BitBlt in RDP Sessions

**Issue:** MSS GDI capture fails in RDP  
**Status:** Expected behavior  
**Workaround:** Install `dxcam` for DXGI support

### Memory Leak After 72+ Hours

**Issue:** Gradual memory increase over days  
**Status:** Under investigation (likely OI dependency)  
**Workaround:** Schedule weekly restarts

### Coordinate Mapping in Multi-Monitor

**Issue:** Off-by-monitor-offset in coordinates  
**Status:** Partially fixed, edge cases remain  
**Workaround:** Use single monitor or ensure `set_monitor_size(left,top)` is called

---

## 📞 Getting Help

### Before Asking for Help

1. **Check Logs:**
   ```bash
   tail -100 logs/mcp_server.log
   ```

2. **Run Health Check:**
   ```python
   from health_monitor import health_check_endpoint
   print(health_check_endpoint())
   ```

3. **Run Tests:**
   ```bash
   pytest tests/ -v
   ```

4. **System Information:**
   ```python
   import platform
   import psutil
   print(f"OS: {platform.platform()}")
   print(f"CPU: {psutil.cpu_percent()}%")
   print(f"Memory: {psutil.virtual_memory().percent}%")
   ```

### Information to Include

When filing an issue, include:
- OS and Python version
- Server logs (last 100 lines)
- Health check JSON
- Steps to reproduce
- Expected vs actual behavior

---

## 🔗 Related Documentation

- [README.md](../README.md) - Quick start
- [CONFIGURATION.md](CONFIGURATION.md) - All settings
- [HEALTH_MONITORING.md](HEALTH_MONITORING.md) - Monitoring guide
- [ULTIMATE_FEATURES.md](../ULTIMATE_FEATURES.md) - Feature list

---

**Last Updated:** 2026-07-13  
**Status:** Production Ready ✅