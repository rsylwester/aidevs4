# S01E04 — Sendit

## Task

Fill out an SPK (System Przesylek Konduktorskich) transport declaration form for a reactor fuel cassettes shipment from Gdansk to Zarnowiec by reading multi-file documentation from the hub server, then submit the completed form.

## Solution

A manual agentic loop using the native OpenAI SDK (GPT-4o via OpenRouter) reads the SPK documentation tree starting from `index.md`, follows all `[include file="..."]` references, analyzes images with a vision call (GPT-4.1-mini), then fills and submits the declaration template from `zalacznik-E.md`. Four tool functions (download_doc, list_artifacts, read_artifact, submit_final_answer) are defined as JSON schema dicts for OpenAI function calling. The loop dispatches tool calls, appends results, and repeats until done. Langfuse tracing integrates via `register_tracing()` monkey-patching and the existing `propagate_attributes` session context.

## Reasoning

The native OpenAI SDK was chosen for direct control over the tool-calling loop — each iteration calls `chat.completions.create()` with tool schemas, checks for `tool_calls` in the response, dispatches them via a match/case block, and appends results as tool messages. Vision analysis uses a separate `chat.completions.create()` call with base64-encoded image content parts. This avoids framework abstractions while remaining fully typed for pyright strict mode.
