# S02E03 — Failure

## Task

A power plant experienced a failure yesterday. The full system log file from that day is huge (2000+ lines). Build a condensed version that contains only events relevant to failure analysis (power supply, cooling, water pumps, software, and other plant components), fits within 1500 tokens, and preserves one event per line with timestamps and severity levels. Submit the condensed log to Centrala for technician review — they provide precise feedback about missing subsystems until the log is complete enough for root cause analysis.

## Solution

Two-agent system using LangChain with native tool calling (bind_tools), both via OpenRouter:

- **Orchestrator** (GPT-4.1-mini): Analyzes failure relevance, builds the condensed log, submits to hub, and iterates on technician feedback. Has tools: `start_researcher`, `add_logline`, `read_result`, `remove_logline`, `replace_result`, `send_answer`.
- **Researcher** (GPT-4.1-mini): Stateless sub-agent invoked per query to grep/search the raw log file on disk (never loads full file into LLM context). Has tools: `grep_log`, `count_lines`.

Strategy: Start by gathering all CRIT and ERRO entries via the researcher, select failure-relevant ones, condense descriptions without losing technical details, submit early, then expand with targeted WARN searches based on technician feedback.

The conductor (`run()`) downloads the log, wires Langfuse tracing, and starts the orchestrator. All log lines are auto-sorted chronologically. Token counting uses tiktoken (o200k_base encoding).

## Reasoning

The two-agent split keeps the large log file out of LLM context — the researcher greps on disk and returns only matching lines. Starting with CRIT+ERRO entries first (rather than broad category searches) minimizes wasted iterations since these are the core failure events. The feedback-driven iteration loop leverages the hub's precise subsystem-level feedback to fill gaps efficiently. Both agents use GPT-4.1-mini — sufficient for this task since the orchestrator's judgment is guided by structured feedback from the hub, and the researcher just does pattern matching.
