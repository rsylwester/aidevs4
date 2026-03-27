# S02E04 — Mailbox

## Task

Search an email inbox via a custom Zmail API to find three pieces of information: a date, a password, and a confirmation code. The inbox contains multiple emails that must be read, analyzed, and cross-referenced to extract the answers. Submit all three values to the hub.

## Solution

Two-tier DSPy ReAct agent system, both using GPT-4.1-mini via OpenRouter:

- **Orchestrator** (DSPy ReAct): Coordinates the investigation, decides which emails to read, reasons about clues across messages, and submits answers to the hub. Has tools: `start_researcher`, `submit_answer`, `read_help`.
- **Researcher** (DSPy ReAct): Stateless sub-agent invoked per query to interact with the Zmail API — list inbox, read specific emails, search by keyword. Returns findings to the orchestrator.

Strategy: The orchestrator reads the API help docs first, then delegates email exploration to the researcher. It aggregates findings across multiple research rounds, extracts the three values, and submits them.

## Reasoning

The two-agent split separates strategic reasoning (orchestrator) from API interaction (researcher). DSPy ReAct handles the tool-calling loop automatically, reducing boilerplate. The researcher is stateless — each invocation gets a fresh context — which prevents context bloat from accumulating email contents. GPT-4.1-mini is sufficient since the task is information retrieval, not complex reasoning.
