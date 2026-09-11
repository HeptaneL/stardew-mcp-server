"""Stardew Valley MCP server package."""

from stardew_mcp_server.server import mcp, start

__all__ = ["mcp", "start", "main"]


def main() -> None:
    """Console-script entry point.

    Never write to stdout here: for a stdio MCP server stdout is the JSON-RPC
    channel, and stray prints corrupt the protocol handshake.
    """
    start()
