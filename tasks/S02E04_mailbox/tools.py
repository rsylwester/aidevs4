"""zmail API tools for DSPy ReAct agents."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from settings import settings

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

logger = logging.getLogger(__name__)

_ZMAIL_URL = f"{settings.aidevs_hub_url}/api/zmail"


def _post_zmail(payload: dict[str, Any], *, log_full: bool = False) -> dict[str, Any]:
    """POST to zmail API and return parsed JSON response."""
    payload["apikey"] = settings.aidevs_key
    resp = httpx.post(_ZMAIL_URL, json=payload, timeout=30)
    data: dict[str, Any] = resp.json()
    text = json.dumps(data, indent=2, ensure_ascii=False)
    if log_full:
        logger.info("[cyan]zmail %s[/] ->\n%s", payload.get("action"), text)
    else:
        logger.info("[cyan]zmail %s[/] -> %s", payload.get("action"), text[:300])
    return data


def make_read_help(workspace: Path) -> Callable[[], str]:
    """Create a read_help tool closure over workspace path."""

    def read_help() -> str:
        """Read zmail API documentation. Returns available actions and parameters. Cached locally."""
        cache_path = workspace / "help.md"
        if cache_path.exists():
            return cache_path.read_text(encoding="utf-8")
        data = _post_zmail({"action": "help"})
        text = json.dumps(data, indent=2, ensure_ascii=False)
        cache_path.write_text(text, encoding="utf-8")
        return text

    return read_help


def search_inbox(query: str, page: int = 1, per_page: int = 20) -> str:
    """Search inbox with Gmail-like operators. Supports: from:, to:, subject:, "phrase", -exclude, OR, AND.

    Args:
        query: Search query string with Gmail-like operators.
        page: Page number (default 1).
        per_page: Results per page, 5-20 (default 20).

    Returns:
        JSON string with matching messages metadata (no body — use read_message for content).
    """
    data = _post_zmail({"action": "search", "query": query, "page": page, "perPage": per_page}, log_full=True)
    return json.dumps(data, indent=2, ensure_ascii=False)


def get_inbox(page: int = 1, per_page: int = 20) -> str:
    """Get inbox thread listing.

    Args:
        page: Page number (default 1).
        per_page: Results per page, 5-20 (default 20).

    Returns:
        JSON string with thread list.
    """
    data = _post_zmail({"action": "getInbox", "page": page, "perPage": per_page})
    return json.dumps(data, indent=2, ensure_ascii=False)


def get_thread(thread_id: int) -> str:
    """Get message IDs for a thread (no message body).

    Args:
        thread_id: Numeric thread identifier.

    Returns:
        JSON string with rowID and messageID list.
    """
    data = _post_zmail({"action": "getThread", "threadID": thread_id})
    return json.dumps(data, indent=2, ensure_ascii=False)


def read_message(message_id: str) -> str:
    """Read full content of one or more messages by ID.

    Args:
        message_id: Numeric rowID or 32-char messageID. For multiple, comma-separate them.

    Returns:
        JSON string with full message content including body.
    """
    ids: list[str] | str = message_id
    if "," in message_id:
        ids = [mid.strip() for mid in message_id.split(",")]
    data = _post_zmail({"action": "getMessages", "ids": ids}, log_full=True)
    return json.dumps(data, indent=2, ensure_ascii=False)
