"""Guard service refusals and failures that the other service tests do not reach: the books
entry path, the review path, a failing environment, and the guard's own records failing."""

import datetime as dt
from decimal import Decimal

import pytest

from conftest import activate_mandate, flagged_invoice_ids, mandate_request
from wali.guard.service import GuardService
from wali.models import NewBookEntry

DAY = dt.date(2026, 10, 1)


def book_entry(**changes) -> NewBookEntry:
    fields = {
        "date": DAY,
        "amount": Decimal("12500.50"),
        "direction": "out",
        "category": "supplies",
        "description": "Ink",
    }
    fields.update(changes)
    return NewBookEntry(**fields)


def events(world) -> list[str]:
    return [entry["event"] for entry in world.audit.entries()]


def clean_invoices(world, owner, ground_truth, low, high):
    flagged = flagged_invoice_ids(ground_truth)
    return sorted(
        (
            i
            for i in world.env.list_invoices(owner, "payable", status="open")
            if i.id not in flagged
            and i.due_date >= world.env.as_of_date
            and low <= i.amount <= high
            and not i.late_fee_bearing
        ),
        key=lambda i: (i.amount, i.id),
    )


@pytest.fixture
def small_invoice(world, owner, ground_truth):
    return clean_invoices(world, owner, ground_truth, 1, 999_999)[0]


@pytest.fixture
def large_invoice(world, owner, ground_truth):
    return clean_invoices(world, owner, ground_truth, 1_000_001, 4_000_000)[-1]


# --- Books entries ---------------------------------------------------------------------------


def test_a_books_entry_is_recorded_exactly_as_given_and_audited(ready, bookkeeper):
    decision = ready.guard.record_book_entry(bookkeeper, book_entry())

    assert decision.status == "recorded"
    assert decision.entry.amount == Decimal("12500.50")
    assert decision.entry in ready.env.get_book_entries(bookkeeper, DAY, DAY)
    assert ready.env.list_payments() == []


def test_a_books_entry_needs_a_valid_mandate(world, bookkeeper):
    decision = world.guard.record_book_entry(bookkeeper, book_entry())

    assert (decision.status, decision.reason_code) == ("denied", "MANDATE_INVALID")
    assert "book_entry_denied" in events(world)


def test_a_mandate_without_the_books_action_refuses_a_books_entry(world, owner, bookkeeper):
    activate_mandate(world.guard, owner, mandate_request(allowed_actions=["pay_invoice"]))

    decision = world.guard.record_book_entry(bookkeeper, book_entry())

    assert (decision.status, decision.reason_code) == ("denied", "MANDATE_INVALID")
    assert "does not allow recording book entries" in decision.user_message


def test_staff_cannot_record_a_books_entry(ready, staff):
    decision = ready.guard.record_book_entry(staff, book_entry())

    assert (decision.status, decision.reason_code) == ("denied", "ROLE_NOT_ALLOWED")


def test_an_entry_for_an_unknown_invoice_is_refused_without_recording_anything(ready, bookkeeper):
    before = len(ready.env.get_book_entries(bookkeeper, DAY, DAY))

    decision = ready.guard.record_book_entry(bookkeeper, book_entry(invoice_id="inv-nope"))

    assert (decision.status, decision.reason_code) == ("denied", "INVOICE_INVALID")
    assert len(ready.env.get_book_entries(bookkeeper, DAY, DAY)) == before


def test_an_unreachable_environment_refuses_a_books_entry(ready, bookkeeper):
    ready.env.inject_failure("record_book_entry", times=2)

    decision = ready.guard.record_book_entry(bookkeeper, book_entry())

    assert (decision.status, decision.reason_code) == ("denied", "INTERNAL_ERROR")


def test_an_expired_mandate_refuses_a_books_entry(ready, bookkeeper):
    ready.clock.advance(days=31)

    decision = ready.guard.record_book_entry(bookkeeper, book_entry())

    assert (decision.status, decision.reason_code) == ("denied", "MANDATE_EXPIRED")


# --- Review items ----------------------------------------------------------------------------


def test_an_unreachable_environment_refuses_to_flag_an_invoice(ready, bookkeeper, large_invoice):
    ready.env.inject_failure("list_invoices", times=2)

    decision = ready.guard.flag_for_review(bookkeeper, large_invoice.id, "check it")

    assert (decision.status, decision.reason_code) == ("denied", "INTERNAL_ERROR")
    assert ready.guard.review_items(bookkeeper) == []


def test_only_the_owner_sees_the_review_list(ready, owner, bookkeeper, staff, large_invoice):
    ready.guard.flag_for_review(bookkeeper, large_invoice.id, "check it")

    assert ready.guard.review_items(bookkeeper) == []
    assert ready.guard.review_items(staff) == []
    assert [item.invoice_id for item in ready.guard.review_items(owner)] == [large_invoice.id]


# --- Drafting a mandate while the environment fails -----------------------------------------


def test_an_unreachable_supplier_lookup_refuses_a_draft_and_leaves_nothing_to_confirm(world, owner):
    world.env.inject_failure("get_supplier", times=2)

    decision = world.guard.draft_mandate(owner, mandate_request())

    assert (decision.status, decision.reason_code) == ("denied", "INTERNAL_ERROR")
    assert world.guard.collect_confirmation_requests() == []


# --- Mandate request limits at the edge ------------------------------------------------------


@pytest.mark.parametrize("days", [0, 367])
def test_a_mandate_cannot_be_valid_for_zero_or_over_a_year(days):
    with pytest.raises(ValueError):
        mandate_request(valid_days=days)


@pytest.mark.parametrize("days", [1, 366])
def test_a_mandate_can_be_valid_for_one_day_or_exactly_a_year(world, owner, days):
    decision = world.guard.draft_mandate(owner, mandate_request(valid_days=days))

    assert decision.status == "needs_confirmation"


@pytest.mark.parametrize("field", ["per_payment", "per_week"])
@pytest.mark.parametrize("value", ["0", "-1"])
def test_a_request_with_a_zero_or_negative_limit_never_reaches_the_guard(field, value):
    with pytest.raises(ValueError):
        mandate_request(**{field: value})


@pytest.mark.parametrize("field", ["confirm_above", "min_cash_buffer"])
def test_a_request_with_a_negative_threshold_never_reaches_the_guard(field):
    with pytest.raises(ValueError):
        mandate_request(**{field: "-1"})


def test_a_request_with_the_same_supplier_twice_is_refused_with_a_plain_reason(world, owner):
    first = mandate_request().allowed_suppliers[0]

    decision = world.guard.draft_mandate(owner, mandate_request(allowed_suppliers=[first, first]))

    assert (decision.status, decision.reason_code) == ("denied", "MANDATE_INVALID")
    assert world.guard.collect_confirmation_requests() == []


# --- The guard's clock -----------------------------------------------------------------------


def test_a_guard_clock_without_a_timezone_is_refused(world, guard_keys, bookkeeper, small_invoice):
    naive = GuardService(
        world.env,
        guard_keys[0],
        world.audit,
        business_id=world.env.business_id,
        currency=world.env.currency,
        store=world.store,
        clock=lambda: dt.datetime(2026, 10, 1, 9, 0),
    )

    decision = naive.propose_payment(bookkeeper, small_invoice.id)

    assert decision.status == "denied"
    assert world.env.list_payments() == []


# --- Failures after the money moved ---------------------------------------------------------


def test_a_failure_writing_the_guards_own_record_is_noted_but_the_payment_stands(
    ready, owner, bookkeeper, small_invoice, monkeypatch
):
    def broken(**kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(ready.store, "record_execution", broken)

    decision = ready.guard.propose_payment(bookkeeper, small_invoice.id)

    assert decision.status == "executed"
    assert "could not be written to the guard's own records" in decision.user_message
    assert len(ready.env.list_payments()) == 1
