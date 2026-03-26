"""LLM-based classification of operator notes."""

from __future__ import annotations

import json
import logging
from typing import Any

from tasks.S03E01_evaluation.llm import chat

logger = logging.getLogger(__name__)

MODEL = "openrouter/openai/gpt-5.4-mini"

SYSTEM_PROMPT = """\
You are a strict anomaly auditor for a nuclear power plant sensor monitoring system.

Your task: given a numbered list of operator notes, classify EACH note into exactly one category:
- "ok" — the note confirms normal/stable operation OR is a routine status update. \
Most notes (>95%) are ok. A note that simply describes readings, confirms stability, or says "all good" is ok.
- "problem" — the note explicitly reports a malfunction, failure, alarm, anomaly, or requests intervention. \
The note must clearly state something is WRONG — not just uncertain or cautious.
- "nonsensical" — the note is gibberish, random characters, or written in a non-English language.

IMPORTANT classification rules:
- Notes expressing slight caution, hedging, or mild uncertainty are OK — operators are naturally cautious.
- Only classify as "problem" if the note makes a clear, unambiguous claim that something is broken or abnormal.
- Do NOT over-flag. When in doubt, classify as "ok".

Respond with ONLY a JSON object:
{"problem": [<note numbers>], "nonsensical": [<note numbers>]}
Empty lists if none. Do not include "ok" notes.
"""


def _build_notes_prompt(notes: list[str]) -> str:
    """Build a numbered list of notes for the LLM."""
    return "\n".join(f"{i + 1}. {note}" for i, note in enumerate(notes))


def _parse_classification(raw: str) -> dict[str, list[int]]:
    """Parse LLM JSON response into classification dict."""
    # Find JSON in response (may be wrapped in markdown)
    start = raw.find("{")
    end = raw.rfind("}") + 1
    if start == -1 or end == 0:
        logger.warning("No JSON found in LLM response: %s", raw[:200])
        return {"problem": [], "nonsensical": []}

    data: Any = json.loads(raw[start:end])
    return {
        "problem": [int(x) for x in data.get("problem", [])],
        "nonsensical": [int(x) for x in data.get("nonsensical", [])],
    }


def _classify_pass(notes: list[str], label: str) -> dict[str, list[int]]:
    """Single classification pass."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": _build_notes_prompt(notes)},
    ]
    response = chat(MODEL, messages, label=label)
    logger.info(
        "[bold]%s[/] tokens: %d prompt + %d completion", label, response.prompt_tokens, response.completion_tokens
    )
    return _parse_classification(response.content)


def classify_notes(unique_notes: list[str]) -> set[int]:
    """Two-pass classification of operator notes. Returns 0-based indices of anomalous notes."""
    if not unique_notes:
        return set()

    logger.info("[bold]Classifying %d unique operator notes (2-pass)[/]", len(unique_notes))

    # Pass 1
    result1 = _classify_pass(unique_notes, label="note-classify-pass1")
    flagged1_problem = set(result1["problem"])
    flagged1_nonsensical = set(result1["nonsensical"])
    flagged1_all = flagged1_problem | flagged1_nonsensical
    logger.info("Pass 1: %d problem, %d nonsensical", len(flagged1_problem), len(flagged1_nonsensical))

    if not flagged1_all:
        return set()

    # Pass 2
    result2 = _classify_pass(unique_notes, label="note-classify-pass2")
    flagged2_problem = set(result2["problem"])
    flagged2_nonsensical = set(result2["nonsensical"])
    flagged2_all = flagged2_problem | flagged2_nonsensical
    logger.info("Pass 2: %d problem, %d nonsensical", len(flagged2_problem), len(flagged2_nonsensical))

    # Diff between passes
    only_pass1 = flagged1_all - flagged2_all
    only_pass2 = flagged2_all - flagged1_all
    both = flagged1_all & flagged2_all
    logger.info(
        "[bold]Pass diff:[/] both=%s, only_pass1=%s, only_pass2=%s",
        sorted(both),
        sorted(only_pass1),
        sorted(only_pass2),
    )
    for idx in sorted(only_pass1 | only_pass2):
        if 1 <= idx <= len(unique_notes):
            src = "pass1-only" if idx in only_pass1 else "pass2-only"
            logger.info("  [yellow]%s[/] #%d: %s", src, idx, unique_notes[idx - 1][:120])

    # Cross-reference: flag if flagged in EITHER pass (err on caution side per plan)
    flagged_indices = flagged1_all | flagged2_all

    # Convert 1-based note numbers to 0-based indices
    return {idx - 1 for idx in flagged_indices if 1 <= idx <= len(unique_notes)}
