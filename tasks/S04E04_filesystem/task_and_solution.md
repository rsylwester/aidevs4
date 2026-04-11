# S04E04 — Filesystem

## Task

Centrala exposes a fake filesystem API under the `filesystem` task name. We must
reconstruct Natan's trade notes (delivered as a ZIP of Polish text notes at
`https://hub.ag3nts.org/dane/natan_notes.zip`) as three virtual directories:

- `/miasta/<city>` — file with a JSON object of goods the city needs and their quantities (no units)
- `/osoby/<person>` — file with the merchant's name and a markdown link to the city they manage
- `/towary/<good>` — file with a markdown link to the city currently offering that good

Every name must be ASCII-only (no Polish diacritics) and in **nominative**
(cities, people) or **nominative singular** (goods: "koparka" not "koparki").
The API accepts individual ops or a batch (`answer: [...]`). Final confirmation
is the `{action: done}` call.

## Solution

An LLM agent with two tools:

1. **`run_bash(cmd)`** — executes bash inside a Daytona self-hosted sandbox
   where the extracted notes are uploaded to `/notes` and chmod'd 444. The
   sandbox also carries `AIDEVS_KEY` in its env so the agent can optionally
   `curl` the Centrala preview page if it wants to visually verify.
2. **`finalize(cities, people, goods)`** — single structured tool call that
   the agent makes exactly once when it's ready. The host validates the
   arguments with a Pydantic `Plan` model (cross-references, ASCII slugs, no
   empty collections), then builds a batch of `createDir`/`createFile` ops
   (prefixed with `reset`) and POSTs the whole thing in one request via
   `lib.hub.submit_answer`. Finally it fires `{action: done}`.

### Why a real shell in a sandbox?

The user wanted the agent's exploration tools to actually be bash — not a
curated `list_dir`/`read_file` API. This gives the LLM a more authentic
exploration experience (it can grep, awk, sort, wc, chain commands) and keeps
the implementation pleasantly thin. The sandbox isolates the bash execution
from the host filesystem; the only thing it can see is `/notes`.

### Daytona OSS self-hosted

Daytona's dashboard defaults to :3000, which collides with our Langfuse stack.
The task's `NotesSandbox.ensure_daytona_running` classmethod:

1. Probes `GET http://localhost:13000/api/health` (override default).
2. If unreachable, clones `daytonaio/daytona` into `~/.local/share/daytona`,
   writes a `docker-compose.override.yaml` that remaps the dashboard service's
   port to `13000:3000`, and `docker compose up -d`s the stack.
3. Polls `/health` for up to 60s.
4. Refuses to proceed if `DAYTONA_API_KEY` is empty, printing instructions to
   visit the dashboard at `http://localhost:13000`, log in with
   `dev@daytona.io / password`, create an API key, and drop it into
   `.env.sops`.

There's also `just daytona-up` / `just daytona-down` for manual control.

### Trade-offs

- **AIDEVS_KEY injected into the sandbox**: lets the agent curl the preview
  endpoint if it wants. Acceptable on a dev machine; would not be acceptable
  in production since the sandbox is not hermetic against the network. The
  notes are read-only and the sandbox is deleted at the end of the run.
- **Port :13000 override for Daytona**: avoids the Langfuse conflict but does
  diverge from upstream defaults. Documented here and via the justfile recipe.
- **Pre-existing ruff/pyright errors** in other `tasks/` packages: not touched.
  Only this task's files and shared stub directories (`typings/daytona_sdk`,
  `typings/unidecode`) are guaranteed clean.

## Running it

```bash
just task tasks.S04E04_filesystem
```

First run: the task will bring up Daytona if needed and then exit with
instructions to set `DAYTONA_API_KEY` in `.env.sops`. After that, subsequent
runs will:

1. Download and extract Natan's notes to `.workspace/notes/`
2. Create a Daytona sandbox, upload notes, start a LangChain agent loop
3. Log every bash command + output to `.workspace/session_log.md`
4. On `finalize`, validate the plan and submit in batch mode + call `done`
5. Log the full Centrala response

Langfuse traces at `http://localhost:3000` under session `S04E04_filesystem-*`.
