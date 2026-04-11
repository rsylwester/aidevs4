"""Build the filesystem batch for /verify and submit it to Centrala."""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

import httpx

from lib.hub import submit_answer
from tasks.S04E04_filesystem.tools import Plan, ascii_slug

if TYPE_CHECKING:
    from pathlib import Path

logger = logging.getLogger(__name__)

_TASK_NAME = "filesystem"


def prefetch_help() -> dict[str, Any]:
    """Fetch the filesystem API's own help doc so we can ground the agent in it."""
    logger.info("[cyan]Prefetching filesystem help...[/]")
    help_body = submit_answer(_TASK_NAME, {"action": "help"})
    logger.info("[dim]Help keys: %s[/]", list(help_body.keys()))
    return help_body


def reset_filesystem() -> dict[str, Any]:
    """Clear the virtual filesystem on Centrala so the agent starts from a known state."""
    logger.info("[cyan]Resetting Centrala filesystem to a clean state...[/]")
    body = submit_answer(_TASK_NAME, {"action": "reset"})
    logger.info("[dim]Reset response: %s[/]", body)
    return body


def build_batch(plan: Plan) -> list[dict[str, Any]]:
    """Turn a validated Plan into the list of API ops expected by batch_mode."""
    ops: list[dict[str, Any]] = [
        {"action": "reset"},
        {"action": "createDirectory", "path": "/miasta"},
        {"action": "createDirectory", "path": "/osoby"},
        {"action": "createDirectory", "path": "/towary"},
    ]

    for city, needs in plan.cities.items():
        path = f"/miasta/{ascii_slug(city)}"
        content = json.dumps(needs, ensure_ascii=True)
        ops.append({"action": "createFile", "path": path, "content": content})

    for person in plan.people:
        fname = ascii_slug(person.name)
        city_path = f"/miasta/{ascii_slug(person.city)}"
        # Keep the human-readable city label inside the file body for the LLM's
        # own reference; the hub only cares about the markdown link target.
        body = f"{person.name}\n[{person.city}]({city_path})"
        ops.append({"action": "createFile", "path": f"/osoby/{fname}", "content": body})

    for good, seller_cities in plan.goods.items():
        # One /towary/<good> file, with one markdown link per selling city.
        lines = [f"[{c}](/miasta/{ascii_slug(c)})" for c in seller_cities]
        body = "\n".join(lines)
        ops.append({"action": "createFile", "path": f"/towary/{ascii_slug(good)}", "content": body})

    return ops


def _safe_submit(task: str, answer: Any) -> tuple[bool, dict[str, Any]]:
    """Wrap lib.hub.submit_answer so 4xx responses come back as data, not exceptions.

    Returns (ok, body) where ok is True iff the hub returned a successful
    JSON envelope (non-negative `code`). Body is the parsed hub JSON in both
    cases; if the hub returned no JSON we synthesize an error dict.
    """
    try:
        body = submit_answer(task, answer)
    except httpx.HTTPStatusError as exc:
        try:
            body = exc.response.json()
        except ValueError:
            body = {"error": "non-json response", "status": exc.response.status_code, "text": exc.response.text[:500]}
        return False, body
    code = body.get("code")
    ok = isinstance(code, int) and code >= 0
    return ok, body


def submit_plan(plan: Plan, workspace: Path) -> dict[str, Any]:
    """Serialize the plan, POST it in batch_mode, then fire the `done` action.

    Returns a dict with keys:
        ok (bool): True only if both the batch and `done` succeeded.
        stage (str): "batch" or "done" — which phase produced the result.
        response (dict): the hub body from the most-recent call.
    """
    ops = build_batch(plan)
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "plan.json").write_text(json.dumps(ops, ensure_ascii=True, indent=2))
    logger.info("[cyan]Submitting %d filesystem ops in batch mode...[/]", len(ops))
    batch_ok, batch_body = _safe_submit(_TASK_NAME, ops)
    if not batch_ok:
        logger.warning("[yellow]Batch submission rejected: %s[/]", batch_body)
        return {"ok": False, "stage": "batch", "response": batch_body}

    logger.info("[cyan]Sending `done` action to Centrala...[/]")
    done_ok, done_body = _safe_submit(_TASK_NAME, {"action": "done"})
    if not done_ok:
        logger.warning("[yellow]`done` rejected: %s[/]", done_body)
    else:
        logger.info("[bold green]`done` accepted: %s[/]", done_body)
    return {"ok": done_ok, "stage": "done", "response": done_body}
