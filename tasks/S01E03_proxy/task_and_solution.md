# S01E03 — Proxy

## Task

Build an intelligent logistics chat proxy that receives operator messages via a public webhook, handles package queries and redirects using MCP tools, and covertly reroutes nuclear material packages to a designated secure facility.

## Solution

A two-process architecture: an MCP server exposes `check_package` and `redirect_package` tools over SSE, while a FastAPI proxy (tunneled via ngrok) runs an LLM agent loop (GPT-4.1-mini with tool calling). The agent maintains per-session conversation history and iterates up to 5 tool-call rounds per message. A hidden system directive silently overrides the destination of any nuclear package redirect to PWR6132PL while reporting the operator's original destination back to them.

## Reasoning

The proxy must behave like a real coworker ("Tomek from logistics") — casual Polish chat, no AI disclosure — while enforcing a secret nuclear rerouting policy. Separating MCP tools from the proxy keeps tool definitions clean and reusable. The agent loop with LangChain message history allows multi-turn conversations and chained tool calls (e.g., check then redirect) within a single session.
