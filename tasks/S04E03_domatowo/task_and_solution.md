# S04E03 — Domatowo

## Task

Find a partisan hiding in the ruined city of Domatowo and evacuate them via helicopter. The city is an 11x11 grid with terrain types (roads, buildings of varying heights, rubble). You command up to 4 transporters and 8 scouts with a 300 action-point budget. Transporters move cheaply (1pt/field) but only on roads; scouts walk anywhere (7pt/field) and can inspect buildings (1pt). An intercepted radio signal reveals the partisan is hiding in "one of the tallest blocks."

## Solution

LLM-driven tactical agent (Gemini 2.5 Flash) with a single generic tool:

1. **Single tool** (`send_request(action, payload)`): Generic API wrapper that handles all game actions — getMap, create, move, disembark, inspect, getLogs, callHelicopter. The agent learns the API dynamically from a prefetched `help` response injected into the system prompt.

2. **System prompt**: Includes the help API reference, action cost table, the intercepted radio clue ("tallest blocks"), and strategic guidelines (prefer transporters for travel, inspect tall buildings first). On retry, includes LLM-generated lessons from previous failed attempts.

3. **Agent loop** (`agent.py`): Runs up to 60 steps. If the agent stops calling tools, it gets nudged to continue searching. Detects flag in API responses to terminate on success. Detects action-point exhaustion to trigger reset and retry.

4. **Reset + retry**: On points exhaustion, the game is reset and a new attempt starts with lessons learned. The LLM summarizes what it inspected and what remains unchecked, injected into the next attempt's system prompt. Up to 3 attempts total. Game is also reset at startup to ensure a clean state.

## Reasoning

A single generic tool keeps the implementation minimal while letting the LLM reason about the full action space. The agent needs spatial reasoning to plan transporter routes along roads and scout deployment to tall buildings — Gemini Flash handles this well with the map data and cost constraints in context. The retry mechanism with lessons addresses the tight 300-point budget: if the agent wastes points on suboptimal routes, it learns from the attempt rather than failing permanently.
