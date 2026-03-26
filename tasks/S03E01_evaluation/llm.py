"""Simplified litellm wrapper for S02E06 — no tool-calling needed."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from settings import settings

logger = logging.getLogger(__name__)

_initialized: bool = False
_completion_fn: Any = None


def _ensure_litellm() -> None:
    global _initialized, _completion_fn
    if _initialized:
        return

    _mod: Any = __import__("litellm")
    _completion_fn = _mod.completion

    _mod.success_callback = ["langfuse_otel"]
    _mod.failure_callback = ["langfuse_otel"]
    _initialized = True


@dataclass
class LLMResponse:
    """Typed LLM response."""

    content: str
    prompt_tokens: int
    completion_tokens: int


def chat(
    model: str,
    messages: list[dict[str, Any]],
    *,
    label: str = "",
) -> LLMResponse:
    """Call litellm.completion and return typed response."""
    _ensure_litellm()
    logger.info("[bold blue][%s][/] calling %s", label or "llm", model)

    raw: Any = _completion_fn(
        model=model,
        messages=messages,
        api_key=settings.openrouter_api_key,
        metadata={"generation_name": label},
    )

    msg: Any = raw.choices[0].message
    content: str = str(msg.content or "")

    raw_usage: Any = raw.usage
    p_tok = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
    c_tok = int(getattr(raw_usage, "completion_tokens", 0) or 0)

    return LLMResponse(content=content, prompt_tokens=p_tok, completion_tokens=c_tok)
