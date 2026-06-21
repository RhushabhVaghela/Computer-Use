"""
Configuration management for Computer-Use MCP Server.

All environment variables are validated and typed here.
Uses pydantic-settings for dotenv loading and validation.
"""

import os
import sys
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings


# ==========================================
# Command Denylist for Bash Tool Sandboxing (C2)
# ==========================================

COMMAND_DENYLIST: list[str] = [
    # Unix/Linux/macOS Destructive
    "rm -rf /",
    "rm -rf /*",
    "rm -rf ~",
    "rm -rf .*",
    "mkfs",
    "dd if=",
    "chmod 777 /",
    "chown -R",
    
    # Windows Destructive (CMD & PowerShell)
    "del /f /s /q C:\\",
    "rd /s /q C:\\",
    "format",
    "Remove-Item -Recurse -Force C:\\",
    "Clear-RecycleBin",
    
    # System Control (Cross-OS)
    "shutdown",
    "reboot",
    "halt",
    "init 0",
    "init 6",
    "poweroff",
    "Stop-Computer",
    "Restart-Computer",
    
    # Fork Bombs & Malicious Payloads
    ":(){ :|:& };:",
    "%0|%0",
    "Invoke-Expression",
    "iex",
    
    # User / Privilege Management
    "net user",
    "usermod",
    "visudo",
]


class ServerConfig(BaseSettings):
    """Server configuration with validation."""
    
    # REQUIRED: Open Interpreter Path
    oi_path: Optional[str] = Field(
        default=None,
        description="Path to open-interpreter clone. Can be overridden per-platform."
    )
    oi_path_win: Optional[str] = Field(
        default=None,
        description="Windows-specific override for OI_PATH"
    )
    oi_path_linux: Optional[str] = Field(
        default=None,
        description="Linux-specific override for OI_PATH"
    )
    
    # Server Configuration
    host: str = Field(default="0.0.0.0", description="Server bind host")
    port: int = Field(default=8000, ge=1, le=65535, description="Server port")
    
    # Tool Configuration
    mcp_tool_timeout: int = Field(
        default=60000, 
        ge=1000, 
        description="Tool timeout in milliseconds"
    )
    
    # Screenshot Configuration
    mcp_screenshot_scaling: bool = Field(
        default=True,
        description="Enable screenshot scaling"
    )
    mcp_max_screenshot_width: int = Field(
        default=1366,
        ge=640,
        le=4096,
        description="Max width for scaled screenshots"
    )
    mcp_max_screenshot_height: int = Field(
        default=768,
        ge=480,
        le=2160,
        description="Max height for scaled screenshots"
    )
    mcp_capture_scope: str = Field(
        default="primary",
        description="Capture scope: primary|virtual|all"
    )
    mcp_coordinate_grid: int = Field(
        default=0,
        ge=0,
        description="Fixed coordinate grid size (0=disabled)"
    )
    
    # UI Scanning
    mcp_auto_scan_always: bool = Field(
        default=False,
        description="Scan after every action (slower but more reliable)"
    )
    mcp_auto_scan_on_change: bool = Field(
        default=True,
        description="Scan when screen changes"
    )
    mcp_auto_scan_max_elements: int = Field(
        default=60,
        ge=10,
        le=500,
        description="Max UI elements to return"
    )
    mcp_ui_scan_browser_element_limit: int = Field(
        default=80,
        ge=10,
        le=500,
        description="Browser element cap"
    )
    mcp_ui_scan_browser_max_depth: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Browser scan depth"
    )
    mcp_ui_scan_browser_active_only: bool = Field(
        default=True,
        description="Restrict browser scan to active window"
    )
    
    # Input/Overlay Tuning
    mcp_move_duration_ms: int = Field(
        default=150,
        ge=50,
        le=1000,
        description="Smooth mouse move duration in ms"
    )
    mcp_overlay_min_hold_ms: int = Field(
        default=450,
        ge=100,
        le=2000,
        description="Min time to hold overlay text"
    )
    mcp_overlay_fade_ms: int = Field(
        default=260,
        ge=50,
        le=1000,
        description="Overlay fade-in duration"
    )
    mcp_type_interval_sec: float = Field(
        default=0.02,
        ge=0.001,
        le=0.5,
        description="Per-character typing interval"
    )
    
    # Browser Configuration
    browser_cdp_port: int = Field(
        default=9222,
        ge=1024,
        le=65535,
        description="Chrome DevTools Protocol port"
    )
    
    # Hybrid Mode (Browser-Use)
    browser_use_python: Optional[str] = Field(
        default=None,
        description="Override Python executable for browser-use"
    )
    browser_use_headless: bool = Field(
        default=False,
        description="Run browser-use in headless mode"
    )
    hybrid_debug: bool = Field(
        default=False,
        description="Enable hybrid mode debug logging"
    )
    hybrid_bu_start_timeout_s: float = Field(
        default=25.0,
        ge=5.0,
        le=120.0,
        description="Browser-use startup timeout in seconds"
    )
    hybrid_bu_call_timeout_s: float = Field(
        default=25.0,
        ge=5.0,
        le=120.0,
        description="Browser-use call timeout in seconds"
    )
    hybrid_bu_errlog_path: Optional[str] = Field(
        default=None,
        description="Path to browser-use error log"
    )
    
    # Voice Server (Optional)
    voice_screen_w: Optional[int] = Field(
        default=None,
        ge=640,
        le=4096,
        description="Override screen width for voice server"
    )
    voice_screen_h: Optional[int] = Field(
        default=None,
        ge=480,
        le=2160,
        description="Override screen height for voice server"
    )
    
    # PersonaPlex (Moshi) Unified Voice Pipeline Settings
    personaplex_mode: str = Field(
        default="websocket",
        description="PersonaPlex integration mode: websocket|subprocess"
    )
    personaplex_url: str = Field(
        default="ws://localhost:8998/api/chat",
        description="WebSocket URL for PersonaPlex server (Moshi server)"
    )
    personaplex_binary: str = Field(
        default="moshi-sts.exe",
        description="Path to local moshi-sts executable (for subprocess mode)"
    )
    personaplex_model_path: str = Field(
        default="models/personaplex-7b-v1-q4_k.gguf",
        description="Path to the GGUF model file"
    )
    personaplex_prompt: str = Field(
        default="You enjoy having a good conversation.",
        description="System prompt for PersonaPlex model"
    )
    personaplex_temperature: float = Field(
        default=0.7,
        description="Temperature for PersonaPlex model generation"
    )
    
    # Browser-Use Logging
    browser_use_logging_level: str = Field(
        default="warning",
        description="Browser-use logging level"
    )
    browser_use_setup_logging: bool = Field(
        default=False,
        description="Enable browser-use setup logging"
    )
    
    # ==========================================
    # Security Configuration (C2: Command Sandboxing)
    # ==========================================
    ALLOW_UNSAFE_COMMANDS: bool = Field(
        default=False,
        description="Bypass command denylist validation. Set to true only in trusted environments."
    )
    
    # ==========================================
    # Security Configuration (C3: Risky Action Controls)
    # ==========================================
    risky_action_enabled: bool = Field(
        default=True,
        description="Enable risky computer actions (mouse/keyboard) without confirmation. "
                    "Set to false in production for user confirmation before actions."
    )
    computer_action_rate_limit: int = Field(
        default=60,
        ge=0,
        description="Max computer actions per minute (0 = unlimited). Rate limits mouse/keyboard actions."
    )
    
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        "case_sensitive": False,
        "extra": "ignore",  # Ignore unknown env vars
    }
    
    @field_validator("mcp_capture_scope", mode="after")
    @classmethod
    def validate_capture_scope(cls, v):
        """Validate capture scope is one of allowed values."""
        valid = ["primary", "virtual", "all", "desktop"]
        if v.lower() not in valid:
            raise ValueError(f"mcp_capture_scope must be one of {valid}, got '{v}'")
        return v.lower()
        
    @field_validator("personaplex_mode", mode="after")
    @classmethod
    def validate_personaplex_mode(cls, v):
        valid = ["websocket", "subprocess", "none", "false", ""]
        if v.lower() not in valid:
            raise ValueError(f"personaplex_mode must be one of {valid}, got '{v}'")
        return v.lower()
    
    def get_oi_path(self) -> str:
        """Get platform-specific OI_PATH with validation."""
        # Platform-specific override takes priority
        if sys.platform == "win32" and self.oi_path_win:
            oi_path = self.oi_path_win
        elif sys.platform.startswith("linux") and self.oi_path_linux:
            oi_path = self.oi_path_linux
        else:
            oi_path = self.oi_path
        
        if not oi_path:
            raise ValueError(
                "OI_PATH is required and not set.\n"
                "Set one of: OI_PATH, OI_PATH_WIN (on Windows), OI_PATH_LINUX (on Linux)"
            )
        
        oi_path = oi_path.strip('"').strip("'")
        oi_path_obj = Path(oi_path)
        
        if not oi_path_obj.exists():
            raise ValueError(f"OI_PATH directory does not exist: {oi_path}")
        
        interpreter_path = oi_path_obj / "interpreter"
        if not interpreter_path.exists():
            raise ValueError(f"'interpreter' module not found in OI_PATH: {oi_path}")
        
        return str(oi_path_obj)


# Global config instance (loaded on module import)
try:
    CONFIG = ServerConfig()
    # Validate OI_PATH immediately
    OI_PATH = CONFIG.get_oi_path()
except Exception as e:
    print(f"[CONFIG ERROR]: {e}", file=sys.stderr)
    sys.exit(1)
