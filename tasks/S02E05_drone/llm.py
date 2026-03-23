"""Typed wrapper around litellm.completion with Langfuse integration."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from settings import settings

logger = logging.getLogger(__name__)

# litellm has partially-unknown types in strict mode; this module isolates that boundary.
_initialized: bool = False
_completion_fn: Any = None
_cost_fn: Any = None


def _ensure_litellm() -> None:
    global _initialized, _completion_fn, _cost_fn
    if _initialized:
        return

    _mod: Any = __import__("litellm")
    _completion_fn = _mod.completion
    _cost_fn = _mod.completion_cost

    # Enable Langfuse tracing via OpenTelemetry (compatible with Langfuse v4).
    # Env vars (LANGFUSE_*) are set by lib.tracing._ensure_langfuse_env()
    # which runs inside langfuse_session() before any LLM calls happen.
    _mod.success_callback = ["langfuse_otel"]
    _mod.failure_callback = ["langfuse_otel"]

    _initialized = True


@dataclass
class LLMUsage:
    """Token usage from a single LLM call."""

    prompt_tokens: int
    completion_tokens: int


@dataclass
class LLMToolCall:
    """A single tool call from the LLM response."""

    id: str
    name: str
    arguments: str


@dataclass
class LLMResponse:
    """Typed LLM response extracted from litellm ModelResponse."""

    content: str | None
    tool_calls: list[LLMToolCall]
    usage: LLMUsage
    raw: Any  # original ModelResponse for cost calculation


def chat(
    model: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: str | None = None,
    label: str = "",
) -> LLMResponse:
    """Call litellm.completion and return a typed response."""
    _ensure_litellm()
    logger.info("[bold blue][%s][/] calling %s", label or "llm", model)

    kwargs: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "api_key": settings.openrouter_api_key,
        "metadata": {"generation_name": label},
    }
    if tools is not None:
        kwargs["tools"] = tools
    if tool_choice is not None:
        kwargs["tool_choice"] = tool_choice

    raw: Any = _completion_fn(**kwargs)

    # Extract message
    msg: Any = raw.choices[0].message

    content: str | None = str(msg.content) if msg.content else None

    # Extract tool calls
    raw_tool_calls: list[Any] | None = msg.tool_calls
    tool_calls: list[LLMToolCall] = [
        LLMToolCall(id=str(tc.id), name=str(tc.function.name), arguments=str(tc.function.arguments))
        for tc in (raw_tool_calls or [])
    ]

    # Extract usage
    raw_usage: Any = raw.usage
    p_tok = int(getattr(raw_usage, "prompt_tokens", 0) or 0)
    c_tok = int(getattr(raw_usage, "completion_tokens", 0) or 0)

    return LLMResponse(
        content=content,
        tool_calls=tool_calls,
        usage=LLMUsage(prompt_tokens=p_tok, completion_tokens=c_tok),
        raw=raw,
    )


def get_completion_cost(raw_response: Any) -> float:
    """Calculate cost for a litellm response."""
    _ensure_litellm()
    try:
        result: float = float(_cost_fn(completion_response=raw_response))
    except Exception:
        result = 0.0
    return result
