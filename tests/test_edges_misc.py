"""Small edge cases that sit between modules: paying exactly the balance, approval and clock
boundaries in the simulated bank, and the audit chain's refusal to hash odd content."""

import datetime as dt
import json
from decimal import Decimal

import pytest

from conftest import flagged_invoice_ids
from wali.config import ConfigError, load_settings
from wali.guard.audit import AuditLog, verify_chain
from wali.guard.store import GuardStore


def a_clean_payable(env, owner, ground_truth):
    flagged = flagged_invoice_ids(ground_truth)
    return next(
        i
        for i in env.list_invoices(owner, "payable", status="open")
        if i.id not in flagged and i.amount < env.get_balance(owner).amount
    )


@pytest.fixture
def at_balance(make_env, edit_seed, env, owner, ground_truth):
    """Build an environment where one clean invoice is worth the balance plus ``extra``."""
    target = a_clean_payable(env, owner, ground_truth)
    balance = env.get_balance(owner).amount

    def build(extra: int):
        def change(row):
            if row["id"] == target.id:
                row["amount"] = str(balance + extra)

        return make_env(seed_dir=edit_seed("invoices", change)), target.id

    return build


def pay(env, owner, invoice_id, make_approval):
    invoice = next(i for i in env.list_invoices(owner, "payable") if i.id == invoice_id)
    supplier = env.get_supplier(owner, invoice.counterparty_id)
    return env.execute_payment(make_approval(invoice, supplier))


def test_an_invoice_equal_to_the_whole_balance_can_be_paid_and_leaves_zero(
    at_balance, owner, make_approval
):
    env, invoice_id = at_balance(0)

    result = pay(env, owner, invoice_id, make_approval)

    assert result.status == "success"
    assert env.get_balance(owner).amount == Decimal(0)


def test_an_invoice_one_unit_over_the_balance_is_rejected_and_changes_nothing(
    at_balance, owner, make_approval
):
    env, invoice_id = at_balance(1)
    before = env.get_balance(owner).amount

    result = pay(env, owner, invoice_id, make_approval)

    assert result.status == "rejected"
    assert "balance is not sufficient" in result.message
    assert env.get_balance(owner).amount == before
    assert env.list_payments() == []


def test_an_approval_is_still_good_one_microsecond_before_it_expires(
    make_env, now, owner, ground_truth, make_approval
):
    env = make_env(clock=lambda: now)
    invoice = a_clean_payable(env, owner, ground_truth)
    supplier = env.get_supplier(owner, invoice.counterparty_id)
    approval = make_approval(invoice, supplier, expires_at=now + dt.timedelta(microseconds=1))

    assert env.execute_payment(approval).status == "success"


def test_a_bank_clock_without_a_timezone_is_an_error_not_a_payment(
    make_env, owner, ground_truth, make_approval
):
    env = make_env(clock=lambda: dt.datetime(2026, 10, 1, 9, 0))
    invoice = a_clean_payable(env, owner, ground_truth)
    supplier = env.get_supplier(owner, invoice.counterparty_id)

    with pytest.raises(ValueError, match="timezone-aware"):
        env.execute_payment(make_approval(invoice, supplier))
    assert env.list_payments() == []


def test_the_guard_store_refuses_a_timestamp_without_a_timezone():
    store = GuardStore()

    with pytest.raises(ValueError, match="timezone-aware"):
        store.record_execution(
            approval_id="a",
            invoice_id="i",
            supplier_id="s",
            amount=Decimal(1),
            currency="IDR",
            proposed_by="u",
            now=dt.datetime(2026, 10, 1, 9, 0),
        )


def test_a_log_entry_whose_content_cannot_be_hashed_is_reported_not_crashed(tmp_path):
    path = tmp_path / "audit.jsonl"
    AuditLog(path).append(
        ts=dt.datetime(2026, 10, 1, tzinfo=dt.UTC), event="e", principal=None, data={}
    )
    entry = json.loads(path.read_text(encoding="utf-8"))
    entry["data"] = {"n": 1.5}
    path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

    status = verify_chain(path)

    assert not status.ok
    assert status.bad_line == 1
    assert status.problem


# --- Settings boundaries ---------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "low", "high"),
    [
        ("WALI_AGENT_MAX_STEPS", "1", "50"),
        ("WALI_CONFIRM_TOKEN_TTL_SECONDS", "1", "3600"),
        ("WALI_HISTORY_MAX_TURNS", "4", "200"),
        ("WALI_UTC_OFFSET_HOURS", "-12", "14"),
        ("WALI_RECON_DATE_WINDOW_DAYS", "0", "31"),
        ("WALI_RECON_MISMATCH_MAX_RATIO", "0", "1"),
        ("SIM_FAIL_RATE", "0", "1"),
        ("WALI_PROPOSALS_PER_HOUR", "1", "1000000"),
    ],
)
def test_settings_accept_exactly_their_limits_and_refuse_one_step_beyond(name, low, high):
    for value in (low, high):
        load_settings(env={name: value}, env_file=None)

    step = {"1": "0", "4": "3", "-12": "-13", "0": "-1"}[low]
    beyond_high = {"50": "51", "3600": "3601", "200": "201", "14": "15", "31": "32", "1": "1.01"}
    refused = [step]
    if high in beyond_high:
        refused.append(beyond_high[high])
    for value in refused:
        with pytest.raises(ConfigError):
            load_settings(env={name: value}, env_file=None)


def test_a_dotenv_value_with_an_equals_sign_keeps_everything_after_the_first(tmp_path):
    path = tmp_path / ".env"
    path.write_text("WALI_LLM_BASE_URL=https://example.test/v1?a=b\n", encoding="utf-8")

    assert load_settings(env={}, env_file=path).llm_base_url == "https://example.test/v1?a=b"


def test_a_quoted_dotenv_value_loses_only_the_outer_quotes(tmp_path):
    path = tmp_path / ".env"
    path.write_text("WALI_AGENT_MODEL=\"model 'x'\"\n", encoding="utf-8")

    assert load_settings(env={}, env_file=path).agent_model == "model 'x'"
