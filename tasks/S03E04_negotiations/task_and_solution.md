# S03E04 — Negotiations

## Task

Help a remote hub agent find cities that sell ALL items needed to build a wind turbine. The agent communicates in Polish natural language and has no direct access to the knowledge base (3 CSV files: cities, items, connections). Expose two HTTP tool endpoints via ngrok that the agent calls to search items and reset its session. The agent has max 10 steps and each response must be 4–500 bytes. After the agent identifies the correct cities, the hub returns a flag.

## Solution

FastAPI server with two POST endpoints, ngrok tunnel, SQLite in-memory DB, and LLM-based query normalization:

1. **Data loading**: Download `cities.csv`, `items.csv`, `connections.csv` from the hub (if not cached). Load into SQLite with FTS5 full-text index on item names.
2. **Tool registration**: On startup, submit both tool URLs + English descriptions to the hub via `submit_answer("negotiations", {"tools": [...]})`. The hub agent then calls our endpoints.
3. **`/find_item`** — accepts `{"params": "<Polish query>"}`:
   - LLM normalization (GPT-4o-mini) strips conversational Polish, extracting just the component name (e.g. "potrzebuję rezystora 10 ohm" → "rezystor 10 ohm").
   - FTS5 search (AND first, then OR fallback, then LIKE fallback) matches items in the DB.
   - Session state accumulates city sets per searched item; returns the **intersection** of all sets (cities offering ALL items).
   - If response with city names exceeds 490 bytes, returns a hint-only response ("item found, search for next item") without city names.
4. **`/reset_session`** — clears accumulated search state so the agent can start fresh.
5. **Background polling**: After tool registration, polls the hub every 5 seconds for the flag. On flag receipt, sends SIGINT to gracefully shut down the server.

## Reasoning

LLM normalization is needed because the hub agent speaks conversational Polish — raw queries like "Czy macie jakiś kondensator ceramiczny?" would fail FTS5 matching without stripping filler words first. The three-tier search strategy (FTS5 AND → FTS5 OR → LIKE) handles varying query precision gracefully. Session-based intersection across calls lets the agent narrow down cities incrementally — after 3 items the intersection is small enough to fit in the 500-byte response limit. The hint-only fallback for large responses prevents the agent from getting overwhelmed with city names early on, guiding it to search more items first.
