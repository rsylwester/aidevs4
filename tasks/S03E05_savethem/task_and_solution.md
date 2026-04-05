# S03E05 — Save Them

## Task

Plan an optimal route for an emissary to travel from base to the city of Skolwin on a 10x10 grid map. The emissary has 10 fuel and 10 food units. Choose a vehicle (rocket, car, horse, or walk), navigate around obstacles (rocks, water, trees), and manage resources — faster vehicles burn more fuel, slower travel consumes more food. The agent must discover available tools via a toolsearch API, fetch the map and vehicle data, compute the optimal path, and submit the route.

## Solution

LLM-driven orchestrator agent (GPT-5.4) that dynamically delegates to sub-agents (GPT-5.4-mini):

1. **Orchestrator** (`orchestrator.py`): Main agent loop with two tools — `create_agent` (spawns sub-agents with dynamic system prompts) and `submit_route` (submits the final answer). Guided by a system prompt to execute phases: discover → gather map → gather vehicles → compute route → submit.

2. **Sub-agents** (`agents.py`): Fire-and-forget LLM agents spawned at runtime. Each gets a role, goal, and tool set. They run a LangChain tool-calling loop for up to 10 steps and return their findings as text.

3. **Tools** (`tools.py`):
   - `call_hub_api(endpoint, query)`: POST to hub APIs (toolsearch, maps, wehicles, books).
   - `compute_optimal_path(grid, start, goal, vehicle, fuel, food)`: A* pathfinder with Pareto-dominance visited states. Handles fuel/food constraints, terrain penalties (trees +0.2 fuel for powered vehicles), water/rock blocking, and automatic dismount optimization. `vehicle="auto"` tries all 4 vehicles.

4. **A* pathfinder**: State space is `(row, col, mode)` with fuel/food tracked per node. Uses Pareto frontier for visited states — only prunes if strictly dominated on both resources. Dismount is modeled as a zero-cost mode transition from vehicle to walk. Manhattan distance heuristic.

## Reasoning

The orchestrator-with-sub-agents architecture satisfies the task requirement of dynamic tool discovery — the agent doesn't hardcode which APIs exist but discovers them via toolsearch. Sub-agents isolate concerns (data gathering vs. pathfinding) and keep each LLM context focused. The A* pathfinder with Pareto dominance is necessary because the resource optimization has two competing dimensions (fuel vs. food) that depend on vehicle choice and dismount timing — simple shortest-path algorithms can't handle this tradeoff. The "auto" vehicle mode lets the pathfinder compare all strategies (pure car, pure horse, car+dismount, etc.) and return the globally optimal route.
