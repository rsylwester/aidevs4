"""S03E03 reactor — LLM agent navigating a robot through oscillating reactor blocks."""

from __future__ import annotations

import json
import logging
import re
import time
from typing import Any

import httpx
from pydantic import BaseModel, Field

from lib.llm import get_llm
from settings import settings

logger = logging.getLogger(__name__)

MAX_STEPS = 50
MAX_RETRIES = 3

SYSTEM_PROMPT = """\
You are a critical mission operator. A nuclear reactor is overheating and you must \
transport the cooling module across the reactor chamber to prevent a meltdown. \
Thousands of lives depend on your success. Be extremely careful — one wrong move \
and the robot carrying the module gets crushed by reactor blocks, causing a catastrophe.

## Situation
- 7x5 grid. Robot starts at column 1, row 5 (bottom-left).
- Goal: reach column 7, row 5 (bottom-right) to install the cooling module.
- Reactor blocks (marked B) are 2 cells tall and oscillate up/down cyclically.
- Blocks ONLY move when you send a command — time does not advance on its own.
- If a block occupies the robot's cell after a move, the robot is CRUSHED.

## Commands
Call the send_command function with exactly one of: start, reset, left, right, wait.
- start: begin new game (always send this first)
- right: move robot one column right
- left: move robot one column left (retreat to safety)
- wait: stay in place (blocks still move — use this to let blocks pass)
- reset: restart the game from scratch

## Map symbols
- P: robot position
- G: goal
- Bv / B^: reactor block moving down / up (2 cells tall)
- . : empty cell

## Required reasoning protocol
Before EVERY command you MUST think through these steps in your response text:

1. **Current state**: Where is the robot? Which columns have blocks? What direction is each block moving?
2. **Predict next state**: After the next tick, where will each block be? \
(Blocks move 1 row in their direction per tick. When they reach the edge, they reverse.)
3. **Evaluate options**: Is column to the right safe after the tick? Is current column safe if I wait? \
Do I need to retreat left?
4. **Decision**: State your chosen command and WHY it is safe.

## Strategy
- First send "start" to begin.
- BEFORE moving right, predict where blocks will be AFTER the move. \
Blocks move simultaneously with your command.
- If the next column has a block that could reach row 5, WAIT until it moves away.
- If your current column becomes dangerous, move LEFT to retreat.
- Never rush. Wait as many turns as needed. Lives depend on this.
"""

# Tool definition for LangChain function calling (OpenAI format)
_TOOL_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "send_command",
        "description": (
            "Send a single command to the reactor robot. "
            "Valid commands: start (begin game), reset (restart), left, right, wait. "
            "Returns an ASCII map showing the grid with block positions and direction arrows (^ up, v down)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "enum": ["start", "reset", "left", "right", "wait"],
                    "description": "The command to send to the robot.",
                }
            },
            "required": ["command"],
        },
    },
}


class _ToolCall(BaseModel):
    """Parsed tool call from LLM response."""

    id: str
    name: str
    args: dict[str, str] = Field(default_factory=dict)


def _send_command(command: str) -> dict[str, Any]:
    """POST a command to the reactor API and return the parsed JSON response."""
    payload: dict[str, Any] = {
        "apikey": settings.aidevs_key,
        "task": "reactor",
        "answer": {"command": command},
    }
    resp = httpx.post(settings.aidevs_verify_address, json=payload, timeout=30)
    data: dict[str, Any] = resp.json()
    return data


def _check_flag(text: str) -> str | None:
    """Extract FLG pattern from text if present."""
    m = re.search(r"\{FLG:.*?}", text)
    return m.group(0) if m else None


def _is_failure(data: dict[str, Any]) -> bool:
    """Check if the API response indicates the robot was crushed."""
    text = json.dumps(data).lower()
    return any(word in text for word in ("crushed", "destroyed", "game over", "lost", "dead", "killed"))


def _is_success(data: dict[str, Any]) -> bool:
    """Check if the API response indicates the robot reached the goal."""
    text = json.dumps(data)
    if _check_flag(text):
        return True
    # Check if player position matches goal position
    player = data.get("player", {})
    goal = data.get("goal", {})
    return bool(player and goal and player.get("col") == goal.get("col") and player.get("row") == goal.get("row"))


def _render_ascii_map(data: dict[str, Any]) -> str:
    """Render the board state as an ASCII map with direction arrows.

    Example output:
        C1  C2  C3  C4  C5  C6  C7
    R1   .   .   .   .  Bv  Bv   .
    R2   .  Bv  Bv  Bv  Bv  Bv   .
    R3   .  Bv  Bv  Bv   .   .   .
    R4   .   .   .   .   .   .   .
    R5   P   .   .   .   .   .   G

    Blocks annotated with ^ (moving up) or v (moving down).
    """
    board: list[list[str]] = data.get("board", [])
    if not board:
        return json.dumps(data, ensure_ascii=False)

    # Build block direction lookup: (row, col) -> direction
    blocks: list[dict[str, Any]] = data.get("blocks", [])
    block_dirs: dict[tuple[int, int], str] = {}
    for blk in blocks:
        col = int(blk["col"])
        direction = str(blk.get("direction", ""))
        arrow = "v" if direction == "down" else "^" if direction == "up" else "?"
        top_row = int(blk["top_row"])
        bottom_row = int(blk["bottom_row"])
        for row in range(top_row, bottom_row + 1):
            block_dirs[(row, col)] = arrow

    num_cols = len(board[0]) if board else 0
    lines: list[str] = []

    # Header row
    header = "    " + "".join(f" C{c + 1:>1} " for c in range(num_cols))
    lines.append(header)

    # Board rows
    for r, row_data in enumerate(board):
        row_label = f"R{r + 1}"
        cells: list[str] = []
        for c, cell in enumerate(row_data):
            if cell == "B":
                arrow = block_dirs.get((r + 1, c + 1), "?")
                cells.append(f"B{arrow}")
            else:
                cells.append(f" {cell}")
        lines.append(f"{row_label:>4} " + "  ".join(cells))

    # Player and message info
    player = data.get("player", {})
    message = data.get("message", "")
    lines.append(f"\nRobot at column {player.get('col', '?')}, row {player.get('row', '?')}")
    if message:
        lines.append(f"Status: {message}")

    return "\n".join(lines)


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
    if isinstance(content, list):
        parts: list[str] = [str(c) for c in content]  # type: ignore[misc]
        return " ".join(parts)
    return str(content)


def _extract_usage(response_msg: Any) -> tuple[int, int, int]:
    """Extract (input_tokens, output_tokens, cached_tokens) from a LangChain AIMessage.

    Checks usage_metadata first (LangChain native), then response_metadata.token_usage (OpenAI).
    """
    # Try usage_metadata (LangChain >=0.2)
    meta: Any = getattr(response_msg, "usage_metadata", None)
    if meta is not None:
        inp: int = int(getattr(meta, "input_tokens", 0) or 0)
        out: int = int(getattr(meta, "output_tokens", 0) or 0)
        # Cached tokens may be in input_token_details
        details: Any = getattr(meta, "input_token_details", None)
        cached: int = int(getattr(details, "cache_read", 0) or 0) if details else 0
        return (inp, out, cached)

    # Fallback: response_metadata.token_usage (OpenAI-style via OpenRouter)
    resp_meta: dict[str, Any] = dict(getattr(response_msg, "response_metadata", None) or {})
    usage: dict[str, Any] = dict(resp_meta.get("token_usage") or {})
    prompt = int(usage.get("prompt_tokens", 0))
    completion = int(usage.get("completion_tokens", 0))
    # OpenAI-style cached tokens
    details_dict: dict[str, Any] = dict(usage.get("prompt_tokens_details") or {})
    cached_tokens = int(details_dict.get("cached_tokens", 0))
    return (prompt, completion, cached_tokens)


def run_reactor_agent() -> str:
    """Run the reactor navigation agent with retry logic."""
    llm = get_llm(model="openai/gpt-5.4")
    llm_with_tools = llm.bind(tools=[_TOOL_SCHEMA])

    last_error = ""
    total_input_tokens = 0
    total_output_tokens = 0
    total_cached_tokens = 0
    total_steps = 0

    def _log_token_summary() -> None:
        total = total_input_tokens + total_output_tokens
        logger.info(
            "[bold]== Token summary: input=%d (cached=%d), output=%d, total=%d, steps=%d ==[/]",
            total_input_tokens,
            total_cached_tokens,
            total_output_tokens,
            total,
            total_steps,
        )

    result = ""
    try:
        for attempt in range(1, MAX_RETRIES + 1):
            # --- onStart hook ---
            logger.info("[bold cyan]== Reactor agent | attempt %d/%d ==[/]", attempt, MAX_RETRIES)

            initial_prompt = "Begin the mission. Send the 'start' command to initialize the reactor chamber."
            if attempt > 1:
                initial_prompt = (
                    f"Previous attempt failed: {last_error}. "
                    "Send 'start' to begin a new attempt. Be more cautious this time — "
                    "wait longer before moving through dangerous columns."
                )

            messages: list[dict[str, Any]] = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": initial_prompt},
            ]

            crushed = False
            first_step = True

            for step in range(1, MAX_STEPS + 1):
                # --- onStepStart hook ---
                t0 = time.monotonic()
                logger.info("[bold]-- Step %d/%d --[/]", step, MAX_STEPS)

                # Phase 1: Reasoning (no tools — force the LLM to think)
                if first_step:
                    first_step = False
                    # No map yet — just prompt to start
                else:
                    messages.append(
                        {
                            "role": "user",
                            "content": (
                                "Analyze the current map. Follow the reasoning protocol: "
                                "current state, predict next state, evaluate options, "
                                "then state your decision."
                            ),
                        }
                    )
                reasoning_response = llm.invoke(messages)
                messages.append(reasoning_response)  # type: ignore[arg-type]

                inp, out, cached = _extract_usage(reasoning_response)
                total_input_tokens += inp
                total_output_tokens += out
                total_cached_tokens += cached

                reasoning = _get_content(reasoning_response)
                if reasoning:
                    logger.info("[magenta]Reasoning:[/] %s", reasoning[:800])

                # Phase 2: Action (with tools — execute the decided command)
                messages.append(
                    {
                        "role": "user",
                        "content": "Now execute your decision. Call send_command with your chosen command.",
                    }
                )
                response = llm_with_tools.invoke(messages)
                messages.append(response)  # type: ignore[arg-type]

                inp, out, cached = _extract_usage(response)
                total_input_tokens += inp
                total_output_tokens += out
                total_cached_tokens += cached
                total_steps += 1

                tool_calls = _extract_tool_calls(response)

                if not tool_calls:
                    logger.warning("[yellow]No tool call — nudging agent[/]")
                    elapsed = time.monotonic() - t0
                    logger.info("[dim]Step %d finished in %.1fs (no tool call)[/]", step, elapsed)
                    continue

                for tc in tool_calls:
                    cmd = tc.args.get("command", "unknown")

                    # --- onToolCallStart hook ---
                    logger.info("[yellow]>> send_command('%s')[/]", cmd)

                    result_data = _send_command(cmd)
                    result_str = json.dumps(result_data, ensure_ascii=False)
                    ascii_map = _render_ascii_map(result_data)

                    # --- onToolCallFinish hook ---
                    logger.info("[cyan]<< Map:\n%s[/]", ascii_map)

                    messages.append({"role": "tool", "tool_call_id": tc.id, "content": ascii_map})

                    # Check for flag/success
                    flag = _check_flag(result_str)
                    if flag:
                        logger.info("[bold green]FLAG CAPTURED: %s[/]", flag)
                        result = flag
                        return result

                    if _is_success(result_data):
                        logger.info("[bold green]Mission complete![/]")
                        result = result_str
                        return result

                    # Check for crush
                    if _is_failure(result_data):
                        logger.warning("[bold red]Robot crushed! Resetting...[/]")
                        last_error = result_str[:300]
                        _send_command("reset")
                        crushed = True
                        break

                # --- onStepFinish hook ---
                elapsed = time.monotonic() - t0
                logger.info("[dim]Step %d finished in %.1fs[/]", step, elapsed)

                if crushed:
                    break

            if not crushed:
                logger.warning("[bold red]Max steps (%d) reached without completion[/]", MAX_STEPS)
                last_error = "max steps reached"
                _send_command("reset")

        result = f"Failed after {MAX_RETRIES} attempts. Last error: {last_error}"
        return result
    finally:
        # --- onFinish hook ---
        _log_token_summary()
        logger.info("[bold]== Agent finished: %s ==[/]", result[:200] if result else "no result")
