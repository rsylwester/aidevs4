"""S03E05 sub-agent runner — spawns LLM-driven agents with dynamic system prompts."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from lib.llm import get_llm
from tasks.S03E05_savethem import tools

logger = logging.getLogger(__name__)

_SUB_AGENT_MODEL = "openai/gpt-5.4-mini"


# ---------------------------------------------------------------------------
# Helpers (adapted from S03E03 reactor agent pattern)
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
            args={k: str(v) for k, v in tc.get("args", {}).items()},
        )
        for tc in raw_calls
    ]


def _get_content(response_msg: Any) -> str:
    """Extract text content from a LangChain AIMessage."""
    content: Any = getattr(response_msg, "content", "")
    if isinstance(content, str):
        return content
    return str(content)


# ---------------------------------------------------------------------------
# Tool dispatching
# ---------------------------------------------------------------------------


def _dispatch_call_hub_api(args: dict[str, Any]) -> str:
    """Dispatch a call_hub_api tool call."""
    endpoint = str(args.get("endpoint", ""))
    query = str(args.get("query", ""))
    return tools.call_hub_api(endpoint, query)


def _dispatch_compute_path(args: dict[str, Any]) -> str:
    """Dispatch a compute_optimal_path tool call."""
    grid_json = str(args.get("grid_json", "[]"))
    grid = tools.parse_grid(grid_json)
    start = (int(args.get("start_row", 0)), int(args.get("start_col", 0)))
    goal = (int(args.get("goal_row", 0)), int(args.get("goal_col", 0)))
    vehicle = str(args.get("vehicle", "auto"))
    fuel = float(args.get("fuel", 10.0))
    food = float(args.get("food", 10.0))
    return tools.compute_optimal_path(grid, start, goal, vehicle, fuel, food)


_TOOL_DISPATCHERS: dict[str, Any] = {
    "call_hub_api": _dispatch_call_hub_api,
    "compute_optimal_path": _dispatch_compute_path,
}


# ---------------------------------------------------------------------------
# Sub-agent runner
# ---------------------------------------------------------------------------


def run_sub_agent(
    role: str,
    goal: str,
    available_tools: list[str],
    *,
    max_steps: int = 10,
) -> str:
    """Spawn a sub-agent with a dynamic system prompt and run it to completion.

    The agent runs autonomously for up to *max_steps*, calling tools as needed,
    and returns its final text response.
    """
    logger.info("[bold magenta]>> Sub-agent [%s] spawned | tools=%s[/]", role, available_tools)
    t0 = time.monotonic()

    # Build system prompt
    system_prompt = (
        f"You are a specialist agent with the role: {role}.\n\n"
        f"Your goal: {goal}\n\n"
        "Use the available tools to accomplish your goal. "
        "When you have gathered all needed information or computed the result, "
        "respond with a clear, structured summary of your findings. "
        "Do NOT call tools unnecessarily — be efficient."
    )

    # Select tool schemas
    selected_schemas: list[dict[str, Any]] = [
        tools.TOOL_SCHEMAS[name] for name in available_tools if name in tools.TOOL_SCHEMAS
    ]

    llm = get_llm(model=_SUB_AGENT_MODEL)
    llm_with_tools = llm.bind(tools=selected_schemas) if selected_schemas else llm

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": goal},
    ]

    for step in range(1, max_steps + 1):
        logger.info("[dim]  Sub-agent [%s] step %d/%d[/]", role, step, max_steps)

        response = llm_with_tools.invoke(messages)
        messages.append(response)  # type: ignore[arg-type]

        tool_calls = _extract_tool_calls(response)

        if not tool_calls:
            # Agent is done — return its content
            content = _get_content(response)
            elapsed = time.monotonic() - t0
            logger.info("[bold magenta]<< Sub-agent [%s] done in %.1fs[/]", role, elapsed)
            return content

        # Dispatch tool calls
        for tc in tool_calls:
            dispatcher = _TOOL_DISPATCHERS.get(tc.name)
            if dispatcher is None:
                result_str = json.dumps({"error": f"Unknown tool: {tc.name}"})
            else:
                result_str = dispatcher(tc.args)

            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

    # Max steps reached — return whatever we have
    elapsed = time.monotonic() - t0
    logger.warning("[yellow]Sub-agent [%s] hit max steps (%d) in %.1fs[/]", role, max_steps, elapsed)
    last_content = _get_content(messages[-1]) if messages else "No result"
    return f"[Max steps reached] {last_content}"
