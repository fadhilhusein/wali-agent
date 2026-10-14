# Convenience targets. On machines without make, run the uv commands directly (see README.md).
.PHONY: install test lint format key seed chat telegram web live-check eval-dialogues eval-sentinel

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

telegram:
	uv run python -m wali.interfaces.telegram_bot

web:
	uv run python -m wali.interfaces.web

# Talks to the REAL model and spends a little credit.
live-check:
	uv run python scripts/live_check.py

# Talks to the REAL model and spends a little credit.
eval-dialogues:
	uv run python -m eval.run_eval --suite dialogues

# Talks to the REAL screening model and spends a little credit.
eval-sentinel:
	uv run python -m eval.run_eval --suite sentinel
