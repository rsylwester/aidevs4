# S01E04 — Sendit

## Task

Fill out an SPK (System Przesylek Konduktorskich) transport declaration form for a reactor fuel cassettes shipment from Gdansk to Zarnowiec by reading multi-file documentation from the hub server, then submit the completed form.

## Solution

A pydantic-ai agent (GPT-4o via OpenRouter) autonomously reads the SPK documentation tree starting from `index.md`, follows all `[include file="..."]` references, analyzes images with a vision sub-agent (GPT-4.1-mini), then fills and submits the declaration template from `zalacznik-E.md`. Four plain tools handle downloads, artifact management, image analysis, and submission. The agent retries on hub rejection.

## Reasoning

Pydantic-ai was chosen over LangChain for this task because it provides better type safety — the agent, tools, and outputs are all generic and fully typed, giving pyright strict-mode compliance without suppression comments. The manual tool-call loop from LangChain (bind_tools → invoke → check tool_calls → dispatch → append ToolMessage → repeat) collapses into a single `agent.run_sync()` call. Vision analysis uses an async sub-agent (`await vision_agent.run()`) to avoid nested event loop issues. Langfuse tracing integrates via `Agent.instrument_all()` and the existing `propagate_attributes` session context.
