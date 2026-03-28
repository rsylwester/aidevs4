"""FastAPI server exposing item-search tools for the negotiations agent."""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, cast

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

from fastapi import FastAPI
from langfuse import propagate_attributes
from pydantic import BaseModel

from lib.hub import submit_answer
from lib.llm import get_llm

logger = logging.getLogger(__name__)

WORKSPACE = Path(__file__).parent / ".workspace"

PUBLIC_URL: str = ""
check_result_fn: Any = None  # injected from __main__

MAX_RESPONSE_BYTES = 490


# ---------------------------------------------------------------------------
# SQLite setup
# ---------------------------------------------------------------------------

_db: sqlite3.Connection | None = None


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE cities (name TEXT, code TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE items (name TEXT, code TEXT PRIMARY KEY)")
    conn.execute("CREATE TABLE connections (item_code TEXT, city_code TEXT)")
    conn.execute("CREATE INDEX idx_conn_item ON connections(item_code)")
    conn.execute("CREATE INDEX idx_conn_city ON connections(city_code)")

    with (WORKSPACE / "cities.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute("INSERT INTO cities VALUES (?, ?)", (row["name"], row["code"]))

    with (WORKSPACE / "items.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute("INSERT INTO items VALUES (?, ?)", (row["name"], row["code"]))

    with (WORKSPACE / "connections.csv").open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            conn.execute("INSERT INTO connections VALUES (?, ?)", (row["itemCode"], row["cityCode"]))

    # FTS5 index for full-text search on item names
    conn.execute("CREATE VIRTUAL TABLE items_fts USING fts5(name, code UNINDEXED, tokenize='unicode61')")
    conn.execute("INSERT INTO items_fts SELECT name, code FROM items")

    conn.commit()
    logger.info(
        "SQLite DB initialised - cities=%d items=%d connections=%d",
        conn.execute("SELECT count(*) FROM cities").fetchone()[0],
        conn.execute("SELECT count(*) FROM items").fetchone()[0],
        conn.execute("SELECT count(*) FROM connections").fetchone()[0],
    )
    return conn


def get_db() -> sqlite3.Connection:
    global _db
    if _db is None:
        _db = _init_db()
    return _db


# ---------------------------------------------------------------------------
# LLM normalization
# ---------------------------------------------------------------------------

_llm = get_llm("openai/gpt-4o-mini")

_NORMALIZE_PROMPT = (
    "You are given a natural-language query in Polish about an electronic component. "
    "Extract ONLY the component name/description in Polish. "
    "Strip conversational words, keep technical details (values, units, types). "
    "Return ONLY the item name, nothing else. No quotes, no explanation.\n\n"
    "Query: {query}"
)


def _normalize_query(query: str) -> str:
    """Use LLM to extract item name from a natural-language Polish query."""
    with propagate_attributes(trace_name="S03E04_negotiations", session_id="S03E04"):
        result = _llm.invoke(_NORMALIZE_PROMPT.format(query=query))
    content: str = cast("str", getattr(result, "content", ""))
    normalized = content.strip()
    logger.info("LLM normalized '%s' -> '%s'", query, normalized)
    return normalized


# ---------------------------------------------------------------------------
# Search helpers
# ---------------------------------------------------------------------------

_city_sets: list[set[str]] = []
_queried_items: list[str] = []


def _extract_keywords(query: str) -> list[str]:
    """Extract meaningful search keywords from a query (post-normalization)."""
    words = query.lower().replace(",", " ").replace(".", " ").split()
    return [w for w in words if len(w) > 1]


def _search_items(query: str) -> list[tuple[str, str]]:
    """Search items matching the query. Returns [(name, code), ...]."""
    conn = get_db()
    keywords = _extract_keywords(query)
    if not keywords:
        return []

    # Strategy 1: FTS5 with all keywords (AND)
    fts_query = " AND ".join(f'"{kw}"' for kw in keywords)
    results: list[tuple[str, str]] = conn.execute(
        "SELECT name, code FROM items_fts WHERE items_fts MATCH ? ORDER BY rank LIMIT 30",
        (fts_query,),
    ).fetchall()
    if results:
        return results

    # Strategy 2: FTS5 with OR (broader)
    fts_query_or = " OR ".join(f'"{kw}"' for kw in keywords)
    results = conn.execute(
        "SELECT name, code FROM items_fts WHERE items_fts MATCH ? ORDER BY rank LIMIT 30",
        (fts_query_or,),
    ).fetchall()
    if results:
        return results

    # Strategy 3: LIKE fallback with all keywords
    like_conditions = " AND ".join(["lower(name) LIKE ?"] * len(keywords))
    params = [f"%{kw}%" for kw in keywords]
    results = conn.execute(
        f"SELECT name, code FROM items WHERE {like_conditions} LIMIT 30",
        params,
    ).fetchall()
    return results


def _get_cities_for_items(item_codes: list[str]) -> set[str]:
    """Get city codes that offer any of the given items."""
    conn = get_db()
    placeholders = ",".join("?" * len(item_codes))
    rows = conn.execute(
        f"SELECT DISTINCT city_code FROM connections WHERE item_code IN ({placeholders})",
        item_codes,
    ).fetchall()
    return {r[0] for r in rows}


def _city_codes_to_names(codes: set[str]) -> list[str]:
    """Resolve city codes to human-readable names."""
    if not codes:
        return []
    conn = get_db()
    code_list = sorted(codes)
    placeholders = ",".join("?" * len(code_list))
    rows = conn.execute(
        f"SELECT name FROM cities WHERE code IN ({placeholders})",
        code_list,
    ).fetchall()
    return sorted(r[0] for r in rows)


# ---------------------------------------------------------------------------
# FastAPI app
# ---------------------------------------------------------------------------


class ToolRequest(BaseModel):
    params: str


class ToolResponse(BaseModel):
    output: str


async def _poll_result() -> None:
    """Background task that polls the hub for negotiation result."""
    if check_result_fn is None:
        return
    await asyncio.sleep(10)
    for i in range(60):
        try:
            result = check_result_fn()
            logger.info("Poll #%d result: %s", i + 1, result)
            msg = str(result.get("message", ""))
            if "FLG:" in msg or result.get("code", -1) == 0:
                logger.info("*** FLAG RECEIVED: %s ***", msg)
                import os
                import signal

                os.kill(os.getpid(), signal.SIGINT)
                return
        except Exception:
            logger.exception("Poll error")
        await asyncio.sleep(5)
    logger.warning("Polling timed out after 60 attempts")


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    _ = app  # unused but required by FastAPI
    get_db()
    poll_task: asyncio.Task[None] | None = None
    if PUBLIC_URL:
        tools: list[dict[str, Any]] = [
            {
                "URL": f"{PUBLIC_URL}/find_item",
                "description": (
                    "Search for an electronic component by name or description (in Polish). "
                    "Pass the item name/description in 'params'. "
                    "The tool remembers previous searches within a session and returns "
                    "cities that have ALL previously searched items simultaneously. "
                    "Returns JSON with 'cities' list and 'hint'."
                ),
            },
            {
                "URL": f"{PUBLIC_URL}/reset_session",
                "description": (
                    "Reset the search session to start fresh. "
                    "Clears all previously searched items so you can begin a new search. "
                    "Pass any value in 'params'."
                ),
            },
        ]
        result = submit_answer("negotiations", {"tools": tools})
        logger.info("Hub response: %s", result)
        poll_task = asyncio.create_task(_poll_result())
    yield
    if poll_task is not None:
        poll_task.cancel()


app = FastAPI(lifespan=_lifespan)


def _make_response(city_names: list[str], hint: str) -> str:
    """Build JSON response, falling back to hint-only if over size limit."""
    response = json.dumps({"cities": city_names, "hint": hint}, ensure_ascii=False)
    if len(response.encode()) <= MAX_RESPONSE_BYTES:
        return response
    return json.dumps(
        {
            "cities": [],
            "hint": (
                f"Item found in database. {len(city_names)} cities match so far. "
                "Search for the next item to narrow down."
            ),
        },
        ensure_ascii=False,
    )


@app.post("/find_item")
async def find_item(req: ToolRequest) -> ToolResponse:
    """Find cities offering a queried item; accumulates across calls."""
    global _city_sets, _queried_items
    query = req.params
    logger.info("find_item query: %s", query)

    normalized = _normalize_query(query)
    if not normalized:
        normalized = query

    items = _search_items(normalized)
    if not items and normalized != query:
        logger.info("Normalized query found nothing, falling back to original")
        items = _search_items(query)

    if not items:
        output = json.dumps(
            {"cities": [], "hint": f"No items found for '{query}'. Try simpler keywords."},
            ensure_ascii=False,
        )
        logger.info("find_item response: %s", output)
        return ToolResponse(output=output)

    item_codes = [code for _, code in items]
    cities_for_item = _get_cities_for_items(item_codes)

    _city_sets.append(cities_for_item)
    _queried_items.append(normalized)

    common: set[str] = _city_sets[0].intersection(*_city_sets[1:])
    city_names = _city_codes_to_names(common)

    matched_names = [name for name, _ in items[:5]]
    hint = (
        f"Matched: {', '.join(matched_names)}. Searched {len(_city_sets)} item(s). {len(city_names)} cities have ALL."
    )

    response = _make_response(city_names, hint)
    logger.info("find_item response (%d bytes): %s", len(response.encode()), response)
    return ToolResponse(output=response)


@app.post("/reset_session")
async def reset_session(req: ToolRequest) -> ToolResponse:
    """Reset the search session."""
    global _city_sets, _queried_items
    _ = req  # unused but required by protocol
    _city_sets = []
    _queried_items = []
    logger.info("Session reset")
    return ToolResponse(output=json.dumps({"hint": "Session reset. All previous searches cleared."}))
