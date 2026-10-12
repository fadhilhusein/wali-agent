# Wali

A safe, conversational finance agent for small businesses, built for the FinTechathon 2026
International AI Track ("AI as a Financial Participant"), direction E: Small-business Finance
Assistant.

**Everything in this repository is a simulation.** There are no real banks, no real money, and no
real personal data. All data is synthetic.

## Status

The project is being built in phases. This section lists only what exists and has been run.

| Phase | Deliverable | State |
| --- | --- | --- |
| 0 | Scaffold: project config, settings, key generator, lint and tests | Done |
| 1 to 10 | Environment, finance logic, guard, agent, interfaces, evaluation, packaging | Not started |

The full architecture description, third-party list, and demo script are added in phase 10.

## Requirements

- Python 3.11
- [uv](https://docs.astral.sh/uv/)

## Setup

```bash
uv sync
cp .env.example .env
uv run python scripts/gen_guard_key.py --write-env
```

`.env` is git-ignored. Never commit it.

## Development

| Task | With make | Without make |
| --- | --- | --- |
| Install | `make install` | `uv sync` |
| Run tests | `make test` | `uv run pytest` |
| Lint | `make lint` | `uv run ruff check .` then `uv run ruff format --check .` |
| Format | `make format` | `uv run ruff format .` then `uv run ruff check --fix .` |

## Documents

- [docs/assumptions.md](docs/assumptions.md): what we do not know yet and the choices we made.
