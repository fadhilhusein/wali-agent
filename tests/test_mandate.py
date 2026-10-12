import copy
import datetime as dt
import json
from decimal import Decimal

import pytest
from pydantic import ValidationError

from conftest import activate_mandate, mandate_request
from wali.guard.keys import generate_keypair, load_private_key, load_public_key
from wali.guard.mandate import Mandate, MandateTerms, mandate_problem, sign_mandate
from wali.models import Principal

NOW = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.timezone(dt.timedelta(hours=7)))

# The example from the build specification, without its signature.
SPEC_EXAMPLE = {
    "mandate_id": "m-001",
    "business_id": "biz-toko-sari",
    "issued_by": "user-owner",
    "expires_at": "2026-10-19T23:59:59+08:00",
    "allowed_actions": ["pay_invoice", "record_book_entry"],
    "limits": {
        "per_payment": {"amount": "5000000", "currency": "IDR"},
        "per_week": {"amount": "15000000", "currency": "IDR"},
    },
    "allowed_suppliers": ["sup-kopi", "sup-listrik", "sup-kemasan"],
    "role_authority": {
        "owner": {"can_propose": True, "can_confirm": True},
        "bookkeeper": {"can_propose": True, "can_confirm": False, "max_propose": "5000000"},
        "staff": {"can_propose": False, "can_confirm": False},
    },
    "confirm_above": {"amount": "1000000", "currency": "IDR"},
    "min_cash_buffer": {"amount": "3000000", "currency": "IDR"},
    "escalate_if": [
        "supplier_account_mismatch",
        "duplicate_invoice",
        "amount_over_30_percent_of_supplier_average",
        "new_supplier",
    ],
}


def example(**changes) -> dict:
    data = copy.deepcopy(SPEC_EXAMPLE)
    for path, value in changes.items():
        target = data
        *parents, last = path.split("__")
        for key in parents:
            target = target[key]
        target[last] = value
    return data


@pytest.fixture(scope="module")
def keys():
    private_b64, public_b64 = generate_keypair()
    return load_private_key(private_b64), load_public_key(public_b64)


@pytest.fixture
def signed(keys) -> Mandate:
    return sign_mandate(MandateTerms.model_validate(SPEC_EXAMPLE), keys[0])


# --- Schema ----------------------------------------------------------------------------------


def test_the_specification_example_is_a_valid_mandate():
    terms = MandateTerms.model_validate(SPEC_EXAMPLE)

    assert terms.limits.per_payment.amount == Decimal("5000000")
    assert terms.role_authority["bookkeeper"].max_propose == Decimal("5000000")
    assert terms.currency == "IDR"
    assert terms.expires_at.utcoffset() == dt.timedelta(hours=8)


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"limits__per_payment__amount": "-1"}, "greater than zero"),
        ({"limits__per_payment__amount": "0"}, "greater than zero"),
        ({"limits__per_week__amount": "0"}, "greater than zero"),
        ({"limits__per_payment__amount": "20000000"}, "cannot exceed the weekly limit"),
        ({"confirm_above__amount": "-5"}, "cannot be negative"),
        ({"min_cash_buffer__amount": "-5"}, "cannot be negative"),
        ({"confirm_above__currency": "USD"}, "one currency"),
        ({"allowed_actions": ["pay_invoice", "change_limits"]}, "allowed_actions"),
        ({"allowed_actions": ["pay_invoice", "pay_invoice"]}, "duplicates"),
        ({"allowed_suppliers": ["sup-kopi", "sup-kopi"]}, "duplicates"),
        ({"allowed_suppliers": [""]}, "allowed_suppliers"),
        ({"escalate_if": ["something_else"]}, "escalate_if"),
        ({"role_authority__admin": {"can_propose": True}}, "role_authority"),
        ({"role_authority__bookkeeper__can_confirm": True}, "only the owner can confirm"),
        ({"role_authority__staff__can_confirm": True}, "only the owner can confirm"),
        ({"role_authority__staff__can_propose": True}, "staff cannot propose"),
        ({"role_authority__owner__can_confirm": False}, "owner must be able"),
        ({"role_authority__bookkeeper__max_propose": "6000000"}, "cannot exceed the per-payment"),
        ({"role_authority__bookkeeper__max_propose": "0"}, "max_propose"),
        ({"expires_at": "2026-10-19T23:59:59"}, "expires_at"),
        ({"expires_at": "soon"}, "expires_at"),
        ({"mandate_id": ""}, "mandate_id"),
        ({"surprise": 1}, "surprise"),
    ],
)
def test_nonsense_terms_are_rejected(change, message):
    with pytest.raises(ValidationError, match=message):
        MandateTerms.model_validate(example(**change))


def test_a_mandate_without_an_owner_is_rejected():
    data = example()
    del data["role_authority"]["owner"]

    with pytest.raises(ValidationError, match="owner must be able"):
        MandateTerms.model_validate(data)


# --- Signing ---------------------------------------------------------------------------------


def test_a_signed_mandate_verifies(keys, signed):
    assert signed.signature.startswith("ed25519:")
    assert mandate_problem(signed, keys[1], "biz-toko-sari", NOW) is None


def test_signature_survives_storage_as_json_in_any_key_order(keys, signed):
    stored = json.loads(signed.model_dump_json())
    shuffled = dict(reversed(list(stored.items())))

    restored = Mandate.model_validate_json(json.dumps(shuffled))

    assert restored == signed
    assert restored.digest() == signed.digest()
    assert mandate_problem(restored, keys[1], "biz-toko-sari", NOW) is None


@pytest.mark.parametrize(
    "change",
    [
        {"limits__per_payment__amount": "5000001"},
        {"limits__per_week__amount": "150000000"},
        {"confirm_above__amount": "4000000"},
        {"min_cash_buffer__amount": "0"},
        {"allowed_suppliers": ["sup-kopi", "sup-listrik", "sup-kemasan", "sup-mesin"]},
        {"role_authority__bookkeeper__max_propose": "4999999"},
        {"role_authority__bookkeeper__can_propose": False},
        {"expires_at": "2027-10-19T23:59:59+08:00"},
        {"issued_by": "user-bookkeeper"},
        {"mandate_id": "m-002"},
        {"allowed_actions": ["pay_invoice"]},
    ],
)
def test_any_change_after_signing_is_detected(keys, signed, change):
    tampered = Mandate.model_validate({**example(**change), "signature": signed.signature})

    assert mandate_problem(tampered, keys[1], "biz-toko-sari", NOW) == "MANDATE_INVALID"


def test_missing_forged_or_misdirected_mandates_are_invalid(keys, signed):
    other_private = load_private_key(generate_keypair()[0])
    forged = sign_mandate(MandateTerms.model_validate(SPEC_EXAMPLE), other_private)
    unsigned = signed.model_copy(update={"signature": ""})

    assert mandate_problem(None, keys[1], "biz-toko-sari", NOW) == "MANDATE_INVALID"
    assert mandate_problem(forged, keys[1], "biz-toko-sari", NOW) == "MANDATE_INVALID"
    assert mandate_problem(unsigned, keys[1], "biz-toko-sari", NOW) == "MANDATE_INVALID"
    assert mandate_problem(signed, keys[1], "biz-other", NOW) == "MANDATE_INVALID"
    assert mandate_problem(SPEC_EXAMPLE, keys[1], "biz-toko-sari", NOW) == "MANDATE_INVALID"


def test_expiry_is_checked_to_the_second(keys, signed):
    just_before = signed.expires_at - dt.timedelta(seconds=1)

    assert mandate_problem(signed, keys[1], "biz-toko-sari", just_before) is None
    assert mandate_problem(signed, keys[1], "biz-toko-sari", signed.expires_at) == (
        "MANDATE_EXPIRED"
    )


def test_a_tampered_expired_mandate_is_invalid_not_merely_expired(keys, signed):
    tampered = signed.model_copy(update={"issued_by": "someone"})
    later = signed.expires_at + dt.timedelta(days=1)

    assert mandate_problem(tampered, keys[1], "biz-toko-sari", later) == "MANDATE_INVALID"


# --- Lifecycle through the guard service -----------------------------------------------------


def test_a_draft_is_not_active_until_the_owner_confirms(world, owner):
    drafted = world.guard.draft_mandate(owner, mandate_request())

    assert drafted.status == "needs_confirmation"
    assert drafted.required_role == "owner"
    assert drafted.raises_authority is True
    assert any("Per-payment limit: 5,000,000 IDR" in line for line in drafted.changes)
    assert world.guard.active_mandate() is None

    (request,) = world.guard.collect_confirmation_requests()
    assert (request.kind, request.required_role) == ("mandate", "owner")
    assert request.changes == drafted.changes

    activated = world.guard.confirm_mandate(owner, request.token)

    assert activated.status == "active"
    mandate = world.guard.active_mandate()
    assert mandate.mandate_id == drafted.mandate_id
    assert mandate.issued_by == owner.user_id
    assert mandate.limits.per_payment.amount == Decimal("5000000")
    assert mandate.role_authority["bookkeeper"].can_confirm is False
    assert mandate.role_authority["staff"].can_propose is False
    assert mandate.expires_at == world.clock.now + dt.timedelta(days=30)


def test_the_draft_decision_holds_no_token(world, owner):
    drafted = world.guard.draft_mandate(owner, mandate_request())
    (request,) = world.guard.collect_confirmation_requests()

    assert request.token not in drafted.model_dump_json()
    assert request.token not in repr(request)
    assert world.guard.collect_confirmation_requests() == []


@pytest.mark.parametrize("role", ["bookkeeper", "staff"])
def test_only_the_owner_can_draft(world, principals, role):
    decision = world.guard.draft_mandate(principals[role], mandate_request())

    assert (decision.status, decision.reason_code) == ("denied", "ROLE_NOT_ALLOWED")
    assert world.guard.collect_confirmation_requests() == []


def test_a_claimed_owner_role_cannot_draft(world, staff):
    pretender = Principal(user_id=staff.user_id, role="owner", business_id=staff.business_id)

    decision = world.guard.draft_mandate(pretender, mandate_request())

    assert (decision.status, decision.reason_code) == ("denied", "ROLE_NOT_ALLOWED")
    assert world.guard.collect_confirmation_requests() == []


@pytest.mark.parametrize("role", ["bookkeeper", "staff"])
def test_only_the_owner_can_confirm_and_a_failed_attempt_keeps_the_token(
    world, owner, principals, role
):
    world.guard.draft_mandate(owner, mandate_request())
    (request,) = world.guard.collect_confirmation_requests()

    refused = world.guard.confirm_mandate(principals[role], request.token)

    assert (refused.status, refused.reason_code) == ("denied", "ROLE_NOT_ALLOWED")
    assert world.guard.active_mandate() is None
    assert world.guard.confirm_mandate(owner, request.token).status == "active"


def test_a_claimed_owner_role_cannot_confirm(world, owner, staff):
    world.guard.draft_mandate(owner, mandate_request())
    (request,) = world.guard.collect_confirmation_requests()
    pretender = Principal(user_id=staff.user_id, role="owner", business_id=staff.business_id)

    refused = world.guard.confirm_mandate(pretender, request.token)

    assert (refused.status, refused.reason_code) == ("denied", "ROLE_NOT_ALLOWED")
    assert world.guard.active_mandate() is None


def test_mandate_token_is_single_use_and_expires(world, owner):
    world.guard.draft_mandate(owner, mandate_request())
    (first,) = world.guard.collect_confirmation_requests()
    assert world.guard.confirm_mandate(owner, first.token).status == "active"
    assert world.guard.confirm_mandate(owner, first.token).reason_code == "CONFIRMATION_INVALID"

    world.guard.draft_mandate(owner, mandate_request(per_payment="6000000"))
    (second,) = world.guard.collect_confirmation_requests()
    world.clock.advance(minutes=5)

    expired = world.guard.confirm_mandate(owner, second.token)
    assert expired.reason_code == "CONFIRMATION_EXPIRED"
    assert world.guard.active_mandate().limits.per_payment.amount == Decimal("5000000")


def test_raising_a_limit_changes_nothing_until_freshly_confirmed(world, owner):
    activate_mandate(world.guard, owner)

    drafted = world.guard.draft_mandate(
        owner, mandate_request(per_payment="50000000", per_week="90000000")
    )

    assert drafted.status == "needs_confirmation"
    assert drafted.raises_authority is True
    assert "Per-payment limit: 5,000,000 IDR -> 50,000,000 IDR (raised)" in drafted.changes
    assert world.guard.active_mandate().limits.per_payment.amount == Decimal("5000000")

    (request,) = world.guard.collect_confirmation_requests()
    world.guard.confirm_mandate(owner, request.token)
    assert world.guard.active_mandate().limits.per_payment.amount == Decimal("50000000")


def test_tightening_the_terms_is_not_reported_as_more_authority(world, owner):
    activate_mandate(world.guard, owner)

    drafted = world.guard.draft_mandate(
        owner,
        mandate_request(
            per_payment="2000000",
            confirm_above="500000",
            min_cash_buffer="4000000",
            bookkeeper_max_propose="1000000",
        ),
    )

    assert drafted.raises_authority is False
    assert "Per-payment limit: 5,000,000 IDR -> 2,000,000 IDR (lowered)" in drafted.changes
    assert "Cash buffer to keep: 3,000,000 IDR -> 4,000,000 IDR (raised)" in drafted.changes


@pytest.mark.parametrize(
    "change",
    [
        {"confirm_above": "4000000"},
        {"min_cash_buffer": "0"},
        {"per_week": "30000000"},
        {"bookkeeper_can_propose": True, "bookkeeper_max_propose": None, "per_payment": "5000000"},
    ],
)
def test_loosening_any_term_is_reported_as_more_authority(world, owner, change):
    activate_mandate(world.guard, owner, mandate_request(bookkeeper_max_propose="1000000"))

    drafted = world.guard.draft_mandate(
        owner, mandate_request(**{"bookkeeper_max_propose": "1000000", **change})
    )

    assert drafted.raises_authority is True


def test_adding_a_supplier_is_reported_as_more_authority(world, owner):
    suppliers = mandate_request().allowed_suppliers
    activate_mandate(world.guard, owner, mandate_request(allowed_suppliers=suppliers[:-1]))

    drafted = world.guard.draft_mandate(owner, mandate_request(allowed_suppliers=suppliers))

    assert drafted.raises_authority is True
    assert f"Suppliers added: {suppliers[-1]}" in drafted.changes


def test_a_newer_draft_replaces_an_older_one(world, owner):
    small = {"bookkeeper_max_propose": "1000000"}
    world.guard.draft_mandate(owner, mandate_request(per_payment="1000000", **small))
    (old,) = world.guard.collect_confirmation_requests()
    world.guard.draft_mandate(owner, mandate_request(per_payment="2000000", **small))
    (new,) = world.guard.collect_confirmation_requests()

    assert world.guard.confirm_mandate(owner, old.token).reason_code == "CONFIRMATION_INVALID"
    assert world.guard.confirm_mandate(owner, new.token).status == "active"
    assert world.guard.active_mandate().limits.per_payment.amount == Decimal("2000000")


def test_invalid_terms_are_refused_with_a_plain_reason(world, owner):
    decision = world.guard.draft_mandate(
        owner, mandate_request(per_payment="20000000", per_week="15000000")
    )

    assert (decision.status, decision.reason_code) == ("denied", "MANDATE_INVALID")
    assert "cannot exceed the weekly limit" in decision.user_message
    assert world.guard.collect_confirmation_requests() == []


def test_unknown_and_unverified_suppliers_cannot_be_added(world, owner, ground_truth):
    unverified = ground_truth["invoices"]["unverified_supplier"][0]["supplier_id"]

    unknown = world.guard.draft_mandate(owner, mandate_request(allowed_suppliers=["sup-nope"]))
    risky = world.guard.draft_mandate(owner, mandate_request(allowed_suppliers=[unverified]))

    assert (unknown.status, unknown.reason_code) == ("denied", "MANDATE_INVALID")
    assert (risky.status, risky.reason_code) == ("denied", "SUPPLIER_ACCOUNT_MISMATCH")
    assert "not verified" in risky.user_message
    assert world.guard.collect_confirmation_requests() == []


def test_the_active_mandate_survives_a_restart_of_the_guard(world, owner):
    activate_mandate(world.guard, owner)

    restarted = world.make_guard()

    assert restarted.active_mandate() == world.guard.active_mandate()
    assert restarted.active_mandate() is not None


def test_a_mandate_changed_in_storage_stops_being_valid(world, owner):
    activate_mandate(world.guard, owner)
    payload = world.store.active_mandate_payload()
    world.store._conn.execute(
        "UPDATE mandates SET payload = ?", (payload.replace('"5000000"', '"50000000"'),)
    )

    assert world.guard.active_mandate() is None


def test_an_expired_mandate_is_no_longer_active(world, owner):
    activate_mandate(world.guard, owner)

    world.clock.advance(days=30)

    assert world.guard.active_mandate() is None


def test_an_unreachable_environment_refuses_a_draft_and_keeps_a_confirmation(world, owner):
    world.env.inject_failure("get_balance", times=2)
    assert world.guard.draft_mandate(owner, mandate_request()).reason_code == "INTERNAL_ERROR"

    world.guard.draft_mandate(owner, mandate_request())
    (request,) = world.guard.collect_confirmation_requests()
    world.env.inject_failure("get_balance", times=2)

    assert world.guard.confirm_mandate(owner, request.token).reason_code == "INTERNAL_ERROR"
    assert world.guard.confirm_mandate(owner, request.token).status == "active"
