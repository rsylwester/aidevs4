default:
    @just --list

# Install dependencies
setup:
    uv sync

# Run main script
run *args:
    uv run python main.py {{args}}

# Execute arbitrary command in venv
exec *cmd:
    uv run {{cmd}}

# Type check
typecheck:
    uv run pyright .

# Lint code
lint:
    uv run ruff check .
    uv run pyright .

# Format code
fmt:
    uv run ruff format .

# Fix lint issues and format
fix:
    -uv run ruff check --fix .
    uv run ruff format .

# Add a dependency
add *pkgs:
    uv add {{pkgs}}

# Add a dev dependency
add-dev *pkgs:
    uv add --group dev {{pkgs}}

# Run a task by package name (supports dotted submodules, e.g. S01E03_proxy.mcp)
task name:
    uv run python -m tasks.{{name}}

# Start Langfuse stack
up:
    docker compose up -d

# Stop Langfuse stack
down:
    docker compose down

# Bring up Daytona self-hosted (for S04E04_filesystem sandbox)
daytona-up:
    uv run python -c "from tasks.S04E04_filesystem.sandbox import NotesSandbox; NotesSandbox.ensure_daytona_running()"

# Stop Daytona self-hosted stack
daytona-down:
    docker compose -f ~/.local/share/daytona/docker/docker-compose.yaml down

# Remove a dependency
remove *pkgs:
    uv remove {{pkgs}}

# Encrypt .env → .env.sops
secrets-encrypt:
    sops -e --input-type dotenv --output-type dotenv .env > .env.sops

# Decrypt .env.sops → .env
secrets-decrypt:
    sops -d --input-type dotenv --output-type dotenv .env.sops > .env
