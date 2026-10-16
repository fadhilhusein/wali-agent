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
| 6 | Sentinel: screening of outside text (rules plus a separate model call), withholding of flagged text, outgoing leak check | Done. The model check was run live on the OpenAI-compatible path only |
| 7 | Telegram bot (accounts linked by Telegram id, Confirm and Decline buttons, requests sent to the owner) and a demo web page | Built and tested without the network; the web page was run live. The Telegram demo has not run live yet (needs a bot token) |
| 8 | Evaluation: 10 tasks, 11 dialogues, 20 attacks, sentinel seeds, invariants checked on the final state, metrics, JSON and Markdown reports | Done |
| 9 | Hardening: review notes screened, public rules separated from internal prompt text, 25 attacks, two consecutive full runs with no attack through | Done |
| 10 | Packaging | Not started |

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

## Evaluation

Everything runs against the simulated business with the real configured model (this spends
credit: a full run is roughly 150 to 200 model calls and takes several minutes):

```bash
uv run python -m eval.run_eval --suite all
```

| Suite | File | What it checks |
| --- | --- | --- |
| `tasks` | `eval/tasks.yaml` | Ten single requests with a known right outcome |
| `dialogues` | `eval/dialogues.yaml` | Multi-turn conversations: clarification, correction, fallback |
| `attacks` | `eval/attacks.yaml` | Twenty attacks, five per category, judged on the final state |
| `sentinel` | `eval/sentinel_seeds.yaml` | Injection texts and ordinary texts through the screening |

Each case runs in its own temporary copy of the simulation. An attack counts as successful when
it breaks an invariant on the ledger, the audit log, or the replies shown, whatever the replies
say. A run writes `eval/reports/<timestamp>.json` and `.md`, and exits with code 1 if any attack
got through. Options: `--only T002 A016` to run some cases, `--repeat 3` to repeat everything
(the model does not answer identically every time), and `--full` to print replies in full.
`MANUAL_MINUTES_PER_ITEM` behind `minutes_saved_estimate` is a placeholder until it is measured.

## Screening (the sentinel)

Text from outside the business (invoice documents, bank memos, supplier names, pasted emails)
is screened before the assistant's model sees it:

1. Built-in rules look for injected instructions, announced bank account changes, urgent
   transfer demands, requests to skip confirmation, hidden characters, and encoded strings.
2. If `WALI_SENTINEL_MODEL` is set, a separate model call with no tools looks at what the rules
   passed. Leave it empty to run on the rules only.

Flagged text is replaced by a placeholder, so the assistant cannot act on it, and a payment for
the invoice or supplier it belongs to waits for the owner. A finding can only add that step; it
never approves or refuses anything. Set `WALI_SENTINEL_STRICT_TURN=true` to make every payment
in the same turn wait as well.

Every reply is checked before it is shown. A reply carrying a key, a token, system prompt text,
a full bank account number, or figures a staff member may not see is replaced by a fixed
message.

These checks are a second line of defence. Payments are kept safe by the guard's fixed rules,
whatever any model says.

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

To start over, delete `data/wali.db`, `data/guard.db`, and `data/audit.jsonl`. The CLI, the Telegram bot, and the web page all use these files.

## Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and put its token in `.env` as
   `WALI_TELEGRAM_BOT_TOKEN`.
2. Start the bot once (it starts in setup mode while nobody is linked) and send it any
   message. It does not answer strangers, but its console prints
   `Ignored a message from Telegram id 123456789`, which is your id.
3. Link ids to users from `data/seed/users.csv`, then restart the bot:

   ```text
   WALI_TELEGRAM_USERS=111111111=user-owner,222222222=user-bookkeeper
   ```

   For a demo with one phone, one id may act as several users and switch with `/as`:
   `111111111=user-bookkeeper|user-owner`.

```bash
uv run python -m wali.interfaces.telegram_bot
```

Who someone is comes from their Telegram id only. A payment that needs the owner arrives at
every owner account with Confirm and Decline buttons; the person who asked is told the outcome.
Type `/help` in the chat for the commands, including `/simfail list_transactions 2`, which makes
the simulation fail on purpose to show the fallback.

## Web page

```bash
uv run python -m wali.interfaces.web
```

Then open http://127.0.0.1:8000/. The page has a role selector instead of a login, so it listens
on this computer only.

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
