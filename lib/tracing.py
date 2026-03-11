"""Langfuse tracing integration for LangChain.

Langfuse v3 reads config from env vars: LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL.
These are set in .env and loaded by pydantic-settings at startup.
"""

from __future__ import annotations

import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

from settings import settings

if TYPE_CHECKING:
    from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)


def _ensure_langfuse_env() -> None:
    """Push Langfuse settings into env vars so the SDK picks them up."""
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url)


def check_langfuse_connection() -> bool:
    """Check if Langfuse is reachable and log the result."""
    url = settings.langfuse_base_url.rstrip("/") + "/api/public/health"
    try:
        resp = httpx.get(url, timeout=5)
    except httpx.ConnectError:
        logger.warning("Langfuse unreachable at %s — is docker-compose up?", settings.langfuse_base_url)
        return False
    except httpx.HTTPError as exc:
        logger.warning("Langfuse connection failed at %s: %s", settings.langfuse_base_url, exc)
        return False
    else:
        if resp.status_code == 200:
            logger.info("Langfuse connected: %s (status: healthy)", settings.langfuse_base_url)
            return True
        logger.warning("Langfuse responded with status %d at %s", resp.status_code, settings.langfuse_base_url)
        return False


def get_langfuse_handler() -> CallbackHandler:
    """Return a Langfuse callback handler for LangChain."""
    _ensure_langfuse_env()
    check_langfuse_connection()

    from langfuse.langchain import CallbackHandler as _Handler

    handler: CallbackHandler = _Handler()
    return handler


def shutdown_langfuse() -> None:
    """Flush pending events and shut down the Langfuse client."""
    from langfuse import get_client

    client: Any = get_client()
    client.shutdown()
