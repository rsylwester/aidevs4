"""Hub API interaction utilities."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from settings import settings

logger = logging.getLogger(__name__)

_BASE_DATA_URL = "https://***REDACTED***/data"


def submit_answer(task: str, answer: Any) -> dict[str, Any]:
    """POST answer to the hub verification endpoint."""
    payload = {"apikey": settings.aidevs_key, "task": task, "answer": answer}
    resp = httpx.post(settings.aidevs_verify_address, json=payload, timeout=30)
    data: dict[str, Any] = resp.json()
    if not resp.is_success:
        logger.error("[bold red]Hub error for '%s' (HTTP %d):[/] %s", task, resp.status_code, data)
    else:
        logger.info("[bold green]Hub response for '%s':[/] %s", task, data)
    resp.raise_for_status()
    return data


def fetch_data(path: str) -> str:
    """GET data from hub data endpoint."""
    url = f"{_BASE_DATA_URL}/{settings.aidevs_key}/{path}"
    resp = httpx.get(url, timeout=30)
    resp.raise_for_status()
    return resp.text
