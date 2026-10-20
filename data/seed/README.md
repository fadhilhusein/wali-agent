# Seed data (SYNTHETIC)

Every file in this folder is **invented** by `scripts/gen_seed_data.py`. No real business, person,
bank, or account is involved. Each CSV row carries a `data_label` column with the value
`SYNTHETIC`.

Do not edit these files by hand. To regenerate them:

```bash
uv run python scripts/gen_seed_data.py --seed 42
```

The same seed always produces byte-identical files, and a test checks that the committed files
match the generator.

| File | Contents |
| --- | --- |
| `business.csv` | The one simulated business, its currency, opening balance, and the last day of data |
| `users.csv` | One user per role: owner, bookkeeper, staff |
| `suppliers.csv` | Suppliers with their registered account; one account is not verified |
| `bank_transactions.csv` | The bank feed |
| `books.csv` | The books entries |
| `invoices.csv` | Payable and receivable invoices |
| `ground_truth.json` | The problems planted on purpose, used by the tests and the evaluation. Its cash scenario also gives the expected forecast when invoices that need verification are set aside (`expected_confirmed`, `pending_verification`) |

The loader in `src/wali/tools/sim_env.py` reads columns by name, ignores columns it does not know,
and hard-codes no names or amounts, so these files can be replaced by more realistic data later.
