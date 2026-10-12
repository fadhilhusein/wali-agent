import datetime as dt

import pytest

from wali.guard.confirm import ConfirmationError, ConfirmationStore
from wali.models import Principal

T0 = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)
OWNER = Principal(user_id="user-owner", role="owner", business_id="biz")
BOOKKEEPER = Principal(user_id="user-bookkeeper", role="bookkeeper", business_id="biz")
STAFF = Principal(user_id="user-staff", role="staff", business_id="biz")
OTHER_OWNER = Principal(user_id="user-x", role="owner", business_id="biz-other")


@pytest.fixture
def store() -> ConfirmationStore:
    return ConfirmationStore(dt.timedelta(minutes=5))


def issue(store, subject_id="p-1", kind="payment", now=T0, subject_hash="hash-1"):
    token, _ = store.issue(
        kind=kind,
        subject_id=subject_id,
        subject_hash=subject_hash,
        required_role="owner",
        business_id="biz",
        now=now,
    )
    return token


def code_of(store, token, principal=OWNER, kind="payment", now=T0) -> str:
    with pytest.raises(ConfirmationError) as excinfo:
        store.redeem(token, principal, kind, now)
    return excinfo.value.code


def test_the_owner_redeems_a_token_once(store):
    token = issue(store)

    item = store.redeem(token, OWNER, "payment", T0 + dt.timedelta(minutes=1))

    assert (item.subject_id, item.subject_hash, item.required_role) == ("p-1", "hash-1", "owner")
    assert code_of(store, token) == "CONFIRMATION_INVALID"


def test_tokens_are_long_random_and_different_each_time(store):
    first, second = issue(store, "p-1"), issue(store, "p-2")

    assert first != second
    assert len(first) >= 40


def test_token_expires_after_five_minutes(store):
    token = issue(store)
    _, expires_at = store.issue(
        kind="payment",
        subject_id="p-2",
        subject_hash="h",
        required_role="owner",
        business_id="biz",
        now=T0,
    )

    assert expires_at == T0 + dt.timedelta(minutes=5)
    assert code_of(store, token, now=T0 + dt.timedelta(minutes=5)) == "CONFIRMATION_EXPIRED"
    assert code_of(store, token, now=T0) == "CONFIRMATION_INVALID"


def test_just_before_expiry_still_works(store):
    token = issue(store)

    assert store.redeem(token, OWNER, "payment", T0 + dt.timedelta(minutes=4, seconds=59))


@pytest.mark.parametrize("principal", [BOOKKEEPER, STAFF, OTHER_OWNER])
def test_wrong_role_or_business_is_refused_without_using_up_the_token(store, principal):
    token = issue(store)

    assert code_of(store, token, principal) == "ROLE_NOT_ALLOWED"
    assert store.redeem(token, OWNER, "payment", T0).subject_id == "p-1"


@pytest.mark.parametrize("token", ["", "guess", None, 123, b"bytes", "a" * 43])
def test_unknown_or_malformed_tokens_are_invalid(store, token):
    issue(store)

    assert code_of(store, token) == "CONFIRMATION_INVALID"


def test_a_payment_token_cannot_confirm_a_mandate(store):
    token = issue(store, kind="payment")

    assert code_of(store, token, kind="mandate") == "CONFIRMATION_INVALID"
    assert store.redeem(token, OWNER, "payment", T0)


def test_voiding_a_subject_kills_its_token(store):
    token = issue(store, "p-1")
    other = issue(store, "p-2")

    assert store.void_subject("p-1") is True
    assert store.void_subject("p-1") is False
    assert code_of(store, token) == "CONFIRMATION_INVALID"
    assert store.redeem(other, OWNER, "payment", T0).subject_id == "p-2"


def test_a_new_token_for_the_same_subject_replaces_the_old_one(store):
    old = issue(store, "p-1", subject_hash="old")
    new = issue(store, "p-1", subject_hash="new")

    assert code_of(store, old) == "CONFIRMATION_INVALID"
    assert store.redeem(new, OWNER, "payment", T0).subject_hash == "new"


def test_has_pending_reflects_expiry_and_use(store):
    token = issue(store)

    assert store.has_pending("p-1", T0)
    assert not store.has_pending("p-1", T0 + dt.timedelta(minutes=5))
    store.redeem(token, OWNER, "payment", T0)
    assert not store.has_pending("p-1", T0)


def test_ttl_must_be_positive():
    with pytest.raises(ValueError):
        ConfirmationStore(dt.timedelta(0))


def test_errors_carry_a_plain_message(store):
    with pytest.raises(ConfirmationError) as excinfo:
        store.redeem("nope", OWNER, "payment", T0)

    assert "Nothing was changed" in excinfo.value.user_message
