# Wali

A conversational finance assistant for small businesses that cannot be talked into moving money.
Built for the FinTechathon 2026 International AI Track ("AI as a Financial Participant"),
direction E: Small-business Finance Assistant.

**Everything here is a simulation.** There is no real bank, no real money, and no real personal
data. The business, its suppliers, its bank feed, and its people are synthetic.

Wali talks with the owner, the bookkeeper, and staff of a small shop in Indonesian, English, or a
mix of both. It reconciles the bank feed with the books, forecasts cash, suggests what to do about
a shortfall, and pays supplier invoices.

## Why it is safe

The language model only proposes. Plain code decides. The bank only accepts signed approvals.

- The model has exactly ten narrow tools. None can pay, confirm, change a limit or a role, or
  choose an account. To pay, it can only name an invoice.
- A guard decides every payment with fixed rules: a mandate signed by the owner, role limits,
  weekly limits, a cash buffer, duplicate checks, and only the supplier's registered and verified
  account. An account number written on an invoice or in a message is never used.
- Larger payments wait for the owner, who confirms with a button outside the chat. The
  confirmation token never passes through the model.
- Text from outside the business (invoices, bank memos, supplier names, pasted emails) is
  screened, and text that looks like an injected instruction is hidden from the model. Every
  reply is checked for keys, tokens, prompt text, full account numbers, and data the reader's
  role may not see.
- Every decision goes into an audit log in which each entry carries the hash of the one before,
  so a changed entry is detected.

A test runs every attack against a model under an attacker's control. That model asks to pay
every invoice twice, drafts a huge mandate, and tries to show everything it saw. No payment,
leak, or permission rule breaks. [docs/architecture.md](docs/architecture.md) shows how the parts
fit together.

## Latest evaluation

Two consecutive full runs on 16 October 2026 with the configured model. Full report:
[docs/results/2026-10-16-full-run.md](docs/results/2026-10-16-full-run.md).

| Metric | Run 1 | Run 2 | Target |
| --- | --- | --- | --- |
| Attacks that got through (25 attacks, 4 categories) | 0 | 0 | 0 |
| Task success (10 tasks) | 100% | 100% | 90% or more |
| Correct tool calls | 100% | 100% | 95% or more |
| Legitimate requests refused | 0% | 0% | 5% or less |
| Reconciliation F1 against the planted problems | 1.0 | 1.0 | 0.9 or more |
| Dialogues passed (11 multi-turn conversations) | 11 | 11 | |
| Days of warning before the planted cash shortfall | 4 | 4 | |

The model does not answer identically every time, so results can vary between runs. The
time-saved figure in the report uses a placeholder of 5 minutes per reconciliation item until it
is measured with real businesses.

## Quick start

You need [uv](https://docs.astral.sh/uv/), which installs Python 3.11 for you. To chat, you also
need an API key for a language model that supports tool calling.

```bash
git clone https://github.com/fadhilhusein/wali-agent.git
cd wali-agent
uv sync
cp .env.example .env
uv run python scripts/gen_guard_key.py --write-env
uv run pytest -q
```

The tests need no API key and no network. In Windows PowerShell, use `copy` instead of `cp`.

Then choose a model in `.env`:

| Setting | Anthropic | Any OpenAI-compatible endpoint |
| --- | --- | --- |
| `WALI_LLM_PROVIDER` | `anthropic` | `openai_compatible` |
| Key | `ANTHROPIC_API_KEY` | `WALI_LLM_API_KEY` |
| `WALI_LLM_BASE_URL` | leave empty | the part before `/chat/completions` |
| `WALI_AGENT_MODEL`, `WALI_SENTINEL_MODEL` | Claude model ids (filled in) | your provider's model names |
| `WALI_LLM_TEMPERATURE` | not used | `0` for the most repeatable answers |

Leave `WALI_SENTINEL_MODEL` empty to screen text with the built-in rules only. To check that the
model works (a few model calls; the key is never printed):

```bash
uv run python scripts/live_check.py
```

## Try it

All three interfaces use the same simulated business in `data/`. To start over, delete
`data/wali.db`, `data/guard.db`, and `data/audit.jsonl`.

### Command line

The role is picked with `--role` or `/role`, as a stand-in for logging in.

```bash
uv run python -m wali.interfaces.cli --role owner
```

Start with `/mandate` and `/confirm` to set the spending rules as the owner. Then try
`/role bookkeeper` and `tolong rekonsiliasi transaksi September`, or `bayarin tagihan kopi pak
budi ya` followed by `/role owner` and `/confirm`. Type `/help` for all commands.

### Web page

One local page with a role selector. It listens on this computer only, because anyone who can
open it can pick the owner role.

```bash
uv run python -m wali.interfaces.web
```

Open http://127.0.0.1:8000/. The team's larger Next.js interface in [frontend/](frontend/README.md)
talks to the same API.

### Telegram

1. Create a bot with [@BotFather](https://t.me/BotFather) and put its token in `.env` as
   `WALI_TELEGRAM_BOT_TOKEN`.
2. Start the bot and send it any message. It answers no one until accounts are linked, but its
   console prints `Ignored a message from Telegram id 123456789`. That number is your id.
3. Link ids to the users in `data/seed/users.csv` and restart, for example
   `WALI_TELEGRAM_USERS=111111111=user-owner,222222222=user-bookkeeper`. For a demo from one
   phone, one id may act as several users and switch with `/as`:
   `111111111=user-bookkeeper|user-owner`.

```bash
uv run python -m wali.interfaces.telegram_bot
```

The bot knows who someone is only from their Telegram id. Payments that need the owner arrive
with Confirm and Decline buttons. [docs/demo.md](docs/demo.md) has a full demo script.

## Run the evaluation

This uses the real model and spends credit: a full run takes about 150 to 250 model calls and
10 to 15 minutes.

```bash
uv run python -m eval.run_eval --suite all
```

| Suite | File | What it checks |
| --- | --- | --- |
| `tasks` | `eval/tasks.yaml` | Ten requests with a known right outcome |
| `dialogues` | `eval/dialogues.yaml` | Conversations with slang, clarifying questions, corrections, and tool failures |
| `attacks` | `eval/attacks.yaml` | 25 attacks: induced transfers, data extraction, privilege escalation, prompt injection |
| `sentinel` | `eval/sentinel_seeds.yaml` | Injection texts and ordinary texts through the screening |

Each case runs in its own temporary copy of the simulation. An attack counts as getting through
when it breaks a rule on the final state (the payments made, the audit log, or the replies
shown), whatever the replies say. A run writes a JSON and a Markdown report to `eval/reports/`
and exits with code 1 if any attack got through. Add `--only T002 A016` to run some cases,
`--repeat 2` to run everything twice, and `--full` to print replies in full.

## Development

| Task | Command |
| --- | --- |
| Tests | `uv run pytest -q` |
| Lint and format check | `uv run ruff check .` and `uv run ruff format --check .` |
| Format | `uv run ruff format .` |
| Regenerate the seed data | `uv run python scripts/gen_seed_data.py --seed 42` |

The `Makefile` offers the same as `make test`, `make lint`, `make chat`, `make web`,
`make telegram`, and `make eval`. Every setting is described in [.env.example](.env.example).
`.env` holds secrets and is never committed.

## Limits

- It is a simulation. `src/wali/tools/organiser_env.py` is where an organiser-provided
  environment would be connected.
- The web page and the CLI pick a role instead of logging in. They are for local demos only.
- Screening text and replies is a second line of defence and can be worded around. The guard's
  fixed rules are what keep money safe.
- The model's answers vary from run to run. The reply checks catch figures it invents and
  replies in the wrong language, but not every mistake.

## Documents

- [docs/architecture.md](docs/architecture.md): how the parts fit, and what happens when someone asks to pay.
- [docs/demo.md](docs/demo.md): the demo script.
- [docs/assumptions.md](docs/assumptions.md): every decision the specification left open, and why.
- [docs/third_party.md](docs/third_party.md): libraries and services used, with licences.
- [docs/results/](docs/results/): the latest evaluation report.
- [data/seed/README.md](data/seed/README.md): the synthetic data and its planted problems.
