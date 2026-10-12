"""Reconcile a bank feed against the books.

Matching runs in passes, strongest evidence first. A pair must always have the same direction
and dates no further apart than the date window.

1. Same amount, and the bank reference appears in the books description.
2. Same amount.
3. Different amount within the mismatch ratio, and the reference appears in the description.
4. What is still left over and is a copy of another record on its own side (same amount,
   counterparty and reference, close in date) is reported as a suspected duplicate.
5. Different amount within the mismatch ratio, without a reference.

Anything still left over is unmatched. Within a pass the closest dates win, and ties are broken
by date and id, so the result does not depend on the order of the input.
"""

from __future__ import annotations

import datetime as dt
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Sequence
from dataclasses import dataclass
from decimal import Decimal

from wali.config import Settings
from wali.models import (
    AmountMismatch,
    BankTransaction,
    BookEntry,
    DuplicateGroup,
    MatchedPair,
    ReconciliationReport,
)

Period = tuple[dt.date, dt.date]


@dataclass(frozen=True)
class ReconcileConfig:
    date_window_days: int = 3
    # Differences up to this size still count as the same amount.
    amount_tolerance: Decimal = Decimal("0")
    # Largest relative difference still treated as the same payment with a different amount.
    mismatch_max_ratio: Decimal = Decimal("0.05")
    # Shorter references are ignored: they would match descriptions by accident.
    min_reference_length: int = 4

    @classmethod
    def from_settings(cls, settings: Settings) -> ReconcileConfig:
        return cls(
            date_window_days=settings.recon_date_window_days,
            amount_tolerance=settings.recon_amount_tolerance,
            mismatch_max_ratio=settings.recon_mismatch_max_ratio,
        )


def _gap(a: dt.date, b: dt.date) -> int:
    return abs((a - b).days)


def _by_date_then_id(record: BankTransaction | BookEntry) -> tuple[dt.date, str]:
    return (record.date, record.id)


def _unique(records: Iterable, what: str) -> dict:
    ordered = sorted(records, key=_by_date_then_id)
    by_id = {record.id: record for record in ordered}
    if len(by_id) != len(ordered):
        raise ValueError(f"Duplicate ids in the {what}")
    return by_id


def _bank_identity(tx: BankTransaction) -> Hashable:
    return (tx.direction, tx.amount, tx.counterparty.casefold(), tx.reference.casefold())


def _book_identity(entry: BookEntry) -> Hashable:
    return (
        entry.direction,
        entry.amount,
        entry.category.casefold(),
        entry.description.casefold(),
        entry.invoice_id,
    )


def _find_duplicates(
    source: str,
    everything: dict,
    leftover: dict,
    identity: Callable[..., Hashable],
    window_days: int,
) -> list[DuplicateGroup]:
    """Move leftover records that copy another record on the same side out of ``leftover``.

    The original is the matched record they copy. If no copy is matched, the earliest record
    stays in ``leftover`` as the original and the later ones are its duplicates.
    """
    by_identity = defaultdict(list)
    for record in everything.values():
        by_identity[identity(record)].append(record)

    copies: dict[str, list[str]] = defaultdict(list)
    for record in list(leftover.values()):
        if record.id not in leftover:
            continue
        twins = [
            other
            for other in by_identity[identity(record)]
            if other.id != record.id and _gap(other.date, record.date) <= window_days
        ]
        matched_twins = [other for other in twins if other.id not in leftover]
        if matched_twins:
            original = min(matched_twins, key=lambda o: (_gap(o.date, record.date), o.date, o.id))
            copies[original.id].append(record.id)
            del leftover[record.id]
        elif twins:
            # The loop runs oldest first, so this record is the earliest of its group.
            for twin in twins:
                if twin.id in leftover:
                    copies[record.id].append(twin.id)
                    del leftover[twin.id]

    return [
        DuplicateGroup(
            source=source,
            original_id=original_id,
            duplicate_ids=duplicate_ids,
            amount=everything[original_id].amount,
        )
        for original_id, duplicate_ids in copies.items()
    ]


def reconcile(
    bank: Sequence[BankTransaction],
    books: Sequence[BookEntry],
    config: ReconcileConfig | None = None,
    period: Period | None = None,
) -> ReconciliationReport:
    """Match ``bank`` against ``books`` and report what does not line up.

    With ``period`` (first day, last day), everything given is used for matching but only
    findings dated inside the period are reported. Pass records from a few days either side of
    the period so that a payment clearing just outside it is not reported as missing.

    Findings are ordered with the largest amounts first.
    """
    config = config or ReconcileConfig()
    all_bank: dict[str, BankTransaction] = _unique(bank, "bank feed")
    all_books: dict[str, BookEntry] = _unique(books, "books")
    free_bank = dict(all_bank)
    free_books = dict(all_books)
    matched: list[tuple[BankTransaction, BookEntry]] = []
    mismatched: list[tuple[BankTransaction, BookEntry]] = []

    def reference_matches(tx: BankTransaction, entry: BookEntry) -> bool:
        reference = tx.reference.strip().casefold()
        return (
            len(reference) >= config.min_reference_length
            and reference in entry.description.casefold()
        )

    def run_pass(
        target: list[tuple[BankTransaction, BookEntry]], *, same_amount: bool, need_reference: bool
    ) -> None:
        books_by_date = defaultdict(list)
        for entry in free_books.values():
            books_by_date[entry.date].append(entry)

        candidates = []
        for tx in free_bank.values():
            for offset in range(-config.date_window_days, config.date_window_days + 1):
                for entry in books_by_date.get(tx.date + dt.timedelta(days=offset), ()):
                    if entry.direction != tx.direction:
                        continue
                    difference = abs(tx.amount - entry.amount)
                    is_same = difference <= config.amount_tolerance
                    if is_same != same_amount:
                        continue
                    ratio = difference / max(tx.amount, entry.amount)
                    if not is_same and ratio > config.mismatch_max_ratio:
                        continue
                    if need_reference and not reference_matches(tx, entry):
                        continue
                    rank = (ratio, abs(offset), tx.date, tx.id, entry.date, entry.id)
                    candidates.append((rank, tx, entry))

        for _, tx, entry in sorted(candidates, key=lambda c: c[0]):
            if tx.id in free_bank and entry.id in free_books:
                del free_bank[tx.id]
                del free_books[entry.id]
                target.append((tx, entry))

    run_pass(matched, same_amount=True, need_reference=True)
    run_pass(matched, same_amount=True, need_reference=False)
    run_pass(mismatched, same_amount=False, need_reference=True)
    duplicates = _find_duplicates(
        "bank", all_bank, free_bank, _bank_identity, config.date_window_days
    ) + _find_duplicates("books", all_books, free_books, _book_identity, config.date_window_days)
    run_pass(mismatched, same_amount=False, need_reference=False)

    def in_period(*dates: dt.date) -> bool:
        return period is None or any(period[0] <= day <= period[1] for day in dates)

    def duplicate_dates(group: DuplicateGroup) -> list[dt.date]:
        records = all_bank if group.source == "bank" else all_books
        return [records[record_id].date for record_id in group.duplicate_ids]

    return ReconciliationReport(
        matched=[
            MatchedPair(bank_id=tx.id, book_id=entry.id)
            for tx, entry in sorted(matched, key=lambda pair: _by_date_then_id(pair[0]))
            if in_period(tx.date, entry.date)
        ],
        unmatched_bank=sorted(
            (tx for tx in free_bank.values() if in_period(tx.date)),
            key=lambda tx: (-tx.amount, tx.date, tx.id),
        ),
        unmatched_books=sorted(
            (entry for entry in free_books.values() if in_period(entry.date)),
            key=lambda entry: (-entry.amount, entry.date, entry.id),
        ),
        amount_mismatches=sorted(
            (
                AmountMismatch(
                    bank_id=tx.id,
                    book_id=entry.id,
                    bank_amount=tx.amount,
                    book_amount=entry.amount,
                    difference=tx.amount - entry.amount,
                )
                for tx, entry in mismatched
                if in_period(tx.date, entry.date)
            ),
            key=lambda m: (-abs(m.difference), m.bank_id),
        ),
        suspected_duplicates=sorted(
            (group for group in duplicates if in_period(*duplicate_dates(group))),
            key=lambda g: (-g.amount, g.source, g.original_id),
        ),
    )


def discrepancy_keys(report: ReconciliationReport) -> set[tuple[str, ...]]:
    """Every finding in a report as a comparable key, for scoring against a ground truth."""
    keys: set[tuple[str, ...]] = set()
    keys |= {("unmatched_bank", tx.id) for tx in report.unmatched_bank}
    keys |= {("unmatched_books", entry.id) for entry in report.unmatched_books}
    keys |= {("amount_mismatch", m.bank_id, m.book_id) for m in report.amount_mismatches}
    for group in report.suspected_duplicates:
        keys |= {(f"duplicate_{group.source}", record_id) for record_id in group.duplicate_ids}
    return keys
