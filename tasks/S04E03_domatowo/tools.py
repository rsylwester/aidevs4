"""S04E03 tools — Domatowo rescue mission API."""

from __future__ import annotations

import json
import logging
from typing import Any

import httpx

from settings import settings

logger = logging.getLogger(__name__)

_VERIFY_URL = settings.aidevs_verify_address
_TASK = "domatowo"
_MAX_RESULT_LEN = 8000

_FLAG_PREFIX = "{FLG:"
_POINTS_EXHAUSTED_KEYWORDS = ["action points", "punktów akcji", "limit", "exceeded", "wyczerpan"]


def send_request(action: str, payload: dict[str, Any] | None = None) -> str:
    """Send a request to the Domatowo API with given action and optional payload."""
    answer: dict[str, Any] = {"action": action}
    if payload:
        answer.update(payload)

    body: dict[str, Any] = {
        "apikey": settings.aidevs_key,
        "task": _TASK,
        "answer": answer,
    }

    logger.info("[yellow]>> API action=%r payload=%s[/]", action, json.dumps(payload or {}, ensure_ascii=False)[:300])

    try:
        resp = httpx.post(_VERIFY_URL, json=body, timeout=30)
        data: dict[str, Any] = resp.json()
        data_str = json.dumps(data, ensure_ascii=False)
        logger.info("[cyan]<< API: %s[/]", data_str[:500])
        return data_str[:_MAX_RESULT_LEN]
    except Exception as exc:
        msg = f"API error: {exc}"
        logger.warning("[red]%s[/]", msg)
        return json.dumps({"error": msg})


def prefetch_help() -> dict[str, Any]:
    """Fetch help data before agent starts."""
    raw = send_request("help")
    result: dict[str, Any] = json.loads(raw)
    return result


def check_flag(text: str) -> str | None:
    """Return the flag if present in text, else None."""
    if _FLAG_PREFIX in text:
        start = text.index(_FLAG_PREFIX)
        end = text.index("}", start + len(_FLAG_PREFIX)) + 1
        return text[start:end]
    return None


def check_points_exhausted(text: str) -> bool:
    """Check if the API response indicates action points are exhausted."""
    lower = text.lower()
    return any(kw in lower for kw in _POINTS_EXHAUSTED_KEYWORDS)


def reset_game() -> str:
    """Send reset action to restart the game with fresh action points."""
    logger.info("[bold red]>> Resetting game...[/]")
    return send_request("reset")


SEND_REQUEST_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "send_request",
        "description": (
            "Send a request to the Domatowo rescue mission API.\n\n"
            "Available actions:\n"
            '- "getMap" — retrieve the 11x11 city map with terrain symbols\n'
            '- "create" — create a unit. Requires payload with "type" ("transporter" or "scout"). '
            'For transporter, optionally include "passengers" (number of scouts aboard).\n'
            '- "move" — move a unit. Requires payload with "unit" (unit ID) and "direction" '
            '("N", "S", "E", "W").\n'
            '- "disembark" — drop scouts from transporter. Requires payload with "unit" (transporter ID).\n'
            '- "inspect" — inspect current field for the partisan. Requires payload with "unit" (scout ID).\n'
            '- "getLogs" — get logs of all actions and their results so far.\n'
            '- "callHelicopter" — call rescue helicopter. Requires payload with "destination" '
            '(field coordinate like "F6" where the partisan was confirmed).\n\n'
            "Cost reference:\n"
            "- create scout: 5 pts\n"
            "- create transporter: 5 pts base + 5 pts per passenger\n"
            "- move scout: 7 pts per field\n"
            "- move transporter: 1 pt per field\n"
            "- inspect: 1 pt\n"
            "- disembark: 0 pts\n"
            "- Total budget: 300 pts"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform",
                    "enum": ["getMap", "create", "move", "disembark", "inspect", "getLogs", "callHelicopter"],
                },
                "payload": {
                    "type": "object",
                    "description": "Additional parameters for the action",
                },
            },
            "required": ["action"],
        },
    },
}

ALL_TOOL_SCHEMAS: list[dict[str, Any]] = [SEND_REQUEST_SCHEMA]
