"""Researcher sub-agent — searches mailbox using DSPy ReAct."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import dspy

from tasks.S02E04_mailbox.prompts import RESEARCHER_INSTRUCTIONS
from tasks.S02E04_mailbox.tools import get_inbox, get_thread, make_read_help, read_message, search_inbox

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

MAX_RESEARCHER_ITERATIONS = 12


class ResearchQuery(dspy.Signature):  # type: ignore[misc]
    __doc__ = f"""Search an email inbox to find specific information.

{RESEARCHER_INSTRUCTIONS}"""

    query: str = dspy.InputField(desc="What to search for in the inbox")  # type: ignore[assignment]
    findings: str = dspy.OutputField(desc="Extracted information from emails, with exact values")  # type: ignore[assignment]


def invoke_researcher(query: str, workspace: Path) -> str:
    """Run the researcher sub-agent with a fresh context. Returns findings as text."""
    logger.info("[bold cyan]Researcher started[/] | query=%.120s", query)

    read_help = make_read_help(workspace)
    tools = [search_inbox, read_message, get_inbox, get_thread, read_help]

    react: dspy.ReAct = dspy.ReAct(  # type: ignore[assignment]
        ResearchQuery,
        tools=tools,
        max_iters=MAX_RESEARCHER_ITERATIONS,
    )

    pred: dspy.Prediction = react(query=query)  # type: ignore[assignment]
    result = str(pred.findings)  # type: ignore[union-attr]
    logger.info("[green]Researcher finished[/] | result_len=%d | result=%.200s", len(result), result)
    return result
