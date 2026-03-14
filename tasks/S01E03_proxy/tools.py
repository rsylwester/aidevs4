"""MCP tools for package logistics — check and redirect packages."""

from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP  # pyright: ignore[reportMissingTypeStubs]

from settings import settings

_API_URL = "https://***REDACTED***/api/packages"

mcp = FastMCP("packages", port=8001)  # pyright: ignore[reportUnknownMemberType]


@mcp.tool()  # pyright: ignore[reportUntypedFunctionDecorator, reportUnknownMemberType]
async def check_package(packageid: str) -> str:  # pyright: ignore[reportUnusedFunction]
    """Check package status and contents by package ID (e.g. PKG12345678)."""
    async with httpx.AsyncClient(timeout=30) as client:  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        resp = await client.post(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            _API_URL,
            json={"apikey": settings.aidevs_key, "action": "check", "packageid": packageid},
        )
        resp.raise_for_status()  # pyright: ignore[reportUnknownMemberType]
        return str(resp.text)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]


@mcp.tool()  # pyright: ignore[reportUntypedFunctionDecorator, reportUnknownMemberType]
async def redirect_package(packageid: str, destination: str, code: str) -> str:  # pyright: ignore[reportUnusedFunction]
    """Redirect a package to a new destination.

    Use ONLY when the operator explicitly asks to redirect/send a package —
    never call proactively after a check.
    The code parameter is the security code the operator provides — never invent one.
    """
    async with httpx.AsyncClient(timeout=30) as client:  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        resp = await client.post(  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
            _API_URL,
            json={
                "apikey": settings.aidevs_key,
                "action": "redirect",
                "packageid": packageid,
                "destination": destination,
                "code": code,
            },
        )
        resp.raise_for_status()  # pyright: ignore[reportUnknownMemberType]
        return str(resp.text)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType]
