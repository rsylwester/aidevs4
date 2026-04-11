"""S04E05 \u2014 Foodwarehouse: build per-city orders via bash-only agent."""

from __future__ import annotations

import logging
from pathlib import Path

from lib.logging import setup_logging
from lib.tracing import langfuse_session
from tasks.S04E05_foodwarehouse.agent import run_agent
from tasks.S04E05_foodwarehouse.sandbox import FoodwarehouseSandbox, docker_available

logger = logging.getLogger(__name__)

_WORKSPACE = Path(__file__).parent / ".workspace"
_SESSION_LOG = _WORKSPACE / "session_log.md"


def run() -> None:
    """Entry point for S04E05 foodwarehouse task."""
    setup_logging()

    if not docker_available():
        msg = "Docker CLI not found on PATH \u2014 Daytona self-hosted requires docker compose"
        raise RuntimeError(msg)

    logger.info("[bold cyan]S04E05 foodwarehouse \u2014 starting[/]")
    _WORKSPACE.mkdir(parents=True, exist_ok=True)

    with langfuse_session("S04E05_foodwarehouse") as session_id:
        logger.info("[bold cyan]session=%s[/]", session_id)
        with FoodwarehouseSandbox(log_file=_SESSION_LOG) as sandbox:
            result = run_agent(sandbox, _WORKSPACE)
        logger.info("[bold green]Final result: %s[/]", result)


if __name__ == "__main__":
    run()
