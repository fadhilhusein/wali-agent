"""The policy as a pure function: hand-built inputs, no environment, no service."""

import datetime as dt
from decimal import Decimal

import pytest

from wali.guard.keys import generate_keypair, load_private_key, load_public_key
from wali.guard.mandate import Limits, MandateTerms, RoleAuthority, sign_mandate
from wali.guard.policy import (
    Allow,
    Deny,
    NeedsConfirmation,
    PaymentProposal,
    PaymentTerms,
    PolicyView,
    check_authority,
    evaluate,
    find_duplicate,
)
from wali.models import Invoice, Money, Principal, Supplier

NOW = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=7)))
BUSINESS = "biz-1"
ACCOUNT = "SIM-1111-222222"

PRIVATE_B64, PUBLIC_B64 = generate_keypair()
PRIVATE_KEY = load_private_key(PRIVATE_B64)
PUBLIC_KEY = load_public_key(PUBLIC_B64)

OWNER = Principal(user_id="u-owner", role="owner", business_id=BUSINESS)
BOOKKEEPER = Principal(user_id="u-book", role="bookkeeper", business_id=BUSINESS)
STAFF = Principal(user_id="u-staff", role="staff", business_id=BUSINESS)


def idr(amount) -> Money:
    return Money(amount=Decimal(amount), currency="IDR")


def mandate(key=PRIVATE_KEY, **changes):
    fields = {
        "mandate_id": "m-001",
        "business_id": BUSINESS,
        "issued_by": OWNER.user_id,
        "expires_at": NOW + dt.timedelta(days=30),
        "allowed_actions": ["pay_invoice", "record_book_entry"],
        "limits": Limits(per_payment=idr(5_000_000), per_week=idr(15_000_000)),
        "allowed_suppliers": ["sup-a", "sup-b"],
        "role_authority": {
            "owner": RoleAuthority(can_propose=True, can_confirm=True),
            "bookkeeper": RoleAuthority(can_propose=True, max_propose=Decimal(5_000_000)),
            "staff": RoleAuthority(),
        },
        "confirm_above": idr(1_000_000),
        "min_cash_buffer": idr(3_000_000),
    }
    fields.update(changes)
    return sign_mandate(MandateTerms(**fields), key)


def invoice(id="inv-1", amount=500_000, **changes) -> Invoice:
    fields = {
        "id": id,
        "kind": "payable",
        "counterparty_id": "sup-a",
        "counterparty_name": "Supplier A",
        "number": f"A/{id}",
        "amount": Decimal(amount),
        "currency": "IDR",
        "issue_date": dt.date(2026, 9, 25),
        "due_date": dt.date(2026, 10, 5),
        "status": "open",
    }
    fields.update(changes)
    return Invoice(**fields)


def supplier(**changes) -> Supplier:
    fields = {
        "id": "sup-a",
        "name": "Supplier A",
        "verified_account": ACCOUNT,
        "account_verified": True,
        "avg_invoice_amount": Decimal(500_000),
    }
    fields.update(changes)
    return Supplier(**fields)


def view(**changes) -> PolicyView:
    fields = {
        "public_key": PUBLIC_KEY,
        "business_id": BUSINESS,
        "invoice": invoice(),
        "supplier": supplier(),
        "supplier_invoices": (),
        "balance": idr(10_000_000),
        "paid_last_7_days": Decimal(0),
        "already_paid": False,
        "proposals_last_hour": 0,
        "proposals_per_hour": 10,
        "suspicious": False,
    }
    fields.update(changes)
    return PolicyView(**fields)


def proposal(principal=BOOKKEEPER, invoice_id="inv-1") -> PaymentProposal:
    return PaymentProposal(
        proposal_id="p-1",
        business_id=principal.business_id,
        invoice_id=invoice_id,
        proposed_by=principal.user_id,
    )


def decide(principal=BOOKKEEPER, signed=None, now=NOW, **view_changes):
    signed = signed if signed is not None else mandate()
    return evaluate(proposal(principal), signed, principal, view(**view_changes), now)


def code(decision) -> str:
    assert isinstance(decision, Deny), decision
    return decision.reason_code


def warnings(decision) -> set[str]:
    assert isinstance(decision, NeedsConfirmation), decision
    return {w.code for w in decision.risk_warnings}


# --- Allowed and confirmed paths -------------------------------------------------------------


def test_a_small_clean_payment_is_allowed():
    decision = decide()

    assert isinstance(decision, Allow)
    assert decision.terms.amount == Decimal(500_000)
    assert decision.terms.destination_account == ACCOUNT
    assert decision.terms.proposed_by == BOOKKEEPER.user_id
    assert decision.terms.mandate_id == "m-001"
    assert decision.balance_after == Decimal(9_500_000)


def test_the_destination_is_always_the_registered_account():
    decision = decide(invoice=invoice(stated_account=ACCOUNT))

    assert isinstance(decision, Allow)
    assert decision.terms.destination_account == ACCOUNT


def test_an_amount_above_the_threshold_needs_the_owner():
    decision = decide(
        invoice=invoice(amount=2_000_000), supplier=supplier(avg_invoice_amount=2_000_000)
    )

    assert warnings(decision) == {"ABOVE_CONFIRM_THRESHOLD"}
    assert decision.required_role == "owner"
    assert decision.balance_after == Decimal(8_000_000)


def test_the_owner_also_has_to_confirm_a_large_payment():
    decision = decide(
        OWNER, invoice=invoice(amount=2_000_000), supplier=supplier(avg_invoice_amount=2_000_000)
    )

    assert warnings(decision) == {"ABOVE_CONFIRM_THRESHOLD"}


def test_dropping_below_the_cash_buffer_needs_the_owner():
    assert warnings(decide(balance=idr(3_400_000))) == {"BELOW_CASH_BUFFER"}


def test_an_unusually_large_amount_needs_the_owner():
    decision = decide(invoice=invoice(amount=700_000))

    assert warnings(decision) == {"AMOUNT_ABOVE_SUPPLIER_AVERAGE"}


def test_a_supplier_without_history_needs_the_owner():
    assert warnings(decide(supplier=supplier(avg_invoice_amount=0))) == {"NO_SUPPLIER_HISTORY"}


def test_suspected_injection_needs_the_owner():
    assert warnings(decide(suspicious=True)) == {"INJECTION_SUSPECTED"}


def test_every_warning_that_applies_is_listed():
    decision = decide(invoice=invoice(amount=2_000_000), balance=idr(4_000_000), suspicious=True)

    assert warnings(decision) == {
        "ABOVE_CONFIRM_THRESHOLD",
        "BELOW_CASH_BUFFER",
        "AMOUNT_ABOVE_SUPPLIER_AVERAGE",
        "INJECTION_SUSPECTED",
    }


@pytest.mark.parametrize(
    "changes",
    [
        {"invoice": invoice(amount=1_000_000), "supplier": supplier(avg_invoice_amount=1_000_000)},
        {"invoice": invoice(amount=650_000)},
        {"balance": idr(3_500_000)},
        {"paid_last_7_days": Decimal(14_500_000)},
        {"proposals_last_hour": 9},
    ],
)
def test_values_exactly_on_a_limit_are_still_allowed(changes):
    assert isinstance(decide(**changes), Allow)


def test_exactly_the_per_payment_limit_is_within_the_limit():
    decision = decide(
        invoice=invoice(amount=5_000_000), supplier=supplier(avg_invoice_amount=5_000_000)
    )

    assert warnings(decision) == {"ABOVE_CONFIRM_THRESHOLD"}


# --- Rule 1: the mandate ---------------------------------------------------------------------


def test_no_mandate_means_no_payment():
    assert code(evaluate(proposal(), None, BOOKKEEPER, view(), NOW)) == "MANDATE_INVALID"


def test_a_mandate_signed_by_another_key_is_invalid():
    other = load_private_key(generate_keypair()[0])

    assert code(decide(signed=mandate(key=other))) == "MANDATE_INVALID"


def test_a_tampered_mandate_is_invalid():
    tampered = mandate().model_copy(
        update={"limits": Limits(per_payment=idr(50_000_000), per_week=idr(90_000_000))}
    )

    assert code(decide(signed=tampered, invoice=invoice(amount=40_000_000))) == "MANDATE_INVALID"


def test_a_mandate_for_another_business_is_invalid():
    assert code(decide(signed=mandate(business_id="biz-other"))) == "MANDATE_INVALID"


def test_an_expired_mandate_is_refused():
    signed = mandate()

    assert code(decide(signed=signed, now=signed.expires_at)) == "MANDATE_EXPIRED"
    assert isinstance(decide(signed=signed, now=signed.expires_at - dt.timedelta(seconds=1)), Allow)


def test_a_mandate_that_does_not_allow_payments_is_refused():
    decision = decide(signed=mandate(allowed_actions=["record_book_entry"]))

    assert code(decision) == "MANDATE_INVALID"
    assert "does not allow payments" in decision.user_message


# --- Rule 2: role authority ------------------------------------------------------------------


def test_staff_cannot_propose():
    assert code(decide(STAFF)) == "ROLE_NOT_ALLOWED"


def test_a_role_missing_from_the_mandate_cannot_propose():
    signed = mandate(role_authority={"owner": RoleAuthority(can_propose=True, can_confirm=True)})

    assert code(decide(BOOKKEEPER, signed=signed)) == "ROLE_NOT_ALLOWED"


def test_a_bookkeeper_who_may_not_propose_is_refused():
    signed = mandate(
        role_authority={
            "owner": RoleAuthority(can_propose=True, can_confirm=True),
            "bookkeeper": RoleAuthority(can_propose=False),
        }
    )

    assert code(decide(BOOKKEEPER, signed=signed)) == "ROLE_NOT_ALLOWED"
    assert isinstance(decide(OWNER, signed=signed), Allow)


def test_an_amount_above_the_role_limit_is_refused_for_that_role_only():
    signed = mandate(
        role_authority={
            "owner": RoleAuthority(can_propose=True, can_confirm=True),
            "bookkeeper": RoleAuthority(can_propose=True, max_propose=Decimal(1_000_000)),
        }
    )
    big = {"invoice": invoice(amount=2_000_000), "supplier": supplier(avg_invoice_amount=2_000_000)}

    refused = decide(BOOKKEEPER, signed=signed, **big)

    assert code(refused) == "ROLE_NOT_ALLOWED"
    assert "above what your role may propose" in refused.user_message
    assert isinstance(decide(OWNER, signed=signed, **big), NeedsConfirmation)


def test_a_proposal_must_come_from_the_principal_it_names():
    someone_elses = proposal(OWNER)

    decision = evaluate(someone_elses, mandate(), BOOKKEEPER, view(), NOW)

    assert code(decision) == "ROLE_NOT_ALLOWED"


def test_a_principal_from_another_business_is_refused():
    outsider = Principal(user_id="u-owner", role="owner", business_id="biz-other")

    assert code(decide(outsider)) == "ROLE_NOT_ALLOWED"


# --- Rule 3: the invoice ---------------------------------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"invoice": None},
        {"invoice": invoice(id="inv-other")},
        {"invoice": invoice(kind="receivable")},
        {"invoice": invoice(status="void")},
        {"invoice": invoice(currency="USD")},
    ],
)
def test_a_missing_wrong_or_closed_invoice_is_invalid(changes):
    assert code(decide(**changes)) == "INVOICE_INVALID"


def test_an_invoice_already_paid_is_a_duplicate_payment():
    assert code(decide(invoice=invoice(status="paid"))) == "DUPLICATE_PAYMENT"
    assert code(decide(already_paid=True)) == "DUPLICATE_PAYMENT"


# --- Rules 4 to 6: supplier, account, duplicates ---------------------------------------------


@pytest.mark.parametrize(
    "changes",
    [
        {"supplier": None},
        {"supplier": supplier(id="sup-other")},
        {
            "invoice": invoice(counterparty_id="sup-new"),
            "supplier": supplier(id="sup-new"),
        },
    ],
)
def test_a_supplier_outside_the_mandate_is_refused_and_flagged(changes):
    decision = decide(**changes)

    assert code(decision) == "NEW_SUPPLIER"
    assert decision.flag_for_review is True


@pytest.mark.parametrize(
    "changes",
    [
        {"supplier": supplier(account_verified=False)},
        {"invoice": invoice(stated_account="SIM-9999-000111")},
        {"invoice": invoice(stated_account=ACCOUNT + "0")},
        {"invoice": invoice(stated_account="")},
    ],
)
def test_an_unverified_or_different_account_is_refused_and_flagged(changes):
    decision = decide(**changes)

    assert code(decision) == "SUPPLIER_ACCOUNT_MISMATCH"
    assert decision.flag_for_review is True


@pytest.mark.parametrize(
    "other",
    [
        invoice(id="inv-2", number="A/inv-1"),
        invoice(id="inv-2", number="a inv 1"),
        invoice(id="inv-2", number="A/inv-1", status="paid", amount=999),
        invoice(id="inv-2", number="A/other"),
    ],
)
def test_a_duplicate_invoice_is_refused_and_flagged(other):
    decision = decide(supplier_invoices=(other,))

    assert code(decision) == "DUPLICATE_INVOICE"
    assert decision.flag_for_review is True


@pytest.mark.parametrize(
    "other",
    [
        invoice(id="inv-2", number="A/inv-2", amount=600_000),
        invoice(id="inv-2", number="A/inv-2", issue_date=dt.date(2026, 9, 18)),
        invoice(id="inv-2", number="A/inv-1", status="void"),
        invoice(id="inv-2", number="A/inv-1", counterparty_id="sup-b"),
        invoice(id="inv-2", number="A/inv-1", kind="receivable"),
        invoice(id="inv-1"),
    ],
)
def test_similar_but_different_invoices_are_not_duplicates(other):
    assert find_duplicate(invoice(), (other,)) is None
    assert isinstance(decide(supplier_invoices=(other,)), Allow)


# --- Rules 7 to 10: limits, balance, rate ----------------------------------------------------


def test_over_the_per_payment_limit_is_refused():
    signed = mandate(
        limits=Limits(per_payment=idr(1_500_000), per_week=idr(15_000_000)),
        role_authority={"owner": RoleAuthority(can_propose=True, can_confirm=True)},
    )

    assert code(decide(OWNER, signed=signed, invoice=invoice(amount=1_500_001))) == (
        "OVER_PAYMENT_LIMIT"
    )


def test_splitting_cannot_get_past_the_weekly_limit():
    assert code(decide(paid_last_7_days=Decimal(14_500_001))) == "OVER_WEEK_LIMIT"
    assert code(decide(paid_last_7_days=Decimal(15_000_000))) == "OVER_WEEK_LIMIT"


def test_a_payment_the_balance_cannot_cover_is_refused():
    assert code(decide(balance=idr(499_999))) == "BELOW_CASH_BUFFER"


def test_too_many_proposals_are_rate_limited():
    assert code(decide(proposals_last_hour=10)) == "RATE_LIMITED"
    assert code(decide(proposals_last_hour=500)) == "RATE_LIMITED"


# --- Order: the first failure wins -----------------------------------------------------------

EVERYTHING_WRONG = {
    "invoice": invoice(amount=9_000_000, counterparty_id="sup-new", stated_account="SIM-0"),
    "supplier": supplier(id="sup-new", account_verified=False),
    "supplier_invoices": (invoice(id="inv-2", number="A/inv-1", counterparty_id="sup-new"),),
    "balance": idr(1),
    "paid_last_7_days": Decimal(99_000_000),
    "proposals_last_hour": 99,
}


def test_rules_are_checked_in_order():
    expired = mandate().expires_at
    owner_only = mandate(
        role_authority={"owner": RoleAuthority(can_propose=True, can_confirm=True)},
        allowed_suppliers=["sup-a", "sup-new"],
    )

    def with_invoice(**fixes):
        bad = EVERYTHING_WRONG["invoice"]
        return {**EVERYTHING_WRONG, "invoice": bad.model_copy(update=fixes)}

    assert code(decide(STAFF, now=expired, **EVERYTHING_WRONG)) == "MANDATE_EXPIRED"
    assert code(decide(STAFF, **EVERYTHING_WRONG)) == "ROLE_NOT_ALLOWED"
    assert code(decide(OWNER, **{**EVERYTHING_WRONG, "invoice": None})) == "INVOICE_INVALID"
    assert code(decide(BOOKKEEPER, **EVERYTHING_WRONG)) == "ROLE_NOT_ALLOWED"
    assert code(decide(OWNER, **EVERYTHING_WRONG)) == "NEW_SUPPLIER"
    assert code(decide(OWNER, signed=owner_only, **EVERYTHING_WRONG)) == (
        "SUPPLIER_ACCOUNT_MISMATCH"
    )

    verified = {"supplier": supplier(id="sup-new")}
    clean_account = with_invoice(stated_account=None)
    assert code(decide(OWNER, signed=owner_only, **{**clean_account, **verified})) == (
        "DUPLICATE_INVOICE"
    )
    no_duplicate = {**clean_account, **verified, "supplier_invoices": ()}
    assert code(decide(OWNER, signed=owner_only, **no_duplicate)) == "OVER_PAYMENT_LIMIT"

    affordable = {**no_duplicate, "invoice": no_duplicate["invoice"].model_copy(
        update={"amount": Decimal(500_000)})}  # fmt: skip
    assert code(decide(OWNER, signed=owner_only, **affordable)) == "OVER_WEEK_LIMIT"
    within_week = {**affordable, "paid_last_7_days": Decimal(0)}
    assert code(decide(OWNER, signed=owner_only, **within_week)) == "BELOW_CASH_BUFFER"
    funded = {**within_week, "balance": idr(10_000_000)}
    assert code(decide(OWNER, signed=owner_only, **funded)) == "RATE_LIMITED"
    calm = {**funded, "proposals_last_hour": 0}
    assert isinstance(decide(OWNER, signed=owner_only, **calm), Allow)


# --- No single violation can ever produce Allow ----------------------------------------------

VIOLATIONS = {
    "no mandate": {"signed": "none"},
    "expired mandate": {"now": NOW + dt.timedelta(days=31)},
    "staff": {"principal": STAFF},
    "missing invoice": {"invoice": None},
    "paid invoice": {"invoice": invoice(status="paid")},
    "paid per guard ledger": {"already_paid": True},
    "unknown supplier": {"supplier": None},
    "unverified account": {"supplier": supplier(account_verified=False)},
    "changed account": {"invoice": invoice(stated_account="SIM-9999-000111")},
    "duplicate": {"supplier_invoices": (invoice(id="inv-2", number="A/inv-1"),)},
    "over payment limit": {"invoice": invoice(amount=5_000_001)},
    "over week limit": {"paid_last_7_days": Decimal(15_000_000)},
    "no funds": {"balance": idr(1)},
    "below buffer": {"balance": idr(3_000_000)},
    "anomaly": {"invoice": invoice(amount=900_000)},
    "rate limited": {"proposals_last_hour": 10},
    "suspicious": {"suspicious": True},
    "above threshold": {
        "invoice": invoice(amount=1_000_001),
        "supplier": supplier(avg_invoice_amount=1_000_001),
    },
}


@pytest.mark.parametrize("name", VIOLATIONS)
def test_no_single_violation_is_allowed(name):
    changes = dict(VIOLATIONS[name])
    principal = changes.pop("principal", BOOKKEEPER)
    now = changes.pop("now", NOW)
    signed = None if changes.pop("signed", None) == "none" else mandate()

    decision = evaluate(proposal(principal), signed, principal, view(**changes), now)

    assert not isinstance(decision, Allow), name


# --- Failing closed --------------------------------------------------------------------------


class Exploding:
    """Fails on any ordinary attribute, like a broken data source would."""

    def __getattr__(self, name):
        if name.startswith("__"):
            raise AttributeError(name)
        raise RuntimeError(f"boom: {name}")


@pytest.mark.parametrize(
    "bad_view",
    [None, Exploding(), "not a view", view(balance=None), view(supplier="nonsense")],
)
def test_any_error_inside_the_policy_is_a_denial(bad_view):
    decision = evaluate(proposal(), mandate(), BOOKKEEPER, bad_view, NOW)

    assert code(decision) == "INTERNAL_ERROR"


def test_garbage_arguments_are_a_denial_not_a_crash():
    assert isinstance(evaluate(None, mandate(), BOOKKEEPER, view(), NOW), Deny)
    assert isinstance(evaluate(proposal(), "mandate", BOOKKEEPER, view(), NOW), Deny)
    assert isinstance(evaluate(proposal(), mandate(), None, view(), NOW), Deny)
    assert isinstance(evaluate(proposal(), mandate(), BOOKKEEPER, view(), None), Deny)
    assert isinstance(check_authority(None, mandate(), None, PUBLIC_KEY, BUSINESS, NOW), Deny)


def test_check_authority_matches_the_first_rules_of_evaluate():
    assert check_authority(proposal(), mandate(), BOOKKEEPER, PUBLIC_KEY, BUSINESS, NOW) is None
    assert check_authority(proposal(STAFF), mandate(), STAFF, PUBLIC_KEY, BUSINESS, NOW) is not None
    assert code(check_authority(proposal(), None, BOOKKEEPER, PUBLIC_KEY, BUSINESS, NOW)) == (
        "MANDATE_INVALID"
    )


def test_every_denial_tells_the_user_something_short():
    for name, changes in VIOLATIONS.items():
        changes = dict(changes)
        principal = changes.pop("principal", BOOKKEEPER)
        now = changes.pop("now", NOW)
        signed = None if changes.pop("signed", None) == "none" else mandate()
        decision = evaluate(proposal(principal), signed, principal, view(**changes), now)
        if isinstance(decision, Deny):
            assert 20 < len(decision.user_message) < 300, name


# --- Terms digest ----------------------------------------------------------------------------


def terms(**changes) -> PaymentTerms:
    fields = {
        "business_id": BUSINESS,
        "mandate_id": "m-001",
        "invoice_id": "inv-1",
        "supplier_id": "sup-a",
        "amount": Decimal("500000"),
        "currency": "IDR",
        "destination_account": ACCOUNT,
        "proposed_by": "u-book",
    }
    fields.update(changes)
    return PaymentTerms(**fields)


def test_digest_ignores_how_the_amount_is_written():
    assert terms().digest() == terms(amount=Decimal("500000.00")).digest()
    assert terms().digest() == terms(amount=Decimal("5E+5")).digest()


@pytest.mark.parametrize(
    "change",
    [
        {"amount": Decimal("500001")},
        {"destination_account": "SIM-9999-000111"},
        {"invoice_id": "inv-2"},
        {"supplier_id": "sup-b"},
        {"mandate_id": "m-002"},
        {"proposed_by": "u-owner"},
        {"business_id": "biz-2"},
        {"currency": "USD"},
    ],
)
def test_digest_changes_with_every_field(change):
    assert terms(**change).digest() != terms().digest()
