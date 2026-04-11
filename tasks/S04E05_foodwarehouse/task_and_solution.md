# S04E05 — Foodwarehouse

## Task

Centrala exposes a `foodwarehouse` task that asks us to prepare one order per
city listed in `food4cities.json`. Each order must:

- Be addressed to the correct `destination` code (looked up somehow).
- Carry a valid `creatorID` (from a read-only SQLite database).
- Carry a valid `signature` produced by the hub's own `signatureGenerator`
  tool (fed the matching user data from SQLite).
- Contain exactly the goods and quantities the target city needs — no missing
  items, no extras.

Once every city has a complete order, the agent calls `{tool: done}` and
Centrala responds with the flag.

The whole interaction goes through `POST /verify` with the `answer` field
shaped as `{tool, action, ...}`. There is no local data to grep — SQLite,
signatures, orders, and the help doc all live behind the hub.

## Solution

A LangChain tool-calling loop with a **single** tool: `run_bash`. The tool
runs inside a Daytona self-hosted sandbox with `curl` and `jq` pre-installed
and two env vars exported: `$HUB_URL` (Centrala's /verify endpoint) and
`$AIDEVS_KEY` (the apikey). The agent drives the whole task via `curl | jq`
pipelines.

Termination is detected by the host: after every `run_bash` we scan the
output for the standard AI_Devs flag pattern `{{FLG:...}}`. The first time we
see one, the loop exits cleanly and the flag is returned.

### Why bash-only instead of typed tools?

This task is deliberately exploratory — the SQLite schema isn't published,
the `creatorID`/`signature` wiring has to be inferred by poking around, and
the right sequence of `create` → `append` → `get` → `done` calls is best
left to the model. Giving the agent one capable primitive (`run_bash`)
instead of many narrow tools keeps the host thin and preserves the "think
out loud, iterate on feedback" loop that worked in S04E04.

### Host-side pre-flight

Before handing control to the agent, `__main__.py` → `run_agent` does three
cheap things up front:

1. **`download_food4cities()`** — fetch `/dane/food4cities.json` once, cache
   to `.workspace/food4cities.json`, and inline it verbatim in the user
   message. The agent sees the full requirements on turn 1.
2. **`reset_orders()`** — call `{tool: reset}` so every run starts from a
   clean order state, regardless of what a previous run left behind.
3. **`prefetch_help()`** — call `{tool: help}` and inline the response in
   the user prompt so the agent doesn't waste steps discovering tool names
   and arguments.

The host does **not** pre-discover the SQLite schema — that's the agent's
job, and letting it drive `database show tables` makes its reasoning more
grounded.

### Daytona sandbox

`FoodwarehouseSandbox` is a trimmed fork of S04E04's `NotesSandbox`:

- Same Daytona OSS bring-up helpers (health check, compose override to
  remap the dashboard from `:3000` to `:13000` to avoid the Langfuse
  conflict, `docker compose up -d` if unreachable).
- No file uploads — this task has no local data.
- On `__enter__`, after the container is up, runs
  `apt-get update && apt-get install -y jq` so the agent has a real JSON
  tool. `curl` is already in `python:3.12-slim`.
- Injects `AIDEVS_KEY` and `HUB_URL` as sandbox env vars via
  `CreateSandboxFromImageParams.env_vars`.

### Loop exit via flag detection

`_dispatch_run_bash` returns `(result_json, flag_or_none)` after each
command. The flag regex is `\{\{FLG:[^}]+\}\}`. When a match shows up —
which normally only happens in the response body from a successful
`{tool: done}` call — we return `{flag, final_output}` from `run_agent` and
the loop exits.

### Trade-offs

- **AIDEVS_KEY injected into the sandbox**: same pattern as S04E04.
  Acceptable on a dev machine; would not be acceptable in production.
- **No local plan validation**: by design — the user asked for bash-only.
  If the agent submits an incomplete order, Centrala's error response is
  the feedback loop.
- **`python:3.12-slim` + `apt-get jq`** adds a few seconds to sandbox
  startup. Could be skipped by baking a custom image, but that's more infra.

## Running it

```bash
just task tasks.S04E05_foodwarehouse
```

First run: the task will bring up Daytona if needed and then exit with
instructions to set `DAYTONA_API_KEY` in `.env.sops` (same workflow as
S04E04). Subsequent runs will:

1. Download `food4cities.json` to `.workspace/food4cities.json`
2. Reset orders state on Centrala
3. Prefetch the foodwarehouse help doc
4. Create a Daytona sandbox, install `jq`, start the agent loop
5. Log every bash command + output to `.workspace/session_log.md`
6. Exit as soon as Centrala emits a `{{FLG:...}}` in any bash output

Langfuse traces at `http://localhost:3000` under session
`S04E05_foodwarehouse-*`.
