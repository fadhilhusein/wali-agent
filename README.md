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
| 1 | Models, `FinancialEnvironment` interface, SQLite simulated environment with role scopes and failure injection, synthetic seed data with ground truth | Done |
| 2 | Finance logic as pure functions: reconciliation, cash-flow forecast, recommendation candidates | Done |
| 3 | Guard core: signed mandate, deterministic policy, one-time confirmation tokens, hash-chained audit log, guard service | Done |
| 4 | Tool registry (exactly ten tools), hand-written agent loop, model wrappers (Anthropic SDK and OpenAI-compatible), CLI chat | Done. Run live on the OpenAI-compatible path only; the Anthropic path is tested without a live model |
| 5 | Dialogue behaviours (periods, clarification, correction, vague references, fallback), full system prompt, automatic reply check, seed dialogues | Done |
| 6 to 10 | Sentinel, Telegram and web, full evaluation, packaging | Not started |

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

Then set up the model in `.env`. There are two kinds of endpoint:

| | Anthropic (default) | OpenAI-compatible |
| --- | --- | --- |
| `WALI_LLM_PROVIDER` | `anthropic` | `openai_compatible` |
| Key goes in | `ANTHROPIC_API_KEY` | `WALI_LLM_API_KEY` |
| `WALI_LLM_BASE_URL` | leave empty | required, the part before `/chat/completions` |
| `WALI_AGENT_MODEL` | a Claude model id (already filled in) | your provider's model name |
| `WALI_LLM_TEMPERATURE` | not used | optional, `0` for repeatable answers |

The model must support tool (function) calling. If your provider's model has a small output
limit, lower `WALI_LLM_MAX_TOKENS`.

Check the model works, against the real endpoint (this spends a little credit):

```bash
uv run python scripts/live_check.py
```

It runs a connection check and five chat scenarios in a temporary folder, and never prints the
key. Add `--quick` for the connection check only.

To run the seed dialogues in `eval/dialogues.yaml` against the real model (also spends credit):

```bash
uv run python -m eval.run_eval --suite dialogues
```

Add `--only D06 D07` to run some of them, and `--full` to print replies in full. Only the
dialogue suite exists so far; tasks, attacks, and written reports come in phase 8.

## Chat locally

```bash
uv run python -m wali.interfaces.cli --role owner
```

The first run builds the simulated business from `data/seed/`. Type `/help` for the commands.
A typical first session:

1. `/mandate`, then `/confirm`: set up the spending mandate as the owner.
2. `/role bookkeeper`, then ask something like `tolong rekonsiliasi transaksi September`.
3. Ask to pay a supplier invoice. A larger one waits for the owner.
4. `/role owner`, then `/confirm`.

The role is chosen at the interface, as a stand-in for logging in. Typing "I am the owner" in
the chat changes nothing, and `/confirm` goes straight to the guard, never through the model.

To start over, delete `data/wali.db`, `data/guard.db`, and `data/audit.jsonl`.

## Development

| Task | With make | Without make |
| --- | --- | --- |
| Install | `make install` | `uv sync` |
| Run tests | `make test` | `uv run pytest` |
| Lint | `make lint` | `uv run ruff check .` then `uv run ruff format --check .` |
| Format | `make format` | `uv run ruff format .` then `uv run ruff check --fix .` |
| Regenerate seed data | `make seed` | `uv run python scripts/gen_seed_data.py --seed 42` |

## Documents

- [docs/assumptions.md](docs/assumptions.md): what we do not know yet and the choices we made.
- [data/seed/README.md](data/seed/README.md): the synthetic seed data and how to regenerate it.
