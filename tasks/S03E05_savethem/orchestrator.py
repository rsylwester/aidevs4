"""S03E05 orchestrator — LLM-driven agent that delegates to sub-agents."""

from __future__ import annotations

import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from lib.llm import get_llm
from tasks.S03E05_savethem import agents

logger = logging.getLogger(__name__)

_ORCHESTRATOR_MODEL = "openai/gpt-5.4"
_MAX_STEPS = 15

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are the mission commander for a rescue operation. Your emissary must travel \
from a base to the city of Skolwin. You must plan an optimal route.

## What you know
- The map is a 10x10 grid. You need to fetch it first.
- Start position and goal position are on the map (marked S and G).
- You have 10 fuel and 10 food.
- Vehicles have different fuel/food consumption rates per move.
- Some terrain blocks certain vehicles (water blocks rocket/car; rocks block all).
- Trees add +0.2 fuel penalty for powered vehicles (rocket, car).
- You can "dismount" mid-route to switch to walking (one-way, cannot remount).

## Your tools
1. **create_agent(role, goal, tools)** — Spawn a specialist sub-agent. Available tool \
names for sub-agents: "call_hub_api", "compute_optimal_path"
2. **submit_route(route)** — Submit the final answer.

## Strategy
Execute these phases:

1. **DISCOVER**: Create an agent with tool "call_hub_api" to search for available \
data sources using the toolsearch endpoint. Query: "maps terrain vehicles movement rules".

2. **GATHER MAP**: Create an agent with tool "call_hub_api" to fetch the Skolwin map \
using the maps endpoint. The agent should query "Skolwin" and return the full grid.

3. **GATHER VEHICLES**: Create an agent with tool "call_hub_api" to query vehicle stats. \
It should call the wehicles endpoint (note spelling!) for each vehicle: rocket, car, \
horse, walk. Return all stats in a structured format.

4. **COMPUTE ROUTE**: Create an agent with tool "compute_optimal_path" to find the \
optimal route. Pass it the grid as JSON, start position, goal position, vehicle="auto" \
(tries all vehicles), fuel=10, food=10. The pathfinder uses A* and handles dismount \
automatically.

5. **SUBMIT**: Once you have the optimal path, call submit_route with the route array. \
The array format is: ["vehicle_name", "direction1", "direction2", ...]. If the path \
includes "dismount", include it at the right position.

Be methodical and efficient. Each sub-agent costs time and tokens.
"""

# ---------------------------------------------------------------------------
# Tool schemas
# ---------------------------------------------------------------------------

_CREATE_AGENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "create_agent",
        "description": (
            "Create a specialist sub-agent to perform a specific task autonomously. "
            "The agent runs with the given tools and returns its findings as text."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "role": {
                    "type": "string",
                    "description": "Agent role description (e.g., 'map researcher', 'route planner')",
                },
                "goal": {
                    "type": "string",
                    "description": "Detailed goal and instructions for the agent",
                },
                "tools": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["call_hub_api", "compute_optimal_path"]},
                    "description": "Tool names available to the sub-agent",
                },
            },
            "required": ["role", "goal", "tools"],
        },
    },
}

_SUBMIT_ROUTE_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "submit_route",
        "description": (
            "Submit the final route answer. The route is a JSON array starting with "
            'the vehicle name, followed by directions. Example: ["car", "up", "right", "dismount", "right"]'
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "route": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Route array: [vehicle_name, direction1, direction2, ...]",
                },
            },
            "required": ["route"],
        },
    },
}

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _ToolCall(BaseModel):
    """Parsed tool call from LLM response."""

    id: str
    name: str
    args: dict[str, Any] = Field(default_factory=dict)


def _extract_tool_calls(response_msg: Any) -> list[_ToolCall]:
    """Extract tool calls from a LangChain AIMessage."""
    raw_calls: list[dict[str, Any]] = getattr(response_msg, "tool_calls", []) or []
    return [
        _ToolCall(
            id=str(tc.get("id", "")),
            name=str(tc.get("name", "")),
            args=tc.get("args", {}),
        )
        for tc in raw_calls
    ]


def _extract_string_list(raw: Any) -> list[str]:
    """Safely extract a list of strings from an Any-typed tool argument."""
    if isinstance(raw, str):
        return [raw]
    try:
        items: list[Any] = list(raw)
        return [str(i) for i in items]
    except TypeError:
        return []


def _get_content(response_msg: Any) -> str:
    """Extract text content from a LangChain AIMessage."""
    content: Any = getattr(response_msg, "content", "")
    if isinstance(content, str):
        return content
    return str(content)


# ---------------------------------------------------------------------------
# Orchestrator loop
# ---------------------------------------------------------------------------


def run_orchestrator() -> list[str]:
    """Run the orchestrator agent. Returns the route as a list of strings."""
    logger.info("[bold cyan]== Orchestrator starting ==[/]")
    t0 = time.monotonic()

    llm = get_llm(model=_ORCHESTRATOR_MODEL)
    llm_with_tools = llm.bind(tools=[_CREATE_AGENT_SCHEMA, _SUBMIT_ROUTE_SCHEMA])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Begin the rescue mission. "
                "Discover available tools, gather the map and vehicle data, "
                "compute the optimal route, and submit it."
            ),
        },
    ]

    for step in range(1, _MAX_STEPS + 1):
        logger.info("[bold]-- Orchestrator step %d/%d --[/]", step, _MAX_STEPS)

        response = llm_with_tools.invoke(messages)
        messages.append(response)  # type: ignore[arg-type]

        # Log any reasoning text
        content = _get_content(response)
        if content:
            logger.info("[magenta]Orchestrator: %s[/]", content[:500])

        tool_calls = _extract_tool_calls(response)

        if not tool_calls:
            logger.info("[yellow]No tool calls — orchestrator finished reasoning[/]")
            continue

        for tc in tool_calls:
            match tc.name:
                case "create_agent":
                    role = str(tc.args.get("role", "specialist"))
                    goal = str(tc.args.get("goal", ""))
                    tool_names = _extract_string_list(tc.args.get("tools", []))
                    agent_result = agents.run_sub_agent(role=role, goal=goal, available_tools=tool_names)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": agent_result})

                case "submit_route":
                    route = _extract_string_list(tc.args.get("route", []))
                    elapsed = time.monotonic() - t0
                    logger.info("[bold green]== Route submitted in %.1fs: %s ==[/]", elapsed, route)
                    return route

                case _:
                    logger.warning("[red]Unknown tool call: %s[/]", tc.name)
                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": f"Unknown tool: {tc.name}"})

    elapsed = time.monotonic() - t0
    logger.warning("[bold red]Orchestrator hit max steps (%d) in %.1fs[/]", _MAX_STEPS, elapsed)
    return []
