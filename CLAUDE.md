# CLAUDE.md

## Tooling conventions

- **uv** for all package management — never use `pip` or `pipx`. Use `uv add`, `uv run`.
- **ruff** for linting and formatting — never use black, isort, or flake8.
- **mise** for runtime versions — never use pyenv.
- **just** for task running — see `justfile` for available commands.

## Workflow

1. After writing code, always run: `just fix` then `just lint`
2. Fix any issues before considering the task done.

## Code style

- **Strict typing**: pyright strict mode is enabled. All functions must have full type annotations.
- **`pathlib.Path`** over `os.path` — enforced by ruff PTH rules.
- **Settings**: use pydantic-settings via `settings.py` singleton. Never use `os.getenv()`.
- **No `print()`**: use `logging` module instead — enforced by ruff T20 rule.
- **Line length**: 120 characters.
- **Target**: Python 3.14.

## Project structure

```
├── main.py           # Entry point
├── settings.py       # pydantic-settings config (reads .env)
├── pyproject.toml    # Project metadata, ruff & pyright config
├── justfile          # Task runner commands
├── .mise.toml        # Runtime version config
└── .env              # API keys (not committed)
```
