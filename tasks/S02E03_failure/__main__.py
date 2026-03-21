"""S02E03 - failure: Condensed power plant failure log analysis."""

from __future__ import annotations

import logging
from pathlib import Path

from lib.hub import fetch_data
from lib.logging import setup_logging
from lib.tracing import langfuse_session
from tasks.S02E03_failure.orchestrator import run_orchestrator

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent / ".workspace"


def run() -> None:
    setup_logging()
    WORKSPACE.mkdir(exist_ok=True)

    log_path = WORKSPACE / "failure.log"
    result_path = WORKSPACE / "result.log"

    with langfuse_session("S02E03-failure") as session_id:
        logger.info("[bold cyan]S02E03-failure | session=%s[/]", session_id)

        # Download the log file
        logger.info("[cyan]Downloading failure.log from hub...[/]")
        log_text = fetch_data("failure.log")
        log_path.write_text(log_text, encoding="utf-8")
        line_count = len(log_text.splitlines())
        logger.info("[green]Downloaded failure.log: %d lines, %d chars[/]", line_count, len(log_text))

        # Run the orchestrator — it drives everything
        result = run_orchestrator(log_path, result_path)
        logger.info("[bold green]Final result: %s[/]", result[:500])


if __name__ == "__main__":
    run()
