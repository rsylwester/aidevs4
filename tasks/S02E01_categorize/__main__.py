"""S02E01 - categorize: Classify CSV items as DNG/NEU using a compact prompt."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, cast

import httpx
import tiktoken
from langfuse import get_client as get_langfuse_client
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from lib.hub import fetch_data
from lib.logging import setup_logging
from lib.tracing import langfuse_session, setup_pydantic_ai_tracing
from settings import settings

logger = logging.getLogger(__name__)

ARTIFACTS = Path(__file__).parent / ".artifacts"
WORKSPACE = Path(__file__).parent / ".workspace"

TOKEN_LIMIT = 100
TASK_NAME = "categorize"
VERIFY_URL = f"{settings.aidevs_hub_url}/verify"

# ---------------------------------------------------------------------------
# Deps
# ---------------------------------------------------------------------------


@dataclass
class CategorizeDeps:
    csv_data: str
    csv_items: list[tuple[str, str]] = field(default_factory=lambda: list[tuple[str, str]]())
    attempt_count: int = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _parse_csv(csv_text: str) -> list[tuple[str, str]]:
    """Parse CSV into list of (id, description) tuples, skipping header."""
    items: list[tuple[str, str]] = []
    for line in csv_text.strip().splitlines()[1:]:
        if "," not in line:
            continue
        id_part, desc = line.split(",", 1)
        items.append((id_part.strip(), desc.strip()))
    return items


def _count_tokens(text: str) -> int:
    """Count tokens using o200k_base encoding."""
    enc = tiktoken.get_encoding("o200k_base")
    return len(enc.encode(text))


def _expand_prompt(template: str, item_id: str, description: str) -> str:
    """Expand prompt template with item data."""
    return template.replace("{id}", item_id).replace("{description}", description)


def _submit_to_hub(prompt: str, item_id: str) -> dict[str, object]:
    """Submit a single expanded prompt to hub for classification."""
    payload: dict[str, object] = {
        "apikey": settings.aidevs_key,
        "task": TASK_NAME,
        "answer": {"prompt": prompt},
    }
    token_count = _count_tokens(prompt)
    logger.info(
        "[cyan]Hub request[/] | item=%s | tokens=%d | prompt=%s",
        item_id,
        token_count,
        prompt,
    )
    resp = httpx.post(VERIFY_URL, json=payload, timeout=30)
    data: dict[str, object] = resp.json()
    logger.info("[cyan]Hub response[/] | item=%s | HTTP %d | %s", item_id, resp.status_code, data)

    # Langfuse generation span for this hub request
    lf: Any = get_langfuse_client()
    lf.start_observation(
        name=f"hub-classify-{item_id}",
        as_type="generation",
        input=prompt,
        output=str(data),
        model="hub-categorize",
        usage_details={"input": token_count},
        metadata={"item_id": item_id, "http_status": resp.status_code},
    )

    return data


def _reset_hub_counter() -> dict[str, object]:
    """Reset hub PP counter."""
    payload: dict[str, object] = {
        "apikey": settings.aidevs_key,
        "task": TASK_NAME,
        "answer": {"prompt": "reset"},
    }
    logger.info("[yellow]Resetting hub PP counter[/]")
    resp = httpx.post(VERIFY_URL, json=payload, timeout=30)
    data: dict[str, object] = resp.json()
    logger.info("[yellow]Reset counter response: %s[/]", data)

    # Langfuse span for reset
    lf: Any = get_langfuse_client()
    lf.start_observation(
        name="hub-reset-counter",
        as_type="span",
        input={"action": "reset"},
        output=str(data),
        metadata={"http_status": resp.status_code},
    )

    return data


def extract_flag(text: str) -> str | None:
    """Extract {FLG:...} flag from text."""
    match = re.search(r"\{FLG:[^}]+\}", text)
    return match.group(0) if match else None


# ---------------------------------------------------------------------------
# Model & Agent
# ---------------------------------------------------------------------------

model = OpenAIChatModel(
    "openai/gpt-4.1-mini",
    provider=OpenAIProvider(
        base_url="https://openrouter.ai/api/v1",
        api_key=settings.openrouter_api_key,
    ),
)

agent: Agent[CategorizeDeps, str] = Agent(
    model,
    deps_type=CategorizeDeps,
    retries=3,
)


@agent.instructions
def build_instructions(ctx: RunContext[CategorizeDeps]) -> str:
    """Build system prompt with CSV data and rules."""
    return f"""\
You are a prompt engineer. Your goal is to craft a classification prompt template
that classifies items as DNG (dangerous) or NEU (neutral).

## Task
The hub has 10 CSV items. It will run YOUR prompt template against each item individually.
Your prompt template must use {{id}} and {{description}} placeholders.
The hub substitutes these with actual item data and expects the model to output exactly "DNG" or "NEU".

## Critical Rules
1. The prompt template AFTER expansion (with actual item data) must be under {TOKEN_LIMIT} tokens for EVERY item.
2. Reactor/nuclear facility items must ALWAYS be NEU — smuggling exception.
3. Dangerous items (weapons, explosives, drugs, threats, violence, sabotage) → DNG.
4. Everything else → NEU.
5. Static instructions FIRST in template, then {{id}} and {{description}} at END.
6. Use extremely concise notation — pseudocode, shorthand, abbreviations. Every token counts.
   Example style: "if reactor/nuclear→NEU;danger/weapon/explos→DNG;else→NEU\\nClassify:\\n{{id}} {{description}}"

## Workflow
1. Read your notes from previous attempts (if any).
2. Draft a compact prompt template.
3. Use test_prompt to verify token counts — it will tell you per-item token counts.
4. If tokens are OK, use send_prompt to submit to the hub.
5. Analyze the hub response. If it fails, write notes about what went wrong, call reset_budget, and iterate.
6. When you get a flag ({{{{FLG:...}}}}), return it as your final answer.

## Current CSV Data (for reference)
```
{ctx.deps.csv_data}
```

## CSV Items Parsed
{chr(10).join(f"- id={item_id}, desc={desc}" for item_id, desc in ctx.deps.csv_items)}
"""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@agent.tool
def test_prompt(ctx: RunContext[CategorizeDeps], prompt: str) -> str:
    """Test a prompt template locally — checks token count for each CSV item after expansion.

    Args:
        ctx: Run context with dependencies.
        prompt: The prompt template with {id} and {description} placeholders.
    """
    logger.info("[bold magenta]TOOL test_prompt called[/] | args: %.100s", prompt)

    if "{id}" not in prompt or "{description}" not in prompt:
        return "ERROR: prompt must contain {id} and {description} placeholders"

    results: list[str] = []
    all_ok = True
    max_tokens = 0

    for item_id, desc in ctx.deps.csv_items:
        expanded = _expand_prompt(prompt, item_id, desc)
        tokens = _count_tokens(expanded)
        max_tokens = max(max_tokens, tokens)
        status = "OK" if tokens <= TOKEN_LIMIT else "OVER"
        if tokens > TOKEN_LIMIT:
            all_ok = False
        results.append(f"  {item_id}: {tokens} tokens [{status}]")

    header = f"Token check: max={max_tokens}/{TOKEN_LIMIT} — {'ALL PASS' if all_ok else 'SOME OVER LIMIT'}"
    return header + "\n" + "\n".join(results)


@agent.tool
def send_prompt(ctx: RunContext[CategorizeDeps], prompt: str) -> str:
    """Submit prompt template to hub — sends one request per CSV item. Only call after test_prompt passes.

    Args:
        ctx: Run context with dependencies.
        prompt: The prompt template with {id} and {description} placeholders.
    """
    ctx.deps.attempt_count += 1
    logger.info("[bold magenta]TOOL send_prompt called[/] | attempt=#%d | args: %.100s", ctx.deps.attempt_count, prompt)

    if "{id}" not in prompt or "{description}" not in prompt:
        return "ERROR: prompt must contain {id} and {description} placeholders"

    results: list[str] = []
    found_flag: str | None = None
    total_tokens = 0
    pass_count = 0
    fail_count = 0
    total_hub_tokens = 0
    total_cached_tokens = 0
    total_input_cost = 0.0
    total_output_cost = 0.0

    for item_id, desc in ctx.deps.csv_items:
        expanded = _expand_prompt(prompt, item_id, desc)
        token_count = _count_tokens(expanded)
        total_tokens += token_count
        logger.info(
            "[cyan]Sending item[/] | id=%s | tokens=%d | prompt=%s",
            item_id,
            token_count,
            expanded,
        )

        data = _submit_to_hub(expanded, item_id)

        # Break early on hub errors — no point sending more items
        error_code = data.get("code")
        if isinstance(error_code, int) and error_code < 0:
            msg = data.get("message")
            return (
                f"ERROR: Hub rejected item {item_id} (code={error_code}, msg={msg})."
                " Call reset_budget, then revise and retry."
            )

        debug_raw = data.get("debug")
        if isinstance(debug_raw, dict):
            dbg = cast("dict[str, Any]", debug_raw)
            hub_tokens = int(dbg.get("tokens", 0) or 0)
            cached = int(dbg.get("cached_tokens", 0) or 0)
            cost_in = float(dbg.get("input_cost", 0) or 0)
            cost_out = float(dbg.get("output_cost", 0) or 0)
            total_hub_tokens += hub_tokens
            total_cached_tokens += cached
            total_input_cost += cost_in
            total_output_cost += cost_out
            logger.info(
                "[green]Hub result[/] | id=%s | output=%s | tokens=%d | cached=%d"
                " | cost_in=%.3f | cost_out=%.3f | balance=%.3f | cache_hit=%.1f%%",
                item_id,
                dbg.get("output", "?"),
                hub_tokens,
                cached,
                cost_in,
                cost_out,
                float(dbg.get("balance", 0) or 0),
                float(dbg.get("global_cache_hit_rate", 0) or 0),
            )

        response_str = str(data)
        flag = extract_flag(response_str)
        if flag:
            found_flag = flag

        # Track pass/fail based on hub response
        if "error" in response_str.lower() or "incorrect" in response_str.lower():
            fail_count += 1
        else:
            pass_count += 1

        results.append(f"  {item_id}: {response_str}")

    logger.info(
        "[bold cyan]send_prompt summary[/] | items=%d | total_tokens=%d | pass=%d | fail=%d",
        len(ctx.deps.csv_items),
        total_tokens,
        pass_count,
        fail_count,
    )
    logger.info(
        "[bold cyan]Hub usage summary[/] | items=%d | hub_tokens=%d | cached=%d"
        " | input_cost=%.3f | output_cost=%.3f | total_cost=%.3f",
        len(ctx.deps.csv_items),
        total_hub_tokens,
        total_cached_tokens,
        total_input_cost,
        total_output_cost,
        total_input_cost + total_output_cost,
    )

    # Save all responses
    artifact = ARTIFACTS / f"response_{ctx.deps.attempt_count}.json"
    artifact.write_text("\n".join(results), encoding="utf-8")

    summary = "\n".join(results)
    if found_flag:
        return f"SUCCESS! Flag found: {found_flag}\nAll responses:\n{summary}"
    return f"All responses:\n{summary}"


@agent.tool
def reset_budget(ctx: RunContext[CategorizeDeps]) -> str:
    """Reset the hub's PP budget counter. Call when budget is exceeded or after a failed attempt.

    Args:
        ctx: Run context with dependencies.
    """
    logger.info("[bold magenta]TOOL reset_budget called[/]")
    _ = ctx.deps  # required by pydantic-ai
    data = _reset_hub_counter()
    return f"Budget reset response: {data}"


@agent.tool
def read_notes(ctx: RunContext[CategorizeDeps]) -> str:
    """Read iteration notes from .workspace/notes.md.

    Args:
        ctx: Run context with dependencies.
    """
    logger.info("[bold magenta]TOOL read_notes called[/]")
    _ = ctx.deps  # required by pydantic-ai
    notes_path = WORKSPACE / "notes.md"
    if notes_path.exists():
        return notes_path.read_text(encoding="utf-8")
    return "(no notes yet)"


@agent.tool
def write_notes(ctx: RunContext[CategorizeDeps], content: str) -> str:
    """Write iteration notes to .workspace/notes.md for tracking attempts.

    Args:
        ctx: Run context with dependencies.
        content: The notes content to write.
    """
    logger.info("[bold magenta]TOOL write_notes called[/] | content_len=%d", len(content))
    _ = ctx.deps  # required by pydantic-ai
    notes_path = WORKSPACE / "notes.md"
    notes_path.write_text(content, encoding="utf-8")
    return "Notes saved."


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    setup_logging()
    ARTIFACTS.mkdir(exist_ok=True)
    WORKSPACE.mkdir(exist_ok=True)
    setup_pydantic_ai_tracing()
    logger.info("[bold cyan]Starting S02E01-categorize | model=%s[/]", model.model_name)

    with langfuse_session("S02E01-categorize"):
        # Download CSV
        csv_text = fetch_data("categorize.csv")
        csv_path = ARTIFACTS / "categorize.csv"
        csv_path.write_text(csv_text, encoding="utf-8")
        logger.info("[green]CSV saved to %s[/]", csv_path)

        items = _parse_csv(csv_text)
        logger.info("[cyan]Parsed %d items from CSV[/]", len(items))

        deps = CategorizeDeps(csv_data=csv_text, csv_items=items)

        result = agent.run_sync(
            "Craft a classification prompt template and iterate until the hub accepts it. "
            "Return the flag when you find one.",
            deps=deps,
        )

        usage = result.usage()
        logger.info(
            "[bold cyan]Agent LLM usage[/] | requests=%d | tool_calls=%d | input=%d | output=%d"
            " | cache_read=%d | cache_write=%d",
            usage.requests,
            usage.tool_calls,
            usage.input_tokens,
            usage.output_tokens,
            usage.cache_read_tokens,
            usage.cache_write_tokens,
        )
        logger.info("[bold green]Agent result: %s[/]", result.output)

        flag = extract_flag(result.output)
        if not flag:
            for msg in result.all_messages():
                for part in msg.parts:
                    if text := getattr(part, "content", None):
                        flag = extract_flag(str(text))
                        if flag:
                            break
                if flag:
                    break

        if flag:
            logger.info("[bold green]Flag: %s[/]", flag)
        else:
            logger.error("[bold red]No flag found in agent output[/]")


if __name__ == "__main__":
    run()
