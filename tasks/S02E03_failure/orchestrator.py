"""Orchestrator agent — builds condensed failure log and submits to hub."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any, cast

import httpx
import tiktoken
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import BaseTool, tool

from lib.hub import submit_answer
from lib.llm import get_llm
from tasks.S02E03_failure.prompts import ORCHESTRATOR_SYSTEM_PROMPT
from tasks.S02E03_failure.researcher import invoke_researcher

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

MODEL = "openai/gpt-4.1-mini"
MAX_ORCHESTRATOR_ITERATIONS = 100
TOKEN_LIMIT = 1500

_enc = tiktoken.get_encoding("o200k_base")


def _count_tokens(text: str) -> int:
    return len(_enc.encode(text))


def _extract_flag(text: str) -> str | None:
    match = re.search(r"\{FLG:[^}]+\}", text)
    return match.group(0) if match else None


def _build_tools(log_path: Path, result_path: Path) -> list[BaseTool]:
    """Build orchestrator tools as closures over paths."""

    @tool
    def start_researcher(query: str) -> str:
        """Ask the researcher sub-agent to search the raw log file.

        Provide a natural language query describing what to search for.
        """
        logger.info("[bold magenta]TOOL start_researcher[/] | query=%.120s", query)
        return invoke_researcher(query, log_path)

    @tool
    def add_logline(line: str) -> str:
        """Add a condensed log line to the result file.

        Format: 'YYYY-MM-DD HH:MM [SEVERITY] COMPONENT_ID description'.
        Lines are automatically sorted chronologically.
        """
        with result_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")
        # Auto-sort chronologically (lines start with YYYY-MM-DD HH:MM so lexicographic works)
        sorted_lines = sorted(result_path.read_text(encoding="utf-8").strip().splitlines())
        result_path.write_text("\n".join(sorted_lines) + "\n", encoding="utf-8")
        content = "\n".join(sorted_lines)
        tokens = _count_tokens(content)
        logger.info("[green]TOOL add_logline[/] | lines=%d | tokens=%d | line=%.80s", len(sorted_lines), tokens, line)
        return f"Added. Result: {len(sorted_lines)} lines, {tokens}/{TOKEN_LIMIT} tokens."

    @tool
    def read_result() -> str:
        """Read the current result file and its token count."""
        if not result_path.exists() or result_path.stat().st_size == 0:
            return "Result is empty. Use add_logline or replace_result to add entries."
        content = result_path.read_text(encoding="utf-8").strip()
        tokens = _count_tokens(content)
        line_count = len(content.splitlines())
        logger.info("[cyan]TOOL read_result[/] | lines=%d | tokens=%d", line_count, tokens)
        return f"Lines: {line_count} | Tokens: {tokens}/{TOKEN_LIMIT}\n---\n{content}"

    @tool
    def remove_logline(line_number: int) -> str:
        """Remove a line from the result file by its 1-based line number."""
        if not result_path.exists():
            return "Result is empty."
        lines = result_path.read_text(encoding="utf-8").strip().splitlines()
        if line_number < 1 or line_number > len(lines):
            return f"Invalid line number {line_number}. Result has {len(lines)} lines."
        removed = lines.pop(line_number - 1)
        result_path.write_text("\n".join(lines) + "\n" if lines else "", encoding="utf-8")
        tokens = _count_tokens("\n".join(lines))
        logger.info(
            "[yellow]TOOL remove_logline[/] | removed=%s | lines=%d | tokens=%d", removed[:60], len(lines), tokens
        )
        return f"Removed line {line_number}: {removed}\nResult: {len(lines)} lines, {tokens}/{TOKEN_LIMIT} tokens."

    @tool
    def replace_result(content: str) -> str:
        """Replace the entire result file content.

        Use for bulk edits after feedback. Lines are auto-sorted chronologically.
        """
        sorted_lines = sorted(content.strip().splitlines())
        result_path.write_text("\n".join(sorted_lines) + "\n", encoding="utf-8")
        sorted_content = "\n".join(sorted_lines)
        tokens = _count_tokens(sorted_content)
        logger.info("[yellow]TOOL replace_result[/] | lines=%d | tokens=%d", len(sorted_lines), tokens)
        return f"Replaced. Result: {len(sorted_lines)} lines, {tokens}/{TOKEN_LIMIT} tokens."

    @tool
    def send_answer() -> str:
        """Submit the current result to the hub for technician review. Returns feedback."""
        if not result_path.exists() or result_path.stat().st_size == 0:
            return "Error: result is empty. Add lines first."
        content = result_path.read_text(encoding="utf-8").strip()
        tokens = _count_tokens(content)
        logger.info("[bold cyan]TOOL send_answer[/] | lines=%d | tokens=%d", len(content.splitlines()), tokens)

        if tokens > TOKEN_LIMIT:
            return f"BLOCKED: {tokens} tokens exceeds {TOKEN_LIMIT} limit. Trim first."

        try:
            result: dict[str, Any] = submit_answer("failure", {"logs": content})
        except httpx.HTTPStatusError as exc:
            error_body: Any = exc.response.json()
            logger.warning("[bold red]Hub rejected: %s[/]", error_body)
            return f"REJECTED: {error_body}. Review feedback and iterate."
        response_str = str(result)
        logger.info("[bold green]Hub response: %s[/]", response_str[:300])
        return f"Hub response: {response_str}"

    return [start_researcher, add_logline, read_result, remove_logline, replace_result, send_answer]


def run_orchestrator(log_path: Path, result_path: Path) -> str:
    """Run the orchestrator agent loop. Returns final result or flag."""
    logger.info("[bold cyan]Orchestrator started[/] | log=%s | result=%s", log_path, result_path)

    # Clear previous result
    if result_path.exists():
        result_path.unlink()

    tools = _build_tools(log_path, result_path)
    llm = get_llm(MODEL)
    llm_with_tools = llm.bind_tools(tools)
    tool_map: dict[str, BaseTool] = {t.name: t for t in tools}

    messages: list[Any] = [
        SystemMessage(content=ORCHESTRATOR_SYSTEM_PROMPT),
        HumanMessage(
            content=(
                "Analyze the power plant failure log and build a condensed version with only "
                "failure-relevant events. Compress to under 1500 tokens and submit for review. "
                "Iterate based on technician feedback until you get the flag."
            ),
        ),
    ]

    for iteration in range(1, MAX_ORCHESTRATOR_ITERATIONS + 1):
        logger.info("[bold blue]Orchestrator iteration %d/%d[/]", iteration, MAX_ORCHESTRATOR_ITERATIONS)
        response: AIMessage = llm_with_tools.invoke(messages)
        messages.append(response)

        # Check for flag in text response
        if response.content:
            flag = _extract_flag(str(response.content))
            if flag:
                logger.info("[bold green]Flag found: %s[/]", flag)
                return flag

        tool_calls = cast("list[dict[str, Any]]", response.tool_calls)
        if not tool_calls:
            content = str(response.content)
            logger.info("[bold green]Orchestrator finished[/] | result=%.200s", content)
            # Nudge if no flag yet
            if "{FLG:" not in content:
                logger.warning("[yellow]No flag yet — nudging orchestrator to continue[/]")
                messages.append(
                    HumanMessage(
                        content="You haven't received the flag yet. Keep iterating: read feedback, "
                        "improve the log, and resubmit with send_answer."
                    ),
                )
                continue
            return content

        for tc in tool_calls:
            tool_name: str = tc["name"]
            tool_args: dict[str, Any] = tc["args"]
            tool_fn = tool_map.get(tool_name)
            tool_result = f"Unknown tool: {tool_name}" if tool_fn is None else str(tool_fn.invoke(tool_args))

            # Check for flag in tool results
            flag = _extract_flag(tool_result)
            if flag:
                logger.info("[bold green]Flag found in tool result: %s[/]", flag)
                return flag

            messages.append(ToolMessage(content=tool_result, tool_call_id=tc["id"]))

    logger.error("[bold red]Orchestrator hit max iterations[/]")
    return "Max iterations reached without flag."
