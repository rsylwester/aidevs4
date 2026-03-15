"""Langfuse v4 tracing integration for LangChain.

Langfuse v4 uses OpenTelemetry under the hood. Config is read from env vars:
LANGFUSE_PUBLIC_KEY, LANGFUSE_SECRET_KEY, LANGFUSE_BASE_URL.
These are set in .env and loaded by pydantic-settings at startup.
"""

from __future__ import annotations

import contextlib
import logging
import os
import uuid
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

import httpx

from settings import settings

if TYPE_CHECKING:
    from collections.abc import Iterator

    from langfuse.langchain import CallbackHandler

logger = logging.getLogger(__name__)

_langfuse_healthy: bool | None = None


def _ensure_langfuse_env() -> None:
    """Push Langfuse settings into env vars so the SDK picks them up."""
    os.environ.setdefault("LANGFUSE_PUBLIC_KEY", settings.langfuse_public_key)
    os.environ.setdefault("LANGFUSE_SECRET_KEY", settings.langfuse_secret_key)
    os.environ.setdefault("LANGFUSE_BASE_URL", settings.langfuse_base_url)


def check_langfuse_connection() -> bool:
    """Check if Langfuse is reachable (cached per process)."""
    global _langfuse_healthy
    if _langfuse_healthy is not None:
        return _langfuse_healthy

    url = settings.langfuse_base_url.rstrip("/") + "/api/public/health"
    try:
        resp = httpx.get(url, timeout=5)
    except httpx.ConnectError:
        logger.warning("Langfuse unreachable at %s — is docker-compose up?", settings.langfuse_base_url)
        _langfuse_healthy = False
    except httpx.HTTPError as exc:
        logger.warning("Langfuse connection failed at %s: %s", settings.langfuse_base_url, exc)
        _langfuse_healthy = False
    else:
        if resp.status_code == 200:
            logger.info("Langfuse connected: %s (status: healthy)", settings.langfuse_base_url)
            _langfuse_healthy = True
        else:
            logger.warning("Langfuse responded with status %d at %s", resp.status_code, settings.langfuse_base_url)
            _langfuse_healthy = False

    return bool(_langfuse_healthy)


def get_langfuse_handler() -> CallbackHandler:
    """Return a Langfuse callback handler for LangChain.

    In Langfuse v4, trace-level attributes (session_id, trace_name, etc.)
    are set via ``propagate_attributes`` context manager, not constructor args.
    """
    _ensure_langfuse_env()
    check_langfuse_connection()

    from langfuse.langchain import CallbackHandler as _Handler

    handler: CallbackHandler = _Handler()
    return handler


def shutdown_langfuse() -> None:
    """Flush pending events and shut down the Langfuse client."""
    try:
        from langfuse import get_client

        client: Any = get_client()
        client.shutdown()
    except Exception:
        logger.debug("Langfuse shutdown skipped — client not active")


@contextlib.contextmanager
def langfuse_session(task_name: str) -> Iterator[str]:
    """Context manager that groups all LLM traces under one Langfuse session.

    Generates a unique session ID, sets it via ``propagate_attributes``,
    and guarantees ``shutdown_langfuse()`` on exit (even on error).

    Yields the session ID string.
    """
    _ensure_langfuse_env()

    from langfuse import propagate_attributes

    ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%S")
    session_id = f"{task_name}-{ts}-{uuid.uuid4().hex[:6]}"

    logger.info("[bold cyan]Langfuse session: %s[/]", session_id)

    with propagate_attributes(session_id=session_id, trace_name=task_name):
        try:
            yield session_id
        finally:
            shutdown_langfuse()
