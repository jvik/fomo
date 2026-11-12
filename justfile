set shell := ["bash", "-euo", "pipefail", "-c"]

# List available recipes
default:
    @just --list

# Install dependencies (incl. dev group)
sync:
    uv sync --group dev

# Run the app (pass extra args, e.g. `just run --dry-run`)
run *args:
    uv run fomo {{args}}

# Run with dummy data, no Azure account needed
demo:
    uv run fomo --demo

# Simulate activation without calling Azure APIs
dry-run:
    uv run fomo --dry-run

# Run tests
test *args:
    uv run pytest {{args}}

# Lint and check formatting (ruff)
lint:
    uv run ruff check .
    uv run ruff format --check .

# Auto-format and apply safe lint fixes (ruff)
fmt:
    uv run ruff check --fix .
    uv run ruff format .

# Type check the package (mypy)
typecheck:
    uv run mypy fomo

# Regenerate SVG screenshots in docs/screenshots/
screenshots:
    uv run python scripts/screenshot.py

# Build sdist and wheel
build:
    uv build
