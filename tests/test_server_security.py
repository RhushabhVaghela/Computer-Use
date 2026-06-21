import pytest
import os
from src.server import validate_command

def test_validate_command_blocks_denylist(monkeypatch):
    import src.config
    monkeypatch.setattr(src.config.CONFIG, "ALLOW_UNSAFE_COMMANDS", False)
    # Attempting to run a blocked command
    is_valid, pattern = validate_command("rm -rf /")
    assert not is_valid
    assert pattern in "rm -rf /"

def test_validate_command_allows_safe(monkeypatch):
    import src.config
    monkeypatch.setattr(src.config.CONFIG, "ALLOW_UNSAFE_COMMANDS", False)
    # Attempting to run a safe command
    is_valid, msg = validate_command("ls -la")
    assert is_valid
    assert msg == ""

def test_validate_command_allow_unsafe_override(monkeypatch):
    # Using an import wrapper to simulate the config reload
    import src.server
    monkeypatch.setattr(src.server.CONFIG, "ALLOW_UNSAFE_COMMANDS", True)
    
    is_valid, msg = validate_command("rm -rf /")
    assert is_valid
    assert msg == ""
