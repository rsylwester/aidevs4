"""Entry point: run MCP packages server over SSE on port 8001."""

from __future__ import annotations

from tasks.S01E03_proxy.tools import mcp as mcp_server

if __name__ == "__main__":
    mcp_server.run(transport="sse")  # pyright: ignore[reportUnknownMemberType]
