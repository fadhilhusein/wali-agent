import datetime as dt
import shutil
from decimal import Decimal

import pytest

from conftest import SEED_DIR
from wali.guard.keys import generate_keypair
from wali.models import NewBookEntry, Principal
from wali.tools.base import (
    AccessDenied,
    FinancialEnvironment,
    NotFound,
    ToolFailure,
    ToolTimeout,
)
from wali.tools.organiser_env import OrganiserEnvironment
from wali.tools.sim_env import PROTOCOL_METHODS, SeedDataError, SimEnvironment

FAR_PAST = dt.date(2000, 1, 1)
FAR_FUTURE = dt.date(2100, 1, 1)


# --- Helpers ---------------------------------------------------------------------------------


def flagged_invoice_ids(ground_truth) -> set[str]:
    planted = ground_truth["invoices"]
    single = ("account_change_fraud", "unverified_supplier", "amount_anomaly")
    ids = {item["invoice_id"] for key in single for item in planted[key]}
    for pair in planted["duplicate_invoices"]:
        ids |= {pair["original"], pair["duplicate"]}
    return ids


@pytest.fixture
def payable(env, owner, ground_truth):
    """An ordinary open payable from a verified supplier that the balance can cover."""
    balance = env.get_balance(owner).amount
    for invoice in env.list_invoices(owner, "payable", status="open"):
        if invoice.id in flagged_invoice_ids(ground_truth) or invoice.amount > balance:
            continue
        supplier = env.get_supplier(owner, invoice.counterparty_id)
        if supplier.account_verified:
            return invoice, supplier
    pytest.fail("The seed data holds no ordinary open payable")


def snapshot(env, owner):
    return (
        env.get_balance(owner).amount,
        len(env.list_transactions(owner, FAR_PAST, FAR_FUTURE, limit=1000)),
        len(env.list_payments()),
        [i.id for i in env.list_invoices(owner, "payable", status="open")],
    )


def assert_rejected(env, owner, approval, expected_text):
    before = snapshot(env, owner)
    result = env.execute_payment(approval)

    assert result.status == "rejected"
    assert result.transaction_id is None
    assert expected_text in result.message.lower()
    assert snapshot(env, owner) == before


# --- Loading ---------------------------------------------------------------------------------


def test_environment_satisfies_the_protocol(env):
    assert isinstance(env, FinancialEnvironment)
    assert isinstance(OrganiserEnvironment(), FinancialEnvironment)


def test_balance_matches_ground_truth(env, owner, ground_truth):
    balance = env.get_balance(owner)

    assert balance.amount == Decimal(ground_truth["business"]["closing_balance"])
    assert balance.currency == ground_truth["business"]["currency"]
    assert env.as_of_date == dt.date.fromisoformat(ground_truth["generator"]["as_of"])


def test_missing_seed_directory_is_an_error(guard_keys, tmp_path):
    with pytest.raises(SeedDataError, match="not found"):
        SimEnvironment.create(tmp_path / "nowhere", guard_keys[1])


def test_malformed_seed_row_is_an_error_that_names_the_file_and_line(guard_keys, tmp_path):
    seed_dir = tmp_path / "seed"
    shutil.copytree(SEED_DIR, seed_dir)
    path = seed_dir / "bank_transactions.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    cells = lines[3].split(",")
    cells[2] = "not-a-number"
    lines[3] = ",".join(cells)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(SeedDataError, match=r"bank_transactions\.csv line 4: invalid amount"):
        SimEnvironment.create(seed_dir, guard_keys[1])


def test_create_refuses_to_overwrite_and_open_keeps_state(
    guard_keys, tmp_path, now, owner, ground_truth, make_approval
):
    db_path = tmp_path / "sim" / "wali.db"
    first = SimEnvironment.create(SEED_DIR, guard_keys[1], db_path=db_path, clock=lambda: now)
    invoice = first.list_invoices(owner, "payable", status="open")[0]
    supplier = first.get_supplier(owner, invoice.counterparty_id)
    assert first.execute_payment(make_approval(invoice, supplier)).status == "success"
    first.close()

    with pytest.raises(FileExistsError):
        SimEnvironment.create(SEED_DIR, guard_keys[1], db_path=db_path)

    reopened = SimEnvironment.open(db_path, guard_keys[1], clock=lambda: now)
    try:
        expected = Decimal(ground_truth["business"]["closing_balance"]) - invoice.amount
        assert reopened.get_balance(owner).amount == expected
        assert [p.invoice_id for p in reopened.list_payments()] == [invoice.id]
    finally:
        reopened.close()

    with pytest.raises(FileNotFoundError):
        SimEnvironment.open(tmp_path / "absent.db", guard_keys[1])


def test_a_malformed_public_key_is_rejected(tmp_path):
    db_path = tmp_path / "wali.db"

    with pytest.raises(ValueError):
        SimEnvironment.create(SEED_DIR, "not-a-key", db_path=db_path)
    assert not db_path.exists()


# --- Role scopes -----------------------------------------------------------------------------


def test_owner_and_bookkeeper_can_read_everything(env, owner, bookkeeper):
    for principal in (owner, bookkeeper):
        assert env.get_balance(principal).amount > 0
        assert env.list_transactions(principal, FAR_PAST, FAR_FUTURE)
        payables = env.list_invoices(principal, "payable")
        assert payables
        assert env.list_invoices(principal, "receivable")
        assert env.get_supplier(principal, payables[0].counterparty_id)
        categories = {e.category for e in env.get_book_entries(principal, FAR_PAST, FAR_FUTURE)}
        assert {"sales", "payroll"} <= categories


def test_staff_cannot_read_balance_bank_feed_payables_or_suppliers(env, owner, staff):
    supplier_id = env.list_invoices(owner, "payable")[0].counterparty_id

    with pytest.raises(AccessDenied):
        env.get_balance(staff)
    with pytest.raises(AccessDenied):
        env.list_transactions(staff, FAR_PAST, FAR_FUTURE)
    with pytest.raises(AccessDenied):
        env.list_invoices(staff, "payable")
    with pytest.raises(AccessDenied):
        env.get_supplier(staff, supplier_id)


def test_staff_sees_only_sales_in_the_books_and_never_payroll(env, owner, staff):
    everything = env.get_book_entries(owner, FAR_PAST, FAR_FUTURE)
    visible = env.get_book_entries(staff, FAR_PAST, FAR_FUTURE)

    assert visible
    assert {e.category for e in visible} == {"sales"}
    assert len(visible) < len(everything)
    payroll_ids = {e.id for e in everything if e.category == "payroll"}
    assert payroll_ids
    assert payroll_ids.isdisjoint(e.id for e in visible)


def test_staff_can_see_receivables(env, staff):
    receivables = env.list_invoices(staff, "receivable")

    assert receivables
    assert {i.kind for i in receivables} == {"receivable"}


def test_staff_cannot_record_book_entries(env, staff):
    entry = NewBookEntry(
        date=dt.date(2026, 10, 1), amount="1000", direction="out", category="other", description="x"
    )

    with pytest.raises(AccessDenied):
        env.record_book_entry(staff, entry)


@pytest.mark.parametrize("method", [m for m in PROTOCOL_METHODS if m != "execute_payment"])
def test_forged_principals_are_denied_everywhere(env, owner, staff, method):
    """A role claimed without being the stored role of that user changes nothing."""
    forged = [
        Principal(user_id=staff.user_id, role="owner", business_id=staff.business_id),
        Principal(user_id="user-nobody", role="owner", business_id=owner.business_id),
        Principal(user_id=owner.user_id, role="owner", business_id="biz-other"),
    ]
    entry = NewBookEntry(
        date=dt.date(2026, 10, 1), amount="1000", direction="out", category="other", description="x"
    )
    arguments = {
        "get_balance": (),
        "list_transactions": (FAR_PAST, FAR_FUTURE),
        "list_invoices": ("payable",),
        "get_supplier": ("sup-anything",),
        "get_book_entries": (FAR_PAST, FAR_FUTURE),
        "record_book_entry": (entry,),
    }[method]

    for principal in forged:
        with pytest.raises(AccessDenied):
            getattr(env, method)(principal, *arguments)


# --- Reads -----------------------------------------------------------------------------------


def test_list_transactions_filters_orders_and_limits(env, owner):
    start, end = dt.date(2026, 9, 1), dt.date(2026, 9, 30)
    september = env.list_transactions(owner, start, end)

    assert september
    assert all(start <= t.date <= end for t in september)
    assert [(t.date, t.id) for t in september] == sorted((t.date, t.id) for t in september)
    assert env.list_transactions(owner, start, end, limit=5) == september[:5]
    assert len(env.list_transactions(owner, start, start)) < len(september)


def test_list_transactions_rejects_bad_arguments(env, owner):
    with pytest.raises(ValueError):
        env.list_transactions(owner, dt.date(2026, 9, 30), dt.date(2026, 9, 1))
    with pytest.raises(ValueError):
        env.list_transactions(owner, FAR_PAST, FAR_FUTURE, limit=0)
    with pytest.raises(ValueError):
        env.list_transactions(owner, FAR_PAST, FAR_FUTURE, limit=10_000)
    with pytest.raises(ValueError):
        env.get_book_entries(owner, dt.date(2026, 9, 30), dt.date(2026, 9, 1))


def test_list_invoices_filters(env, owner, ground_truth):
    payables = env.list_invoices(owner, "payable")
    open_payables = env.list_invoices(owner, "payable", status="open")
    overdue = env.list_invoices(owner, "payable", status="open", due_before=env.as_of_date)

    assert {i.kind for i in payables} == {"payable"}
    assert {i.status for i in open_payables} == {"open"}
    assert len(open_payables) < len(payables)
    assert sorted(i.id for i in overdue) == sorted(ground_truth["invoices"]["overdue_payables"])
    assert all(i.due_date < env.as_of_date for i in overdue)

    overdue_receivables = env.list_invoices(
        owner, "receivable", status="open", due_before=env.as_of_date
    )
    assert sorted(i.id for i in overdue_receivables) == sorted(
        ground_truth["invoices"]["overdue_receivables"]
    )


def test_list_invoices_rejects_unknown_kind_or_status(env, owner):
    with pytest.raises(ValueError):
        env.list_invoices(owner, "everything")
    with pytest.raises(ValueError):
        env.list_invoices(owner, "payable", status="pending")


def test_get_supplier_reports_missing_suppliers(env, owner):
    with pytest.raises(NotFound):
        env.get_supplier(owner, "sup-does-not-exist")


def test_the_account_change_invoice_keeps_the_registered_account_separate(env, owner, ground_truth):
    planted = ground_truth["invoices"]["account_change_fraud"][0]
    invoice = next(i for i in env.list_invoices(owner, "payable") if i.id == planted["invoice_id"])
    supplier = env.get_supplier(owner, invoice.counterparty_id)

    assert invoice.stated_account == planted["stated_account"]
    assert invoice.stated_account != supplier.verified_account
    assert invoice.document_text


# --- Book entries ----------------------------------------------------------------------------


def test_record_book_entry_adds_an_entry_and_never_touches_money(env, bookkeeper, owner):
    before = snapshot(env, owner)
    day = dt.date(2026, 10, 1)
    entry = NewBookEntry(
        date=day, amount="15000", direction="out", category="bank_fee", description="Admin fee"
    )

    first = env.record_book_entry(bookkeeper, entry)
    second = env.record_book_entry(owner, entry)

    assert first.id != second.id
    assert first.amount == Decimal("15000")
    assert first.reconciled is False
    assert [e.id for e in env.get_book_entries(owner, day, day)] == [first.id, second.id]
    assert snapshot(env, owner) == before


def test_record_book_entry_rejects_an_unknown_invoice(env, bookkeeper, owner):
    day = dt.date(2026, 10, 1)
    entry = NewBookEntry(
        date=day, amount="1", direction="out", category="other", description="x", invoice_id="nope"
    )

    with pytest.raises(NotFound):
        env.record_book_entry(bookkeeper, entry)
    assert env.get_book_entries(owner, day, day) == []


# --- Payments --------------------------------------------------------------------------------


def test_a_valid_approval_pays_the_registered_account_once(env, owner, payable, make_approval, now):
    invoice, supplier = payable
    balance_before = env.get_balance(owner).amount

    result = env.execute_payment(make_approval(invoice, supplier))

    assert result.status == "success"
    assert env.get_balance(owner).amount == balance_before - invoice.amount
    assert invoice.id not in [i.id for i in env.list_invoices(owner, "payable", status="open")]
    assert invoice.id in [i.id for i in env.list_invoices(owner, "payable", status="paid")]

    (payment,) = env.list_payments()
    assert payment.destination_account == supplier.verified_account
    assert payment.amount == invoice.amount
    assert payment.transaction_id == result.transaction_id

    (transaction,) = [
        t
        for t in env.list_transactions(owner, now.date(), now.date())
        if t.id == result.transaction_id
    ]
    assert (transaction.direction, transaction.amount) == ("out", invoice.amount)
    assert transaction.counterparty == supplier.name


def test_missing_approval_is_rejected(env, owner):
    assert_rejected(env, owner, None, "no valid approval")
    assert_rejected(env, owner, {"invoice_id": "inv-0001"}, "no valid approval")


def test_unsigned_approval_is_rejected(env, owner, payable, make_approval):
    unsigned = make_approval(*payable).model_copy(update={"signature": ""})

    assert_rejected(env, owner, unsigned, "signature")


def test_approval_signed_by_another_key_is_rejected(env, owner, payable, make_approval):
    forged = make_approval(*payable, private_key=generate_keypair()[0])

    assert_rejected(env, owner, forged, "signature")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("amount", Decimal("1")),
        ("destination_account", "SIM-9999-000111"),
        ("invoice_id", "inv-0001"),
        ("supplier_id", "sup-other"),
        ("business_id", "biz-other"),
        ("approval_id", "ap-another"),
        ("proposal_hash", "another-hash"),
        ("expires_at", dt.datetime(2099, 1, 1, tzinfo=dt.UTC)),
    ],
)
def test_approval_changed_after_signing_is_rejected(
    env, owner, payable, make_approval, field, value
):
    tampered = make_approval(*payable).model_copy(update={field: value})

    assert_rejected(env, owner, tampered, "signature")


def test_expired_approval_is_rejected(env, owner, payable, make_approval, now):
    just_expired = make_approval(*payable, expires_at=now)
    long_expired = make_approval(*payable, expires_at=now - dt.timedelta(hours=1))

    assert_rejected(env, owner, just_expired, "expired")
    assert_rejected(env, owner, long_expired, "expired")


def test_reused_approval_is_rejected(env, owner, payable, make_approval):
    invoice, supplier = payable
    approval = make_approval(invoice, supplier)
    balance_before = env.get_balance(owner).amount

    assert env.execute_payment(approval).status == "success"
    assert_rejected(env, owner, approval, "already used")
    assert env.get_balance(owner).amount == balance_before - invoice.amount
    assert len(env.list_payments()) == 1


def test_a_second_approval_for_a_paid_invoice_is_rejected(env, owner, payable, make_approval):
    assert env.execute_payment(make_approval(*payable)).status == "success"

    assert_rejected(env, owner, make_approval(*payable), "not open")
    assert len(env.list_payments()) == 1


def test_wrong_destination_is_rejected_even_when_signed(env, owner, payable, make_approval):
    wrong = make_approval(*payable, destination_account="SIM-9999-000111")

    assert_rejected(env, owner, wrong, "registered account")


def test_unverified_supplier_account_is_rejected_even_when_signed(
    env, owner, ground_truth, make_approval
):
    planted = ground_truth["invoices"]["unverified_supplier"][0]
    invoice = next(i for i in env.list_invoices(owner, "payable") if i.id == planted["invoice_id"])
    supplier = env.get_supplier(owner, invoice.counterparty_id)
    assert supplier.account_verified is False

    assert_rejected(env, owner, make_approval(invoice, supplier), "not verified")


def test_approval_that_does_not_match_the_invoice_is_rejected(env, owner, payable, make_approval):
    invoice, supplier = payable
    other_supplier = next(
        env.get_supplier(owner, i.counterparty_id)
        for i in env.list_invoices(owner, "payable")
        if i.counterparty_id != supplier.id
    )

    assert_rejected(
        env, owner, make_approval(invoice, supplier, amount=invoice.amount + 1), "does not match"
    )
    assert_rejected(env, owner, make_approval(invoice, other_supplier), "does not match")
    assert_rejected(env, owner, make_approval(invoice, supplier, currency="USD"), "does not match")


def test_approval_for_another_business_is_rejected(env, owner, payable, make_approval):
    assert_rejected(
        env, owner, make_approval(*payable, business_id="biz-other"), "different business"
    )


def test_approval_for_a_missing_or_receivable_invoice_is_rejected(
    env, owner, payable, make_approval
):
    invoice, supplier = payable
    receivable = env.list_invoices(owner, "receivable", status="open")[0]

    assert_rejected(
        env, owner, make_approval(invoice, supplier, invoice_id="inv-nope"), "does not exist"
    )
    assert_rejected(env, owner, make_approval(receivable, supplier), "not a payable")


def test_payment_larger_than_the_balance_is_rejected(env, owner, make_approval):
    balance = env.get_balance(owner).amount
    invoice = next(
        i for i in env.list_invoices(owner, "payable", status="open") if i.amount > balance
    )
    supplier = env.get_supplier(owner, invoice.counterparty_id)

    assert_rejected(env, owner, make_approval(invoice, supplier), "not sufficient")


# --- Failure injection -----------------------------------------------------------------------


def outcomes(env, owner, calls=60):
    seen = []
    for _ in range(calls):
        try:
            env.get_balance(owner)
            seen.append("ok")
        except ToolTimeout:
            seen.append("timeout")
        except ToolFailure:
            seen.append("error")
    return seen


def test_no_failures_by_default(env, owner):
    assert set(outcomes(env, owner)) == {"ok"}


def test_failure_injection_is_reproducible_for_a_seed(make_env, owner):
    first = outcomes(make_env(fail_rate=0.3, seed=7), owner)
    second = outcomes(make_env(fail_rate=0.3, seed=7), owner)
    other_seed = outcomes(make_env(fail_rate=0.3, seed=8), owner)

    assert first == second
    assert set(first) == {"ok", "timeout", "error"}
    assert first != other_seed


def test_fail_rate_one_fails_every_call(make_env, owner):
    assert "ok" not in outcomes(make_env(fail_rate=1.0), owner)


def test_fail_rate_must_be_a_probability(make_env):
    with pytest.raises(ValueError):
        make_env(fail_rate=1.5)


def test_access_is_checked_before_a_failure_is_simulated(make_env, staff):
    env = make_env(fail_rate=1.0)

    with pytest.raises(AccessDenied):
        env.get_balance(staff)


def test_targeted_failures_hit_one_method_the_requested_number_of_times(env, owner):
    env.inject_failure("list_invoices", times=2)
    env.inject_failure("get_balance", timeout=True)

    for _ in range(2):
        with pytest.raises(ToolFailure):
            env.list_invoices(owner, "payable")
    assert env.list_invoices(owner, "payable")

    with pytest.raises(ToolTimeout):
        env.get_balance(owner)
    assert env.get_balance(owner).amount > 0

    with pytest.raises(ValueError):
        env.inject_failure("not_a_method")
    assert set(PROTOCOL_METHODS) == {
        name for name in dir(FinancialEnvironment) if not name.startswith("_")
    }


def test_a_failed_payment_changes_nothing_and_can_be_retried(env, owner, payable, make_approval):
    invoice, _ = payable
    approval = make_approval(*payable)
    before = snapshot(env, owner)
    env.inject_failure("execute_payment")

    with pytest.raises(ToolFailure):
        env.execute_payment(approval)
    assert snapshot(env, owner) == before

    assert env.execute_payment(approval).status == "success"
    assert [p.invoice_id for p in env.list_payments()] == [invoice.id]


def test_a_failed_book_entry_changes_nothing(env, bookkeeper, owner):
    day = dt.date(2026, 10, 1)
    entry = NewBookEntry(date=day, amount="1", direction="out", category="other", description="x")
    env.inject_failure("record_book_entry")

    with pytest.raises(ToolFailure):
        env.record_book_entry(bookkeeper, entry)
    assert env.get_book_entries(owner, day, day) == []


# --- Organiser slot --------------------------------------------------------------------------


def test_organiser_environment_is_an_explicit_empty_slot(owner):
    env = OrganiserEnvironment()

    with pytest.raises(NotImplementedError, match="not implemented yet"):
        env.get_balance(owner)
    with pytest.raises(NotImplementedError):
        env.execute_payment(None)
