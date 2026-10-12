import datetime as dt
import random
from decimal import Decimal

import pytest

from conftest import precision_recall_f1, truth_discrepancy_keys
from wali.config import load_settings
from wali.finance.reconcile import ReconcileConfig, discrepancy_keys, reconcile
from wali.models import BankTransaction, BookEntry

FAR_PAST = dt.date(2000, 1, 1)
FAR_FUTURE = dt.date(2100, 1, 1)
SEPTEMBER = (dt.date(2026, 9, 1), dt.date(2026, 9, 30))


def day(n: int, month: int = 9) -> dt.date:
    return dt.date(2026, month, n)


def tx(id, on, amount, direction="out", counterparty="Supplier A", reference="", memo=""):
    return BankTransaction(
        id=id,
        date=on,
        amount=Decimal(amount),
        direction=direction,
        counterparty=counterparty,
        memo=memo,
        reference=reference,
    )


def entry(id, on, amount, direction="out", category="inventory", description="", invoice_id=None):
    return BookEntry(
        id=id,
        date=on,
        amount=Decimal(amount),
        direction=direction,
        category=category,
        description=description,
        invoice_id=invoice_id,
    )


def pairs(report) -> list[tuple[str, str]]:
    return [(m.bank_id, m.book_id) for m in report.matched]


def ids(records) -> list[str]:
    return [r.id for r in records]


# --- Matching rules --------------------------------------------------------------------------


def test_empty_input_gives_an_empty_report():
    report = reconcile([], [])

    assert report.matched == []
    assert discrepancy_keys(report) == set()


def test_same_amount_same_day_matches():
    report = reconcile([tx("b1", day(10), 1000)], [entry("e1", day(10), 1000)])

    assert pairs(report) == [("b1", "e1")]
    assert discrepancy_keys(report) == set()


def test_timing_difference_inside_the_window_matches_and_outside_does_not():
    inside = reconcile([tx("b1", day(13), 1000)], [entry("e1", day(10), 1000)])
    outside = reconcile([tx("b1", day(14), 1000)], [entry("e1", day(10), 1000)])

    assert pairs(inside) == [("b1", "e1")]
    assert pairs(outside) == []
    assert ids(outside.unmatched_bank) == ["b1"]
    assert ids(outside.unmatched_books) == ["e1"]


def test_money_in_never_matches_money_out():
    report = reconcile(
        [tx("b1", day(10), 1000, direction="in")], [entry("e1", day(10), 1000, direction="out")]
    )

    assert pairs(report) == []
    assert discrepancy_keys(report) == {("unmatched_bank", "b1"), ("unmatched_books", "e1")}


def test_a_matching_reference_beats_a_closer_date():
    bank = [tx("b1", day(10), 1000, reference="INV-77"), tx("b2", day(10), 1000)]
    books = [
        entry("e1", day(10), 1000, description="something else"),
        entry("e2", day(12), 1000, description="Bayar Supplier A inv-77"),
    ]

    assert pairs(reconcile(bank, books)) == [("b1", "e2"), ("b2", "e1")]


def test_without_a_reference_the_closest_date_wins():
    books = [
        entry("e1", day(8), 1000, description="Beli gula"),
        entry("e2", day(10), 1000, description="Beli susu"),
    ]
    report = reconcile([tx("b1", day(10), 1000)], books)

    assert pairs(report) == [("b1", "e2")]
    assert ids(report.unmatched_books) == ["e1"]
    assert report.suspected_duplicates == []


def test_a_very_short_reference_is_not_evidence():
    bank = [tx("b1", day(10), 1000, reference="12")]
    books = [entry("e1", day(10), 1000), entry("e2", day(11), 1000, description="Order 12")]

    assert pairs(reconcile(bank, books)) == [("b1", "e1")]


def test_small_difference_is_reported_as_an_amount_mismatch():
    report = reconcile([tx("b1", day(10), 993, direction="in")], [entry("e1", day(10), 1000, "in")])

    (mismatch,) = report.amount_mismatches
    assert (mismatch.bank_id, mismatch.book_id) == ("b1", "e1")
    assert (mismatch.bank_amount, mismatch.book_amount) == (Decimal(993), Decimal(1000))
    assert mismatch.difference == Decimal(-7)
    assert report.unmatched_bank == report.unmatched_books == []
    assert pairs(report) == []


def test_large_difference_is_two_unmatched_items_not_a_mismatch():
    report = reconcile([tx("b1", day(10), 1100)], [entry("e1", day(10), 1000)])

    assert report.amount_mismatches == []
    assert discrepancy_keys(report) == {("unmatched_bank", "b1"), ("unmatched_books", "e1")}


def test_amount_tolerance_treats_tiny_differences_as_equal():
    config = ReconcileConfig(amount_tolerance=Decimal("5"))
    report = reconcile([tx("b1", day(10), 1003)], [entry("e1", day(10), 1000)], config)

    assert pairs(report) == [("b1", "e1")]
    assert report.amount_mismatches == []


def test_an_exact_match_is_preferred_over_a_mismatch():
    bank = [tx("b1", day(10), 1007, reference="REF-1"), tx("b2", day(10), 1000)]
    books = [
        entry("e1", day(10), 1000, description="REF-1"),
        entry("e2", day(10), 1007, description="other"),
    ]
    report = reconcile(bank, books)

    assert pairs(report) == [("b1", "e2"), ("b2", "e1")]
    assert report.amount_mismatches == []


# --- Duplicates ------------------------------------------------------------------------------


def test_a_copied_bank_transaction_is_a_suspected_duplicate_not_unmatched():
    bank = [
        tx("b1", day(10), 1000, reference="INV-1"),
        tx("b2", day(11), 1000, reference="INV-1"),
    ]
    report = reconcile(bank, [entry("e1", day(10), 1000, description="Bayar INV-1")])

    assert pairs(report) == [("b1", "e1")]
    (group,) = report.suspected_duplicates
    assert (group.source, group.original_id, group.duplicate_ids) == ("bank", "b1", ["b2"])
    assert group.amount == Decimal(1000)
    assert report.unmatched_bank == []
    assert discrepancy_keys(report) == {("duplicate_bank", "b2")}


def test_two_identical_unbooked_transactions_are_one_unmatched_and_one_duplicate():
    bank = [tx("b1", day(10), 15, reference="FEE-09"), tx("b2", day(10), 15, reference="FEE-09")]
    report = reconcile(bank, [])

    assert ids(report.unmatched_bank) == ["b1"]
    assert discrepancy_keys(report) == {("unmatched_bank", "b1"), ("duplicate_bank", "b2")}


def test_a_copied_books_entry_is_a_suspected_duplicate():
    books = [
        entry("e1", day(10), 1000, description="Bayar INV-1"),
        entry("e2", day(10), 1000, description="Bayar INV-1"),
    ]
    report = reconcile([tx("b1", day(10), 1000, reference="INV-1")], books)

    (group,) = report.suspected_duplicates
    assert (group.source, group.original_id, group.duplicate_ids) == ("books", "e1", ["e2"])
    assert report.unmatched_books == []


def test_same_details_far_apart_in_time_are_not_duplicates():
    bank = [tx("b1", day(1), 1000, reference="RENT"), tx("b2", day(20), 1000, reference="RENT")]
    report = reconcile(bank, [entry("e1", day(1), 1000, description="RENT")])

    assert report.suspected_duplicates == []
    assert ids(report.unmatched_bank) == ["b2"]


def test_same_amount_but_another_counterparty_is_not_a_duplicate():
    bank = [tx("b1", day(10), 1000), tx("b2", day(10), 1000, counterparty="Supplier B")]
    report = reconcile(bank, [entry("e1", day(10), 1000)])

    assert report.suspected_duplicates == []
    assert len(report.unmatched_bank) == 1


def test_a_duplicate_is_not_paired_with_an_unrelated_entry_of_a_similar_amount():
    bank = [
        tx("b1", day(10), 1000, reference="INV-1"),
        tx("b2", day(11), 1000, reference="INV-1"),
    ]
    books = [
        entry("e1", day(10), 1000, description="Bayar INV-1"),
        entry("e2", day(11), 990, description="Servis AC"),
    ]
    report = reconcile(bank, books)

    assert report.amount_mismatches == []
    assert discrepancy_keys(report) == {("duplicate_bank", "b2"), ("unmatched_books", "e2")}


# --- Period, ordering, robustness ------------------------------------------------------------


def test_period_limits_what_is_reported_but_not_what_is_matched():
    bank = [
        tx("b1", day(31, month=8), 500, reference="INV-5"),
        tx("b2", day(20, month=8), 70),
        tx("b3", day(5), 80),
    ]
    books = [entry("e1", day(1), 500, description="Bayar INV-5"), entry("e2", day(2, 10), 90)]
    report = reconcile(bank, books, period=SEPTEMBER)

    assert pairs(report) == [("b1", "e1")]
    assert ids(report.unmatched_bank) == ["b3"]
    assert report.unmatched_books == []


def test_findings_are_ordered_largest_first():
    bank = [tx("b1", day(1), 10), tx("b2", day(2), 300), tx("b3", day(3), 20)]
    report = reconcile(bank, [])

    assert ids(report.unmatched_bank) == ["b2", "b3", "b1"]


def test_result_does_not_depend_on_input_order(seed_bank, seed_books):
    expected = reconcile(seed_bank, seed_books)
    shuffled_bank, shuffled_books = list(seed_bank), list(seed_books)
    random.Random(1).shuffle(shuffled_bank)
    random.Random(2).shuffle(shuffled_books)

    assert reconcile(shuffled_bank, shuffled_books) == expected


def test_duplicate_ids_are_refused():
    with pytest.raises(ValueError, match="bank feed"):
        reconcile([tx("b1", day(1), 10), tx("b1", day(2), 20)], [])
    with pytest.raises(ValueError, match="books"):
        reconcile([], [entry("e1", day(1), 10), entry("e1", day(2), 20)])


def test_config_comes_from_settings():
    settings = load_settings(
        env={
            "WALI_RECON_DATE_WINDOW_DAYS": "5",
            "WALI_RECON_AMOUNT_TOLERANCE": "2",
            "WALI_RECON_MISMATCH_MAX_RATIO": "0.1",
        },
        env_file=None,
    )

    assert ReconcileConfig.from_settings(settings) == ReconcileConfig(
        date_window_days=5, amount_tolerance=Decimal("2"), mismatch_max_ratio=Decimal("0.1")
    )


# --- Against the seeded ground truth ---------------------------------------------------------


@pytest.fixture
def seed_bank(env, owner):
    return env.list_transactions(owner, FAR_PAST, FAR_FUTURE, limit=1000)


@pytest.fixture
def seed_books(env, owner):
    return env.get_book_entries(owner, FAR_PAST, FAR_FUTURE)


def test_full_history_meets_the_f1_target(seed_bank, seed_books, ground_truth):
    found = discrepancy_keys(reconcile(seed_bank, seed_books))
    expected = truth_discrepancy_keys(ground_truth)

    precision, recall, f1 = precision_recall_f1(found, expected)
    assert f1 >= 0.9, (precision, recall, sorted(found ^ expected))


def test_one_month_meets_the_f1_target(seed_bank, seed_books, ground_truth):
    found = discrepancy_keys(reconcile(seed_bank, seed_books, period=SEPTEMBER))
    expected = truth_discrepancy_keys(ground_truth, SEPTEMBER)

    assert len(expected) >= 5
    precision, recall, f1 = precision_recall_f1(found, expected)
    assert f1 >= 0.9, (precision, recall, sorted(found ^ expected))


def test_every_kind_of_planted_problem_is_found(seed_bank, seed_books, ground_truth):
    found = discrepancy_keys(reconcile(seed_bank, seed_books))

    for kind in ("duplicate_bank", "amount_mismatch", "unmatched_bank", "unmatched_books"):
        expected = {key for key in truth_discrepancy_keys(ground_truth) if key[0] == kind}
        assert expected, kind
        assert found & expected, kind


def test_timing_differences_are_matched_not_reported(seed_bank, seed_books, ground_truth):
    report = reconcile(seed_bank, seed_books)
    matched = set(pairs(report))
    reported = {record_id for key in discrepancy_keys(report) for record_id in key[1:]}

    for item in ground_truth["reconciliation"]["timing_differences"]:
        assert (item["bank_id"], item["book_id"]) in matched
        assert item["bank_id"] not in reported
        assert item["book_id"] not in reported


def test_every_record_is_accounted_for_exactly_once(seed_bank, seed_books):
    report = reconcile(seed_bank, seed_books)
    duplicate_bank = [
        i for g in report.suspected_duplicates if g.source == "bank" for i in g.duplicate_ids
    ]
    duplicate_books = [
        i for g in report.suspected_duplicates if g.source == "books" for i in g.duplicate_ids
    ]
    bank_ids = (
        [m.bank_id for m in report.matched]
        + [m.bank_id for m in report.amount_mismatches]
        + ids(report.unmatched_bank)
        + duplicate_bank
    )
    book_ids = (
        [m.book_id for m in report.matched]
        + [m.book_id for m in report.amount_mismatches]
        + ids(report.unmatched_books)
        + duplicate_books
    )

    assert sorted(bank_ids) == sorted(ids(seed_bank))
    assert sorted(book_ids) == sorted(ids(seed_books))


def test_a_month_of_data_with_a_margin_gives_the_same_answer_as_the_full_history(
    env, owner, seed_bank, seed_books
):
    """A tool can fetch just the period plus the date window on each side."""
    margin = dt.timedelta(days=ReconcileConfig().date_window_days)
    first, last = SEPTEMBER[0] - margin, SEPTEMBER[1] + margin
    bank = env.list_transactions(owner, first, last, limit=1000)
    books = env.get_book_entries(owner, first, last)

    assert reconcile(bank, books, period=SEPTEMBER) == reconcile(
        seed_bank, seed_books, period=SEPTEMBER
    )
