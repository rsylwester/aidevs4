"""S04E02 orchestrator agent — configures wind turbine schedule via API."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from lib.llm import get_llm
from tasks.S04E02_windpower.tools import (
    ALL_TOOL_SCHEMAS,
    analyze_data,
    call_api,
    fire_async_gets,
    generate_codes_and_submit,
    poll_results,
)

logger = logging.getLogger(__name__)

_MODEL = "google/gemini-2.5-flash"
_MAX_STEPS = 12
_SESSION_TIMEOUT = 40.0


def _build_system_prompt(help_data: dict[str, Any], docs_data: dict[str, Any]) -> str:
    """Build the system prompt with pre-fetched API help and documentation."""
    return f"""\
You are an agent that configures a wind turbine schedule. You have 40s after "start". Be FAST.

## API Help
```json
{json.dumps(help_data, ensure_ascii=False, indent=2)}
```

## Turbine Documentation
```json
{json.dumps(docs_data, ensure_ascii=False, indent=2)}
```

## Tools
1. **call_api(action, params)** — call API (start, done, get)
2. **fire_async_gets()** — fires weather+turbinecheck+powerplantcheck
3. **poll_results(expected, timeout_seconds)** — collects async results
4. **analyze_data()** — computes config points from stored poll data
5. **generate_codes_and_submit()** — generates unlock codes, polls, and submits config

## Workflow (FOLLOW EXACTLY)

Step 1: call_api(action="start")
Step 2: fire_async_gets()
Step 3: poll_results(expected=3, timeout_seconds=25)
Step 4: analyze_data()
Step 5: generate_codes_and_submit()
Step 6: call_api(action="done")

## Rules
- NEVER give up. If a step fails, retry.
- All tools with () take no arguments — just call them.
"""


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
        case "call_api":
            action = str(args.get("action", ""))
            explicit_params: dict[str, Any] | None = args.get("params")
            params = explicit_params or ({k: v for k, v in args.items() if k != "action"} or None)
            return call_api(action, params)
        case "fire_async_gets":
            return fire_async_gets()
        case "poll_results":
            expected = int(args.get("expected", 1))
            timeout = float(args.get("timeout_seconds", 25.0))
            return poll_results(expected, timeout)
        case "analyze_data":
            return analyze_data()
        case "generate_codes_and_submit":
            return generate_codes_and_submit()
        case _:
            return json.dumps({"error": f"Unknown tool: {name}"})


def run_agent(help_data: dict[str, Any], docs_data: dict[str, Any]) -> str:
    """Run the windpower orchestrator agent. Returns the final API response."""
    logger.info("[bold cyan]== Windpower agent starting ==[/]")
    t0 = time.monotonic()

    system_prompt = _build_system_prompt(help_data, docs_data)

    llm = get_llm(model=_MODEL)
    llm_with_tools = llm.bind(tools=ALL_TOOL_SCHEMAS)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "Execute: start -> fire_async_gets -> poll(3) -> analyze_data -> generate_codes_and_submit -> done. GO!"
            ),
        },
    ]

    last_response = ""
    done_called = False

    for step in range(1, _MAX_STEPS + 1):
        elapsed = time.monotonic() - t0
        if elapsed > _SESSION_TIMEOUT:
            logger.warning("[bold red]Session timeout (%.1fs) — aborting[/]", elapsed)
            break
        logger.info("[dim]  Step %d/%d (%.1fs elapsed)[/]", step, _MAX_STEPS, elapsed)

        response = llm_with_tools.invoke(messages)
        messages.append(response)  # type: ignore[arg-type]

        tool_calls = _extract_tool_calls(response)
        content = _get_content(response)

        if content:
            logger.info("[green]  Agent: %s[/]", content[:300])
            last_response = content

        if not tool_calls:
            elapsed = time.monotonic() - t0
            logger.info("[bold cyan]== Agent done in %.1fs (%d steps) ==[/]", elapsed, step)
            break

        for tc in tool_calls:
            logger.info("[dim]  Tool: %s(%s)[/]", tc.name, json.dumps(tc.args, ensure_ascii=False)[:200])
            result_str = _dispatch_tool(tc.name, tc.args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})
            if tc.name == "call_api" and tc.args.get("action") == "done":
                done_called = True

    # Fallback: if agent stopped before calling done, finish the remaining steps
    if not done_called and (time.monotonic() - t0) < _SESSION_TIMEOUT:
        logger.info("[bold yellow]Agent stopped early — running fallback (done)[/]")
        last_response = call_api("done")

    elapsed = time.monotonic() - t0
    logger.info("[bold cyan]== Pipeline finished in %.1fs ==[/]", elapsed)
    return last_response
