"""S03E05 tools — Hub API wrapper, grid parser, and parameterized A* pathfinder."""

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
        data: Any = resp.json()
        logger.info("[cyan]<< hub API %s (HTTP %d): %s[/]", endpoint, resp.status_code, str(data)[:300])
        return json.dumps(data, ensure_ascii=False)
    except httpx.HTTPError as exc:
        msg = f"Hub API error for {endpoint}: {exc}"
        logger.warning("[red]%s[/]", msg)
        return json.dumps({"error": msg})


# ---------------------------------------------------------------------------
# Map parser
# ---------------------------------------------------------------------------


def parse_grid(raw: str) -> list[list[str]]:
    """Parse a hub map response into a grid of single characters.

    Handles both plain-text (newline-separated rows) and JSON array formats.
    Normalizes S/G to '.' (passable terrain).
    """
    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = None

    if isinstance(parsed, list):
        return _normalize_grid(_json_to_grid(parsed))

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
# Dynamic vehicle / terrain configuration
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class VehicleConfig:
    """Per-move costs for a vehicle, discovered from the wehicles API."""

    name: str
    fuel_cost: float
    food_cost: float


@dataclass(frozen=True)
class TerrainRules:
    """Movement rules per terrain type, discovered from API."""

    water_blocked: frozenset[str]
    tree_fuel_penalty: dict[str, float]


# ---------------------------------------------------------------------------
# A* pathfinder (parameterized — no hardcoded vehicle/terrain data)
# ---------------------------------------------------------------------------

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
    frontier[key] = [(f, d) for f, d in frontier[key] if not (fuel >= f - _EPS and food >= d - _EPS)]
    frontier[key].append((fuel, food))


def _astar(
    grid: list[list[str]],
    start: tuple[int, int],
    goal: tuple[int, int],
    vehicle: str,
    fuel: float,
    food: float,
    vehicles: dict[str, VehicleConfig],
    terrain: TerrainRules,
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

    walk_config = vehicles.get("walk")

    while heap:
        node = heapq.heappop(heap)

        if node.row == gr and node.col == gc:
            return {
                "success": True,
                "vehicle": vehicle,
                "path": list(node.path),
                "fuel_remaining": round(node.fuel, 2),
                "food_remaining": round(node.food, 2),
                "moves": len([p for p in node.path if p != "dismount"]),
            }

        key = (node.row, node.col, node.mode)
        if _is_dominated(frontier, key, node.fuel - _EPS * 2, node.food - _EPS * 2):
            pass  # Pareto check at insertion handles pruning

        neighbors: list[tuple[str, int, int, str, float, float]] = []

        for direction, dr, dc in _DIRECTIONS:
            nr, nc = node.row + dr, node.col + dc
            if not (0 <= nr < rows and 0 <= nc < cols):
                continue
            tile = grid[nr][nc]

            if tile == "R":
                continue
            if tile == "W" and node.mode in terrain.water_blocked:
                continue

            vc = vehicles[node.mode]
            fuel_cost = vc.fuel_cost
            food_cost = vc.food_cost

            if tile == "T" and node.mode in terrain.tree_fuel_penalty:
                fuel_cost += terrain.tree_fuel_penalty[node.mode]

            new_fuel = node.fuel - fuel_cost
            new_food = node.food - food_cost
            if new_fuel < -_EPS or new_food < -_EPS:
                continue

            neighbors.append((direction, nr, nc, node.mode, new_fuel, new_food))

        if node.mode != "walk" and walk_config is not None:
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
    vehicles: dict[str, VehicleConfig],
    terrain: TerrainRules,
) -> dict[str, Any]:
    """Compute optimal route using A*. Returns result dict.

    Set vehicle to 'auto' to try all vehicles and return the best result.
    """
    if vehicle == "auto":
        best: dict[str, Any] | None = None
        for v in vehicles:
            result = _astar(grid, start, goal, v, fuel, food, vehicles, terrain)
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
        return best or {"success": False, "reason": "No vehicle can reach the goal with available resources"}

    return _astar(grid, start, goal, vehicle, fuel, food, vehicles, terrain)


# ---------------------------------------------------------------------------
# Tool schema for LLM agent (only call_hub_api — pathfinder is not an LLM tool)
# ---------------------------------------------------------------------------

CALL_HUB_API_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "call_hub_api",
        "description": (
            "Call a hub API endpoint. Use the 'toolsearch' endpoint first to discover "
            "available tools and their descriptions. All endpoints accept a 'query' parameter. "
            "Send a natural language or keyword query."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "endpoint": {
                    "type": "string",
                    "description": "API endpoint name (use 'toolsearch' to discover available endpoints)",
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
