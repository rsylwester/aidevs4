"""DSPy callbacks for logging iterations, tool calls, and token usage."""

from __future__ import annotations

import logging
import re
from typing import Any, override

from dspy.utils.callback import BaseCallback

logger = logging.getLogger(__name__)

_FLAG_RE = re.compile(r"\{FLG:[^}]+\}")


class LoggingCallback(BaseCallback):
    """Logs ReAct iterations, tool calls, and LM token usage."""

    def __init__(self) -> None:
        self._lm_call_count = 0
        self._total_prompt_tokens = 0
        self._total_completion_tokens = 0
        self._total_cost: float = 0.0
        self._last_lm: Any = None
        self.flags: list[str] = []

    @override
    def on_lm_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        self._lm_call_count += 1
        self._last_lm = instance
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
        # Usage data lives in instance.history[-1], not in outputs
        lm = self._last_lm
        history: list[dict[str, Any]] = getattr(lm, "history", [])
        if history:
            entry: dict[str, Any] = history[-1]
            usage: dict[str, Any] = entry.get("usage", {})
            prompt_tokens: int = int(usage.get("prompt_tokens", 0) or 0)
            completion_tokens: int = int(usage.get("completion_tokens", 0) or 0)
            self._total_prompt_tokens += prompt_tokens
            self._total_completion_tokens += completion_tokens
            cost: float = float(entry.get("cost", 0) or 0)
            self._total_cost += cost
            logger.info(
                "[blue]LLM call #%d done[/] | prompt=%d compl=%d cost=$%.6f | total: prompt=%d compl=%d cost=$%.6f",
                self._lm_call_count,
                prompt_tokens,
                completion_tokens,
                cost,
                self._total_prompt_tokens,
                self._total_completion_tokens,
                self._total_cost,
            )
        else:
            logger.info("[blue]LLM call #%d done[/] | no usage data", self._lm_call_count)

    @override
    def on_module_start(self, call_id: str, instance: Any, inputs: dict[str, Any]) -> None:
        module_name = type(instance).__name__
        logger.info("[magenta]Module %s started[/]", module_name)

    @override
    def on_module_end(self, call_id: str, outputs: Any | None, exception: Exception | None = None) -> None:
        if exception:
            logger.warning("[red]Module failed:[/] %s", exception)
        # Capture flags from module outputs
        if outputs:
            for flag in _FLAG_RE.findall(str(outputs)):
                if flag not in self.flags:
                    self.flags.append(flag)

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
            text = str(outputs)
            # Capture flags from tool outputs
            for flag in _FLAG_RE.findall(text):
                if flag not in self.flags:
                    self.flags.append(flag)
            logger.info("[yellow]Tool result:[/] %s", text[:200])

    def log_summary(self, orchestrator_model: str, researcher_model: str) -> None:
        """Log final summary table with token usage and flags."""
        total = self._total_prompt_tokens + self._total_completion_tokens
        logger.info(
            "\n[bold cyan]===== Final summary =====[/]\n"
            "  Orchestrator model : %s\n"
            "  Researcher model   : %s\n"
            "  LLM calls          : %d\n"
            "  Input tokens       : %d\n"
            "  Output tokens      : %d\n"
            "  Total tokens       : %d\n"
            "  Est. cost (USD)    : $%.6f\n",
            orchestrator_model,
            researcher_model,
            self._lm_call_count,
            self._total_prompt_tokens,
            self._total_completion_tokens,
            total,
            self._total_cost,
        )
        if self.flags:
            flag_lines = "\n".join(f"  {f}" for f in self.flags)
            logger.info("[bold green]*** FLAGS CAPTURED ***[/]\n%s", flag_lines)
        else:
            logger.warning("[bold red]No flags captured[/]")
