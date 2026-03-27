"""S03E03 - reactor: Navigate a robot through oscillating reactor blocks."""

from __future__ import annotations

import logging

from lib.logging import setup_logging
from lib.tracing import langfuse_session
from tasks.S03E03_reactor.agent import run_reactor_agent

logger = logging.getLogger(__name__)


def run() -> None:
    """Entry point for S03E03 reactor task."""
    setup_logging()

    with langfuse_session("S03E03-reactor") as session_id:
        logger.info("[bold cyan]S03E03-reactor | session=%s[/]", session_id)
        result = run_reactor_agent()
        logger.info("[bold green]Final result: %s[/]", result[:500])


if __name__ == "__main__":
    run()
