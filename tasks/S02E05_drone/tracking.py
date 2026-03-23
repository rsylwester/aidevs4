"""Token usage tracking for litellm responses."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from tasks.S02E05_drone.llm import LLMResponse

logger = logging.getLogger(__name__)

_FLAG_RE = re.compile(r"\{FLG:[^}]+\}")


@dataclass
class TokenTracker:
    """Accumulates token usage and cost across LLM calls."""

    calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    flags: list[str] = field(default_factory=lambda: list[str]())

    def track(self, response: LLMResponse, *, label: str = "") -> None:
        """Extract and accumulate usage from a typed LLMResponse."""
        from tasks.S02E05_drone.llm import get_completion_cost

        self.calls += 1
        self.prompt_tokens += response.usage.prompt_tokens
        self.completion_tokens += response.usage.completion_tokens

        cost = get_completion_cost(response.raw)
        self.cost_usd += cost

        tag = f"[{label}] " if label else ""
        logger.info(
            "[blue]%sLLM call #%d[/] prompt=%d compl=%d cost=$%.6f | cumul: prompt=%d compl=%d cost=$%.6f",
            tag,
            self.calls,
            response.usage.prompt_tokens,
            response.usage.completion_tokens,
            cost,
            self.prompt_tokens,
            self.completion_tokens,
            self.cost_usd,
        )

        if response.content:
            self.capture_flags(response.content)

    def capture_flags(self, text: str) -> None:
        """Scan arbitrary text for flags."""
        for flag in _FLAG_RE.findall(text):
            if flag not in self.flags:
                self.flags.append(flag)

    def log_summary(self) -> None:
        """Log final summary table."""
        total = self.prompt_tokens + self.completion_tokens
        logger.info(
            "\n[bold cyan]===== Final summary =====[/]\n"
            "  LLM calls          : %d\n"
            "  Input tokens       : %d\n"
            "  Output tokens      : %d\n"
            "  Total tokens       : %d\n"
            "  Est. cost (USD)    : $%.6f",
            self.calls,
            self.prompt_tokens,
            self.completion_tokens,
            total,
            self.cost_usd,
        )
        if self.flags:
            flag_lines = "\n".join(f"  {f}" for f in self.flags)
            logger.info("[bold green]*** FLAGS CAPTURED ***[/]\n%s", flag_lines)
        else:
            logger.warning("[bold red]No flags captured[/]")
