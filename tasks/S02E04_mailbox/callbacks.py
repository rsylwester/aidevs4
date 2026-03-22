"""DSPy callbacks for logging iterations, tool calls, and token usage."""

from __future__ import annotations

import logging
from typing import Any, override

from dspy.utils.callback import BaseCallback

logger = logging.getLogger(__name__)


class LoggingCallback(BaseCallback):
    """Logs ReAct iterations, tool calls, and LM token usage."""

    def __init__(self) -> None:
        self._lm_call_count = 0
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0

    @override
    def on_lm_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        self._lm_call_count += 1
        logger.info(
            "[blue]LLM call #%d[/] | model=%s",
            self._lm_call_count,
            getattr(instance, "model", "?"),
        )

    @override
    def on_lm_end(self, call_id: str, outputs: dict[str, Any] | None, exception: Exception | None = None) -> None:
        if exception:
            logger.warning("[red]LLM call #%d failed:[/] %s", self._lm_call_count, exception)
            return
        if outputs:
            usage: dict[str, Any] = outputs.get("usage", {})
            prompt_tokens = usage.get("prompt_tokens", 0)
            completion_tokens = usage.get("completion_tokens", 0)
            if isinstance(prompt_tokens, int):
                self._total_prompt_tokens += prompt_tokens
            if isinstance(completion_tokens, int):
                self._total_completion_tokens += completion_tokens
            logger.info(
                "[blue]LLM call #%d done[/] | prompt=%d compl=%d | total: prompt=%d compl=%d",
                self._lm_call_count,
                prompt_tokens,
                completion_tokens,
                self._total_prompt_tokens,
                self._total_completion_tokens,
            )

    @override
    def on_module_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        module_name = type(instance).__name__
        logger.info("[magenta]Module %s started[/]", module_name)

    @override
    def on_module_end(self, call_id: str, outputs: Any | None, exception: Exception | None = None) -> None:
        if exception:
            logger.warning("[red]Module failed:[/] %s", exception)

    @override
    def on_tool_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        tool_name = getattr(instance, "name", getattr(instance, "__name__", str(instance)))
        args_str = str(inputs)[:150]
        logger.info("[yellow]Tool call:[/] %s(%s)", tool_name, args_str)

    @override
    def on_tool_end(self, call_id: str, outputs: dict[str, Any] | None, exception: Exception | None = None) -> None:
        if exception:
            logger.warning("[red]Tool failed:[/] %s", exception)
        elif outputs:
            result_str = str(outputs)[:200]
            logger.info("[yellow]Tool result:[/] %s", result_str)

    def log_summary(self) -> None:
        """Log final token usage summary."""
        logger.info(
            "[bold cyan]Token usage summary:[/] llm_calls=%d prompt_tokens=%d completion_tokens=%d total=%d",
            self._lm_call_count,
            self._total_prompt_tokens,
            self._total_completion_tokens,
            self._total_prompt_tokens + self._total_completion_tokens,
        )
