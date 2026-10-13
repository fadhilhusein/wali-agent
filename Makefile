# Convenience targets. On machines without make, run the uv commands directly (see README.md).
.PHONY: install test lint format key seed chat live-check eval-dialogues

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

# Talks to the REAL model and spends a little credit.
live-check:
	uv run python scripts/live_check.py

# Talks to the REAL model and spends a little credit.
eval-dialogues:
	uv run python -m eval.run_eval --suite dialogues
