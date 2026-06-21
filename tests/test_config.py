import pytest
import os
from src.config import ServerConfig, COMMAND_DENYLIST

def test_command_denylist_contains_os_specific_destructives():
    assert "rm -rf /" in COMMAND_DENYLIST
    assert "format" in COMMAND_DENYLIST
    assert "shutdown" in COMMAND_DENYLIST
    assert "Clear-RecycleBin" in COMMAND_DENYLIST
    assert "Remove-Item -Recurse -Force C:\\" in COMMAND_DENYLIST

def test_config_validation(monkeypatch):
    # Test valid capture scope
    config = ServerConfig(mcp_capture_scope="primary", oi_path="C:\\fake\\path")
    assert config.mcp_capture_scope == "primary"
    
    # Test invalid capture scope
    with pytest.raises(ValueError):
        ServerConfig(mcp_capture_scope="invalid_scope", oi_path="C:\\fake\\path")

def test_oi_path_logic(monkeypatch, tmp_path):
    # Create fake interpreter module in a temp dir
    oi_dir = tmp_path / "oi"
    oi_dir.mkdir()
    (oi_dir / "interpreter").mkdir()
    
    config = ServerConfig(oi_path=str(oi_dir))
    assert config.get_oi_path() == str(oi_dir)
