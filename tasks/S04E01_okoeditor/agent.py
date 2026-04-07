"""S04E01 orchestrator agent — discovers OKO system state via web + API and executes required changes."""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from pydantic import BaseModel, Field

from lib.llm import get_llm
from tasks.S04E01_okoeditor.tools import (
    ALL_TOOL_SCHEMAS,
    call_verify_api,
    get_page_text,
    search_web_content,
)

logger = logging.getLogger(__name__)

_ORCHESTRATOR_MODEL = "openai/gpt-5.4"
_MAX_STEPS = 40

_SYSTEM_PROMPT = """\
You are an agent operating on the OKO Operations Center system. You have two ways to interact:
1. **Web tools** — read-only access to the OKO web panel to discover current state
2. **API tool** — write access via the /verify API to make changes

## Your mission

### Phase 1: Deep discovery (complete ALL before making ANY changes)
1. Call the API with action="help" to learn available commands and parameter syntax.
2. Browse every main section of the web panel to map out the system structure.
3. **CRITICAL**: List pages show truncated content. You MUST navigate to individual detail pages \
(click-through URLs) to read FULL content. Some pages contain operational rules, coding systems, \
or classification schemas that you absolutely need before making changes.
4. Identify the Skolwin-related items across all sections. Note their exact IDs, titles, codes, \
and current classification.

### Phase 2: Execute changes (only after full understanding)
5. **Change Skolwin incident classification**: The Skolwin incident currently classifies sightings \
as vehicles and people. Change it so it classifies as ANIMALS instead. The title code prefix must \
match the correct classification — use the coding system you discovered in the notes.
6. **Update Skolwin task**: Find the task related to Skolwin. Mark it as done. Write in its content \
that animals were spotted (e.g. beavers/bobry).
7. **Create Komarowo diversion**: Ensure there is an incident reporting HUMAN movement near Komarowo. \
Use the correct title code for human movement from the coding system you discovered.
8. **Finish**: Call action="done" to verify all changes are correct.

## Strategy
- Always read detail pages, not just list pages — the details matter.
- Use browse_page_summary to extract structured info from pages.
- Use search_web_content for targeted keyword lookups.
- Pay close attention to API error messages — they hint at what's expected.
- If "done" fails, re-read the error, verify your changes on the web panel, and fix.

## Rules
- Only use the API for changes — never modify the web interface.
- Discover everything dynamically — do not guess IDs, codes, or values.
- The incident title format is strictly validated — get the prefix code right.
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
        case "call_verify_api":
            action = str(args.get("action", ""))
            # Accept either nested {"payload": {...}} or flat extra fields
            explicit_payload: dict[str, Any] | None = args.get("payload")
            payload = explicit_payload or ({k: v for k, v in args.items() if k != "action"} or None)
            return call_verify_api(action, payload)
        case "search_web_content":
            url = str(args.get("url", ""))
            query = str(args.get("query", ""))
            return search_web_content(url, query)
        case "get_page_text":
            url = str(args.get("url", ""))
            return get_page_text(url)
        case _:
            return json.dumps({"error": f"Unknown tool: {name}"})


def run_orchestrator() -> str:
    """Run the OKO editor orchestrator agent. Returns the final API response."""
    logger.info("[bold cyan]== OKO Editor orchestrator starting ==[/]")
    t0 = time.monotonic()

    llm = get_llm(model=_ORCHESTRATOR_MODEL)
    llm_with_tools = llm.bind(tools=ALL_TOOL_SCHEMAS)

    messages: list[dict[str, Any]] = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                "Begin the mission. Start by calling the API help action to discover available commands, "
                "then explore the OKO web panel to find current state of reports, tasks, and incidents. "
                "Complete all objectives and finish with the done action."
            ),
        },
    ]

    last_response = ""

    for step in range(1, _MAX_STEPS + 1):
        logger.info("[dim]  Orchestrator step %d/%d[/]", step, _MAX_STEPS)

        response = llm_with_tools.invoke(messages)
        messages.append(response)  # type: ignore[arg-type]

        tool_calls = _extract_tool_calls(response)
        content = _get_content(response)

        if content:
            logger.info("[green]  Agent says: %s[/]", content[:300])
            last_response = content

        if not tool_calls:
            elapsed = time.monotonic() - t0
            logger.info("[bold cyan]== Orchestrator done in %.1fs (%d steps) ==[/]", elapsed, step)
            return last_response

        for tc in tool_calls:
            logger.info("[dim]  Tool: %s(%s)[/]", tc.name, json.dumps(tc.args, ensure_ascii=False)[:200])
            result_str = _dispatch_tool(tc.name, tc.args)
            messages.append({"role": "tool", "tool_call_id": tc.id, "content": result_str})

    elapsed = time.monotonic() - t0
    logger.warning("[bold red]Orchestrator hit max steps (%d) in %.1fs[/]", _MAX_STEPS, elapsed)
    return last_response
