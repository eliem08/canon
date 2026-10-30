"""Permission-aware MCP server exposing Canon's resolved customer data."""

from canon.mcp_server.server import build_server
from canon.mcp_server.service import CallerDirectory, CanonService, ServiceConfig

__all__ = ["CallerDirectory", "CanonService", "ServiceConfig", "build_server"]
