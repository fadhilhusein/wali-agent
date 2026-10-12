"""The committed seed data must match its generator, and the planted ground truth must be
consistent with the data files. These checks read the CSV files directly so they do not depend
on the reconciliation logic they will later be used to test."""

import csv
import datetime as dt
from decimal import Decimal
from pathlib import Path

import pytest

from conftest import SEED_DIR
from wali.tools.sim_env import SimEnvironment

FILES = ("business", "users", "suppliers", "bank_transactions", "books", "invoices")
MATCH_WINDOW_DAYS = 5


def rows(name: str, seed_dir: Path = SEED_DIR) -> list[dict[str, str]]:
    with (seed_dir / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def by_id(name: str) -> dict[str, dict[str, str]]:
    return {row["id"]: row for row in rows(name)}


def day(row: dict[str, str], column: str = "date") -> dt.date:
    return dt.date.fromisoformat(row[column])


def as_of(ground_truth) -> dt.date:
    return dt.date.fromisoformat(ground_truth["generator"]["as_of"])


# --- Determinism -----------------------------------------------------------------------------


def write(seed_generator, out_dir: Path, seed: int) -> None:
    tables, truth = seed_generator.generate(seed, dt.date(2026, 9, 30), 90)
    seed_generator.write_seed(tables, truth, out_dir)


def test_committed_seed_data_matches_the_generator(seed_generator, ground_truth, tmp_path):
    generator = ground_truth["generator"]
    tables, truth = seed_generator.generate(
        generator["seed"], dt.date.fromisoformat(generator["as_of"]), generator["days"]
    )
    seed_generator.write_seed(tables, truth, tmp_path)

    for name in [f"{f}.csv" for f in FILES] + ["ground_truth.json"]:
        assert (tmp_path / name).read_bytes() == (SEED_DIR / name).read_bytes(), name


def test_generator_is_deterministic_and_seed_dependent(seed_generator, tmp_path):
    for folder, seed in (("a", 7), ("b", 7), ("c", 8)):
        write(seed_generator, tmp_path / folder, seed)

    def content(folder):
        return (tmp_path / folder / "bank_transactions.csv").read_bytes()

    assert content("a") == content("b")
    assert content("a") != content("c")


@pytest.mark.parametrize("seed", [1, 2, 3, 2026])
def test_other_seeds_also_produce_loadable_data(seed_generator, guard_keys, tmp_path, seed):
    write(seed_generator, tmp_path, seed)

    env = SimEnvironment.create(tmp_path, guard_keys[1])
    env.close()


# --- Shape required by the specification ------------------------------------------------------


def test_every_row_is_labelled_synthetic(ground_truth):
    assert ground_truth["label"] == "SYNTHETIC"
    for name in FILES:
        table = rows(name)
        assert table, name
        assert {row["data_label"] for row in table} == {"SYNTHETIC"}, name


def test_one_business_three_users_one_per_role():
    assert len(rows("business")) == 1
    assert sorted(row["role"] for row in rows("users")) == ["bookkeeper", "owner", "staff"]


def test_eight_to_ten_suppliers_with_exactly_one_unverified():
    suppliers = rows("suppliers")

    assert 8 <= len(suppliers) <= 10
    assert [s["account_verified"] for s in suppliers].count("false") == 1
    assert len({s["verified_account"] for s in suppliers}) == len(suppliers)


def test_history_covers_sixty_to_ninety_days(ground_truth):
    dates = [day(row) for row in rows("bank_transactions")]

    assert 60 <= (max(dates) - min(dates)).days + 1 <= 90
    assert max(dates) == as_of(ground_truth)
    assert {row["kind"] for row in rows("invoices")} == {"payable", "receivable"}
    assert {"open", "paid"} <= {row["status"] for row in rows("invoices")}


def test_closing_balance_is_opening_plus_net_flow_and_never_negative(ground_truth):
    running = Decimal(ground_truth["business"]["opening_balance"])
    lowest = running
    for row in sorted(rows("bank_transactions"), key=lambda r: (r["date"], r["id"])):
        amount = Decimal(row["amount"])
        running += amount if row["direction"] == "in" else -amount
        lowest = min(lowest, running)

    assert running == Decimal(ground_truth["business"]["closing_balance"])
    assert lowest > 0


def test_book_entries_point_at_existing_invoices():
    invoices = by_id("invoices")

    linked = [row["invoice_id"] for row in rows("books") if row["invoice_id"]]
    assert linked
    assert set(linked) <= set(invoices)


# --- Ground truth is consistent with the files ------------------------------------------------


def test_every_planted_problem_type_is_present(ground_truth):
    for name, items in ground_truth["reconciliation"].items():
        assert len(items) >= 3, name
    for name, items in ground_truth["invoices"].items():
        assert items, name
    assert len(ground_truth["invoices"]["duplicate_invoices"]) >= 2


def test_duplicate_bank_entries_are_real_copies(ground_truth):
    bank = by_id("bank_transactions")

    for item in ground_truth["reconciliation"]["duplicate_bank"]:
        original, copy = bank[item["original"]], bank[item["duplicate"]]
        for column in ("amount", "direction", "counterparty", "memo", "reference"):
            assert original[column] == copy[column]
        assert 0 <= (day(copy) - day(original)).days <= 1


def test_amount_mismatches_differ_by_the_recorded_difference(ground_truth):
    bank, books = by_id("bank_transactions"), by_id("books")

    for item in ground_truth["reconciliation"]["amount_mismatches"]:
        bank_amount = Decimal(bank[item["bank_id"]]["amount"])
        book_amount = Decimal(books[item["book_id"]]["amount"])
        assert bank_amount == Decimal(item["bank_amount"])
        assert book_amount == Decimal(item["book_amount"])
        assert bank_amount - book_amount == Decimal(item["difference"]) != 0
        assert abs(bank_amount - book_amount) / book_amount < Decimal("0.05")
        assert bank[item["bank_id"]]["direction"] == books[item["book_id"]]["direction"]


def test_timing_differences_are_the_same_payment_a_few_days_apart(ground_truth):
    bank, books = by_id("bank_transactions"), by_id("books")

    for item in ground_truth["reconciliation"]["timing_differences"]:
        tx, entry = bank[item["bank_id"]], books[item["book_id"]]
        assert tx["amount"] == entry["amount"]
        assert tx["direction"] == entry["direction"]
        assert (day(tx) - day(entry)).days == item["days_apart"]
        assert 1 <= item["days_apart"] <= 3


def nearby_same_amount(row, others) -> list[dict[str, str]]:
    return [
        other
        for other in others
        if other["amount"] == row["amount"]
        and other["direction"] == row["direction"]
        and abs((day(other) - day(row)).days) <= MATCH_WINDOW_DAYS
    ]


def test_unmatched_items_have_no_counterpart_on_the_other_side(ground_truth):
    bank, books = by_id("bank_transactions"), by_id("books")

    for item in ground_truth["reconciliation"]["unmatched_bank"]:
        assert nearby_same_amount(bank[item["bank_id"]], books.values()) == []
    for item in ground_truth["reconciliation"]["unmatched_books"]:
        assert nearby_same_amount(books[item["book_id"]], bank.values()) == []


def test_planted_problems_do_not_overlap(ground_truth):
    recon = ground_truth["reconciliation"]
    bank_ids = (
        [i["duplicate"] for i in recon["duplicate_bank"]]
        + [i["original"] for i in recon["duplicate_bank"]]
        + [i["bank_id"] for i in recon["amount_mismatches"]]
        + [i["bank_id"] for i in recon["unmatched_bank"]]
        + [i["bank_id"] for i in recon["timing_differences"]]
    )
    book_ids = (
        [i["book_id"] for i in recon["amount_mismatches"]]
        + [i["book_id"] for i in recon["unmatched_books"]]
        + [i["book_id"] for i in recon["timing_differences"]]
    )

    assert len(bank_ids) == len(set(bank_ids))
    assert len(book_ids) == len(set(book_ids))


def test_everything_else_in_the_bank_feed_has_an_exact_books_match(ground_truth):
    """Outside the planted problems, each bank transaction pairs with exactly one books entry of
    the same amount and direction on the same day."""
    recon = ground_truth["reconciliation"]
    planted_bank = (
        {i["duplicate"] for i in recon["duplicate_bank"]}
        | {i["bank_id"] for i in recon["amount_mismatches"]}
        | {i["bank_id"] for i in recon["unmatched_bank"]}
        | {i["bank_id"] for i in recon["timing_differences"]}
    )
    planted_books = (
        {i["book_id"] for i in recon["amount_mismatches"]}
        | {i["book_id"] for i in recon["unmatched_books"]}
        | {i["book_id"] for i in recon["timing_differences"]}
    )

    def key(row):
        return (row["date"], row["direction"], row["amount"])

    clean_bank = sorted(key(r) for r in rows("bank_transactions") if r["id"] not in planted_bank)
    clean_books = sorted(key(r) for r in rows("books") if r["id"] not in planted_books)

    assert clean_bank == clean_books
    assert len(clean_bank) > 150


def test_duplicate_invoices_share_supplier_and_basis(ground_truth):
    invoices = by_id("invoices")

    for item in ground_truth["invoices"]["duplicate_invoices"]:
        original, copy = invoices[item["original"]], invoices[item["duplicate"]]
        assert original["counterparty_id"] == copy["counterparty_id"] == item["supplier_id"]
        assert original["amount"] == copy["amount"]
        assert copy["status"] == "open"
        if item["basis"] == "same_number":
            assert original["number"] == copy["number"]
        else:
            assert original["number"] != copy["number"]
            assert original["issue_date"] == copy["issue_date"]


def test_flagged_invoices_match_their_description(ground_truth):
    invoices, suppliers = by_id("invoices"), by_id("suppliers")
    planted = ground_truth["invoices"]

    for item in planted["account_change_fraud"]:
        invoice, supplier = invoices[item["invoice_id"]], suppliers[item["supplier_id"]]
        assert supplier["account_verified"] == "true"
        assert invoice["stated_account"] == item["stated_account"]
        assert invoice["stated_account"] != supplier["verified_account"]
        assert item["stated_account"] in invoice["document_text"]

    for item in planted["unverified_supplier"]:
        assert suppliers[item["supplier_id"]]["account_verified"] == "false"
        assert invoices[item["invoice_id"]]["status"] == "open"

    for item in planted["amount_anomaly"]:
        average = Decimal(suppliers[item["supplier_id"]]["avg_invoice_amount"])
        assert Decimal(invoices[item["invoice_id"]]["amount"]) > average * Decimal("1.3")


def test_overdue_lists_follow_the_plain_definition(ground_truth):
    cutoff = as_of(ground_truth)

    for kind, key in (("payable", "overdue_payables"), ("receivable", "overdue_receivables")):
        expected = sorted(
            row["id"]
            for row in rows("invoices")
            if row["kind"] == kind and row["status"] == "open" and day(row, "due_date") < cutoff
        )
        assert sorted(ground_truth["invoices"][key]) == expected
        assert len(expected) >= 2


def test_there_is_an_ordinary_small_and_an_ordinary_larger_open_payable(ground_truth):
    """Later phases need one clean invoice that can be paid without confirmation and one that
    needs it, so the seed must keep at least one of each from a verified supplier."""
    planted = ground_truth["invoices"]
    single = ("account_change_fraud", "unverified_supplier", "amount_anomaly")
    flagged = {item["invoice_id"] for key in single for item in planted[key]}
    for pair in planted["duplicate_invoices"]:
        flagged |= {pair["original"], pair["duplicate"]}
    suppliers = by_id("suppliers")
    cutoff = as_of(ground_truth)

    amounts = [
        Decimal(row["amount"])
        for row in rows("invoices")
        if row["kind"] == "payable"
        and row["status"] == "open"
        and row["id"] not in flagged
        and day(row, "due_date") >= cutoff
        and suppliers[row["counterparty_id"]]["account_verified"] == "true"
    ]

    assert any(amount < 1_000_000 for amount in amounts)
    assert any(1_000_000 < amount <= 5_000_000 for amount in amounts)
