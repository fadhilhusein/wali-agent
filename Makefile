# Convenience targets. On machines without make, run the uv commands directly (see README.md).
.PHONY: install test lint format key seed chat

install:
	uv sync

test:
	uv run pytest

lint:
	uv run ruff check .
	uv run ruff format --check .

format:
	uv run ruff format .
	uv run ruff check --fix .

key:
	uv run python scripts/gen_guard_key.py --write-env

seed:
	uv run python scripts/gen_seed_data.py --seed 42

chat:
	uv run python -m wali.interfaces.cli --role owner
