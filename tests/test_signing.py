import datetime as dt
from decimal import Decimal

import pytest

from wali.guard.keys import generate_keypair, load_private_key, load_public_key
from wali.guard.signing import SIGNATURE_PREFIX, canonical_json, sign_payload, verify_payload
from wali.models import GuardApproval


@pytest.fixture(scope="module")
def keys():
    private_b64, public_b64 = generate_keypair()
    return load_private_key(private_b64), load_public_key(public_b64)


def test_canonical_json_is_sorted_compact_and_order_independent():
    first = canonical_json({"b": 1, "a": {"y": [1, "x", None, True], "x": "é"}})
    second = canonical_json({"a": {"x": "é", "y": [1, "x", None, True]}, "b": 1})

    assert first == second
    assert first == '{"a":{"x":"é","y":[1,"x",null,true]},"b":1}'.encode()


@pytest.mark.parametrize(
    "payload",
    [
        {"amount": 1.5},
        {"amount": Decimal("1.5")},
        {"when": dt.date(2026, 1, 1)},
        {1: "x"},
        {"s": {1}},
    ],
)
def test_canonical_json_rejects_values_that_are_not_stable(payload):
    with pytest.raises(TypeError):
        canonical_json(payload)


def test_sign_and_verify_round_trip(keys):
    private, public = keys
    payload = {"amount": "5000000", "currency": "IDR"}
    signature = sign_payload(private, payload)

    assert signature.startswith(SIGNATURE_PREFIX)
    assert verify_payload(public, payload, signature)
    assert verify_payload(public, {"currency": "IDR", "amount": "5000000"}, signature)


def test_any_change_to_the_payload_breaks_the_signature(keys):
    private, public = keys
    signature = sign_payload(private, {"amount": "5000000", "currency": "IDR"})

    assert not verify_payload(public, {"amount": "5000001", "currency": "IDR"}, signature)
    assert not verify_payload(public, {"amount": "5000000", "currency": "IDR", "x": 1}, signature)


def test_a_signature_from_another_key_is_rejected(keys):
    _, public = keys
    other_private = load_private_key(generate_keypair()[0])
    payload = {"amount": "1"}

    assert not verify_payload(public, payload, sign_payload(other_private, payload))


@pytest.mark.parametrize(
    "signature",
    ["", "ed25519:", "ed25519:not-base64!!", "ed25519:AAAA", "rsa:AAAA", None, 123, b"ed25519:AA"],
)
def test_malformed_signatures_are_rejected_without_raising(keys, signature):
    _, public = keys

    assert verify_payload(public, {"amount": "1"}, signature) is False


def test_verify_returns_false_for_a_payload_that_cannot_be_canonicalised(keys):
    private, public = keys
    signature = sign_payload(private, {"amount": "1"})

    assert verify_payload(public, {"amount": 1.0}, signature) is False


def test_approval_signing_payload_covers_every_field_but_the_signature():
    approval = GuardApproval(
        approval_id="ap-1",
        proposal_hash="hash",
        business_id="biz",
        invoice_id="inv",
        supplier_id="sup",
        amount=Decimal("1500000"),
        currency="IDR",
        destination_account="SIM-1",
        expires_at=dt.datetime(2026, 10, 1, 9, 5, tzinfo=dt.UTC),
        signature="ed25519:abc",
    )
    payload = approval.signing_payload()

    assert set(payload) == set(GuardApproval.model_fields) - {"signature"}
    assert payload["amount"] == "1500000"
    canonical_json(payload)  # must be canonicalisable as is
