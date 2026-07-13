"""
Health Check & Monitoring System for MCP Server.

Provides:
- System health metrics (CPU, memory, GPU)
- Tool execution statistics
- Performance monitoring
- Error tracking
- Self-healing recommendations
"""

import os
import sys
import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, Dict, List
from collections import defaultdict
import asyncio

logger = logging.getLogger("health_monitor")


@dataclass
class HealthMetrics:
    """Current system health metrics."""
    # System
    cpu_percent: float = 0.0
    memory_percent: float = 0.0
    memory_used_mb: float = 0.0
    memory_total_mb: float = 0.0
    
    # Process
    process_cpu_percent: float = 0.0
    process_memory_mb: float = 0.0
    process_threads: int = 0
    
    # Screenshots
    screenshot_backend: str = "unknown"
    last_screenshot_time: float = 0.0
    screenshot_success_rate: float = 1.0
    avg_screenshot_time_ms: float = 0.0
    
    # Tools
    total_tool_calls: int = 0
    successful_tool_calls: int = 0
    failed_tool_calls: int = 0
    tool_success_rate: float = 1.0
    
    # Errors
    recent_errors: List[str] = field(default_factory=list)
    error_count_last_hour: int = 0
    
    # Uptime
    uptime_seconds: float = 0.0
    start_time: float = field(default_factory=time.time)
    
    # Status
    status: str = "healthy"  # healthy, degraded, unhealthy
    recommendations: List[str] = field(default_factory=list)


class HealthMonitor:
    """
    Real-time health monitoring for the MCP server.
    
    Tracks system resources, tool performance, and provides
    self-healing recommendations.
    """
    
    def __init__(self):
        self._start_time = time.time()
        self._metrics = HealthMetrics(start_time=self._start_time)
        self._tool_stats: Dict[str, Dict] = defaultdict(lambda: {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "total_time_ms": 0.0,
            "last_error": None,
        })
        self._screenshot_stats = {
            "calls": 0,
            "successes": 0,
            "failures": 0,
            "total_time_ms": 0.0,
            "backend_counts": defaultdict(int),
        }
        self._error_log: List[tuple] = []  # (timestamp, tool_name, error_msg)
        self._lock = threading.Lock()
        self._monitoring = False
        self._monitor_thread: Optional[threading.Thread] = None
        
    def record_tool_call(self, tool_name: str, duration_ms: float, success: bool, error: str = None):
        """Record a tool execution."""
        with self._lock:
            stats = self._tool_stats[tool_name]
            stats["calls"] += 1
            stats["total_time_ms"] += duration_ms
            
            if success:
                stats["successes"] += 1
            else:
                stats["failures"] += 1
                stats["last_error"] = error
                self._error_log.append((time.time(), tool_name, error))
                
                # Keep error log bounded
                if len(self._error_log) > 1000:
                    self._error_log = self._error_log[-500:]
    
    def record_screenshot(self, duration_ms: float, success: bool, backend: str):
        """Record a screenshot capture."""
        with self._lock:
            self._screenshot_stats["calls"] += 1
            self._screenshot_stats["total_time_ms"] += duration_ms
            
            if success:
                self._screenshot_stats["successes"] += 1
            else:
                self._screenshot_stats["failures"] += 1
            
            self._screenshot_stats["backend_counts"][backend] += 1
            
            # Update last screenshot time
            self._metrics.last_screenshot_time = time.time()
    
    def get_metrics(self) -> HealthMetrics:
        """Get current health metrics."""
        with self._lock:
            self._update_system_metrics()
            self._update_tool_metrics()
            self._update_screenshot_metrics()
            self._compute_health_status()
            
            return self._metrics
    
    def _update_system_metrics(self):
        """Update system resource metrics."""
        try:
            import psutil
            
            # System-wide
            self._metrics.cpu_percent = psutil.cpu_percent(interval=0.1)
            self._metrics.memory_percent = psutil.virtual_memory().percent
            self._metrics.memory_used_mb = psutil.virtual_memory().used / 1024 / 1024
            self._metrics.memory_total_mb = psutil.virtual_memory().total / 1024 / 1024
            
            # Process-specific
            proc = psutil.Process(os.getpid())
            self._metrics.process_cpu_percent = proc.cpu_percent(interval=0.1)
            self._metrics.process_memory_mb = proc.memory_info().rss / 1024 / 1024
            self._metrics.process_threads = proc.num_threads()
            
        except ImportError:
            logger.debug("psutil not installed, skipping system metrics")
        except Exception as e:
            logger.debug(f"Failed to get system metrics: {e}")
    
    def _update_tool_metrics(self):
        """Update tool execution metrics."""
        total_calls = sum(s["calls"] for s in self._tool_stats.values())
        total_successes = sum(s["successes"] for s in self._tool_stats.values())
        total_failures = sum(s["failures"] for s in self._tool_stats.values())
        
        self._metrics.total_tool_calls = total_calls
        self._metrics.successful_tool_calls = total_successes
        self._metrics.failed_tool_calls = total_failures
        
        if total_calls > 0:
            self._metrics.tool_success_rate = total_successes / total_calls
        
        # Count recent errors (last hour)
        now = time.time()
        hour_ago = now - 3600
        recent_errors = [e for e in self._error_log if e[0] > hour_ago]
        self._metrics.error_count_last_hour = len(recent_errors)
        
        # Store last few error messages
        self._metrics.recent_errors = [
            f"{t:.0f}s ago: {tool} - {err[:200]}"
            for t, tool, err in self._error_log[-5:]
        ]
    
    def _update_screenshot_metrics(self):
        """Update screenshot capture metrics."""
        calls = self._screenshot_stats["calls"]
        successes = self._screenshot_stats["successes"]
        
        if calls > 0:
            self._metrics.screenshot_success_rate = successes / calls
            self._metrics.avg_screenshot_time_ms = (
                self._screenshot_stats["total_time_ms"] / calls
            )
        
        # Get primary backend
        if self._screenshot_stats["backend_counts"]:
            primary_backend = max(
                self._screenshot_stats["backend_counts"].items(),
                key=lambda x: x[1]
            )[0]
            self._metrics.screenshot_backend = primary_backend
    
    def _compute_health_status(self):
        """Compute overall health status and recommendations."""
        recommendations = []
        status = "healthy"
        
        # Check memory usage
        if self._metrics.memory_percent > 90:
            status = "unhealthy"
            recommendations.append(
                f"Critical: Memory usage at {self._metrics.memory_percent:.1f}%. "
                "Consider restarting the server."
            )
        elif self._metrics.memory_percent > 75:
            status = "degraded"
            recommendations.append(
                f"Warning: Memory usage at {self._metrics.memory_percent:.1f}%. "
                "Monitor for memory leaks."
            )
        
        # Check tool failure rate
        if self._metrics.tool_success_rate < 0.5 and self._metrics.total_tool_calls > 10:
            status = "unhealthy"
            recommendations.append(
                f"Critical: Tool success rate at {self._metrics.tool_success_rate*100:.1f}%. "
                "Check system state and dependencies."
            )
        elif self._metrics.tool_success_rate < 0.8 and self._metrics.total_tool_calls > 10:
            status = "degraded"
            recommendations.append(
                f"Warning: Tool success rate at {self._metrics.tool_success_rate*100:.1f}%. "
                "Recent errors may indicate issues."
            )
        
        # Check screenshot failure rate
        if (self._metrics.screenshot_success_rate < 0.5 and 
            self._screenshot_stats["calls"] > 5):
            status = "degraded"
            recommendations.append(
                f"Warning: Screenshot success rate at {self._metrics.screenshot_success_rate*100:.1f}%. "
                f"Using backend: {self._metrics.screenshot_backend}. "
                "Consider installing dxcam for DXGI capture."
            )
        
        # Check error rate
        if self._metrics.error_count_last_hour > 20:
            status = "degraded"
            recommendations.append(
                f"Warning: {self._metrics.error_count_last_hour} errors in the last hour. "
                "Review error logs for patterns."
            )
        
        # Check uptime (suggest restart if very long)
        uptime_hours = self._metrics.uptime_seconds / 3600
        if uptime_hours > 72:
            recommendations.append(
                f"Info: Server uptime is {uptime_hours:.1f} hours. "
                "Consider periodic restarts for optimal performance."
            )
        
        self._metrics.status = status
        self._metrics.recommendations = recommendations
        self._metrics.uptime_seconds = time.time() - self._start_time
    
    def get_tool_breakdown(self) -> dict:
        """Get detailed breakdown of tool performance."""
        with self._lock:
            breakdown = {}
            for tool_name, stats in self._tool_stats.items():
                calls = stats["calls"]
                avg_time = stats["total_time_ms"] / calls if calls > 0 else 0
                success_rate = stats["successes"] / calls if calls > 0 else 0
                
                breakdown[tool_name] = {
                    "calls": calls,
                    "success_rate": success_rate,
                    "avg_time_ms": avg_time,
                    "last_error": stats["last_error"],
                }
            return breakdown
    
    def get_screenshot_breakdown(self) -> dict:
        """Get detailed breakdown of screenshot backends used."""
        with self._lock:
            return {
                "total_calls": self._screenshot_stats["calls"],
                "success_rate": (
                    self._screenshot_stats["successes"] / self._screenshot_stats["calls"]
                    if self._screenshot_stats["calls"] > 0 else 0
                ),
                "avg_time_ms": (
                    self._screenshot_stats["total_time_ms"] / self._screenshot_stats["calls"]
                    if self._screenshot_stats["calls"] > 0 else 0
                ),
                "backends": dict(self._screenshot_stats["backend_counts"]),
            }
    
    def start_background_monitoring(self, interval_seconds: int = 60):
        """Start background health monitoring thread."""
        if self._monitoring:
            return
        
        self._monitoring = True
        
        def monitor_loop():
            while self._monitoring:
                try:
                    metrics = self.get_metrics()
                    if metrics.status != "healthy":
                        logger.warning(
                            f"Health status: {metrics.status}. "
                            f"Recommendations: {metrics.recommendations}"
                        )
                except Exception as e:
                    logger.error(f"Monitoring error: {e}")
                
                time.sleep(interval_seconds)
        
        self._monitor_thread = threading.Thread(
            target=monitor_loop,
            daemon=True,
            name="health_monitor"
        )
        self._monitor_thread.start()
        logger.info(f"Health monitoring started (interval={interval_seconds}s)")
    
    def stop_background_monitoring(self):
        """Stop background monitoring."""
        self._monitoring = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5)
            self._monitor_thread = None
        logger.info("Health monitoring stopped")


# Global instance
_health_monitor: Optional[HealthMonitor] = None
_monitor_lock = threading.Lock()


def get_health_monitor() -> HealthMonitor:
    """Get or create global health monitor instance."""
    global _health_monitor
    
    with _monitor_lock:
        if _health_monitor is None:
            _health_monitor = HealthMonitor()
        return _health_monitor


def health_check_endpoint() -> dict:
    """
    Get health check data for API endpoint.
    
    Returns comprehensive health report.
    """
    monitor = get_health_monitor()
    metrics = monitor.get_metrics()
    
    return {
        "status": metrics.status,
        "uptime_seconds": metrics.uptime_seconds,
        "system": {
            "cpu_percent": metrics.cpu_percent,
            "memory_percent": metrics.memory_percent,
            "memory_used_mb": metrics.memory_used_mb,
        },
        "process": {
            "cpu_percent": metrics.process_cpu_percent,
            "memory_mb": metrics.process_memory_mb,
            "threads": metrics.process_threads,
        },
        "tools": {
            "total_calls": metrics.total_tool_calls,
            "success_rate": metrics.tool_success_rate,
            "errors_last_hour": metrics.error_count_last_hour,
        },
        "screenshots": {
            "backend": metrics.screenshot_backend,
            "success_rate": metrics.screenshot_success_rate,
            "avg_time_ms": metrics.avg_screenshot_time_ms,
        },
        "recommendations": metrics.recommendations,
        "timestamp": time.time(),
    }