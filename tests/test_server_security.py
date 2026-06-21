import pytest
import os
from src.server import validate_command

def test_validate_command_blocks_denylist(monkeypatch):
    monkeypatch.setenv("ALLOW_UNSAFE_COMMANDS", "false")
    # Attempting to run a blocked command
    is_valid, msg = validate_command("rm -rf /")
    assert not is_valid
    assert "Blocked command pattern detected" in msg

def test_validate_command_allows_safe(monkeypatch):
    monkeypatch.setenv("ALLOW_UNSAFE_COMMANDS", "false")
    # Attempting to run a safe command
    is_valid, msg = validate_command("ls -la")
    assert is_valid
    assert msg == ""

def test_validate_command_allow_unsafe_override(monkeypatch):
    monkeypatch.setenv("ALLOW_UNSAFE_COMMANDS", "true")
    # Using an import wrapper to simulate the config reload
    import src.config
    monkeypatch.setattr(src.config.CONFIG, "ALLOW_UNSAFE_COMMANDS", True)
    
    is_valid, msg = validate_command("rm -rf /")
    assert is_valid
    assert msg == ""
