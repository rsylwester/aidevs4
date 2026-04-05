"""S03E05 tools — Hub API wrappers, A* pathfinder, and tool schemas."""

from __future__ import annotations

import heapq
import json
import logging
from dataclasses import dataclass, field
from typing import Any

import httpx

from settings import settings

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Hub API caller
# ---------------------------------------------------------------------------

_HUB_API_BASE = f"{settings.aidevs_hub_url}/api"


def call_hub_api(endpoint: str, query: str) -> str:
    """POST to a hub API endpoint and return the JSON response as a string."""
    url = f"{_HUB_API_BASE}/{endpoint}"
    payload: dict[str, str] = {"apikey": settings.aidevs_key, "query": query}
    logger.info("[yellow]>> hub API %s query=%r[/]", endpoint, query)
    try:
        resp = httpx.post(url, json=payload, timeout=30)
        resp.raise_for_status()
        data: Any = resp.json()
        logger.info("[cyan]<< hub API %s: %s[/]", endpoint, str(data)[:300])
        return json.dumps(data, ensure_ascii=False)
    except httpx.HTTPError as exc:
        msg = f"Hub API error for {endpoint}: {exc}"
        logger.warning("[red]%s[/]", msg)
        return json.dumps({"error": msg})


# ---------------------------------------------------------------------------
# Map parser
# ---------------------------------------------------------------------------


def parse_grid(raw: str) -> list[list[str]]:
    """Parse a hub map response into a 10x10 grid of single characters.

    Handles both plain-text (newline-separated rows) and JSON array formats.
    Normalizes S/G to '.' (passable terrain).
    """
    # Try JSON array first
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None

    if isinstance(parsed, list):
        return _normalize_grid(_json_to_grid(parsed))

    # Plain text: split by newlines
    lines = [line.strip() for line in raw.strip().splitlines() if line.strip()]
    rows = [list(line) for line in lines]
    return _normalize_grid(rows)


def _json_to_grid(data: Any) -> list[list[str]]:
    """Convert a JSON-parsed list of rows into a typed string grid."""
    serialized: str = json.dumps(data)
    rows_typed: list[str] = json.loads(serialized)
    return [list(row) for row in rows_typed]


def _normalize_grid(grid: list[list[str]]) -> list[list[str]]:
    """Replace S and G with passable terrain markers."""
    for r, row in enumerate(grid):
        for c, cell in enumerate(row):
            if cell in ("S", "G"):
                grid[r][c] = "."
    return grid


# ---------------------------------------------------------------------------
# A* pathfinder
# ---------------------------------------------------------------------------

_VEHICLE_COSTS: dict[str, tuple[float, float]] = {
    "rocket": (1.0, 0.1),
    "car": (0.7, 1.0),
    "horse": (0.0, 1.6),
    "walk": (0.0, 2.5),
}

_POWERED_VEHICLES: frozenset[str] = frozenset({"rocket", "car"})
_WATER_BLOCKED: frozenset[str] = frozenset({"rocket", "car"})

_DIRECTIONS: list[tuple[str, int, int]] = [
    ("up", -1, 0),
    ("down", 1, 0),
    ("left", 0, -1),
    ("right", 0, 1),
]

_EPS: float = 1e-9


@dataclass(order=True)
class _Node:
    f_cost: float
    g_cost: float = field(compare=False)
    row: int = field(compare=False)
    col: int = field(compare=False)
    mode: str = field(compare=False)
    fuel: float = field(compare=False)
    food: float = field(compare=False)
    path: tuple[str, ...] = field(compare=False)


def _manhattan(r1: int, c1: int, r2: int, c2: int) -> float:
    return float(abs(r1 - r2) + abs(c1 - c2))


def _is_dominated(
    frontier: dict[tuple[int, int, str], list[tuple[float, float]]],
    key: tuple[int, int, str],
    fuel: float,
    food: float,
) -> bool:
    """Check if (fuel, food) is dominated by any point in the Pareto frontier for this key."""
    if key not in frontier:
        return False
    return any(f >= fuel - _EPS and d >= food - _EPS for f, d in frontier[key])


def _add_to_frontier(
    frontier: dict[tuple[int, int, str], list[tuple[float, float]]],
    key: tuple[int, int, str],
    fuel: float,
    food: float,
) -> None:
    """Add (fuel, food) to the Pareto frontier, removing dominated points."""
    if key not in frontier:
        frontier[key] = [(fuel, food)]
        return
    # Remove points dominated by the new one
    frontier[key] = [(f, d) for f, d in frontier[key] if not (fuel >= f - _EPS and food >= d - _EPS)]
    frontier[key].append((fuel, food))


def _astar(
    grid: list[list[str]],
    start: tuple[int, int],
    goal: tuple[int, int],
    vehicle: str,
    fuel: float,
    food: float,
) -> dict[str, Any]:
    """Run A* search for a single vehicle configuration."""
    rows = len(grid)
    cols = len(grid[0]) if grid else 0
    sr, sc = start
    gr, gc = goal

    frontier: dict[tuple[int, int, str], list[tuple[float, float]]] = {}
    h = _manhattan(sr, sc, gr, gc)
    start_node = _Node(f_cost=h, g_cost=0.0, row=sr, col=sc, mode=vehicle, fuel=fuel, food=food, path=())

    heap: list[_Node] = [start_node]
    _add_to_frontier(frontier, (sr, sc, vehicle), fuel, food)

    while heap:
        node = heapq.heappop(heap)

        # Goal check
        if node.row == gr and node.col == gc:
            return {
                "success": True,
                "vehicle": vehicle,
                "path": list(node.path),
                "fuel_remaining": round(node.fuel, 2),
                "food_remaining": round(node.food, 2),
                "moves": len([p for p in node.path if p != "dismount"]),
            }

        # Skip if this state is now dominated
        key = (node.row, node.col, node.mode)
        if _is_dominated(frontier, key, node.fuel - _EPS * 2, node.food - _EPS * 2):
            # Only skip if strictly dominated (our resources are less than stored)
            pass  # Still process — Pareto check at insertion handles pruning

        # Generate neighbors: 4 directions + dismount
        neighbors: list[tuple[str, int, int, str, float, float]] = []

        # Cardinal directions
        for direction, dr, dc in _DIRECTIONS:
            nr, nc = node.row + dr, node.col + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            tile = grid[nr][nc]

            # Rock blocks all
            if tile == "R":
                continue
            # Water blocks powered vehicles
            if tile == "W" and node.mode in _WATER_BLOCKED:
                continue

            fuel_cost, food_cost = _VEHICLE_COSTS[node.mode]
            # Tree penalty for powered vehicles
            if tile == "T" and node.mode in _POWERED_VEHICLES:
                fuel_cost += 0.2

            new_fuel = node.fuel - fuel_cost
            new_food = node.food - food_cost
            if new_fuel < -_EPS or new_food < -_EPS:
                continue

            neighbors.append((direction, nr, nc, node.mode, new_fuel, new_food))

        # Dismount: switch to walk mode (zero cost, same position)
        if node.mode != "walk":
            neighbors.append(("dismount", node.row, node.col, "walk", node.fuel, node.food))

        for action, nr, nc, mode, nfuel, nfood in neighbors:
            nkey = (nr, nc, mode)
            if _is_dominated(frontier, nkey, nfuel, nfood):
                continue

            _add_to_frontier(frontier, nkey, nfuel, nfood)
            new_g = node.g_cost + (0.0 if action == "dismount" else 1.0)
            new_h = _manhattan(nr, nc, gr, gc)
            new_path = (*node.path, action)
            new_node = _Node(
                f_cost=new_g + new_h,
                g_cost=new_g,
                row=nr,
                col=nc,
                mode=mode,
                fuel=nfuel,
                food=nfood,
                path=new_path,
            )
            heapq.heappush(heap, new_node)

    return {"success": False, "vehicle": vehicle, "reason": "No path found — resources exhausted or blocked"}


def compute_optimal_path(
    grid: list[list[str]],
    start: tuple[int, int],
    goal: tuple[int, int],
    vehicle: str,
    fuel: float,
    food: float,
) -> str:
    """Compute optimal route using A*. Returns JSON result string.

    Set vehicle to 'auto' to try all vehicles and return the best result.
    """
    if vehicle == "auto":
        best: dict[str, Any] | None = None
        for v in _VEHICLE_COSTS:
            result = _astar(grid, start, goal, v, fuel, food)
            if result["success"] and (
                best is None
                or result["moves"] < best["moves"]
                or (
                    result["moves"] == best["moves"]
                    and (result["fuel_remaining"] + result["food_remaining"])
                    > (best["fuel_remaining"] + best["food_remaining"])
                )
            ):
                best = result
        if best:
            return json.dumps(best, ensure_ascii=False)
        return json.dumps({"success": False, "reason": "No vehicle can reach the goal with available resources"})

    result = _astar(grid, start, goal, vehicle, fuel, food)
    return json.dumps(result, ensure_ascii=False)


# ---------------------------------------------------------------------------
# Tool schemas (OpenAI function-calling format)
# ---------------------------------------------------------------------------

CALL_HUB_API_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "call_hub_api",
        "description": (
            "Call a hub API endpoint. Known endpoints: "
            "toolsearch (discover tools by query), "
            "maps (get 10x10 city grid map), "
            "wehicles (get vehicle stats — note the spelling), "
            "books (search archive notes). "
            "Send a natural language or keyword query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "description": "API endpoint name",
                },
                "query": {
                    "type": "string",
                    "description": "Query string for the endpoint",
                },
            },
            "required": ["endpoint", "query"],
        },
    },
}

COMPUTE_PATH_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "compute_optimal_path",
        "description": (
            "Compute optimal route on a 10x10 grid using A* pathfinding. "
            "Accounts for fuel, food, vehicle constraints, terrain penalties, "
            "water/rock blocking, and dismount option. "
            "Set vehicle to 'auto' to try all vehicles and get the best route."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "grid_json": {
                    "type": "string",
                    "description": 'JSON 2D array of the grid, e.g. [[".","R",...],...]',
                },
                "start_row": {"type": "integer", "description": "Start row (0-indexed)"},
                "start_col": {"type": "integer", "description": "Start column (0-indexed)"},
                "goal_row": {"type": "integer", "description": "Goal row (0-indexed)"},
                "goal_col": {"type": "integer", "description": "Goal column (0-indexed)"},
                "vehicle": {
                    "type": "string",
                    "enum": ["rocket", "car", "horse", "walk", "auto"],
                    "description": "Vehicle to use. 'auto' tries all and returns the best.",
                },
                "fuel": {"type": "number", "description": "Available fuel (default 10)"},
                "food": {"type": "number", "description": "Available food (default 10)"},
            },
            "required": ["grid_json", "start_row", "start_col", "goal_row", "goal_col", "vehicle", "fuel", "food"],
        },
    },
}

# Mapping of tool name → schema for easy lookup
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "call_hub_api": CALL_HUB_API_SCHEMA,
    "compute_optimal_path": COMPUTE_PATH_SCHEMA,
}
