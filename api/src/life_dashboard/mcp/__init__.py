"""Hearth MCP server package (mcp-001). See server.py for the tool surface."""
from life_dashboard.mcp.server import mcp_routes, mcp_server

__all__ = ["mcp_server", "mcp_routes"]
