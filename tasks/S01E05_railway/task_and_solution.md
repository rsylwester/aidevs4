# S01E05 — Railway

## Task

Activate route X-01 on a railway control system via a self-documenting API. The API exposes a help endpoint that describes available actions, their required parameters, and the correct activation sequence. The agent must read the docs, figure out the steps, and execute them in order.

## Solution

A pydantic-ai agent (GPT-4.1-mini via OpenRouter) pre-fetches the API help docs, then autonomously calls the railway API through a single `query_api` tool with explicit `action`, `route`, and `value` parameters. The agent reads the docs from its system prompt, determines the correct sequence (reconfigure → setstatus → save), and executes each step with the required parameters. The flag is extracted from the agent's final output using regex. Rate limiting (429 responses) is handled with exponential backoff and retry-after header parsing. Langfuse tracing is integrated via `setup_pydantic_ai_tracing()`.

## Reasoning

Explicit named tool parameters (`route`, `value`) were chosen over a generic `params: dict` to make it harder for the LLM to forget required fields — the model sees `route` as a distinct argument rather than having to remember to include it in an opaque dict. The help docs are pre-fetched and injected into the system prompt so the agent has full API documentation available from the first turn. Flag submission is handled in Python code rather than as an agent tool, since the hub expects `answer` as a JSON object and the raw `{FLG:...}` string triggers a parse error.
