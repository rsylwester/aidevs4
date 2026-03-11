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
just secrets-decrypt   # decrypt .env from .env.sops (requires age key)
# or: cp .env.example .env and fill in API keys manually
just run              # run main script
```

## Running tasks

```bash
just task S01E01_people   # Run a specific course task
```

## Just commands

```
just setup      # Install dependencies
just run        # Run main script
just task <name># Run a task by package name
just exec <cmd> # Execute command in venv
just lint       # Lint + type check
just fmt        # Format code
just fix        # Auto-fix lint issues + format
just typecheck  # Type check only
just add <pkg>  # Add a dependency
just add-dev    # Add a dev dependency
just remove            # Remove a dependency
just secrets-encrypt   # Encrypt .env → .env.sops
just secrets-decrypt   # Decrypt .env.sops → .env
```

## Secrets management

Secrets are stored encrypted in `.env.sops` using [SOPS](https://github.com/getsops/sops) with [age](https://age-encryption.org/) encryption. The `.sops.yaml` config contains only public recipient keys — private keys live at `~/.config/sops/age/keys.txt`.

```bash
just secrets-decrypt   # Decrypt .env.sops → .env
just secrets-encrypt   # Re-encrypt after editing .env
```
