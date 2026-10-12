# Assumptions

Everything here is either something we do not know yet or a choice we made where the build
specification was silent. Update this file whenever an assumption is added, confirmed, or dropped.

## Unknown, waiting on the organisers or the team

| # | Unknown | How the code copes | Needed from |
| --- | --- | --- | --- |
| U1 | Whether the organisers provide a simulated environment, and its API | All access goes through the `FinancialEnvironment` protocol. We ship our own `sim_env.py`; `organiser_env.py` is an empty slot | Organisers |
| U2 | How scripted tasks are run and scored | Our own harness in `eval/` runs tasks, dialogues, and attacks against `sim_env.py` | Organisers |
| U3 | Submission format | Not addressed yet | Organisers |
| U4 | Realistic transaction patterns and fees | Seed data is SYNTHETIC and generated; loaders hard-code no names or amounts | Finance analyst |
| U5 | Manual minutes per reconciliation item | `MANUAL_MINUTES_PER_ITEM` defaults to 5, which is a PLACEHOLDER, not a measured figure | Finance analyst |
| U6 | Business profile (type of business, typical suppliers and problems) | The seed generator uses a generic small shop or cafe | Business analyst |

## Decisions confirmed by the team (12 October 2026)

| # | Decision |
| --- | --- |
| D1 | Supplier account mismatch, unverified account, duplicate invoice, already-paid invoice, and unknown supplier are hard denies. The guard also creates a review item for the owner. No confirmation can override them. |
| D2 | Owner confirmation is used only for: amount above `confirm_above`, balance below `min_cash_buffer`, amount more than 30 percent above the supplier average, and sentinel suspicion in the same turn. |
| D3 | A payment that passes every rule and is at or below `confirm_above` is approved and executed by the guard (plain code) without a button press. The signed mandate is the owner's prior authorisation. The model only receives the result. |

## Design choices where the specification was silent

| # | Choice | Reason | Status |
| --- | --- | --- | --- |
| C1 | Python 3.11 managed with `uv`; versions pinned in `pyproject.toml` and locked in `uv.lock` | Reproducible installs from a fresh clone | Implemented (phase 0) |
| C2 | Settings come from environment variables with an optional `.env` file, parsed by a small built-in reader | Avoids an extra dependency | Implemented (phase 0) |
| C3 | The business timezone is a fixed UTC offset (`WALI_UTC_OFFSET_HOURS`, default 7) | Indonesia has no daylight saving, and a fixed offset avoids needing a tz database on Windows | Implemented (phase 0) |
| C4 | One Ed25519 key pair, exchanged as base64 of the raw 32 bytes. The guard holds the private key; the environment gets only the public key | Matches the `ed25519:<base64>` signature format in the mandate example | Key helpers implemented (phase 0); signing in phases 1 and 3 |
| C5 | Model names have no default in code. `WALI_AGENT_MODEL` and `WALI_SENTINEL_MODEL` must be set | The specification forbids hard-coded model names | Implemented (phase 0) |
