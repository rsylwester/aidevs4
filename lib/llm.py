"""LLM helpers — LangChain + OpenRouter."""

from __future__ import annotations

import logging
from typing import Any

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from lib.tracing import get_langfuse_handler
from settings import settings

logger = logging.getLogger(__name__)


def get_llm(
    model: str = "openai/gpt-4o-mini",
    *,
    callbacks: list[Any] | None = None,
) -> ChatOpenAI:
    """Return a ChatOpenAI instance configured for OpenRouter with Langfuse tracing.

    Trace-level attributes (session_id, trace_name) are set via
    ``propagate_attributes`` context manager, not here.
    """
    all_callbacks: list[Any] = list(callbacks) if callbacks else []
    try:
        all_callbacks.append(get_langfuse_handler())
    except Exception:
        logger.warning("Langfuse handler not available, tracing disabled", exc_info=True)

    return ChatOpenAI(
        model=model,
        api_key=SecretStr(settings.openrouter_api_key),
        base_url="https://openrouter.ai/api/v1",
        callbacks=list(all_callbacks) if all_callbacks else None,
    )
