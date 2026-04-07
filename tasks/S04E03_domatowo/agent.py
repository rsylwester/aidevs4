"""S04E03 orchestrator agent — Domatowo rescue mission."""

from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from lib.llm import get_llm
from tasks.S04E03_domatowo.tools import ALL_TOOL_SCHEMAS, check_flag, check_points_exhausted, reset_game, send_request

logger = logging.getLogger(__name__)

_MODEL = "google/gemini-2.5-flash"
_MAX_STEPS = 60
_MAX_RETRIES = 3


def _build_system_prompt(help_data: dict[str, Any], lessons: list[str] | None = None) -> str:
    """Build the system prompt with pre-fetched help data and optional lessons from prior attempts."""
    lessons_block = ""
    if lessons:
        joined = "\n".join(f"- {lesson}" for lesson in lessons)
        lessons_block = f"""

## Lessons from previous attempts (CRITICAL — do NOT repeat these mistakes)
{joined}
"""

    return f"""\
You are a tactical rescue agent commanding a mission in the ruined city of Domatowo.

## Mission
Find a partisan hiding in the ruins and evacuate them via helicopter.

## Intercepted radio signal
"I survived. Bombs destroyed the city. Soldiers were here, took the oil. Now it's empty. \
I have a weapon, I'm wounded. I hid in one of the tallest blocks. No food. Help."

KEY CLUE: The partisan is hiding in one of the TALLEST buildings on the map. \
Focus your search on the tallest structures.

## API Reference
```json
{json.dumps(help_data, ensure_ascii=False, indent=2)}
```

## Action costs
- create scout: 5 pts
- create transporter: 5 pts base + 5 pts per passenger scout
- move scout on foot: 7 pts per field
- move transporter: 1 pt per field
- inspect field: 1 pt
- disembark scouts: 0 pts
- Total budget: 300 pts

## Strategy guidelines
1. First call getMap to understand the terrain layout.
2. Analyze the map: identify roads (transporters can only drive on roads/streets) and tall buildings.
3. Use transporters to move scouts cheaply along roads to positions near tall buildings.
4. Disembark scouts and inspect tall building fields.
5. When a scout confirms the partisan's location, immediately call the helicopter to that field.
6. Transporters are MUCH cheaper to move (1pt vs 7pt per field) — always prefer them for travel.
7. Plan routes carefully — you have limited action points.
8. Scouts can walk on any terrain. Transporters can only use roads/streets.

## Important
- Coordinate format is like "A1", "F6", "K11" (column letter + row number).
- When you find the partisan via inspect, call callHelicopter with that field's coordinates.
- Be efficient with action points. Plan before acting.
{lessons_block}"""


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


def _dispatch_tool(name: str, args: dict[str, Any]) -> str:
    """Execute a tool call and return the result string."""
    match name:
        case "send_request":
            action = str(args.get("action", ""))
            payload: dict[str, Any] | None = args.get("payload")
            return send_request(action, payload)
        case _:
            return json.dumps({"error": f"Unknown tool: {name}"})


def _ask_for_lessons(messages: list[Any]) -> str:
    """Ask the LLM to summarize what it learned from a failed attempt."""
    llm = get_llm(model=_MODEL)
    summary_messages: list[dict[str, str]] = [
        {
            "role": "user",
            "content": (
                "The rescue attempt failed (ran out of action points). "
                "Summarize in 2-3 bullet points:\n"
                "1. Which fields/buildings did you inspect and what did you find?\n"
                "2. Which tall buildings remain unchecked?\n"
                "3. What strategy changes would you make next time?\n"
                "Be concise and specific with coordinates."
            ),
        },
    ]
    # Include last ~20 non-tool messages for context
    context: list[dict[str, str]] = []
    for msg in messages[-30:]:
        role: str = str(msg.get("role", "")) if hasattr(msg, "get") else "assistant"
        if role == "tool":
            continue
        c: Any = msg.get("content", "") if hasattr(msg, "get") else getattr(msg, "content", "")
        if isinstance(c, str) and c:
            context.append({"role": role or "user", "content": c})
    response = llm.invoke(context + summary_messages)
    result = _get_content(response)
    logger.info("[yellow]Lessons from failed attempt: %s[/]", result[:500])
    return result


def _run_single_attempt(
    help_data: dict[str, Any],
    lessons: list[str] | None = None,
) -> tuple[str | None, str, str]:
    """Run one attempt. Returns (flag_or_none, last_response, lessons_summary)."""
    system_prompt = _build_system_prompt(help_data, lessons)

    llm = get_llm(model=_MODEL)
    llm_with_tools = llm.bind(tools=ALL_TOOL_SCHEMAS)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "Start the rescue mission. First get the map, analyze it to find tall buildings, "
                "then plan and execute your search strategy efficiently. GO!"
            ),
        },
    ]

    last_response = ""
    flag: str | None = None
    points_exhausted = False

    for step in range(1, _MAX_STEPS + 1):
        logger.info("[dim]  Step %d/%d[/]", step, _MAX_STEPS)

        response = llm_with_tools.invoke(messages)
        messages.append(response)  # type: ignore[arg-type]

        tool_calls = _extract_tool_calls(response)
        content = _get_content(response)

        if content:
            logger.info("[green]  Agent: %s[/]", content[:500])
            last_response = content
            flag = check_flag(content)
            if flag:
                break

        if not tool_calls:
            logger.info("[bold yellow]  Agent stopped calling tools at step %d, nudging...[/]", step)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You still have action points remaining. "
                        "Review the results of your previous inspections and adjust your strategy. "
                        "Try different tall buildings you haven't inspected yet. "
                        "Use getLogs to check what you've done so far. "
                        "Do NOT stop until you find the partisan or run out of action points."
                    ),
                }
            )
            continue

        for tc in tool_calls:
            logger.info("[dim]  Tool: %s(%s)[/]", tc.name, json.dumps(tc.args, ensure_ascii=False)[:300])
            result_str = _dispatch_tool(tc.name, tc.args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

            flag = check_flag(result_str)
            if flag:
                break

            if check_points_exhausted(result_str):
                points_exhausted = True
                logger.warning("[bold red]Action points exhausted![/]")
                break

        if flag or points_exhausted:
            break

    lessons_summary = _ask_for_lessons(messages) if not flag else ""
    return flag, last_response, lessons_summary


def run_agent(help_data: dict[str, Any]) -> str:
    """Run the Domatowo rescue agent with automatic reset+retry on points exhaustion."""
    lessons: list[str] = []
    last_response = ""

    for attempt in range(1, _MAX_RETRIES + 1):
        logger.info("[bold cyan]== Domatowo rescue attempt %d/%d ==[/]", attempt, _MAX_RETRIES)

        flag, attempt_response, lessons_summary = _run_single_attempt(help_data, lessons or None)
        last_response = attempt_response

        if flag:
            logger.info("[bold green]FLAG FOUND: %s[/]", flag)
            return flag

        if attempt < _MAX_RETRIES:
            lessons.append(lessons_summary)
            logger.info("[bold yellow]Resetting game for retry...[/]")
            reset_result = reset_game()
            logger.info("[cyan]Reset result: %s[/]", reset_result[:300])

    logger.warning("[bold yellow]No flag found after %d attempts[/]", _MAX_RETRIES)
    return last_response
