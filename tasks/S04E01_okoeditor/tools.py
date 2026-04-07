"""S04E01 tools — OKO web browser (Playwright) and verify API caller."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

import httpx
from markdownify import markdownify
from playwright.sync_api import Browser, Page, sync_playwright

from settings import settings

logger = logging.getLogger(__name__)

_VERIFY_URL = settings.aidevs_verify_address
_OKO_BASE = "***REMOVED***"

_OKO_USERNAME = "Zofia"
_OKO_PASSWORD = "Zofia2026!"  # noqa: S105 — provided in task description, not a real secret

_MAX_RESULT_LEN = 2000


# ---------------------------------------------------------------------------
# Verify API caller
# ---------------------------------------------------------------------------


def call_verify_api(action: str, payload: dict[str, Any] | None = None) -> str:
    """POST to the /verify endpoint with given action and optional payload fields."""
    answer: dict[str, Any] = {"action": action}
    if payload:
        answer.update(payload)

    body: dict[str, Any] = {
        "apikey": settings.aidevs_key,
        "task": "okoeditor",
        "answer": answer,
    }
    logger.info("[yellow]>> verify API action=%r payload=%s[/]", action, json.dumps(answer, ensure_ascii=False)[:300])
    try:
        resp = httpx.post(_VERIFY_URL, json=body, timeout=30)
        data: Any = resp.json()
        data_str = json.dumps(data, ensure_ascii=False)[:500]
        logger.info("[cyan]<< verify API (HTTP %d): %s[/]", resp.status_code, data_str)
        return json.dumps(data, ensure_ascii=False)[:_MAX_RESULT_LEN]
    except Exception as exc:
        msg = f"Verify API error: {exc}"
        logger.warning("[red]%s[/]", msg)
        return json.dumps({"error": msg})


# ---------------------------------------------------------------------------
# Playwright browser singleton — login once, reuse across tool calls
# ---------------------------------------------------------------------------

_browser: Browser | None = None
_page: Page | None = None


def _get_page() -> Page:
    """Return a logged-in Playwright page, creating/logging in if needed."""
    global _browser, _page
    if _page is not None and not _page.is_closed():
        return _page

    pw = sync_playwright().start()
    _browser = pw.chromium.launch(headless=True)
    _page = _browser.new_page()

    # Login
    _page.goto(f"{_OKO_BASE}/")
    _page.wait_for_load_state("networkidle")
    _page.fill('input[type="text"], input[name="username"], input[name="login"]', _OKO_USERNAME)
    _page.fill('input[type="password"]', _OKO_PASSWORD)
    # Fill API key if there's a third input
    api_key_inputs = _page.locator("input").all()
    for inp in api_key_inputs:
        input_type = inp.get_attribute("type") or ""
        if input_type not in ("text", "password", "submit", "hidden"):
            continue
        val = inp.input_value()
        if val == "":
            name = inp.get_attribute("name") or inp.get_attribute("placeholder") or ""
            if "key" in name.lower() or "klucz" in name.lower() or "api" in name.lower():
                inp.fill(settings.aidevs_key)
                break
    # If there's a third empty text-like input, fill it with the API key
    text_inputs = _page.locator('input[type="text"], input:not([type])').all()
    if len(text_inputs) >= 2:
        for inp in text_inputs[1:]:
            if inp.input_value() == "" and inp != _page.locator('input[type="password"]').first:
                inp.fill(settings.aidevs_key)
                break

    _page.locator('button[type="submit"], button:has-text("Zaloguj"), input[type="submit"]').first.click()
    _page.wait_for_load_state("networkidle")
    logger.info("[green]Playwright: logged into OKO panel[/]")
    return _page


def cleanup_browser() -> None:
    """Close the Playwright browser."""
    global _browser, _page
    if _browser:
        _browser.close()
        _browser = None
        _page = None


# ---------------------------------------------------------------------------
# Page content extraction — strip nav boilerplate, return main content only
# ---------------------------------------------------------------------------

_NAV_PATTERNS = re.compile(
    r"(system operatora|Centrum operacyjne|Aktywna sesja|API key|Menu operatora"
    r"|Incydenty|Notatki|Zadania|Użytkownicy|Wyloguj|OKO\b)",
    re.IGNORECASE,
)


def _extract_main_content(html: str) -> str:
    """Convert HTML to markdown, strip scripts/styles/nav boilerplate."""
    cleaned = re.sub(r"<(script|style|nav|header)[^>]*>.*?</\1>", "", html, flags=re.DOTALL | re.IGNORECASE)
    md: str = markdownify(cleaned, strip=["img"])
    lines = [line.rstrip() for line in md.splitlines()]
    # Keep only non-empty lines that aren't repeated nav boilerplate
    content_lines = [line for line in lines if line.strip() and not _NAV_PATTERNS.fullmatch(line.strip())]
    return "\n".join(content_lines)


# ---------------------------------------------------------------------------
# Web tools
# ---------------------------------------------------------------------------


def get_page_text(url: str) -> str:
    """Navigate to an OKO page and return its main text content as markdown.

    Strips navigation/header boilerplate. No LLM call — returns raw text.
    """
    logger.info("[yellow]>> get_page_text url=%s[/]", url)
    try:
        page = _get_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")

        html = page.content()
        content = _extract_main_content(html)
        logger.info("[cyan]<< get_page_text: %d chars[/]", len(content))
        return content[:_MAX_RESULT_LEN]
    except Exception as exc:
        msg = f"get_page_text error for {url}: {exc}"
        logger.warning("[red]%s[/]", msg)
        return msg


def search_web_content(url: str, query: str) -> str:
    """Navigate to an OKO page and search rendered content for keywords.

    Returns matching lines with surrounding context.
    """
    logger.info("[yellow]>> web search url=%s query=%r[/]", url, query)
    try:
        page = _get_page()
        page.goto(url)
        page.wait_for_load_state("networkidle")

        html = page.content()
        content = _extract_main_content(html)
        lines = content.splitlines()

        keywords = [kw.lower() for kw in query.split() if len(kw) > 2]
        matching_indices: set[int] = set()
        for i, line in enumerate(lines):
            lower_line = line.lower()
            if any(kw in lower_line for kw in keywords):
                matching_indices.add(i)

        if not matching_indices:
            preview = "\n".join(f"  L{i}: {line}" for i, line in enumerate(lines[:30]))
            result = f"No keyword matches for '{query}'. Preview ({len(lines)} lines):\n{preview}"
            logger.info("[cyan]<< web search: no matches, returning preview[/]")
            return result[:_MAX_RESULT_LEN]

        context_lines: list[str] = []
        shown: set[int] = set()
        for idx in sorted(matching_indices):
            start = max(0, idx - 2)
            end = min(len(lines), idx + 3)
            for j in range(start, end):
                if j not in shown:
                    prefix = ">>>" if j in matching_indices else "   "
                    context_lines.append(f"{prefix} L{j}: {lines[j]}")
                    shown.add(j)
            context_lines.append("---")

        result = "\n".join(context_lines)
        logger.info("[cyan]<< web search: %d matches, %d context lines[/]", len(matching_indices), len(context_lines))
        return result[:_MAX_RESULT_LEN]
    except Exception as exc:
        msg = f"Web search error for {url}: {exc}"
        logger.warning("[red]%s[/]", msg)
        return msg


# ---------------------------------------------------------------------------
# Tool schemas for LLM agent
# ---------------------------------------------------------------------------


CALL_VERIFY_API_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "call_verify_api",
        "description": (
            "Call the /verify API endpoint to perform actions on the OKO system. "
            "Start with action='help' to discover available actions and their parameters. "
            "The API modifies the OKO system state (reports, tasks, incidents)."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "The action to perform (e.g. 'help', 'done', etc.)",
                },
                "payload": {
                    "type": "object",
                    "description": (
                        "Additional key-value pairs to include in the answer object alongside the action. Optional."
                    ),
                },
            },
            "required": ["action"],
        },
    },
}

GET_PAGE_TEXT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "get_page_text",
        "description": (
            "Navigate to an OKO web page and return its main text content as markdown. "
            "Strips navigation boilerplate. Use this to read full page content including detail pages. "
            f"Base URL: {_OKO_BASE}. Sections: / (incydenty), /notatki, /zadania. "
            "Detail pages: /incydenty/<id>, /notatki/<id>, /zadania/<id>."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": f"Full URL (e.g. '{_OKO_BASE}/notatki' or '{_OKO_BASE}/notatki/<id>')",
                },
            },
            "required": ["url"],
        },
    },
}

SEARCH_WEB_CONTENT_SCHEMA: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "search_web_content",
        "description": (
            "Search for keywords on a rendered OKO web page. Returns matching lines with context. "
            "Cheaper than get_page_text when you know what to look for. "
            f"Base URL: {_OKO_BASE}."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": f"Full URL to search (e.g. '{_OKO_BASE}/notatki')",
                },
                "query": {
                    "type": "string",
                    "description": "Space-separated keywords to search for",
                },
            },
            "required": ["url", "query"],
        },
    },
}

ALL_TOOL_SCHEMAS: list[dict[str, Any]] = [
    CALL_VERIFY_API_SCHEMA,
    GET_PAGE_TEXT_SCHEMA,
    SEARCH_WEB_CONTENT_SCHEMA,
]
