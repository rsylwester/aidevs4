# CLAUDE.md

## Tooling conventions

- **uv** for all package management — never use `pip` or `pipx`. Use `uv add`, `uv run`.
- **ruff** for linting and formatting — never use black, isort, or flake8.
- **mise** for runtime versions — never use pyenv.
- **just** for task running — see `justfile` for available commands.

## Workflow

1. After writing code, always run: `just fix` then `just lint`
2. Fix any issues before considering the task done.
3. **Never suppress warnings** — fix ruff and pyright issues properly. Do not use `# noqa`, `# type: ignore`, `# pyright: ignore`, or per-file overrides to silence diagnostics.

## Code style

- **Strict typing**: pyright strict mode is enabled. All functions must have full type annotations.
- **`pathlib.Path`** over `os.path` — enforced by ruff PTH rules.
- **Settings**: use pydantic-settings via `settings.py` singleton. Never use `os.getenv()`.
- **No `print()`**: use `logging` module instead — enforced by ruff T20 rule.
- **Line length**: 120 characters.
- **Target**: Python 3.14.

## Pythonic code

- **Use Python 3.14 syntax** — type aliases (`type X = ...`), generic functions/classes (`def f[T](...)`), `match`/`case`, union types (`X | Y`), `except*` for exception groups, assignment expressions (`:=`).
- **Prefer libraries over hand-rolled code** — reach for stdlib (`itertools`, `functools`, `collections`, `operator`, `contextlib`, `dataclasses`) and third-party packages before writing complex utilities. `uv add` a well-maintained library rather than reinventing.
- **Pythonic idioms** — comprehensions/generators over manual loops, EAFP over LBYL, duck typing, unpacking, `enumerate()`/`zip()`/`any()`/`all()`, context managers, `sum()`/`min()`/`max()` with generators.
- **Keep it concise** — favor one-expression solutions when readable; avoid unnecessary intermediate variables, `range(len(...))` indexing, or `isinstance()` checks when duck typing suffices.

## Artifacts

- **Required**: all task artifacts (downloaded data, API responses, generated files) must be saved to a `.artifacts/` subdirectory within the task folder (e.g. `tasks/S01E01_people/.artifacts/people.csv`).
- `.artifacts/` is gitignored — never commit data files.

## LLM conventions

- **LangChain + OpenRouter** for all LLM calls.
- Use `lib.llm.get_llm()` — never instantiate `ChatOpenAI` directly in tasks.
- Use `.with_structured_output()` for typed LLM responses.
- **No LLM for math/computation**: use code, libraries, or APIs for geocoding, distance calculations, arithmetic, etc. — never delegate computable tasks to an LLM.

## Tracing

- **Langfuse** for all LLM observability — every task must set `trace_name` and `session_id`.
- **Batch/CLI tasks**: wrap processing in `lib.tracing.langfuse_session(task_name)` context manager — it generates a unique session ID and sets both attributes via `propagate_attributes`.
- **Long-lived servers** (FastAPI, etc.): use `langfuse.propagate_attributes(session_id=..., trace_name=...)` at request scope.
- `get_llm()` auto-attaches the Langfuse callback handler; trace attributes come from the surrounding `propagate_attributes` context, not from `get_llm()` args.

## Secrets

- Secrets are stored in `.env.sops` (sops-encrypted dotenv format).
- To regenerate `.env`: `sops --input-type dotenv --output-type dotenv -d .env.sops > .env`
- Never commit `.env` — only `.env.sops` is tracked in git.

## Project structure

```
├── main.py           # Entry point
├── settings.py       # pydantic-settings config (reads .env)
├── lib/              # Shared utilities
│   ├── hub.py        # Hub API (submit_answer, fetch_data)
│   ├── llm.py        # LangChain LLM via OpenRouter
│   └── logging.py    # Rich logging setup
├── tasks/            # Course task packages (S01E01_name/)
│   └── S01E01_people/
├── pyproject.toml    # Project metadata, ruff & pyright config
├── justfile          # Task runner commands
├── .mise.toml        # Runtime version config
└── .env              # API keys (not committed)
```
