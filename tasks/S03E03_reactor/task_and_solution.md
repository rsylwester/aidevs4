# S03E03 — Reactor

## Task

Navigate a robot carrying a cooling module across a 7x5 reactor grid from (1,5) to (7,5). Reactor blocks (2 cells tall) oscillate up/down and move only when a command is sent. The robot is crushed if a block occupies its cell. Commands: `start`, `reset`, `left`, `right`, `wait`. Submit commands one at a time via the `/verify` endpoint with `{"task": "reactor", "answer": {"command": "..."}}`.

## Solution

Pure LLM agent (GPT-5.4 via OpenRouter) with a two-phase manual tool-calling loop using LangChain:

1. **Two-phase step cycle**: Each step has a reasoning phase (LLM invoked WITHOUT tools to analyze the map and plan) followed by an action phase (LLM invoked WITH tools to execute the decided command). This forces explicit reasoning before every move.
2. **Single tool** `send_command` — POSTs the command to the reactor API and returns an ASCII-rendered map with block direction arrows (`Bv` = moving down, `B^` = moving up).
3. **ASCII map renderer** — converts the API's board array into a labeled grid with column/row headers and block direction annotations, replacing raw JSON for clearer LLM reasoning.
4. **Life-saving mission identity** — system prompt frames the task as a critical reactor meltdown scenario to maximize LLM caution.
5. **Auto-reset + retry** — on crush, resets the game and retries with error context (max 3 attempts, 50 steps each).
6. **Logging hooks** — rich-formatted logs at every stage: onStart (attempt N), onStepStart/Finish (step N, timing), onToolCallStart/Finish (command sent, map received), onFinish (token summary with input/output/cached counts).

## Reasoning

The two-phase approach (reason then act) prevents the LLM from making impulsive moves — it must analyze block positions and predict their next state before committing. ASCII map rendering with direction arrows gives the LLM a spatial view that's easier to reason about than raw JSON coordinates. The life-saving identity framing makes GPT-5.4 more conservative, preferring `wait` over risky `right` moves. Auto-retry with error context lets the agent learn from crush failures across attempts.
