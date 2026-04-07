"""S04E01 - OKO Editor: Agentic system for modifying OKO Operations Center via API."""

from __future__ import annotations

import logging

from lib.logging import setup_logging
from lib.tracing import langfuse_session
from tasks.S04E01_okoeditor.agent import run_orchestrator
from tasks.S04E01_okoeditor.tools import cleanup_browser

logger = logging.getLogger(__name__)


def run() -> None:
    """Entry point for S04E01 OKO Editor task."""
    setup_logging()

    try:
        with langfuse_session("S04E01_okoeditor") as session_id:
            logger.info("[bold cyan]S04E01_okoeditor | session=%s[/]", session_id)
            result = run_orchestrator()
            logger.info("[bold green]Final result: %s[/]", result[:500])
    finally:
        cleanup_browser()


if __name__ == "__main__":
    run()
