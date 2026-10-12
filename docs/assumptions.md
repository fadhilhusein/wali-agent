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
| C6 | `BookEntry` has a `direction` (`in` or `out`) and its amount is always positive, like `BankTransaction` | The specification lists only an amount; without a direction income and expense cannot be told apart | Implemented (phase 1) |
| C7 | `Invoice` has four extra fields: `counterparty_name`, `late_fee_bearing`, `stated_account`, `document_text` | The name is needed for receivables (customers are not suppliers); the late-fee flag is needed by the "delay a payable" rule; the last two hold what the invoice document claims, so a fake "our account has changed" invoice can exist in the data. They are untrusted and never used as a payment destination | Implemented (phase 1) |
| C8 | `GuardApproval` has a `destination_account` field covered by the signature | The environment can then check that the signed destination equals the supplier's registered account, and a wrong destination is testable | Implemented (phase 1) |
| C9 | The seed folder has one extra file, `business.csv`, and every CSV has a `data_label` column with the value `SYNTHETIC` | The opening balance and the last day of data need a home; the label makes every row self-describing without breaking CSV tools | Implemented (phase 1) |
| C10 | Staff scope in the simulated environment: sales entries in the books and receivable invoices only. No balance, bank feed, payables, suppliers, or payroll | Our reading of "see sales and a limited summary only". The bank feed is denied entirely because it contains payroll transfers | Implemented (phase 1) |
| C11 | The simulated environment checks every principal against its own user table (user exists, stored role equals claimed role, business matches) | Defence in depth: a forged principal is refused even if a bug upstream lets one through | Implemented (phase 1) |
| C12 | `execute_payment` in the simulated environment changes only the bank feed, the invoice status, and the payment ledger. It does not write a books entry | Books are the bookkeeper's record. Whether the guard also records a books entry after a payment is decided in phase 3 | Open |
| C13 | A simulated timeout raises `ToolTimeout` immediately instead of really waiting | Keeps tests and evaluation fast and reproducible | Implemented (phase 1) |
| C14 | The simulated environment holds exactly one business, so rows carry no business id | The specification asks for one business. "Belongs to this business" is therefore true for every row; the organisers' environment may differ | Implemented (phase 1) |
| C15 | Seed data ends on 30 September 2026. The environment's clock is injectable and tests pin it to 1 October 2026, 09:00 Jakarta time | Deterministic tests. What "today" means in a live demo is decided in phase 4 | Implemented (phase 1) |
| C16 | `ground_truth.json` records the inputs of the cash scenario (closing balance, open payables and receivables, payroll) but not yet the expected forecast figures | The expected lowest balance depends on the forecast definition, which is written in phase 2 | Open |
| C17 | The base seed contains one invoice with a changed bank account and a hidden instruction in its document text. It contains no injected text in bank memos or supplier names | The account-change invoice is needed for the demo. Other injections would add noise to ordinary tasks, so they will be added per attack in the evaluation fixtures | Implemented (phase 1) |
