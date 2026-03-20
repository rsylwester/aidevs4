"""S01E05 - railway: Activate route X-01 via self-documenting railway API."""

from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
from pydantic_ai import Agent, RunContext
from pydantic_ai.models.openai import OpenAIChatModel
from pydantic_ai.providers.openai import OpenAIProvider

from lib.logging import setup_logging
from lib.tracing import langfuse_session, setup_pydantic_ai_tracing
from settings import settings

logger = logging.getLogger(__name__)

ARTIFACTS = Path(__file__).parent / ".artifacts"

# ---------------------------------------------------------------------------
# Deps
# ---------------------------------------------------------------------------


@dataclass
class RailwayDeps:
    client: httpx.Client
    help_docs: str = field(default="")
    rate_limit_sleep: float = field(default=0.0)
    request_count: int = field(default=0)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def parse_rate_limit_headers(headers: httpx.Headers) -> float:
    """Check rate-limit headers and return seconds to sleep (0.0 if none)."""
    for hdr in ("retry-after", "x-ratelimit-reset", "ratelimit-reset"):
        val = headers.get(hdr)
        if val is not None:
            logger.debug("[yellow]Rate limit header %s=%s[/]", hdr, val)
            try:
                return float(val)
            except ValueError:
                pass

    remaining = headers.get("x-ratelimit-remaining")
    if remaining is not None:
        logger.debug("[yellow]X-RateLimit-Remaining: %s[/]", remaining)
        if int(remaining) == 0:
            reset = headers.get("x-ratelimit-reset", "1")
            try:
                return float(reset)
            except ValueError:
                return 1.0

    return 0.0


def extract_flag(text: str) -> str | None:
    """Extract {FLG:...} flag from text."""
    match = re.search(r"\{FLG:[^}]+\}", text)
    if match:
        return match.group(0)
    return None


def _post_api(client: httpx.Client, payload: dict[str, Any]) -> httpx.Response:
    """Simple POST — does NOT raise on error status codes."""
    return client.post(f"{settings.aidevs_hub_url}/verify", json=payload, timeout=30)


def _parse_retry_after(resp: httpx.Response) -> float:
    """Extract retry-after seconds from JSON body (primary) or HTTP headers (fallback)."""
    try:
        data: dict[str, object] = dict(resp.json())
        retry_val = data.get("retry_after")
        if retry_val is not None:
            return float(str(retry_val))
    except ValueError, KeyError, TypeError:
        pass

    for hdr in ("retry-after", "x-ratelimit-reset", "ratelimit-reset"):
        val = resp.headers.get(hdr)
        if val is not None:
            try:
                return float(val)
            except ValueError:
                pass

    return 0.0


def fetch_help(client: httpx.Client) -> str:
    """Pre-fetch API help docs and save as artifact."""
    payload: dict[str, Any] = {
        "apikey": settings.aidevs_key,
        "task": "railway",
        "answer": {"action": "help"},
    }
    resp = client.post(f"{settings.aidevs_hub_url}/verify", json=payload, timeout=30)
    body = resp.text
    logger.info("[bold cyan]← Help response: HTTP %d | %s[/]", resp.status_code, body)

    # Strip apikey, pretty-print for readability
    try:
        parsed: dict[str, object] = dict(json.loads(body))
        parsed.pop("apikey", None)
        clean_body = json.dumps(parsed, indent=2, ensure_ascii=False)
    except ValueError, TypeError:
        clean_body = body

    help_path = ARTIFACTS / "help.md"
    help_path.write_text(clean_body, encoding="utf-8")
    logger.info("[bold green]Help docs saved to %s[/]", help_path)

    return clean_body


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

agent: Agent[RailwayDeps, str] = Agent(model, deps_type=RailwayDeps, retries=3)


@agent.instructions
def build_instructions(ctx: RunContext[RailwayDeps]) -> str:
    """Build system prompt with pre-fetched API docs."""
    return f"""\
You are a railway operations agent. Your goal is to activate route X-01 using the railway API.

## Critical rules
- Read the API documentation below thoroughly before making any calls.
- Pay close attention to each action's required and optional fields — always provide ALL required parameters.
- When you see a {{{{FLG:...}}}} flag in any response, return it as your final answer immediately.

## Workflow
1. Study the API documentation below. Understand available actions, their parameters, and the correct sequence.
2. Follow the documented steps exactly — use only action names and parameters from the docs.
3. Never give up — if you get errors, re-read the docs and retry with corrected parameters.
4. Be methodical: follow instructions step by step.

## API Documentation (raw JSON from help endpoint)
{ctx.deps.help_docs}
"""


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------


@agent.tool
def query_api(ctx: RunContext[RailwayDeps], action: str, route: str | None = None, value: str | None = None) -> str:
    """Query the railway API with an action and explicit parameters.

    Args:
        ctx: Run context with dependencies.
        action: The API action name (e.g. "help", "status", "reconfigure", "setstatus", "save", etc.)
        route: Route identifier (e.g. "X-01"). Required by most actions — check the API docs `requires` field.
        value: Value parameter when needed (e.g. "RTOPEN" for setstatus).
    """
    deps = ctx.deps
    answer: dict[str, str] = {"action": action}
    if route:
        answer["route"] = route
    if value:
        answer["value"] = value

    payload: dict[str, Any] = {
        "apikey": settings.aidevs_key,
        "task": "railway",
        "answer": answer,
    }

    deps.request_count += 1
    log_payload = {**payload, "apikey": "***"}
    logger.info(
        "[bold cyan]→ API request #%d: action=%s route=%s value=%s payload=%s[/]",
        deps.request_count,
        action,
        route,
        value,
        log_payload,
    )

    # Proactive rate limit sleep from previous successful response
    if deps.rate_limit_sleep > 0:
        logger.info("[yellow]Sleeping %.1fs (proactive rate limit)[/]", deps.rate_limit_sleep)
        time.sleep(deps.rate_limit_sleep)

    max_retries = 7
    for attempt in range(1, max_retries + 1):
        try:
            resp = _post_api(deps.client, payload)
        except httpx.TimeoutException as exc:
            logger.warning("[yellow]Timeout on attempt %d/%d: %s[/]", attempt, max_retries, exc)
            if attempt == max_retries:
                return f"ERROR: timed out after {max_retries} attempts"
            time.sleep(3.0 * attempt)
            continue

        body = resp.text
        logger.info("[bold cyan]← Response: HTTP %d | %s[/]", resp.status_code, body)

        if resp.status_code in {429, 503}:
            retry_after = _parse_retry_after(resp)
            sleep_secs = (retry_after + 1.0) if retry_after > 0 else 3.0 * attempt
            logger.warning(
                "[yellow]Got %d on attempt %d/%d — sleeping %.1fs (retry_after=%.1f)[/]",
                resp.status_code,
                attempt,
                max_retries,
                sleep_secs,
                retry_after,
            )
            if attempt == max_retries:
                return f"ERROR: still getting {resp.status_code} after {max_retries} attempts. Body: {body[:300]}"
            time.sleep(sleep_secs)
            continue

        if not resp.is_success:
            return f"ERROR: HTTP {resp.status_code} — {body}"

        # Success path — track rate limits for next call
        sleep_time = parse_rate_limit_headers(resp.headers)
        deps.rate_limit_sleep = sleep_time

        # Flag detection
        flag = extract_flag(body)
        if flag:
            body = f"FLAG DETECTED: {flag}\n\n{body}"

        # Save artifact
        ts = datetime.now(UTC).strftime("%H%M%S")
        artifact_path = ARTIFACTS / f"response_{action}_{ts}.json"
        artifact_path.write_text(body, encoding="utf-8")

        return body

    return "ERROR: retry loop exited unexpectedly"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------


def run() -> None:
    setup_logging()
    ARTIFACTS.mkdir(exist_ok=True)
    setup_pydantic_ai_tracing()
    logger.info("[bold cyan]Starting S01E05-railway | model=%s[/]", model.model_name)

    with langfuse_session("S01E05-railway"), httpx.Client() as client:
        help_docs = fetch_help(client)
        deps = RailwayDeps(client=client, help_docs=help_docs)
        result = agent.run_sync(
            "Activate route X-01. The API documentation is already in your system prompt. "
            "When you find a {FLG:...} flag, return it as your final answer.",
            deps=deps,
        )
        logger.info("[bold green]Agent result: %s[/]", result.output)
        logger.info("[bold cyan]Total API requests made: %d[/]", deps.request_count)

        flag = extract_flag(result.output)
        if not flag:
            # Also scan all message text for the flag
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
