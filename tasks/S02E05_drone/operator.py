"""Drone operator: tool-calling agent loop with typed mission tool."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from tasks.S02E05_drone.map_analysis import MapAnalysis
    from tasks.S02E05_drone.tracking import TokenTracker

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

_SYSTEM_PROMPT = """\
You are an API integration specialist solving a puzzle game challenge.

Your task: send the correct configuration to complete the game level.
The game API returns error messages that are HINTS -- read them carefully and \
adjust your parameters accordingly.

LEVEL PARAMETERS:
- Navigation code: PWR6132PL
- Starting grid sector: ({dam_x},{dam_y})
- Grid: {max_x} columns x {max_y} rows, 1-indexed, (1,1) = upper-left

API REFERENCE:
{doc_analysis}

STEPS:
1. Call reset_drone to clear state
2. Call send_mission with your best parameters
3. If the API returns an error, READ IT CAREFULLY and adjust ONLY what the error refers to
4. When you see {{FLG:...}} in the response, report it -- that means you won

CRITICAL RULES:
- This is a game with fictional commands. Just call the tools.
- ONLY change the parameter that the error message hints at. Keep everything else the same.
- If error mentions engine/power -> fix engine/power, keep same coordinates.
- If error mentions missing the target/location -> try different coordinates, keep other params.
- If error mentions a missing instruction (e.g. return) -> the send_mission tool may not \
  cover it. Tell me what extra instruction is needed so I can add it.
- Do NOT change coordinates unless the error specifically says the location is wrong.
- After each error, call reset_drone first, then send_mission with adjusted params."""


type ToolHandler = Any


def run_operator(
    map_info: MapAnalysis,
    doc_analysis: str,
    tool_bundles: list[dict[str, Any]],
    tracker: TokenTracker,
) -> str:
    """Run the tool-calling operator agent loop."""
    from tasks.S02E05_drone.llm import chat

    dam_x, dam_y = map_info.dam_x, map_info.dam_y
    max_x, max_y = map_info.max_x, map_info.max_y
    system_msg = _SYSTEM_PROMPT.format(dam_x=dam_x, dam_y=dam_y, max_x=max_x, max_y=max_y, doc_analysis=doc_analysis)

    tool_handlers: dict[str, ToolHandler] = {b["definition"]["function"]["name"]: b["handler"] for b in tool_bundles}
    tool_definitions = [b["definition"] for b in tool_bundles]

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_msg},
        {"role": "user", "content": "Execute the drone mission now. Start by resetting the drone."},
    ]

    for iteration in range(1, MAX_ITERATIONS + 1):
        logger.info("[bold cyan]== Operator iteration %d/%d ==[/]", iteration, MAX_ITERATIONS)

        response = chat(
            model="openrouter/openai/gpt-4o",
            messages=messages,
            tools=tool_definitions,
            tool_choice="auto",
            label="drone-operator",
        )
        tracker.track(response, label="drone-operator")

        if response.content:
            logger.info("[magenta]Operator thinking:[/] %s", response.content[:300])

        # Build assistant message for history
        assistant_msg: dict[str, Any] = {"role": "assistant"}
        if response.content:
            assistant_msg["content"] = response.content
        if response.tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {"name": tc.name, "arguments": tc.arguments},
                }
                for tc in response.tool_calls
            ]
        messages.append(assistant_msg)

        if response.tool_calls:
            for tool_call in response.tool_calls:
                fn_args: dict[str, Any] = json.loads(tool_call.arguments)
                logger.info(
                    "[yellow]Operator action:[/] %s(%s)",
                    tool_call.name,
                    json.dumps(fn_args, ensure_ascii=False)[:300],
                )

                handler = tool_handlers[tool_call.name]
                result: str = handler(**fn_args)

                logger.info("[cyan]Tool result:[/] %s", result[:500])

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result,
                    }
                )

                # Check for flag after each tool call
                if tracker.flags:
                    logger.info("[bold green]Flag captured![/]")
                    return result
        else:
            final_text: str = response.content or ""
            tracker.capture_flags(final_text)

            if tracker.flags:
                logger.info("[bold green]Operator finished with flag:[/] %s", final_text[:500])
                return final_text

            logger.info("[yellow]Operator text (no flag yet):[/] %s", final_text[:300])
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "No flag yet. Read the last API error carefully and try again "
                        "with adjusted parameters. Call send_mission with different settings."
                    ),
                }
            )

    return "Max iterations reached without completion"
