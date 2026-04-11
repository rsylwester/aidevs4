"""Host-side pre-flight for the S04E05 foodwarehouse agent.

The agent itself drives /verify via curl inside the sandbox, but we do three
things up-front to save the model from wasting steps:

1. Download ``food4cities.json`` once and cache it to ``.workspace/``.
2. Prefetch the API ``{tool: help}`` so the agent sees the full tool reference
   before its first move.
3. Call ``{tool: reset}`` so every run starts from a clean orders state.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from lib.hub import submit_answer
from settings import settings

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_TASK_NAME = "foodwarehouse"
_FOOD4CITIES_PATH = "/dane/food4cities.json"


def download_food4cities(workspace: Path) -> dict[str, Any]:
    """Fetch food4cities.json once, cache to .workspace/, return parsed JSON."""
    cache = workspace / "food4cities.json"
    if cache.exists():
        logger.info("[dim]food4cities cached at %s[/]", cache)
        return json.loads(cache.read_text())

    url = f"{settings.aidevs_hub_url.rstrip('/')}{_FOOD4CITIES_PATH}"
    logger.info("[cyan]Downloading %s...[/]", url)
    resp = httpx.get(url, timeout=30, follow_redirects=True)
    resp.raise_for_status()
    workspace.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text)
    data: dict[str, Any] = resp.json()
    logger.info("[green]food4cities loaded \u2014 %d top-level keys[/]", len(data))
    return data


def prefetch_help() -> dict[str, Any]:
    """Fetch the foodwarehouse API's own help doc so we can ground the agent in it."""
    logger.info("[cyan]Prefetching foodwarehouse help...[/]")
    help_body = submit_answer(_TASK_NAME, {"tool": "help"})
    logger.info("[dim]Help keys: %s[/]", list(help_body.keys()))
    return help_body


def reset_orders() -> dict[str, Any]:
    """Reset the foodwarehouse state on Centrala so the agent starts clean."""
    logger.info("[cyan]Resetting foodwarehouse state to initial...[/]")
    body = submit_answer(_TASK_NAME, {"tool": "reset"})
    logger.info("[dim]Reset response: %s[/]", body)
    return body
