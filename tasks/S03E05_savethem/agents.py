"""S03E05 discovery agent — single LLM agent that discovers map, vehicles, and terrain rules."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any, cast

from pydantic import BaseModel, Field

from lib.llm import get_llm
from tasks.S03E05_savethem.tools import CALL_HUB_API_SCHEMA, call_hub_api

logger = logging.getLogger(__name__)

_DISCOVERY_MODEL = "openai/gpt-5.4"
_MAX_STEPS = 20

# ---------------------------------------------------------------------------
# System prompt — tells the agent WHAT to discover, not the answers
# ---------------------------------------------------------------------------

_SYSTEM_PROMPT = """\
You are a reconnaissance agent for a rescue mission to Skolwin.

Your job: discover all information needed to plan an optimal route.

## What you know
- The map is a 10x10 grid (fetch it via the maps API, query "Skolwin").
- Markers on the map: S = start position, G = goal position.
- Resources available: 10 fuel and 10 food.
- The 'toolsearch' endpoint discovers available APIs (returns top 3 matches).
- All discovered endpoints accept the same interface: POST with {"apikey": ..., "query": ...}.

## What you must discover
1. Available API endpoints — use toolsearch with relevant keywords.
2. The Skolwin map grid — fetch it from the maps endpoint.
3. Vehicle stats — query for vehicle information. Find out fuel_cost and food_cost per move \
for each available vehicle.
4. Terrain interaction rules — which vehicles are blocked by which terrain types, \
any fuel penalties for specific terrain.
5. Movement rules — can you switch vehicles mid-route? What are the constraints?

## Strategy
- Start by calling toolsearch to discover available endpoints and what queries they accept.
- Then fetch the map and vehicle/terrain data from the discovered endpoints.
- Query multiple times if needed — each endpoint returns only the top 3 matches per query.
- Read API error responses carefully — they often contain hints about valid queries.
- Try different keywords if a query returns no results or an error.
- Be thorough: make sure you have data for ALL vehicles and ALL terrain interactions.

## Output format
When you have gathered ALL needed information, respond with ONLY a JSON object (no markdown, \
no explanation):
{
  "map": [[row0_cells], [row1_cells], ...],
  "start": [row, col],
  "goal": [row, col],
  "vehicles": {
    "vehicle_name": {"fuel_cost": <float>, "food_cost": <float>},
    ...
  },
  "water_blocked": ["vehicle1", ...],
  "tree_fuel_penalty": {"vehicle1": <penalty_float>, ...}
}
"""


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


def _get_content(response_msg: Any) -> str:
    """Extract text content from a LangChain AIMessage."""
    content: Any = getattr(response_msg, "content", "")
    return content if isinstance(content, str) else str(content)


# ---------------------------------------------------------------------------
# Output parser — robust JSON extraction from LLM response
# ---------------------------------------------------------------------------


def parse_agent_output(content: str) -> dict[str, Any]:
    """Extract structured JSON from the agent's final response.

    Handles raw JSON, ```json code blocks, and JSON embedded in prose.
    """

    def _try_parse(text: str) -> dict[str, Any] | None:
        try:
            parsed: Any = json.loads(text.strip())
        except json.JSONDecodeError:
            return None
        if not isinstance(parsed, dict):
            return None
        return cast("dict[str, Any]", parsed)

    # Try raw JSON
    if (result := _try_parse(content)) is not None:
        return result

    # Try ```json ... ``` blocks
    code_block = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", content, re.DOTALL)
    if code_block and (result := _try_parse(code_block.group(1))) is not None:
        return result

    # Try first { ... last }
    first_brace = content.find("{")
    last_brace = content.rfind("}")
    if (
        first_brace != -1
        and last_brace > first_brace
        and (result := _try_parse(content[first_brace : last_brace + 1])) is not None
    ):
        return result

    msg = f"Failed to parse agent output as JSON: {content[:200]}"
    raise ValueError(msg)


# ---------------------------------------------------------------------------
# Discovery agent runner
# ---------------------------------------------------------------------------


def run_discovery_agent() -> dict[str, Any]:
    """Run the discovery agent. Returns parsed structured data about map, vehicles, and terrain."""
    logger.info("[bold cyan]== Discovery agent starting ==[/]")
    t0 = time.monotonic()

    llm = get_llm(model=_DISCOVERY_MODEL)
    llm_with_tools = llm.bind(tools=[CALL_HUB_API_SCHEMA])

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Discover all available tools, fetch the Skolwin map, and gather complete "
                "vehicle stats and terrain rules. Return the structured JSON when done."
            ),
        },
    ]

    for step in range(1, _MAX_STEPS + 1):
        logger.info("[dim]  Discovery agent step %d/%d[/]", step, _MAX_STEPS)

        response = llm_with_tools.invoke(messages)
        messages.append(response)  # type: ignore[arg-type]

        tool_calls = _extract_tool_calls(response)

        if not tool_calls:
            content = _get_content(response)
            elapsed = time.monotonic() - t0
            logger.info("[bold cyan]== Discovery agent done in %.1fs ==[/]", elapsed)
            return parse_agent_output(content)

        for tc in tool_calls:
            if tc.name == "call_hub_api":
                endpoint = str(tc.args.get("endpoint", ""))
                query = str(tc.args.get("query", ""))
                result_str = call_hub_api(endpoint, query)
            else:
                result_str = json.dumps({"error": f"Unknown tool: {tc.name}"})

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

    elapsed = time.monotonic() - t0
    logger.warning("[bold red]Discovery agent hit max steps (%d) in %.1fs[/]", _MAX_STEPS, elapsed)
    # Try to parse the last content anyway
    last_content = _get_content(messages[-1]) if messages else ""
    return parse_agent_output(last_content)
