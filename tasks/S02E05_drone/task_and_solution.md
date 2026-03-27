# S02E05 — Drone

## Task

Program a drone to navigate a grid-based map and reach the dam near the Zarnowiec power plant. The game API accepts mission configurations with navigation codes and grid coordinates. Error responses contain hints about what to adjust.

## Solution

Multi-phase pipeline with a tool-calling agent loop using LangChain (native `bind_tools`), GPT-4.1-mini via OpenRouter:

1. **Resource preparation**: Download game documentation (HTML), convert to Markdown for LLM consumption.
2. **Map analysis**: Use vision LLM to analyze the grid map image, detect grid dimensions, and identify the dam's coordinates.
3. **Operator agent**: Tool-calling loop that sends mission configurations to the game API, reads error hints, and adjusts parameters iteratively. Tools: `reset_drone`, `send_mission`.

Token usage tracked across all phases via a `TokenTracker` class.

## Reasoning

The vision-based map analysis avoids hardcoding coordinates — the LLM reads the actual map image to find the dam. The operator agent treats error messages as hints (game design pattern), iterating until the correct configuration is found. Resource download is cached to avoid re-fetching on retries. GPT-4.1-mini handles both vision and tool-calling adequately for this structured task.
