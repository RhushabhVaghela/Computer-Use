# Health Monitoring Guide

Enterprise-grade real-time health monitoring for the Computer-Use MCP Server.

---

## 🎯 Overview

The health monitoring system provides:
- **Real-time metrics**: CPU, memory, threads
- **Tool performance**: Success rates, execution times
- **Screenshot tracking**: Backend usage, capture performance
- **Error monitoring**: Rolling 1-hour window
- **Self-healing**: Actionable recommendations
- **API integration**: JSON endpoints for dashboards

---

## 📊 Health Status Levels

### 🟢 Healthy
- All systems operational
- Tool success rate > 95%
- Memory usage < 75%
- No critical errors

### 🟡 Degraded
- Minor issues detected
- Tool success rate 75-95%
- Memory usage 75-90%
- Elevated error rate (>20/hour)

### 🔴 Unhealthy
- Critical issues
- Tool success rate < 75%
- Memory usage > 90%
- Requires immediate attention

---

## 🔍 Monitoring APIs

### Python API

```python
from health_monitor import health_check_endpoint, get_health_monitor

# Get comprehensive health report
health = health_check_endpoint()

# Access individual metrics
print(f"Status: {health['status']}")
print(f"CPU: {health['system']['cpu_percent']:.1f}%")
print(f"Memory: {health['system']['memory_percent']:.1f}%")
print(f"Tool calls: {health['tools']['total_calls']}")
print(f"Success rate: {health['tools']['success_rate']*100:.1f}%")
print(f"Screenshot backend: {health['screenshots']['backend']}")
print(f"Recommendations: {health['recommendations']}")
```

### Monitoring Instance

```python
from health_monitor import get_health_monitor

monitor = get_health_monitor()
metrics = monitor.get_metrics()

# System metrics
print(f"CPU: {metrics.cpu_percent}%")
print(f"Memory: {metrics.memory_percent}%")
print(f"Process threads: {metrics.process_threads}")

# Tool metrics
print(f"Tool calls: {metrics.total_tool_calls}")
print(f"Success rate: {metrics.tool_success_rate*100}%")

# Screenshot metrics
print(f"Screenshot backend: {metrics.screenshot_backend}")
print(f"Avg capture time: {metrics.avg_screenshot_time_ms:.1f}ms")

# Get detailed breakdowns
tool_breakdown = monitor.get_tool_breakdown()
screenshot_breakdown = monitor.get_screenshot_breakdown()
```

---

## 📈 Health Endpoint Response Format

```json
{
  "status": "healthy",
  "uptime_seconds": 7234.5,
  "timestamp": 1720884825.123,
  
  "system": {
    "cpu_percent": 15.2,
    "memory_percent": 45.8,
    "memory_used_mb": 512.3,
    "memory_total_mb": 16384.0
  },
  
  "process": {
    "cpu_percent": 8.5,
    "memory_mb": 256.7,
    "threads": 12
  },
  
  "tools": {
    "total_calls": 1523,
    "successful_calls": 1503,
    "failed_calls": 20,
    "success_rate": 0.987,
    "errors_last_hour": 3
  },
  
  "screenshots": {
    "backend": "dxgi",
    "success_rate": 0.995,
    "avg_time_ms": 45.2,
    "backends": {
      "dxgi": 1450,
      "mss_gdi": 73
    }
  },
  
  "recent_errors": [
    "120s ago: computer - Screen capture timeout",
    "300s ago: bash - Command failed with exit code 1"
  ],
  
  "recommendations": []
}
```

---

## 🔧 Tool Breakdown

Get per-tool performance statistics:

```python
monitor = get_health_monitor()
breakdown = monitor.get_tool_breakdown()

for tool_name, stats in breakdown.items():
    print(f"{tool_name}:")
    print(f"  Calls: {stats['calls']}")
    print(f"  Success rate: {stats['success_rate']*100:.1f}%")
    print(f"  Avg time: {stats['avg_time_ms']:.1f}ms")
    print(f"  Last error: {stats['last_error']}")
```

**Example output:**
```
computer:
  Calls: 856
  Success rate: 98.5%
  Avg time: 234.5ms
  Last error: None

read_screen_ui:
  Calls: 412
  Success rate: 100.0%
  Avg time: 3456.2ms
  Last error: None

bash:
  Calls: 255
  Success rate: 96.1%
  Avg time: 189.3ms
  Last error: Command failed with exit code 1
```

---

## 🖥️ Screenshot Breakdown

Track screenshot backend performance:

```python
monitor = get_health_monitor()
screenshot_stats = monitor.get_screenshot_breakdown()

print(f"Total captures: {screenshot_stats['total_calls']}")
print(f"Success rate: {screenshot_stats['success_rate']*100:.1f}%")
print(f"Avg time: {screenshot_stats['avg_time_ms']:.1f}ms")
print(f"Backends used:")
for backend, count in screenshot_stats['backends'].items():
    print(f"  {backend}: {count}")
```

**Example:**
```
Total captures: 1523
Success rate: 99.5%
Avg time: 45.2ms
Backends used:
  dxgi: 1450
  mss_gdi: 73
```

---

## 🚨 Alerts & Recommendations

The system automatically generates recommendations based on health metrics.

### Common Recommendations

#### High Memory Usage
```
Warning: Memory usage at 82.3%. Monitor for memory leaks.
```
**Action:**
- Restart server if > 90%
- Reduce `MCP_AUTO_SCAN_MAX_ELEMENTS`
- Check for memory leaks in custom scripts

#### Low Tool Success Rate
```
Warning: Tool success rate at 73.2%. Check system state and dependencies.
```
**Action:**
- Review recent errors
- Verify `OI_PATH` is correct
- Check system resources

#### Screenshot Backend Issues
```
Warning: Screenshot success rate at 85.7%. Using backend: mss_gdi.
Consider installing dxcam for DXGI capture.
```
**Action:**
- Install dxcam: `pip install dxcam numpy`
- Set `SCREENSHOT_BACKEND=dxgi`
- Restart server

#### High Error Rate
```
Warning: 47 errors in the last hour. Review error logs for patterns.
```
**Action:**
- Check `logs/mcp_server.log`
- Review `recent_errors` in health endpoint
- Identify and fix root cause

#### Long Uptime
```
Info: Server uptime is 96.5 hours. Consider periodic restarts for optimal performance.
```
**Action:**
- Schedule weekly restarts
- Monitor memory trends
- Consider auto-restart on degraded health

---

## 📊 Integration Examples

### Grafana Dashboard

Export metrics to Prometheus:

```python
from prometheus_client import Counter, Histogram, Gauge, start_http_server
from health_monitor import get_health_monitor
import time

# Define metrics
tool_calls_total = Counter('mcp_tool_calls_total', 'Total tool calls', ['tool', 'status'])
tool_duration_seconds = Histogram('mcp_tool_duration_seconds', 'Tool execution time', ['tool'])
health_status = Gauge('mcp_health_status', 'Current health status')
memory_usage = Gauge('mcp_memory_usage_percent', 'Memory usage percentage')
screenshot_success_rate = Gauge('mcp_screenshot_success_rate', 'Screenshot success rate')

# Start Prometheus metrics server
start_http_server(9090)

monitor = get_health_monitor()

while True:
    metrics = monitor.get_metrics()
    
    # Update gauges
    health_status.set(1 if metrics.status == 'healthy' else (2 if metrics.status == 'degraded' else 3))
    memory_usage.set(metrics.memory_percent)
    screenshot_success_rate.set(metrics.screenshot_success_rate)
    
    time.sleep(15)
```

### Slack/Discord Alerts

```python
import requests
from health_monitor import get_health_monitor

def send_alert(message):
    """Send alert to Slack/Discord webhook."""
    webhook_url = "YOUR_WEBHOOK_URL"
    
    payload = {
        "text": f"🚨 Computer-Use MCP Alert\n{message}",
        "username": "Health Monitor",
        "icon_emoji": ":warning:"
    }
    
    requests.post(webhook_url, json=payload)

# Check health periodically
monitor = get_health_monitor()
metrics = monitor.get_metrics()

if metrics.status != "healthy":
    alert_msg = f"Status: {metrics.status}\n"
    alert_msg += f"Memory: {metrics.memory_percent:.1f}%\n"
    alert_msg += f"Tool success: {metrics.tool_success_rate*100:.1f}%\n"
    if metrics.recommendations:
        alert_msg += f"Recommendations: {', '.join(metrics.recommendations)}"
    
    send_alert(alert_msg)
```

### Auto-Restart on Unhealthy

```python
import subprocess
import time
from health_monitor import get_health_monitor

def auto_restart_on_unhealthy(check_interval=300, consecutive_failures=3):
    """Auto-restart server if unhealthy for consecutive checks."""
    monitor = get_health_monitor()
    failure_count = 0
    
    while True:
        metrics = monitor.get_metrics()
        
        if metrics.status == "unhealthy":
            failure_count += 1
            print(f"Unhealthy check #{failure_count}")
            
            if failure_count >= consecutive_failures:
                print("Auto-restarting server...")
                subprocess.run(["taskkill", "/f", "/im", "python.exe"])
                time.sleep(5)
                subprocess.run(["start.bat"])  # Your startup script
                failure_count = 0
        else:
            failure_count = 0
        
        time.sleep(check_interval)
```

---

## 🏃 Background Monitoring

Enable background health monitoring thread:

```python
from health_monitor import get_health_monitor

monitor = get_health_monitor()

# Start background monitoring (checks every 60 seconds)
monitor.start_background_monitoring(interval_seconds=60)

# Server continues running...
# Health warnings will be logged automatically

# To stop monitoring:
# monitor.stop_background_monitoring()
```

**Log output example:**
```
[health_monitor] Health status: degraded. Recommendations: ['Warning: Memory usage at 78.5%. Monitor for memory leaks.']
```

---

## 📊 Performance Impact

Health monitoring has minimal overhead:

| Feature | CPU Overhead | Memory Overhead |
|---------|--------------|-----------------|
| Basic metrics | < 0.5% | ~1 MB |
| Background thread | < 1% | ~2 MB |
| Full monitoring | 1-2% | ~3 MB |

**Recommendation:** Keep enabled in production - the insights are worth the minimal overhead.

---

## 🔍 Troubleshooting

### Metrics Not Updating

**Check:**
1. Ensure `HEALTH_MONITOR_ENABLED=true` in `.env`
2. Verify psutil is installed: `pip install psutil`
3. Check monitor instance is being retrieved: `get_health_monitor()`

### High Memory Reported

**Verify:**
```python
import psutil
proc = psutil.Process()
print(f"Memory: {proc.memory_info().rss / 1024 / 1024:.1f}MB")
```

If actual memory is lower than reported, restart the monitoring thread.

### Missing Tool Statistics

**Ensure:** Tools are being recorded:
```python
from health_monitor import get_health_monitor

monitor = get_health_monitor()
monitor.record_tool_call('my_tool', 100.0, True)
```

---

## 📖 Related Documentation

- [README.md](../README.md) - Quick start
- [CONFIGURATION.md](CONFIGURATION.md) - All environment variables
- [TROUBLESHOOTING.md](TROUBLESHOOTING.md) - Common issues
- [ULTIMATE_FEATURES.md](../ULTIMATE_FEATURES.md) - Complete feature list

---

**Last Updated:** 2026-07-13  
**Status:** Production Ready ✅