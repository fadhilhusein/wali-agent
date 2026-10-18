"""The registry is the whole surface the model can touch, so its shape is pinned down here."""

import datetime as dt
import json
from decimal import Decimal

import pytest

from conftest import flagged_invoice_ids, mandate_request, truth_discrepancy_keys
from wali.tools import registry as registry_module
from wali.tools.registry import TOOL_NAMES, TOOL_SCHEMAS, ToolRegistry

EXPECTED_TOOLS = {
    "get_balance",
    "list_transactions",
    "list_invoices",
    "get_supplier",
    "reconcile_period",
    "forecast_cashflow",
    "record_book_entry",
    "flag_for_review",
    "propose_payment",
    "propose_mandate",
}
IDENTITY_WORDS = ("user", "role", "principal", "business", "owner", "identity", "session", "actor")
FORBIDDEN_TOOL_WORDS = (
    "confirm",
    "execute",
    "approve",
    "transfer",
    "limit",
    "role",
    "account",
    "token",
    "sign",
    "delete",
)
SEPTEMBER = {"start": "2026-09-01", "end": "2026-09-30"}


def data(outcome):
    assert not outcome.is_error, outcome.content
    body = json.loads(outcome.content)
    # Data is always inside the wrapper. The only thing allowed beside it is the registry's
    # own note that some text was withheld.
    assert set(body) <= {"untrusted_data", "screening"}
    return body["untrusted_data"]


def error(outcome) -> str:
    assert outcome.is_error, outcome.content
    body = json.loads(outcome.content)
    assert body["untrusted_data"] is None
    assert body["error"]["code"] == outcome.error_code
    assert body["error"]["message"]
    return outcome.error_code


def property_names(schema) -> list[str]:
    names = []
    if isinstance(schema, dict):
        for name, sub in schema.get("properties", {}).items():
            names.append(name)
            names += property_names(sub)
        for key in ("items", "anyOf"):
            sub = schema.get(key)
            for item in sub if isinstance(sub, list) else [sub]:
                names += property_names(item)
    return names


def objects(schema) -> list[dict]:
    found = []
    if isinstance(schema, dict):
        if schema.get("type") == "object":
            found.append(schema)
        for value in schema.values():
            for item in value if isinstance(value, list) else [value]:
                found += objects(item)
    return found


@pytest.fixture
def tools(ready, owner) -> ToolRegistry:
    return ready.make_registry(owner)


def small_invoice(world, owner, ground_truth):
    flagged = flagged_invoice_ids(ground_truth)
    return min(
        (
            i
            for i in world.env.list_invoices(owner, "payable", status="open")
            if i.id not in flagged and i.due_date >= world.env.as_of_date
        ),
        key=lambda i: i.amount,
    )


def large_invoice(world, owner, ground_truth):
    flagged = flagged_invoice_ids(ground_truth)
    return max(
        (
            i
            for i in world.env.list_invoices(owner, "payable", status="open")
            if i.id not in flagged and Decimal(1_000_000) < i.amount <= Decimal(4_000_000)
        ),
        key=lambda i: i.amount,
    )


# --- The shape of the registry ---------------------------------------------------------------


def test_the_registry_contains_exactly_the_ten_allowed_tools():
    assert set(TOOL_NAMES) == EXPECTED_TOOLS
    assert len(TOOL_NAMES) == len(TOOL_SCHEMAS) == 10
    assert ToolRegistry.schemas() is TOOL_SCHEMAS


def test_no_tool_takes_an_identity_argument():
    for tool in TOOL_SCHEMAS:
        for name in property_names(tool["input_schema"]):
            assert not any(word in name.lower() for word in IDENTITY_WORDS), (tool["name"], name)


def test_no_tool_confirms_executes_or_changes_authority():
    for name in TOOL_NAMES:
        assert not any(word in name for word in FORBIDDEN_TOOL_WORDS), name


def test_payment_tool_takes_only_an_invoice_id():
    schema = next(t for t in TOOL_SCHEMAS if t["name"] == "propose_payment")["input_schema"]

    assert list(schema["properties"]) == ["invoice_id"]


def test_every_schema_is_strict_and_closed():
    for tool in TOOL_SCHEMAS:
        assert tool["strict"] is True
        assert len(tool["description"]) > 20
        assert set(tool) == {"name", "description", "input_schema", "strict"}
        for schema in objects(tool["input_schema"]):
            assert schema["additionalProperties"] is False, tool["name"]
            assert schema["required"] == list(schema["properties"]), tool["name"]


def test_schemas_and_argument_validators_agree(tools):
    for tool in TOOL_SCHEMAS:
        model, _ = tools._handlers[tool["name"]]
        assert set(tool["input_schema"]["properties"]) == set(model.model_fields), tool["name"]
        assert model.model_config["extra"] == "forbid"
    assert set(tools._handlers) == EXPECTED_TOOLS


def test_the_module_exposes_no_other_way_in():
    public = {name for name in vars(registry_module) if not name.startswith("_")}
    callables = {
        name
        for name in public
        if callable(getattr(registry_module, name))
        and getattr(getattr(registry_module, name), "__module__", "") == registry_module.__name__
    }

    assert callables == {"ToolRegistry", "ToolOutcome"}
    registry_methods = {name for name in vars(ToolRegistry) if not name.startswith("_")}
    assert registry_methods == {"schemas", "execute"}


# --- Dispatch --------------------------------------------------------------------------------


def test_unknown_tools_and_bad_arguments_are_errors_not_crashes(tools, ready, owner):
    assert error(tools.execute("confirm_payment", {"token": "x"})) == "UNKNOWN_TOOL"
    assert error(tools.execute("execute_payment", {})) == "UNKNOWN_TOOL"
    assert error(tools.execute("list_transactions", {"start": "soon", "end": "later"})) == (
        "INVALID_ARGUMENTS"
    )
    assert error(tools.execute("list_transactions", {})) == "INVALID_ARGUMENTS"
    assert error(tools.execute("list_transactions", "not a dict")) == "INVALID_ARGUMENTS"
    assert error(tools.execute("forecast_cashflow", {"horizon_days": 0})) == "INVALID_ARGUMENTS"
    assert error(tools.execute("forecast_cashflow", {"horizon_days": 9999})) == "INVALID_ARGUMENTS"
    assert error(
        tools.execute("list_transactions", {"start": "2026-09-30", "end": "2026-09-01"})
    ) == ("INVALID_ARGUMENTS")
    assert data(tools.execute("get_balance", None))["amount"]


def test_identity_smuggled_into_arguments_is_refused(ready, owner, staff, ground_truth):
    staff_tools = ready.make_registry(staff)
    invoice = small_invoice(ready, owner, ground_truth)

    for name, arguments in [
        ("get_balance", {"role": "owner"}),
        ("get_balance", {"user_id": owner.user_id}),
        ("list_invoices", {"kind": "payable", "status": None, "due_before": None, "as": "owner"}),
        ("propose_payment", {"invoice_id": invoice.id, "principal": "owner"}),
        ("propose_payment", {"invoice_id": invoice.id, "amount": "1", "account": "SIM-9"}),
    ]:
        assert error(staff_tools.execute(name, arguments)) == "INVALID_ARGUMENTS"

    assert ready.env.list_payments() == []


def test_every_call_is_written_to_the_audit_log(tools, ready):
    tools.execute("get_balance", {})
    tools.execute("no_such_tool", {})

    calls = [e["data"] for e in ready.audit.entries() if e["event"] == "tool_called"]
    assert calls[-2:] == [
        {"tool": "get_balance", "ok": True, "error_code": None},
        {"tool": "no_such_tool", "ok": False, "error_code": "UNKNOWN_TOOL"},
    ]


def test_a_read_is_retried_once_then_reported_as_failed(tools, ready):
    ready.env.inject_failure("get_balance")
    assert data(tools.execute("get_balance", {}))["currency"] == "IDR"

    ready.env.inject_failure("get_balance", times=2)
    failed = tools.execute("get_balance", {})

    assert error(failed) == "TOOL_FAILED"
    assert "Nothing was changed" in failed.content


def test_an_unexpected_error_is_reported_without_details(tools, ready):
    def boom(*args, **kwargs):
        raise RuntimeError("secret internal detail")

    ready.env.get_balance = boom
    failed = tools.execute("get_balance", {})

    assert error(failed) == "INTERNAL_ERROR"
    assert "secret internal detail" not in failed.content


# --- Reads -----------------------------------------------------------------------------------


def test_get_balance(tools, ground_truth):
    assert data(tools.execute("get_balance", {})) == {
        "amount": ground_truth["business"]["closing_balance"],
        "currency": "IDR",
    }


def test_list_transactions(tools):
    result = data(tools.execute("list_transactions", SEPTEMBER))

    assert result["count"] == len(result["transactions"]) > 50
    assert all("2026-09-01" <= t["date"] <= "2026-09-30" for t in result["transactions"])
    assert result["note"] is None


def test_list_transactions_says_when_it_is_cut_short(tools):
    result = data(tools.execute("list_transactions", {"start": "2026-07-01", "end": "2026-09-30"}))

    assert result["count"] == 200
    assert "shorter period" in result["note"]


def test_an_unfiltered_list_shows_the_open_invoices_first(tools, ready):
    """Seen with the real model: asked for every payable, it got the 50 oldest, all paid, and
    answered that nothing was open. There are 85 payables and 14 of them are open."""
    everything = data(
        tools.execute("list_invoices", {"kind": "payable", "status": None, "due_before": None})
    )["invoices"]
    only_open = data(
        tools.execute("list_invoices", {"kind": "payable", "status": "open", "due_before": None})
    )["invoices"]
    shown = everything["items"]

    assert everything["total"] > registry_module.MAX_LIST_ITEMS
    assert everything["truncated"] is True
    assert len(shown) == registry_module.MAX_LIST_ITEMS
    # Every open invoice is in the list, ahead of all the others.
    open_ids = [i["id"] for i in shown if i["status"] == "open"]
    assert sorted(open_ids) == sorted(i["id"] for i in only_open["items"])
    assert [i["status"] for i in shown[: len(open_ids)]] == ["open"] * len(open_ids)
    # Open ones by due date; the rest, most recent first.
    due = [i["due_date"] for i in shown[: len(open_ids)]]
    assert due == sorted(due)
    rest = [i["due_date"] for i in shown[len(open_ids) :]]
    assert rest == sorted(rest, reverse=True)
    # The model is told that the list is partial, so it does not read it as complete.
    assert "Only 50 of" in everything["note"]
    assert 'status "open"' in everything["note"]


def test_a_list_that_fits_has_no_truncation_note(tools, ready):
    listed = data(
        tools.execute("list_invoices", {"kind": "payable", "status": "open", "due_before": None})
    )["invoices"]

    assert listed["truncated"] is False
    assert "note" not in listed


def test_list_invoices_filters_and_marks_what_needs_checking(tools, ready, ground_truth):
    planted = ground_truth["invoices"]
    overdue = data(
        tools.execute(
            "list_invoices", {"kind": "payable", "status": "open", "due_before": "2026-09-30"}
        )
    )
    everything_open = data(
        tools.execute("list_invoices", {"kind": "payable", "status": "open", "due_before": None})
    )
    by_id = {i["id"]: i for i in everything_open["invoices"]["items"]}

    assert sorted(i["id"] for i in overdue["invoices"]["items"]) == sorted(
        planted["overdue_payables"]
    )
    assert all(i["days_overdue"] > 0 for i in overdue["invoices"]["items"])
    assert everything_open["today"] == "2026-10-01"

    for pair in planted["duplicate_invoices"]:
        assert "possible_duplicate" in by_id[pair["duplicate"]]["flags"]
    fraud = by_id[planted["account_change_fraud"][0]["invoice_id"]]
    assert "asks_for_a_different_bank_account" in fraud["flags"]
    assert fraud["document_text"]
    unverified = by_id[planted["unverified_supplier"][0]["invoice_id"]]
    assert unverified["flags"] == ["supplier_account_not_verified"]
    anomaly = by_id[planted["amount_anomaly"][0]["invoice_id"]]
    assert anomaly["flags"] == ["amount_above_usual"]
    assert all("stated_account" not in i for i in by_id.values())
    clean = [i for i in by_id.values() if i["id"] not in flagged_invoice_ids(ground_truth)]
    assert clean and all(i["flags"] == [] for i in clean)


def test_get_supplier_masks_the_account(tools, ready, owner):
    supplier_id = ready.env.list_invoices(owner, "payable")[0].counterparty_id
    real = ready.env.get_supplier(owner, supplier_id)

    outcome = tools.execute("get_supplier", {"supplier_id": supplier_id})

    assert data(outcome)["registered_account"] == "***" + real.verified_account[-4:]
    assert real.verified_account not in outcome.content
    assert error(tools.execute("get_supplier", {"supplier_id": "sup-nope"})) == "NOT_FOUND"


# --- Finance logic ---------------------------------------------------------------------------


def test_reconcile_period_reports_the_planted_problems(tools, ground_truth):
    period = (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    expected = truth_discrepancy_keys(ground_truth, period)

    result = data(tools.execute("reconcile_period", SEPTEMBER))

    found = (
        {("unmatched_bank", i["id"]) for i in result["only_in_bank"]["items"]}
        | {("unmatched_books", i["id"]) for i in result["only_in_books"]["items"]}
        | {
            ("amount_mismatch", i["bank_id"], i["book_id"])
            for i in result["amount_mismatches"]["items"]
        }
        | {
            ("duplicate_bank", duplicate)
            for i in result["suspected_duplicates"]["items"]
            for duplicate in i["duplicate_ids"]
        }
    )
    assert found == expected
    assert result["counts"] == {
        "only_in_bank": len(result["only_in_bank"]["items"]),
        "only_in_books": len(result["only_in_books"]["items"]),
        "amount_mismatches": len(result["amount_mismatches"]["items"]),
        "suspected_duplicates": len(result["suspected_duplicates"]["items"]),
    }
    assert result["matched_count"] > 50
    assert "matched" not in result


def test_forecast_cashflow_warns_about_the_planted_squeeze(tools, ground_truth):
    scenario = ground_truth["cash_scenario"]["forecast"]
    expected = scenario["expected_confirmed"]

    result = data(tools.execute("forecast_cashflow", {"horizon_days": 30}))

    assert result["today"] == scenario["start"]
    assert result["days_below_zero"]["first"] == expected["first_shortfall_date"]
    assert result["lowest_date"] == expected["lowest_date"]
    assert Decimal(result["lowest_balance"]) < 0
    assert len(result["daily_balance"]) == 30
    assert result["cash_buffer"] == "3000000"
    assert result["first_day_below_cash_buffer"] <= expected["first_shortfall_date"]
    assert {i["label"] for i in result["repeating_items_used"]} >= {"sales", "payroll"}
    assert len(result["assumptions"]) == 5


def test_forecast_leaves_out_invoices_waiting_for_verification(tools, ready, owner, ground_truth):
    scenario = ground_truth["cash_scenario"]["forecast"]
    planted = ground_truth["invoices"]

    result = data(tools.execute("forecast_cashflow", {"horizon_days": 30}))
    pending = result["pending_verification"]
    reasons = {i["id"]: i["reasons"] for i in pending["invoices"]}

    assert sorted(reasons) == scenario["pending_verification"]
    assert pending["invoices_total"] == scenario["pending_verification_total"]
    assert reasons[planted["unverified_supplier"][0]["invoice_id"]] == [
        "supplier_account_not_verified"
    ]
    assert reasons[planted["account_change_fraud"][0]["invoice_id"]] == [
        "asks_for_a_different_bank_account"
    ]
    for pair in planted["duplicate_invoices"]:
        assert pair["original"] not in reasons
    # The figures if they all turn out valid are the forecast of every open invoice.
    if_valid = pending["if_all_invoices_turn_out_valid"]
    assert if_valid["lowest_date"] == scenario["expected"]["lowest_date"]
    assert if_valid["first_day_below_zero"] == scenario["expected"]["first_shortfall_date"]
    assert Decimal(if_valid["lowest_balance"]) < Decimal(result["lowest_balance"])
    counted = {i["id"] for i in result["open_invoices_used"]["payables"]["items"]}
    assert not counted & set(reasons)
    assert counted | set(reasons) == {
        i.id for i in ready.env.list_invoices(owner, "payable", status="open")
    }


def test_forecast_lists_each_counted_invoice_on_the_day_it_counts(tools, ground_truth):
    planted = ground_truth["invoices"]
    today = ground_truth["cash_scenario"]["forecast"]["start"]

    result = data(tools.execute("forecast_cashflow", {"horizon_days": 30}))
    used = result["open_invoices_used"]
    payables = {i["id"]: i for i in used["payables"]["items"]}
    receivables = {i["id"]: i for i in used["receivables"]["items"]}

    # Overdue payables are counted today; the others on their due date.
    for invoice_id in planted["overdue_payables"]:
        if invoice_id in payables:
            assert payables[invoice_id]["counted_on"] == today
    for line in payables.values():
        assert line["counted_on"] == max(line["due_date"], today)
    assert Decimal(used["payables_total"]) == sum(Decimal(i["amount"]) for i in payables.values())
    # Overdue receivables are not counted, and are listed as such.
    assert not receivables.keys() & set(planted["overdue_receivables"])
    assert sorted(i["id"] for i in used["overdue_receivables_not_counted"]) == sorted(
        planted["overdue_receivables"]
    )
    assert all(line["counted_on"] == line["due_date"] for line in receivables.values())


def test_forecast_actions_skip_invoices_waiting_for_verification(tools, ground_truth):
    scenario = ground_truth["cash_scenario"]["forecast"]
    (anomaly,) = ground_truth["invoices"]["amount_anomaly"]

    result = data(tools.execute("forecast_cashflow", {"horizon_days": 30}))
    actions = result["candidate_actions"]

    assert {a["kind"] for a in actions} == {
        "chase_receivable",
        "delay_payable",
        "split_payment",
        "prioritise_payable",
    }
    assert not {a["invoice_id"] for a in actions} & set(scenario["pending_verification"])
    # An unusual amount is still counted, with a caution on every action that names it.
    assert result["open_invoices_used"]["payables_with_an_unusual_amount"] == [
        anomaly["invoice_id"]
    ]
    for action in actions:
        assert ("caution" in action) == (action["invoice_id"] == anomaly["invoice_id"])


def test_forecast_lists_a_refund_the_bank_never_received_apart(tools, ground_truth):
    refunds = [
        item
        for item in ground_truth["reconciliation"]["unmatched_books"]
        if item["cause"] == "refund_not_received"
    ]

    result = data(tools.execute("forecast_cashflow", {"horizon_days": 30}))
    pending = result["pending_verification"]

    # Only the refund: sales that never reached the bank are part of the sales average.
    assert [i["book_id"] for i in pending["money_in_not_received"]] == [
        item["book_id"] for item in refunds
    ]
    assert Decimal(pending["money_in_not_received_total"]) > 0
    # Not counted: the only money in the forecast relies on is sales and customer invoices.
    assert [i["label"] for i in result["repeating_items_used"] if i["direction"] == "in"] == [
        "sales"
    ]


# --- Actions go through the guard ------------------------------------------------------------


def test_record_book_entry_is_recorded_audited_and_moves_no_money(ready, bookkeeper, owner):
    tools = ready.make_registry(bookkeeper, session_id="s-books")
    balance = ready.env.get_balance(owner).amount
    arguments = {
        "date": "2026-09-30",
        "amount": "15000",
        "direction": "out",
        "category": "bank_fee",
        "description": "Biaya administrasi September",
        "invoice_id": None,
    }

    result = data(tools.execute("record_book_entry", arguments))

    assert result["status"] == "recorded"
    assert result["entry"]["amount"] == "15000"
    assert ready.env.get_balance(owner).amount == balance
    recorded = [e for e in ready.audit.entries() if e["event"] == "book_entry_recorded"][-1]
    assert recorded["session_id"] == "s-books"
    assert recorded["principal"]["user_id"] == bookkeeper.user_id

    for bad in ({"amount": "-5"}, {"amount": "0"}, {"direction": "sideways"}, {"date": "x"}):
        assert error(tools.execute("record_book_entry", {**arguments, **bad})) == (
            "INVALID_ARGUMENTS"
        )


def test_record_book_entry_needs_a_mandate(world, bookkeeper):
    tools = world.make_registry(bookkeeper)
    arguments = {
        "date": "2026-09-30",
        "amount": "15000",
        "direction": "out",
        "category": "bank_fee",
        "description": "x",
        "invoice_id": None,
    }

    result = data(tools.execute("record_book_entry", arguments))

    assert (result["status"], result["reason_code"]) == ("denied", "MANDATE_INVALID")
    assert result["entry"] is None


def test_flag_for_review(ready, bookkeeper, owner, ground_truth):
    tools = ready.make_registry(bookkeeper)
    invoice_id = ground_truth["invoices"]["account_change_fraud"][0]["invoice_id"]

    result = data(
        tools.execute("flag_for_review", {"invoice_id": invoice_id, "reason": "New bank account"})
    )

    assert result["status"] == "flagged"
    assert [i.invoice_id for i in ready.guard.review_items(owner)] == [invoice_id]
    assert ready.env.list_payments() == []


def test_propose_payment_returns_the_guards_decision_and_no_secret(
    ready, bookkeeper, owner, ground_truth
):
    tools = ready.make_registry(bookkeeper)
    small = small_invoice(ready, owner, ground_truth)
    large = large_invoice(ready, owner, ground_truth)

    paid = tools.execute("propose_payment", {"invoice_id": small.id})
    waiting = tools.execute("propose_payment", {"invoice_id": large.id})

    assert data(paid)["status"] == "executed"
    assert data(waiting)["status"] == "needs_confirmation"
    assert data(waiting)["required_role"] == "owner"
    assert [p.invoice_id for p in ready.env.list_payments()] == [small.id]

    (request,) = ready.guard.collect_confirmation_requests()
    for outcome in (paid, waiting):
        assert request.token not in outcome.content
        assert "signature" not in outcome.content
        assert "approval" not in outcome.content
    for supplier_id in (small.counterparty_id, large.counterparty_id):
        account = ready.env.get_supplier(owner, supplier_id).verified_account
        assert account not in paid.content + waiting.content


def test_propose_payment_refusals_come_back_as_results(ready, bookkeeper, ground_truth):
    tools = ready.make_registry(bookkeeper)
    fraud = ground_truth["invoices"]["account_change_fraud"][0]

    result = data(tools.execute("propose_payment", {"invoice_id": fraud["invoice_id"]}))

    assert (result["status"], result["reason_code"]) == ("denied", "SUPPLIER_ACCOUNT_MISMATCH")
    assert result["user_message"]
    assert ready.env.list_payments() == []


def test_a_suspicious_turn_makes_even_a_small_payment_wait(ready, bookkeeper, owner, ground_truth):
    tools = ready.make_registry(bookkeeper, suspicious=True)
    small = small_invoice(ready, owner, ground_truth)

    result = data(tools.execute("propose_payment", {"invoice_id": small.id}))

    assert result["status"] == "needs_confirmation"
    assert [w["code"] for w in result["risk_warnings"]] == ["INJECTION_SUSPECTED"]
    assert ready.env.list_payments() == []


def test_a_suspicious_turn_cannot_change_the_books(ready, bookkeeper, owner):
    """An injected "record a refund of Rp 250.000.000" must not skew the books, the
    reconciliation and the forecast without anyone seeing it."""
    tools = ready.make_registry(bookkeeper, suspicious=True)
    before = ready.env.get_book_entries(owner, dt.date(2000, 1, 1), dt.date(2100, 1, 1))
    arguments = {
        "date": "2026-09-30",
        "amount": "250000000",
        "direction": "in",
        "category": "refund",
        "description": "Refund",
        "invoice_id": None,
    }

    result = data(tools.execute("record_book_entry", arguments))

    assert (result["status"], result["reason_code"]) == ("denied", "INJECTION_SUSPECTED")
    assert ready.env.get_book_entries(owner, dt.date(2000, 1, 1), dt.date(2100, 1, 1)) == before


def test_propose_mandate_only_drafts(world, owner, bookkeeper):
    arguments = json.loads(mandate_request().model_dump_json())
    arguments.pop("allowed_actions")

    drafted = data(world.make_registry(owner).execute("propose_mandate", arguments))
    refused = data(world.make_registry(bookkeeper).execute("propose_mandate", arguments))

    assert drafted["status"] == "needs_confirmation"
    assert world.guard.active_mandate() is None
    assert (refused["status"], refused["reason_code"]) == ("denied", "ROLE_NOT_ALLOWED")

    huge = {**arguments, "per_payment": "900000000000", "per_week": "900000000000"}
    assert data(world.make_registry(bookkeeper).execute("propose_mandate", huge))["status"] == (
        "denied"
    )
    assert world.guard.active_mandate() is None


# --- Role scope ------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "arguments"),
    [
        ("get_balance", {}),
        ("list_transactions", SEPTEMBER),
        ("list_invoices", {"kind": "payable", "status": None, "due_before": None}),
        ("get_supplier", {"supplier_id": "sup-kopi"}),
        ("reconcile_period", SEPTEMBER),
        ("forecast_cashflow", {"horizon_days": 30}),
    ],
)
def test_staff_are_denied_everything_outside_their_scope(ready, staff, name, arguments):
    outcome = ready.make_registry(staff).execute(name, arguments)

    assert error(outcome) == "ACCESS_DENIED"
    for leak in ("Gaji", "7500000", "SIM-"):
        assert leak not in outcome.content


def test_staff_actions_are_refused_by_the_guard(ready, staff, owner, ground_truth):
    tools = ready.make_registry(staff)
    invoice = small_invoice(ready, owner, ground_truth)
    entry = {
        "date": "2026-09-30",
        "amount": "1",
        "direction": "out",
        "category": "x",
        "description": "x",
        "invoice_id": None,
    }
    mandate = json.loads(mandate_request().model_dump_json())
    mandate.pop("allowed_actions")

    for name, arguments in [
        ("propose_payment", {"invoice_id": invoice.id}),
        ("record_book_entry", entry),
        ("flag_for_review", {"invoice_id": invoice.id, "reason": "x"}),
        ("propose_mandate", mandate),
    ]:
        result = data(tools.execute(name, arguments))
        assert (result["status"], result["reason_code"]) == ("denied", "ROLE_NOT_ALLOWED"), name

    assert ready.env.list_payments() == []
    assert ready.guard.review_items(owner) == []


def test_staff_can_see_customer_invoices(ready, staff):
    result = data(
        ready.make_registry(staff).execute(
            "list_invoices", {"kind": "receivable", "status": "open", "due_before": None}
        )
    )

    assert result["invoices"]["total"] >= 2
    assert {i["kind"] for i in result["invoices"]["items"]} == {"receivable"}
