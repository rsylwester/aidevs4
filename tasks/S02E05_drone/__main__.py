"""S02E05 - drone: Program a drone to reach the dam near Zarnowiec power plant."""

from __future__ import annotations

import logging
from pathlib import Path

from lib.logging import setup_logging
from lib.tracing import langfuse_session
from tasks.S02E05_drone.map_analysis import identify_dam_coordinates
from tasks.S02E05_drone.operator import run_operator
from tasks.S02E05_drone.resources import analyze_documentation, convert_html_to_markdown, ensure_resources
from tasks.S02E05_drone.tools import make_reset_drone, make_send_mission
from tasks.S02E05_drone.tracking import TokenTracker

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent / ".workspace"
RESOURCES = WORKSPACE / "resources"


def run() -> None:
    setup_logging()
    WORKSPACE.mkdir(exist_ok=True)
    RESOURCES.mkdir(exist_ok=True)

    with langfuse_session("S02E05-drone") as session_id:
        logger.info("[bold cyan]S02E05-drone | session=%s[/]", session_id)
        tracker = TokenTracker()

        # Step 1: Download and prepare resources
        logger.info("[bold]== Resource preparation ==[/]")
        ensure_resources(RESOURCES)
        convert_html_to_markdown(RESOURCES)
        doc_analysis = analyze_documentation(RESOURCES, tracker)

        # Step 2: Detect grid + identify dam coordinates
        logger.info("[bold]== Map analysis ==[/]")
        map_info = identify_dam_coordinates(RESOURCES, tracker)
        logger.info(
            "[bold cyan]Dam at (%d, %d), grid %dx%d[/]",
            map_info.dam_x,
            map_info.dam_y,
            map_info.max_x,
            map_info.max_y,
        )

        # Step 3: Run operator agent with reset + mission tools
        logger.info("[bold]== Drone operator ==[/]")
        tool_bundles = [make_reset_drone(tracker), make_send_mission(tracker)]
        result = run_operator(map_info, doc_analysis, tool_bundles, tracker)

        # Step 4: Summary
        tracker.log_summary()
        logger.info("[bold green]Final result: %s[/]", result[:500])


if __name__ == "__main__":
    run()
