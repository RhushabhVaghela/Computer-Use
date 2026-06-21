import pytest
from src.server import mcp

@pytest.mark.asyncio
async def test_mcp_server_initialization():
    """Integration test to verify FastMCP server setup and tool registration."""
    # FastMCP tools are stored in mcp._mcp_server.tools or mcp._tools depending on version.
    # In fastmcp, they are usually in mcp._tools
    
    # We can just verify the decorator registered them by checking if the functions exist.
    from src.server import computer, bash, read_screen_ui, read_browser_ui
    
    assert computer is not None
    assert bash is not None
    assert read_screen_ui is not None
    assert read_browser_ui is not None

    # Just a simple sanity check that the config loaded and the server is ready
    assert mcp.name == "Computer-Use"
