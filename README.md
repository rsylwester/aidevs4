# AI Devs 4

Course workspace for [AI Devs 4](https://aidevs.pl/) — building AI-powered applications with LLMs.

## Stack

- **Python 3.14** — runtime
- **LangChain + OpenRouter** — LLM orchestration and model access
- **pydantic-settings** — typed configuration from `.env`

## Tooling

| Tool | Purpose |
|------|---------|
| [mise](https://mise.jdx.dev/) | Runtime version management |
| [uv](https://docs.astral.sh/uv/) | Package & virtualenv management |
| [just](https://just.systems/) | Task runner |
| [ruff](https://docs.astral.sh/ruff/) | Linter & formatter |
| [pyright](https://github.com/microsoft/pyright) | Static type checker (strict mode) |

## Quick start

```bash
mise install          # install Python 3.14
just setup            # install dependencies (uv sync)
cp .env.example .env  # configure API keys
just run              # run main script
```

## Just commands

```
just setup      # Install dependencies
just run        # Run main script
just exec <cmd> # Execute command in venv
just lint       # Lint + type check
just fmt        # Format code
just fix        # Auto-fix lint issues + format
just typecheck  # Type check only
just add <pkg>  # Add a dependency
just add-dev    # Add a dev dependency
just remove     # Remove a dependency
```
