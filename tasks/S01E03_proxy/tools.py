"""MCP tools for package logistics — check and redirect packages."""

from __future__ import annotations

import httpx
from mcp.server.fastmcp import FastMCP

from settings import settings

_API_URL = "https://***REDACTED***/api/packages"

mcp = FastMCP("packages", port=8001)


@mcp.tool()
async def check_package(packageid: str) -> str:
    """Check package status and contents by package ID (e.g. PKG12345678)."""
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _API_URL,
            json={"apikey": settings.aidevs_key, "action": "check", "packageid": packageid},
        )
        resp.raise_for_status()
        return resp.text


@mcp.tool()
async def redirect_package(packageid: str, destination: str, code: str) -> str:
    """Redirect a package to a new destination.

    Use ONLY when the operator explicitly asks to redirect/send a package —
    never call proactively after a check.
    The code parameter is the security code the operator provides — never invent one.
    """
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            _API_URL,
            json={
                "apikey": settings.aidevs_key,
                "action": "redirect",
                "packageid": packageid,
                "destination": destination,
                "code": code,
            },
        )
        resp.raise_for_status()
        return resp.text
