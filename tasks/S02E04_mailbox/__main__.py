"""S02E04 - mailbox: Search email inbox for date, password, and confirmation code."""

from __future__ import annotations

import logging
from pathlib import Path

import dspy

from lib.logging import setup_logging
from lib.tracing import langfuse_session
from settings import settings
from tasks.S02E04_mailbox.callbacks import LoggingCallback
from tasks.S02E04_mailbox.orchestrator import run_orchestrator

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent / ".workspace"


def run() -> None:
    setup_logging()
    WORKSPACE.mkdir(exist_ok=True)

    with langfuse_session("S02E04-mailbox") as session_id:
        logger.info("[bold cyan]S02E04-mailbox | session=%s[/]", session_id)

        cb = LoggingCallback()
        lm = dspy.LM(
            "openai/gpt-4.1-mini",
            api_key=settings.openrouter_api_key,
            api_base="https://openrouter.ai/api/v1",
            cache=False,
        )
        dspy.configure(lm=lm, callbacks=[cb])

        result = run_orchestrator(WORKSPACE)
        cb.log_summary()
        logger.info("[bold green]Final result: %s[/]", result[:500])


if __name__ == "__main__":
    run()
