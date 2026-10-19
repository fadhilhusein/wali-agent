"""The guard service end to end against the simulated environment and the seed data."""

import datetime as dt
from decimal import Decimal

import pytest

from conftest import activate_mandate, flagged_invoice_ids, mandate_request
from wali.guard.audit import verify_chain
from wali.guard.keys import generate_keypair
from wali.guard.service import GuardService
from wali.models import Principal
from wali.tools.base import ToolTimeout

FAR_PAST = dt.date(2000, 1, 1)
FAR_FUTURE = dt.date(2100, 1, 1)


# --- Helpers ---------------------------------------------------------------------------------


def clean_invoices(world, owner, ground_truth, low, high):
    """Ordinary open payables (verified supplier, nothing planted, not overdue) by amount."""
    flagged = flagged_invoice_ids(ground_truth)
    found = []
    for invoice in world.env.list_invoices(owner, "payable", status="open"):
        if invoice.id in flagged or invoice.due_date < world.env.as_of_date:
            continue
        if low <= invoice.amount <= high and not invoice.late_fee_bearing:
            found.append(invoice)
    return sorted(found, key=lambda i: (i.amount, i.id))


@pytest.fixture
def small(world, owner, ground_truth):
    """A clean invoice under the confirmation threshold."""
    return clean_invoices(world, owner, ground_truth, 1, 999_999)[0]


@pytest.fixture
def large(world, owner, ground_truth):
    """A clean invoice above the confirmation threshold and within every limit."""
    return clean_invoices(world, owner, ground_truth, 1_000_001, 4_000_000)[-1]


@pytest.fixture
def ready(world, owner):
    """A world with the standard mandate active."""
    activate_mandate(world.guard, owner)
    return world


def snapshot(world, owner):
    return (
        world.env.get_balance(owner).amount,
        len(world.env.list_payments()),
        len(world.env.get_book_entries(owner, FAR_PAST, FAR_FUTURE)),
    )


def events(world) -> list[str]:
    return [entry["event"] for entry in world.audit.entries()]


def pending_token(world) -> str:
    (request,) = world.guard.collect_confirmation_requests()
    return request.token


def lower_balance_by(world, amount) -> None:
    """Simulate money leaving the account by some other route."""
    world.env._conn.execute(
        "INSERT INTO bank_transactions VALUES ('bt-test-out', '2026-10-01', ?, 'out', "
        "'Other', 'Other payment', 'OTHER-1')",
        (str(amount),),
    )


def invoice_by_id(world, owner, invoice_id):
    return next(i for i in world.env.list_invoices(owner, "payable") if i.id == invoice_id)


# --- No mandate ------------------------------------------------------------------------------


def test_without_a_mandate_nothing_is_paid(world, owner, bookkeeper, small):
    before = snapshot(world, owner)

    for principal in (owner, bookkeeper):
        decision = world.guard.propose_payment(principal, small.id)
        assert (decision.status, decision.reason_code) == ("denied", "MANDATE_INVALID")

    assert snapshot(world, owner) == before


# --- Small payments: allowed by the mandate, executed by the guard ---------------------------


def test_a_small_clean_payment_is_executed_and_recorded(ready, owner, bookkeeper, small):
    balance_before = ready.env.get_balance(owner).amount
    supplier = ready.env.get_supplier(owner, small.counterparty_id)

    decision = ready.guard.propose_payment(bookkeeper, small.id, session_id="s-1")

    assert decision.status == "executed"
    assert decision.transaction_id
    assert decision.summary.amount == small.amount
    assert decision.summary.registered_account == "***" + supplier.verified_account[-4:]
    assert supplier.verified_account not in decision.model_dump_json()

    assert ready.env.get_balance(owner).amount == balance_before - small.amount
    (payment,) = ready.env.list_payments()
    assert payment.destination_account == supplier.verified_account
    assert (payment.invoice_id, payment.amount) == (small.id, small.amount)
    assert invoice_by_id(ready, owner, small.id).status == "paid"

    (entry,) = [
        e
        for e in ready.env.get_book_entries(owner, FAR_PAST, FAR_FUTURE)
        if e.id.startswith("be-new")
    ]
    assert (entry.invoice_id, entry.amount, entry.direction) == (small.id, small.amount, "out")
    assert small.number in entry.description

    assert ready.guard.collect_confirmation_requests() == []
    assert events(ready)[-4:] == [
        "payment_proposed",
        "approval_issued",
        "payment_executed",
        "book_entry_recorded",
    ]


def test_the_owner_can_also_pay_a_small_invoice_directly(ready, owner, small):
    assert ready.guard.propose_payment(owner, small.id).status == "executed"


def test_paying_the_same_invoice_twice_is_refused(ready, owner, bookkeeper, small):
    assert ready.guard.propose_payment(bookkeeper, small.id).status == "executed"
    before = snapshot(ready, owner)

    again = ready.guard.propose_payment(bookkeeper, small.id)
    by_owner = ready.guard.propose_payment(owner, small.id)

    assert (again.status, again.reason_code) == ("denied", "DUPLICATE_PAYMENT")
    assert by_owner.reason_code == "DUPLICATE_PAYMENT"
    assert snapshot(ready, owner) == before
    assert len(ready.env.list_payments()) == 1


def test_the_guard_ledger_alone_stops_a_second_payment(ready, owner, bookkeeper, small):
    """Even if the environment still showed the invoice as open, the guard remembers."""
    assert ready.guard.propose_payment(bookkeeper, small.id).status == "executed"
    ready.env._conn.execute("UPDATE invoices SET status = 'open' WHERE id = ?", (small.id,))

    again = ready.guard.propose_payment(bookkeeper, small.id)

    assert again.reason_code == "DUPLICATE_PAYMENT"
    assert len(ready.env.list_payments()) == 1


# --- Larger payments: the owner must confirm -------------------------------------------------


def test_a_larger_payment_waits_for_the_owner(ready, owner, bookkeeper, large):
    before = snapshot(ready, owner)

    decision = ready.guard.propose_payment(bookkeeper, large.id)

    assert decision.status == "needs_confirmation"
    assert decision.required_role == "owner"
    assert {w.code for w in decision.risk_warnings} == {"ABOVE_CONFIRM_THRESHOLD"}
    assert decision.summary.invoice_number == large.number
    assert decision.summary.due_date == large.due_date
    assert decision.summary.balance_after == before[0] - large.amount
    assert decision.transaction_id is None
    assert snapshot(ready, owner) == before

    (request,) = ready.guard.collect_confirmation_requests()
    assert (request.kind, request.required_role) == ("payment", "owner")
    assert request.requested_by == bookkeeper.user_id
    assert request.summary == decision.summary
    assert request.expires_at == ready.clock.now + dt.timedelta(minutes=5)
    assert request.token not in decision.model_dump_json()
    assert ready.guard.collect_confirmation_requests() == []


def test_the_owner_confirms_and_the_payment_is_made(ready, owner, bookkeeper, large):
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    balance_before = ready.env.get_balance(owner).amount

    decision = ready.guard.confirm_payment(owner, token)

    assert decision.status == "executed"
    assert ready.env.get_balance(owner).amount == balance_before - large.amount
    (payment,) = ready.env.list_payments()
    assert payment.invoice_id == large.id
    assert "payment_confirmed" in events(ready)


@pytest.mark.parametrize("role", ["bookkeeper", "staff"])
def test_nobody_but_the_owner_can_confirm(ready, owner, bookkeeper, principals, large, role):
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    before = snapshot(ready, owner)

    refused = ready.guard.confirm_payment(principals[role], token)

    assert (refused.status, refused.reason_code) == ("denied", "ROLE_NOT_ALLOWED")
    assert snapshot(ready, owner) == before
    assert ready.guard.confirm_payment(owner, token).status == "executed"


def test_a_role_claimed_without_being_real_cannot_confirm(ready, owner, bookkeeper, staff, large):
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    pretenders = [
        Principal(user_id=staff.user_id, role="owner", business_id=staff.business_id),
        Principal(user_id=bookkeeper.user_id, role="owner", business_id=owner.business_id),
        Principal(user_id="user-ghost", role="owner", business_id=owner.business_id),
        Principal(user_id=owner.user_id, role="owner", business_id="biz-other"),
    ]

    for pretender in pretenders:
        refused = ready.guard.confirm_payment(pretender, token)
        assert (refused.status, refused.reason_code) == ("denied", "ROLE_NOT_ALLOWED")

    assert ready.env.list_payments() == []
    assert ready.guard.confirm_payment(owner, token).status == "executed"


def test_a_confirmation_works_only_once(ready, owner, bookkeeper, large):
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    assert ready.guard.confirm_payment(owner, token).status == "executed"
    before = snapshot(ready, owner)

    again = ready.guard.confirm_payment(owner, token)

    assert (again.status, again.reason_code) == ("denied", "CONFIRMATION_INVALID")
    assert snapshot(ready, owner) == before


def test_a_confirmation_expires_after_five_minutes(ready, owner, bookkeeper, large):
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    ready.clock.advance(minutes=5)

    expired = ready.guard.confirm_payment(owner, token)

    assert (expired.status, expired.reason_code) == ("denied", "CONFIRMATION_EXPIRED")
    assert ready.env.list_payments() == []


@pytest.mark.parametrize("token", ["", "made-up-token", None, "x" * 43])
def test_a_made_up_token_confirms_nothing(ready, owner, bookkeeper, large, token):
    ready.guard.propose_payment(bookkeeper, large.id)

    refused = ready.guard.confirm_payment(owner, token)

    assert (refused.status, refused.reason_code) == ("denied", "CONFIRMATION_INVALID")
    assert ready.env.list_payments() == []


def test_a_mandate_token_cannot_confirm_a_payment(ready, owner, bookkeeper, large):
    ready.guard.propose_payment(bookkeeper, large.id)
    payment_token = pending_token(ready)
    ready.guard.draft_mandate(owner, mandate_request(per_payment="50000000", per_week="90000000"))
    mandate_token = pending_token(ready)

    assert ready.guard.confirm_payment(owner, mandate_token).reason_code == "CONFIRMATION_INVALID"
    assert ready.guard.confirm_mandate(owner, payment_token).reason_code == "CONFIRMATION_INVALID"
    assert ready.env.list_payments() == []
    assert ready.guard.active_mandate().limits.per_payment.amount == Decimal("5000000")


# --- The proposal is re-checked when it is confirmed -----------------------------------------


@pytest.mark.parametrize("changed", ["amount", "account"])
def test_a_confirmation_is_void_if_what_would_be_paid_has_changed(
    ready, owner, bookkeeper, large, changed
):
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    if changed == "amount":
        ready.env._conn.execute("UPDATE invoices SET amount = '1500000' WHERE id = ?", (large.id,))
    else:
        ready.env._conn.execute(
            "UPDATE suppliers SET verified_account = 'SIM-0000-999999' WHERE id = ?",
            (large.counterparty_id,),
        )

    refused = ready.guard.confirm_payment(owner, token)

    assert (refused.status, refused.reason_code) == ("denied", "CONFIRMATION_VOID")
    assert ready.env.list_payments() == []
    assert ready.guard.confirm_payment(owner, token).reason_code == "CONFIRMATION_INVALID"


def test_confirming_after_the_invoice_was_paid_elsewhere_pays_nothing(
    ready, owner, bookkeeper, large, make_approval
):
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    supplier = ready.env.get_supplier(owner, large.counterparty_id)
    assert ready.env.execute_payment(make_approval(large, supplier)).status == "success"

    refused = ready.guard.confirm_payment(owner, token)

    assert (refused.status, refused.reason_code) == ("denied", "DUPLICATE_PAYMENT")
    assert len(ready.env.list_payments()) == 1


def test_confirming_after_the_mandate_expired_pays_nothing(ready, owner, bookkeeper, large):
    activate_mandate(ready.guard, owner, mandate_request(valid_days=1))
    ready.clock.advance(hours=23, minutes=58)
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    ready.clock.advance(minutes=3)

    refused = ready.guard.confirm_payment(owner, token)

    assert (refused.status, refused.reason_code) == ("denied", "MANDATE_EXPIRED")
    assert ready.env.list_payments() == []


def test_a_new_risk_at_confirmation_time_asks_the_owner_again(ready, owner, bookkeeper, large):
    ready.guard.propose_payment(bookkeeper, large.id)
    old_token = pending_token(ready)
    lower_balance_by(ready, 3_000_000)

    answer = ready.guard.confirm_payment(owner, old_token)

    assert answer.status == "needs_confirmation"
    assert {w.code for w in answer.risk_warnings} == {
        "ABOVE_CONFIRM_THRESHOLD",
        "BELOW_CASH_BUFFER",
    }
    assert "confirm again" in answer.user_message
    assert ready.env.list_payments() == []
    assert ready.guard.confirm_payment(owner, old_token).reason_code == "CONFIRMATION_INVALID"

    assert ready.guard.confirm_payment(owner, pending_token(ready)).status == "executed"
    assert len(ready.env.list_payments()) == 1


def test_a_newer_proposal_for_the_same_invoice_replaces_the_older_one(
    ready, owner, bookkeeper, large
):
    ready.guard.propose_payment(bookkeeper, large.id)
    old_token = pending_token(ready)
    ready.guard.propose_payment(bookkeeper, large.id)
    new_token = pending_token(ready)

    assert ready.guard.confirm_payment(owner, old_token).reason_code == "CONFIRMATION_INVALID"
    assert ready.guard.confirm_payment(owner, new_token).status == "executed"
    assert len(ready.env.list_payments()) == 1


def test_a_withdrawn_proposal_cannot_be_confirmed(ready, owner, bookkeeper, staff, large):
    decision = ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)

    assert ready.guard.withdraw_proposal(staff, decision.proposal_id) is False
    assert ready.guard.withdraw_proposal(bookkeeper, "p-unknown") is False
    assert ready.guard.withdraw_proposal(bookkeeper, decision.proposal_id) is True

    assert ready.guard.confirm_payment(owner, token).reason_code == "CONFIRMATION_INVALID"
    assert ready.env.list_payments() == []


def test_the_owner_can_decline_instead_of_confirming(ready, owner, bookkeeper, large):
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)

    assert ready.guard.cancel_confirmation(bookkeeper, token, "payment") is False
    assert ready.guard.cancel_confirmation(owner, token, "payment") is True

    assert ready.guard.confirm_payment(owner, token).reason_code == "CONFIRMATION_INVALID"
    assert ready.env.list_payments() == []
    assert "confirmation_cancelled" in events(ready)


# --- Roles -----------------------------------------------------------------------------------


def test_staff_cannot_propose_and_the_environment_is_not_even_read(ready, owner, staff, small):
    ready.env.inject_failure("list_invoices", times=3)
    before = len(ready.env.list_payments())

    decision = ready.guard.propose_payment(staff, small.id)

    assert (decision.status, decision.reason_code) == ("denied", "ROLE_NOT_ALLOWED")
    assert decision.summary is None
    assert len(ready.env.list_payments()) == before
    assert ready.guard.collect_confirmation_requests() == []


def test_a_forged_principal_cannot_propose(ready, owner, staff, small):
    pretender = Principal(user_id=staff.user_id, role="owner", business_id=staff.business_id)
    outsider = Principal(user_id=owner.user_id, role="owner", business_id="biz-other")

    for principal in (pretender, outsider):
        decision = ready.guard.propose_payment(principal, small.id)
        assert (decision.status, decision.reason_code) == ("denied", "ROLE_NOT_ALLOWED")

    assert ready.env.list_payments() == []


def test_a_bookkeeper_cannot_propose_above_the_role_limit(ready, owner, bookkeeper, large):
    activate_mandate(ready.guard, owner, mandate_request(bookkeeper_max_propose="1000000"))

    refused = ready.guard.propose_payment(bookkeeper, large.id)

    assert (refused.status, refused.reason_code) == ("denied", "ROLE_NOT_ALLOWED")
    assert ready.guard.propose_payment(owner, large.id).status == "needs_confirmation"


# --- Hard denials that raise a review item ---------------------------------------------------


def test_the_invoice_that_changes_the_bank_account_is_refused_and_flagged(
    ready, owner, bookkeeper, ground_truth
):
    planted = ground_truth["invoices"]["account_change_fraud"][0]
    before = snapshot(ready, owner)

    for principal in (bookkeeper, owner):
        decision = ready.guard.propose_payment(principal, planted["invoice_id"])
        assert (decision.status, decision.reason_code) == ("denied", "SUPPLIER_ACCOUNT_MISMATCH")
        assert planted["stated_account"] not in decision.model_dump_json()

    assert snapshot(ready, owner) == before
    assert ready.guard.collect_confirmation_requests() == []
    (item,) = ready.guard.review_items(owner)
    assert (item.invoice_id, item.reason_code, item.created_by) == (
        planted["invoice_id"],
        "SUPPLIER_ACCOUNT_MISMATCH",
        "guard",
    )
    assert "review_item_created" in events(ready)


def test_duplicate_invoices_are_refused_and_flagged(ready, owner, bookkeeper, ground_truth):
    before = snapshot(ready, owner)
    pairs = ground_truth["invoices"]["duplicate_invoices"]

    for pair in pairs:
        decision = ready.guard.propose_payment(bookkeeper, pair["duplicate"])
        assert (decision.status, decision.reason_code) == ("denied", "DUPLICATE_INVOICE")

    assert snapshot(ready, owner) == before
    assert [i.invoice_id for i in ready.guard.review_items(owner)] == [
        pair["duplicate"] for pair in pairs
    ]


def test_an_unverified_new_supplier_is_refused_and_flagged(ready, owner, ground_truth):
    planted = ground_truth["invoices"]["unverified_supplier"][0]

    decision = ready.guard.propose_payment(owner, planted["invoice_id"])

    assert (decision.status, decision.reason_code) == ("denied", "NEW_SUPPLIER")
    assert ready.env.list_payments() == []
    assert [i.reason_code for i in ready.guard.review_items(owner)] == ["NEW_SUPPLIER"]


def test_a_supplier_left_out_of_the_mandate_cannot_be_paid(ready, owner, bookkeeper, small):
    others = [s for s in mandate_request().allowed_suppliers if s != small.counterparty_id]
    activate_mandate(ready.guard, owner, mandate_request(allowed_suppliers=others))

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert (decision.status, decision.reason_code) == ("denied", "NEW_SUPPLIER")
    assert ready.env.list_payments() == []


def test_repeated_attempts_do_not_flood_the_review_list(ready, owner, bookkeeper, ground_truth):
    invoice_id = ground_truth["invoices"]["account_change_fraud"][0]["invoice_id"]

    for _ in range(4):
        ready.guard.propose_payment(bookkeeper, invoice_id)

    assert len(ready.guard.review_items(owner)) == 1


def test_only_the_owner_sees_review_items(ready, owner, bookkeeper, staff, ground_truth):
    ready.guard.propose_payment(
        bookkeeper, ground_truth["invoices"]["account_change_fraud"][0]["invoice_id"]
    )

    assert len(ready.guard.review_items(owner)) == 1
    assert ready.guard.review_items(bookkeeper) == []
    assert ready.guard.review_items(staff) == []


# --- Limits, balance, anomalies, rate --------------------------------------------------------


def test_an_amount_over_the_per_payment_limit_is_refused(ready, owner):
    too_big = next(
        i
        for i in ready.env.list_invoices(owner, "payable", status="open")
        if i.amount > Decimal("5000000") and i.late_fee_bearing
    )

    decision = ready.guard.propose_payment(owner, too_big.id)

    assert (decision.status, decision.reason_code) == ("denied", "OVER_PAYMENT_LIMIT")
    assert ready.env.list_payments() == []


def test_small_payments_cannot_add_up_past_the_weekly_limit(ready, owner, bookkeeper, ground_truth):
    first, second = clean_invoices(ready, owner, ground_truth, 1, 999_999)[:2]
    limit = first.amount + second.amount - 1
    activate_mandate(
        ready.guard,
        owner,
        mandate_request(
            per_payment=str(limit),
            per_week=str(limit),
            confirm_above=str(limit),
            bookkeeper_max_propose=str(limit),
            min_cash_buffer="0",
            valid_days=60,
        ),
    )

    assert ready.guard.propose_payment(bookkeeper, first.id).status == "executed"
    refused = ready.guard.propose_payment(bookkeeper, second.id)

    assert (refused.status, refused.reason_code) == ("denied", "OVER_WEEK_LIMIT")
    assert len(ready.env.list_payments()) == 1

    ready.clock.advance(days=7, seconds=1)
    assert ready.guard.propose_payment(bookkeeper, second.id).status == "executed"


def test_the_weekly_limit_is_remembered_across_a_restart(ready, owner, bookkeeper, ground_truth):
    first, second = clean_invoices(ready, owner, ground_truth, 1, 999_999)[:2]
    limit = str(first.amount + second.amount - 1)
    activate_mandate(
        ready.guard,
        owner,
        mandate_request(
            per_payment=limit, per_week=limit, confirm_above=limit, bookkeeper_max_propose=limit
        ),
    )
    assert ready.guard.propose_payment(bookkeeper, first.id).status == "executed"

    restarted = ready.make_guard()

    assert restarted.propose_payment(bookkeeper, second.id).reason_code == "OVER_WEEK_LIMIT"


def test_dropping_below_the_cash_buffer_needs_the_owner(ready, owner, bookkeeper, small):
    balance = ready.env.get_balance(owner).amount
    activate_mandate(ready.guard, owner, mandate_request(min_cash_buffer=str(balance)))

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert decision.status == "needs_confirmation"
    assert {w.code for w in decision.risk_warnings} == {"BELOW_CASH_BUFFER"}
    assert ready.env.list_payments() == []


def test_a_payment_the_balance_cannot_cover_is_refused(ready, owner, large):
    lower_balance_by(ready, ready.env.get_balance(owner).amount - 1000)

    decision = ready.guard.propose_payment(owner, large.id)

    assert (decision.status, decision.reason_code) == ("denied", "BELOW_CASH_BUFFER")
    assert ready.env.list_payments() == []


def test_an_unusually_large_invoice_needs_the_owner(ready, owner, bookkeeper, ground_truth):
    planted = ground_truth["invoices"]["amount_anomaly"][0]

    decision = ready.guard.propose_payment(bookkeeper, planted["invoice_id"])

    assert decision.status == "needs_confirmation"
    assert "AMOUNT_ABOVE_SUPPLIER_AVERAGE" in {w.code for w in decision.risk_warnings}
    assert ready.env.list_payments() == []


def test_suspected_injection_turns_a_small_payment_into_a_confirmation(
    ready, owner, bookkeeper, small
):
    decision = ready.guard.propose_payment(bookkeeper, small.id, suspicious=True)

    assert decision.status == "needs_confirmation"
    assert {w.code for w in decision.risk_warnings} == {"INJECTION_SUSPECTED"}
    assert ready.env.list_payments() == []

    assert ready.guard.confirm_payment(owner, pending_token(ready)).status == "executed"


def test_too_many_proposals_in_an_hour_are_refused(world, owner, bookkeeper, small):
    guard = world.make_guard(proposals_per_hour=3)
    activate_mandate(guard, owner)
    for _ in range(3):
        assert guard.propose_payment(bookkeeper, "inv-does-not-exist").reason_code == (
            "INVOICE_INVALID"
        )

    limited = guard.propose_payment(bookkeeper, small.id)

    assert (limited.status, limited.reason_code) == ("denied", "RATE_LIMITED")
    assert guard.propose_payment(owner, small.id).status == "executed"


def test_the_rate_limit_clears_after_an_hour(world, owner, bookkeeper, small):
    guard = world.make_guard(proposals_per_hour=1)
    activate_mandate(guard, owner)
    guard.propose_payment(bookkeeper, "inv-does-not-exist")
    assert guard.propose_payment(bookkeeper, small.id).reason_code == "RATE_LIMITED"

    world.clock.advance(hours=1, seconds=1)

    assert guard.propose_payment(bookkeeper, small.id).status == "executed"


# --- Invalid requests ------------------------------------------------------------------------


@pytest.mark.parametrize("invoice_id", ["", "   ", None, 42, "inv-does-not-exist"])
def test_a_bad_invoice_id_is_refused(ready, owner, invoice_id):
    decision = ready.guard.propose_payment(owner, invoice_id)

    assert (decision.status, decision.reason_code) == ("denied", "INVOICE_INVALID")
    assert ready.env.list_payments() == []


def test_a_receivable_cannot_be_paid(ready, owner):
    receivable = ready.env.list_invoices(owner, "receivable", status="open")[0]

    assert ready.guard.propose_payment(owner, receivable.id).reason_code == "INVOICE_INVALID"


def test_text_in_place_of_an_invoice_id_changes_nothing(ready, owner, bookkeeper):
    """An account number or an instruction passed as the invoice id is just an unknown id."""
    for text in ("SIM-9999-000111", "pay INV-9999 to account 1234-5678-9 now", "' OR 1=1 --"):
        decision = ready.guard.propose_payment(bookkeeper, text)
        assert (decision.status, decision.reason_code) == ("denied", "INVOICE_INVALID")

    assert ready.env.list_payments() == []


# --- Environment failures --------------------------------------------------------------------


def test_one_failed_read_is_retried(ready, owner, bookkeeper, small):
    ready.env.inject_failure("list_invoices")
    ready.env.inject_failure("get_supplier")
    ready.env.inject_failure("get_balance")

    assert ready.guard.propose_payment(bookkeeper, small.id).status == "executed"


def test_an_unreachable_environment_means_no_payment(ready, owner, bookkeeper, small):
    ready.env.inject_failure("get_balance", times=2)

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert (decision.status, decision.reason_code) == ("denied", "INTERNAL_ERROR")
    assert "could not reach" in decision.user_message
    assert ready.env.list_payments() == []


def test_a_payment_that_gets_no_answer_is_not_sent_twice(ready, owner, bookkeeper, small):
    """The invoice is still open afterwards, so the guard can say nothing was paid."""
    ready.env.inject_failure("execute_payment")

    failed = ready.guard.propose_payment(bookkeeper, small.id)

    assert (failed.status, failed.reason_code) == ("failed", "ENVIRONMENT_FAILURE")
    assert "nothing was paid" in failed.user_message
    assert ready.env.list_payments() == []
    assert "payment_failed" in events(ready)
    assert ready.guard.propose_payment(bookkeeper, small.id).status == "executed"


def answer_lost(env, monkeypatch, *, then_unreachable=False):
    """The bank pays, but its answer never arrives."""
    pay = env.execute_payment

    def lost(approval):
        pay(approval)
        if then_unreachable:
            env.inject_failure("list_invoices", times=2)
        raise ToolTimeout("No answer in time.")

    monkeypatch.setattr(env, "execute_payment", lost)


def test_a_payment_whose_answer_is_lost_is_reported_as_possibly_paid(
    ready, owner, bookkeeper, small, monkeypatch
):
    answer_lost(ready.env, monkeypatch)

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert (decision.status, decision.reason_code) == ("failed", "OUTCOME_UNCERTAIN")
    assert "nothing was paid" not in decision.user_message
    assert "shows as paid" in decision.user_message
    assert len(ready.env.list_payments()) == 1
    monkeypatch.undo()
    assert ready.guard.propose_payment(bookkeeper, small.id).reason_code == "DUPLICATE_PAYMENT"


def test_a_payment_whose_outcome_cannot_be_checked_is_reported_as_uncertain(
    ready, owner, bookkeeper, small, monkeypatch
):
    answer_lost(ready.env, monkeypatch, then_unreachable=True)

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert (decision.status, decision.reason_code) == ("failed", "OUTCOME_UNCERTAIN")
    assert "not certain" in decision.user_message
    assert "nothing was paid" not in decision.user_message


def test_a_books_entry_after_a_payment_is_not_written_twice(
    ready, owner, bookkeeper, small, monkeypatch
):
    calls = []

    def unanswered(*args):
        calls.append(args)
        raise ToolTimeout("No answer in time.")

    monkeypatch.setattr(ready.env, "record_book_entry", unanswered)

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert decision.status == "executed"
    assert len(calls) == 1


def test_a_payment_the_environment_rejects_is_reported_as_failed(world, owner, bookkeeper, small):
    """A guard whose key the environment does not trust: its approvals are rejected there."""
    untrusted = GuardService(
        world.env,
        generate_keypair()[0],
        world.audit,
        business_id=world.env.business_id,
        currency=world.env.currency,
        clock=world.clock,
    )
    activate_mandate(untrusted, owner)

    decision = untrusted.propose_payment(bookkeeper, small.id)

    assert (decision.status, decision.reason_code) == ("failed", "ENVIRONMENT_REJECTED")
    assert "nothing was paid" in decision.user_message
    assert world.env.list_payments() == []
    assert "payment_rejected" in events(world)


def test_a_payment_still_counts_when_the_books_entry_fails(ready, owner, bookkeeper, small):
    ready.env.inject_failure("record_book_entry", times=2)

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert decision.status == "executed"
    assert "books entry could not be recorded" in decision.user_message
    assert len(ready.env.list_payments()) == 1
    assert ready.guard.propose_payment(bookkeeper, small.id).reason_code == "DUPLICATE_PAYMENT"


def test_no_books_entry_when_the_mandate_does_not_allow_it(ready, owner, bookkeeper, small):
    activate_mandate(ready.guard, owner, mandate_request(allowed_actions=["pay_invoice"]))
    entries_before = len(ready.env.get_book_entries(owner, FAR_PAST, FAR_FUTURE))

    assert ready.guard.propose_payment(bookkeeper, small.id).status == "executed"
    assert len(ready.env.get_book_entries(owner, FAR_PAST, FAR_FUTURE)) == entries_before


# --- Failing closed --------------------------------------------------------------------------


def test_an_unexpected_error_is_a_refusal_not_a_payment(ready, owner, bookkeeper, small, large):
    def boom(*args, **kwargs):
        raise RuntimeError("database on fire")

    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    ready.store.proposals_since = boom
    ready.store.paid_since = boom

    proposed = ready.guard.propose_payment(bookkeeper, small.id)
    confirmed = ready.guard.confirm_payment(owner, token)

    assert (proposed.status, proposed.reason_code) == ("denied", "INTERNAL_ERROR")
    assert (confirmed.status, confirmed.reason_code) == ("denied", "INTERNAL_ERROR")
    assert ready.env.list_payments() == []
    assert "error" in events(ready)


def test_if_the_audit_log_cannot_be_written_nothing_is_paid(ready, owner, bookkeeper, small):
    def boom(**kwargs):
        raise OSError("disk full")

    ready.audit.append = boom

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert (decision.status, decision.reason_code) == ("denied", "INTERNAL_ERROR")
    assert ready.env.list_payments() == []


def test_a_mandate_that_expires_stops_payments(ready, owner, bookkeeper, small):
    ready.clock.advance(days=30)

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert (decision.status, decision.reason_code) == ("denied", "MANDATE_EXPIRED")
    assert ready.env.list_payments() == []


def test_a_mandate_changed_in_storage_stops_payments(ready, owner, bookkeeper, small):
    payload = ready.store.active_mandate_payload()
    ready.store._conn.execute(
        "UPDATE mandates SET payload = ?", (payload.replace('"5000000"', '"900000000"'),)
    )

    decision = ready.guard.propose_payment(bookkeeper, small.id)

    assert (decision.status, decision.reason_code) == ("denied", "MANDATE_INVALID")
    assert ready.env.list_payments() == []


# --- Flagging --------------------------------------------------------------------------------


def test_owner_and_bookkeeper_can_flag_an_invoice(ready, owner, bookkeeper, staff, large):
    before = snapshot(ready, owner)

    flagged = ready.guard.flag_for_review(bookkeeper, large.id, "  Supplier called twice.  ")
    again = ready.guard.flag_for_review(owner, large.id, "x" * 2000)
    refused = ready.guard.flag_for_review(staff, large.id, "let me see")
    unknown = ready.guard.flag_for_review(bookkeeper, "inv-nope", "?")

    assert flagged.status == "flagged"
    assert again.review_id == flagged.review_id
    assert (refused.status, refused.reason_code) == ("denied", "ROLE_NOT_ALLOWED")
    assert (unknown.status, unknown.reason_code) == ("denied", "INVOICE_INVALID")
    (item,) = ready.guard.review_items(owner)
    assert (item.invoice_id, item.reason, item.created_by) == (
        large.id,
        "Supplier called twice.",
        bookkeeper.user_id,
    )
    assert snapshot(ready, owner) == before


def test_a_long_reason_is_cut_short(ready, owner, large):
    ready.guard.flag_for_review(owner, large.id, "x" * 2000)

    assert len(ready.guard.review_items(owner)[0].reason) == 500


# --- Audit and secrets -----------------------------------------------------------------------


def test_everything_is_audited_and_the_chain_holds(
    ready, owner, bookkeeper, staff, small, large, ground_truth
):
    ready.guard.propose_payment(bookkeeper, small.id, session_id="s-book")
    ready.guard.propose_payment(staff, large.id, session_id="s-staff")
    ready.guard.propose_payment(
        bookkeeper, ground_truth["invoices"]["account_change_fraud"][0]["invoice_id"]
    )
    ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    ready.guard.confirm_payment(bookkeeper, token)
    ready.guard.confirm_payment(owner, token)

    seen = set(events(ready))
    assert {
        "mandate_drafted",
        "mandate_activated",
        "payment_proposed",
        "payment_denied",
        "review_item_created",
        "confirmation_requested",
        "confirmation_refused",
        "payment_confirmed",
        "approval_issued",
        "payment_executed",
        "book_entry_recorded",
    } <= seen
    status = verify_chain(ready.audit.path)
    assert status.ok
    assert status.entries == len(ready.audit.entries())

    denied = [e for e in ready.audit.entries() if e["event"] == "payment_denied"]
    assert {e["data"]["reason_code"] for e in denied} == {
        "ROLE_NOT_ALLOWED",
        "SUPPLIER_ACCOUNT_MISMATCH",
    }
    by_session = {e["session_id"] for e in ready.audit.entries()}
    assert {"s-book", "s-staff"} <= by_session


def test_secrets_never_reach_the_audit_log_or_a_decision(
    ready, owner, bookkeeper, small, large, guard_keys
):
    executed = ready.guard.propose_payment(bookkeeper, small.id)
    waiting = ready.guard.propose_payment(bookkeeper, large.id)
    token = pending_token(ready)
    confirmed = ready.guard.confirm_payment(owner, token)
    mandate = ready.guard.active_mandate()

    log_text = ready.audit.path.read_text(encoding="utf-8")
    decisions = "".join(d.model_dump_json() for d in (executed, waiting, confirmed))

    for secret in (token, guard_keys[0], mandate.signature, "ed25519:"):
        assert secret not in log_text
        assert secret not in decisions
    for supplier_id in (small.counterparty_id, large.counterparty_id):
        account = ready.env.get_supplier(owner, supplier_id).verified_account
        assert account not in log_text
        assert account not in decisions
