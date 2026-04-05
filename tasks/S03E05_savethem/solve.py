"""S03E05 - Save Them: Agent-based route planning for Skolwin mission."""

from __future__ import annotations

import json
import logging
from typing import Any

from lib.hub import submit_answer
from lib.tracing import langfuse_session
from tasks.S03E05_savethem.agents import run_discovery_agent
from tasks.S03E05_savethem.tools import TerrainRules, VehicleConfig, compute_optimal_path, parse_grid

logger = logging.getLogger(__name__)


def _find_marker(grid_raw: list[list[str]], marker: str) -> tuple[int, int]:
    """Find a marker (S or G) position in the raw grid."""
    for r, row in enumerate(grid_raw):
        for c, cell in enumerate(row):
            if cell == marker:
                return (r, c)
    msg = f"Marker '{marker}' not found in grid"
    raise ValueError(msg)


def _build_config(
    discovery: dict[str, Any],
) -> tuple[list[list[str]], tuple[int, int], tuple[int, int], dict[str, VehicleConfig], TerrainRules]:
    """Parse discovery agent output into typed configuration for the pathfinder."""
    # Grid
    grid_raw: list[list[str]] = discovery["map"]
    grid = parse_grid(json.dumps(grid_raw))

    # Start / goal — prefer agent-provided positions, fall back to grid scan
    if discovery.get("start"):
        start = (int(discovery["start"][0]), int(discovery["start"][1]))
    else:
        start = _find_marker(grid_raw, "S")

    if discovery.get("goal"):
        goal = (int(discovery["goal"][0]), int(discovery["goal"][1]))
    else:
        goal = _find_marker(grid_raw, "G")

    # Vehicles
    vehicles_raw: dict[str, dict[str, Any]] = discovery["vehicles"]
    vehicles: dict[str, VehicleConfig] = {
        name: VehicleConfig(name=name, fuel_cost=float(v["fuel_cost"]), food_cost=float(v["food_cost"]))
        for name, v in vehicles_raw.items()
    }

    # Terrain rules
    water_blocked = frozenset(str(v) for v in discovery.get("water_blocked", []))
    tree_penalty_raw: dict[str, Any] = discovery.get("tree_fuel_penalty", {})
    tree_fuel_penalty: dict[str, float] = {str(k): float(v) for k, v in tree_penalty_raw.items()}
    terrain = TerrainRules(water_blocked=water_blocked, tree_fuel_penalty=tree_fuel_penalty)

    return grid, start, goal, vehicles, terrain


def main() -> None:
    """Solve S03E05: discover data via agent, compute optimal route, submit."""
    with langfuse_session("S03E05_savethem") as session_id:
        logger.info("[bold cyan]S03E05_savethem | session=%s[/]", session_id)

        # Phase 1: Discovery agent fetches map, vehicles, terrain rules
        discovery = run_discovery_agent()
        logger.info("[bold green]Discovery result keys: %s[/]", list(discovery.keys()))

        # Phase 2: Build typed config from discovery
        grid, start, goal, vehicles, terrain = _build_config(discovery)
        logger.info("Start=%s  Goal=%s  Vehicles=%s", start, goal, list(vehicles.keys()))
        logger.info("Water-blocked=%s  Tree-penalty=%s", terrain.water_blocked, terrain.tree_fuel_penalty)

        # Phase 3: Deterministic A* pathfinding
        result = compute_optimal_path(
            grid, start, goal, "auto", fuel=10.0, food=10.0, vehicles=vehicles, terrain=terrain
        )
        logger.info("Pathfinder result: %s", result)

        if not result.get("success"):
            logger.warning("[bold red]No route found: %s[/]", result.get("reason"))
            return

        vehicle = str(result["vehicle"])
        path: list[str] = [str(p) for p in result["path"]]
        route = [vehicle, *path]
        logger.info("[bold green]Route (%d entries): %s[/]", len(route), route)

        submit_answer("savethem", route)
