"""Driftline's MCP server (spec section 5), mounted on the gateway at `/mcp`."""

from driftline.mcp.server import build_mcp

__all__ = ["build_mcp"]
