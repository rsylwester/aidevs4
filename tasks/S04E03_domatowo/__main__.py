"""S04E03 - Domatowo: Rescue mission to find and evacuate a partisan."""

from __future__ import annotations

import logging

from lib.logging import setup_logging
from lib.tracing import langfuse_session
from tasks.S04E03_domatowo.agent import run_agent
from tasks.S04E03_domatowo.tools import prefetch_help, reset_game

logger = logging.getLogger(__name__)


def run() -> None:
    """Entry point for S04E03 domatowo task."""
    setup_logging()

    logger.info("[bold cyan]Resetting game state...[/]")
    reset_game()

    logger.info("[bold cyan]Pre-fetching help data...[/]")
    help_data = prefetch_help()
    logger.info("[bold green]Help data: %s[/]", list(help_data.keys())[:10])

    with langfuse_session("S04E03_domatowo") as session_id:
        logger.info("[bold cyan]S04E03_domatowo | session=%s[/]", session_id)
        result = run_agent(help_data)
        logger.info("[bold green]Final result: %s[/]", result[:500])


if __name__ == "__main__":
    run()
