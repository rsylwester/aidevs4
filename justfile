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

# Remove a dependency
remove *pkgs:
    uv remove {{pkgs}}
