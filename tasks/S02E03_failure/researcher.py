"""Researcher sub-agent — searches power plant log file on disk."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, cast

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool

from lib.llm import get_llm
from tasks.S02E03_failure.prompts import RESEARCHER_SYSTEM_PROMPT

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-4.1-mini"
MAX_RESEARCHER_ITERATIONS = 10
MAX_GREP_RESULTS = 50


def _build_tools(log_path: Path) -> list[BaseTool]:
    """Build researcher tools as closures over log_path."""

    @tool
    def grep_log(pattern: str) -> str:
        """Search log file for lines matching a case-insensitive regex pattern.

        Returns up to 50 matches with line numbers.
        """
        logger.info("[magenta]TOOL grep_log[/] | pattern=%s", pattern)
        try:
            compiled = re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            return f"Invalid regex: {exc}"

        matches: list[str] = []
        with log_path.open(encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if compiled.search(line):
                    matches.append(f"{i}: {line.rstrip()}")
                    if len(matches) >= MAX_GREP_RESULTS:
                        break

        if not matches:
            return f"No lines matching pattern '{pattern}'"
        return f"Found {len(matches)} matches (up to {MAX_GREP_RESULTS}):\n" + "\n".join(matches)

    @tool
    def count_lines(pattern: str) -> str:
        """Count lines in the log file matching a regex pattern. Use empty string to count all lines."""
        logger.info("[magenta]TOOL count_lines[/] | pattern=%s", pattern)
        count = 0
        if pattern:
            try:
                compiled = re.compile(pattern, re.IGNORECASE)
            except re.error as exc:
                return f"Invalid regex: {exc}"
            with log_path.open(encoding="utf-8") as f:
                for line in f:
                    if compiled.search(line):
                        count += 1
        else:
            with log_path.open(encoding="utf-8") as f:
                for _ in f:
                    count += 1
        return f"Lines matching '{pattern}': {count}" if pattern else f"Total lines: {count}"

    return [grep_log, count_lines]


def invoke_researcher(query: str, log_path: Path) -> str:
    """Run the researcher sub-agent with a fresh context. Returns findings as text."""
    logger.info("[bold cyan]Researcher started[/] | query=%.120s", query)

    tools = _build_tools(log_path)
    llm = get_llm(MODEL)
    llm_with_tools = llm.bind_tools(tools)
    tool_map: dict[str, BaseTool] = {t.name: t for t in tools}

    messages: list[Any] = [
        SystemMessage(content=RESEARCHER_SYSTEM_PROMPT),
        HumanMessage(content=query),
    ]

    for iteration in range(1, MAX_RESEARCHER_ITERATIONS + 1):
        logger.info("[blue]  Researcher iteration %d/%d[/]", iteration, MAX_RESEARCHER_ITERATIONS)
        response: AIMessage = llm_with_tools.invoke(messages)
        messages.append(response)

        tool_calls = cast("list[dict[str, Any]]", response.tool_calls)
        if not tool_calls:
            result = str(response.content)
            logger.info("[green]Researcher finished[/] | result_len=%d", len(result))
            return result

        for tc in tool_calls:
            tool_name: str = tc["name"]
            tool_args: dict[str, Any] = tc["args"]
            tool_fn = tool_map.get(tool_name)
            tool_result = f"Unknown tool: {tool_name}" if tool_fn is None else str(tool_fn.invoke(tool_args))
            messages.append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))

    logger.warning("[yellow]Researcher hit max iterations[/]")
    return "Researcher reached max iterations without a final answer."
