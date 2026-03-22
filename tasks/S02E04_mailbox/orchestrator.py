"""Orchestrator agent — coordinates inbox search and submits answers via DSPy ReAct."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

import dspy

from lib.hub import submit_answer
from tasks.S02E04_mailbox.prompts import ORCHESTRATOR_INSTRUCTIONS
from tasks.S02E04_mailbox.researcher import invoke_researcher
from tasks.S02E04_mailbox.tools import make_read_help

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

MAX_ORCHESTRATOR_ITERATIONS = 30


class MailboxInvestigation(dspy.Signature):  # type: ignore[misc]
    __doc__ = f"""Investigate an email inbox to find date, password, and confirmation code.

{ORCHESTRATOR_INSTRUCTIONS}"""

    task_description: str = dspy.InputField(desc="Description of what to find in the inbox")  # type: ignore[assignment]
    result: str = dspy.OutputField(  # type: ignore[assignment]
        desc="Final result including the flag {FLG:...} or all found values"
    )


def _extract_flag(text: str) -> str | None:
    match = re.search(r"\{FLG:[^}]+\}", text)
    return match.group(0) if match else None


def run_orchestrator(workspace: Path) -> str:
    """Run the orchestrator agent loop. Returns final result or flag."""
    logger.info("[bold cyan]Orchestrator started[/] | workspace=%s", workspace)

    def delegate_to_researcher(query: str) -> str:
        """Delegate a search task to the researcher sub-agent.

        Args:
            query: Natural language description of what to search for in the inbox.

        Returns:
            Researcher's findings as text with extracted information.
        """
        return invoke_researcher(query, workspace)

    def submit_mailbox_answer(date: str, password: str, confirmation_code: str) -> str:
        """Submit the three found values to the hub for verification.

        Args:
            date: Date in YYYY-MM-DD format when security dept plans the attack.
            password: System password found in the mailbox.
            confirmation_code: Confirmation code in format SEC- + 32 chars (36 total).

        Returns:
            Hub response — contains flag if all values are correct, or error feedback.
        """
        answer: dict[str, str] = {
            "date": date,
            "password": password,
            "confirmation_code": confirmation_code,
        }
        logger.info("[bold yellow]Submitting answer:[/] %s", answer)
        try:
            hub_result: dict[str, Any] = submit_answer("mailbox", answer)
            response = str(hub_result)
        except Exception:
            logger.exception("[bold red]Hub submission failed[/]")
            response = "Error submitting answer. Check values and try again."
        logger.info("[bold green]Hub response:[/] %s", response[:300])
        flag = _extract_flag(response)
        if flag:
            logger.info("[bold green]FLAG FOUND: %s[/]", flag)
        return response

    read_help = make_read_help(workspace)
    tools = [delegate_to_researcher, submit_mailbox_answer, read_help]

    react: dspy.ReAct = dspy.ReAct(  # type: ignore[assignment]
        MailboxInvestigation,
        tools=tools,
        max_iters=MAX_ORCHESTRATOR_ITERATIONS,
    )

    task_desc = (
        "Search the email inbox to find three pieces of information:\n"
        "1. date (YYYY-MM-DD): When the security department plans an attack on the power plant.\n"
        "2. password: A system password found in the mailbox.\n"
        "3. confirmation_code: SEC- + 32 chars (36 total) from a security department ticket.\n\n"
        "Key hints:\n"
        "- Wiktor sent an email from proton.me domain.\n"
        "- The mailbox is active — new messages may arrive during your search.\n"
        "- Start by reading the help docs, then search systematically.\n"
        "- Try both Polish and English search terms.\n"
    )

    pred: dspy.Prediction = react(task_description=task_desc)  # type: ignore[assignment]
    result_text = str(pred.result)  # type: ignore[union-attr]

    flag = _extract_flag(result_text)
    if flag:
        logger.info("[bold green]Flag in final result: %s[/]", flag)
        return flag

    logger.warning("[yellow]No flag in final result: %.300s[/]", result_text)
    return result_text
