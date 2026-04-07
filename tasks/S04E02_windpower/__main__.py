"""S04E02 - Windpower: Configure wind turbine schedule within 40-second service window."""

from __future__ import annotations

import logging

from lib.logging import setup_logging
from lib.tracing import langfuse_session
from tasks.S04E02_windpower.agent import run_agent
from tasks.S04E02_windpower.tools import call_api, init_log, prefetch_api, set_docs_data

logger = logging.getLogger(__name__)


def run() -> None:
    """Entry point for S04E02 windpower task."""
    setup_logging()
    init_log()

    # Pre-fetch help and documentation (free — before the 40s timer)
    logger.info("[bold cyan]Pre-fetching help and documentation...[/]")
    help_data = prefetch_api("help")

    # If stale session blocks help, reset by starting then re-fetch
    if help_data.get("code", 0) < 0:
        logger.warning("[yellow]Pre-fetch blocked (stale session), resetting...[/]")
        call_api("start")
        help_data = prefetch_api("help")

    docs_data = prefetch_api("get", {"param": "documentation"})
    set_docs_data(docs_data)

    logger.info("[bold green]Help actions: %s[/]", list(help_data.get("actions", {}).keys()))
    logger.info("[bold green]Docs: ratedPowerKw=%s[/]", docs_data.get("ratedPowerKw"))

    with langfuse_session("S04E02_windpower") as session_id:
        logger.info("[bold cyan]S04E02_windpower | session=%s[/]", session_id)
        result = run_agent(help_data, docs_data)
        logger.info("[bold green]Final result: %s[/]", result[:500])


if __name__ == "__main__":
    run()
