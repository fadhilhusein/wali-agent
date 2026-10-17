# Convenience targets. On machines without make, run the uv commands directly (see README.md).
.PHONY: install test lint format key seed chat telegram web live-check eval eval-dialogues eval-sentinel eval-compare baseline-offline baseline-offline-write

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

# Talks to the REAL model and spends credit (roughly 150 to 200 calls).
eval:
	uv run python -m eval.run_eval --suite all

# Talks to the REAL model and spends a little credit.
eval-dialogues:
	uv run python -m eval.run_eval --suite dialogues

# Talks to the REAL screening model and spends a little credit.
eval-sentinel:
	uv run python -m eval.run_eval --suite sentinel

# Compares the newest report in eval/reports/ with the baseline of the same model. No model call.
eval-compare:
	uv run python -m eval.compare

# The baseline that needs no model (docs/baseline/offline.json). Free, no model call.
baseline-offline:
	uv run python -m eval.offline --check

# Stores a new offline baseline after an intended code change. Commit the file afterwards.
baseline-offline-write:
	uv run python -m eval.offline --write
