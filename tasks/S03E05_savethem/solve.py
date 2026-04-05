"""S03E05 - Save Them: Route planning agent for Skolwin mission."""

from __future__ import annotations

import logging

from lib.hub import submit_answer
from lib.tracing import langfuse_session
from tasks.S03E05_savethem.orchestrator import run_orchestrator

logger = logging.getLogger(__name__)


def main() -> None:
    """Solve S03E05: orchestrator agent discovers tools, gathers data, computes route."""
    with langfuse_session("S03E05_savethem") as session_id:
        logger.info("[bold cyan]S03E05_savethem | session=%s[/]", session_id)
        route = run_orchestrator()
        if route:
            logger.info("[bold green]Final route (%d entries): %s[/]", len(route), route)
            submit_answer("savethem", route)
        else:
            logger.warning("[bold red]No route computed — skipping submission[/]")


if __name__ == "__main__":
    from lib.logging import setup_logging

    setup_logging()
    main()
