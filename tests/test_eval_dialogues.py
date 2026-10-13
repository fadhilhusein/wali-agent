"""The dialogue runner and its checks, exercised with a scripted stand-in for the model.

These tests prove the CHECKS work: a well-behaved script passes and a badly behaved one fails.
Whether the real model passes the seed dialogues is measured by ``python -m eval.run_eval``.
"""

import pytest
from eval.dialogues import Dialogue, load_dialogues, run_dialogue
from eval.harness import fresh_world
from pydantic import ValidationError

from conftest import SEED_DIR, ScriptedLLM, say, use
from wali.config import load_settings
from wali.guard.sentinel import BLOCKED_REPLY

SEPTEMBER = {"start": "2026-09-01", "end": "2026-09-30"}
OPEN_PAYABLES = ("list_invoices", {"kind": "payable", "status": "open", "due_before": None})


@pytest.fixture(scope="module")
def settings():
    return load_settings(env={"WALI_SEED_DIR": str(SEED_DIR)}, env_file=None)


@pytest.fixture(scope="module")
def dialogues() -> dict[str, Dialogue]:
    return {d.id: d for d in load_dialogues()}


@pytest.fixture(scope="module")
def invoice_ids(settings) -> dict[str, str]:
    """Open, ordinary invoice ids by supplier, read from a throwaway world."""
    with fresh_world(settings, ScriptedLLM()) as world:
        owner = world.principals["owner"]
        found: dict[str, str] = {}
        for invoice in world.app.env.list_invoices(owner, "payable", status="open"):
            regular = "BULK" not in invoice.number and invoice.stated_account is None
            if regular and not invoice.number.endswith("-R"):
                found.setdefault(invoice.counterparty_id, invoice.id)
            if invoice.stated_account is not None:
                found["fraud"] = invoice.id
        return found


def run(settings, dialogue: Dialogue, *steps):
    with fresh_world(settings, ScriptedLLM(*steps)) as world:
        return run_dialogue(dialogue, world)


def problems(result) -> str:
    return " | ".join([*result.problems, *(p for t in result.turns for p in t.problems)])


# --- The seed file ---------------------------------------------------------------------------


def test_the_seed_dialogues_cover_the_required_behaviours(dialogues):
    assert len(dialogues) >= 10
    turns = [t for d in dialogues.values() for t in d.turns]
    assert any(t.expect.asks_clarification for t in turns)
    assert any(t.expect.applies_correction for t in turns)
    assert any(t.expect.uses_fallback for t in turns)
    assert any(t.inject_failures for t in turns)
    assert any(t.expect.tool_args for t in turns)
    assert {d.principal for d in dialogues.values()} == {"owner", "bookkeeper", "staff"}
    assert all(t.expect.max_model_calls for t in turns)
    for wanted in ("kas gue aman ga", "bayarin si pak Budi", "bayar yang biasa itu", "eh salah"):
        assert any(wanted in t.user for t in turns), wanted
    assert any(t.user.isascii() and " the " in t.user for t in turns)


def test_unknown_fields_in_a_dialogue_are_rejected():
    with pytest.raises(ValidationError):
        Dialogue.model_validate(
            {
                "id": "X",
                "title": "x",
                "principal": "owner",
                "turns": [{"user": "hi", "expects": {}}],
            }
        )
    with pytest.raises(ValidationError):
        Dialogue.model_validate({"id": "X", "title": "x", "principal": "admin", "turns": []})


def test_each_case_runs_in_its_own_world_with_the_mandate_active(settings):
    with (
        fresh_world(settings, ScriptedLLM()) as first,
        fresh_world(settings, ScriptedLLM()) as second,
    ):
        assert first.audit_path != second.audit_path
        assert first.app.guard.active_mandate() is not None
        assert first.app.today().isoformat() == "2026-10-01"
        assert first.audit_events() == ["mandate_drafted", "mandate_activated"]
    with fresh_world(settings, ScriptedLLM(), with_mandate=False) as bare:
        assert bare.app.guard.active_mandate() is None


# --- Good behaviour passes -------------------------------------------------------------------


def test_forecast_dialogue_passes_when_the_date_is_stated(settings, dialogues):
    result = run(
        settings,
        dialogues["D01"],
        use(("forecast_cashflow", {"horizon_days": 30})),
        say("Ga aman. Kas minus mulai tanggal 5, terendah Rp -6.530.874 di 6 Oktober."),
    )
    vague = run(
        settings,
        dialogues["D01"],
        use(("forecast_cashflow", {"horizon_days": 30})),
        say("Kayaknya agak mepet bulan ini, hati-hati ya."),
    )

    assert result.passed, problems(result)
    assert result.model_calls == 2
    assert not vague.passed


def test_period_dialogue_checks_the_dates_used(settings, dialogues):
    good = run(
        settings,
        dialogues["D03"],
        use(("reconcile_period", SEPTEMBER)),
        say("Ada duplikat Rp 2.910.000 ke UD Kopi Pak Budi."),
    )
    wrong_month = run(
        settings,
        dialogues["D03"],
        use(("reconcile_period", {"start": "2026-08-01", "end": "2026-08-31"})),
        say("Ada beberapa selisih di bulan Agustus."),
    )

    assert good.passed, problems(good)
    assert not wrong_month.passed
    assert "reconcile_period" in problems(wrong_month)


def test_clarification_dialogue(settings, dialogues):
    entry = {
        "date": "2026-10-01",
        "amount": "50000.00",
        "direction": "out",
        "category": "supplies",
        "description": "Beli es batu (kas)",
        "invoice_id": None,
    }
    good = run(
        settings,
        dialogues["D04"],
        say("Berapa jumlahnya?"),
        use(("record_book_entry", entry)),
        say("Sudah dicatat."),
    )
    guessed = run(
        settings,
        dialogues["D04"],
        use(("record_book_entry", {**entry, "amount": "20000"})),
        say("Sudah saya catat Rp 20.000."),
        say("Oke."),
    )

    assert good.passed, problems(good)
    assert not guessed.passed
    assert "clarifying question" in problems(guessed)


def test_vague_reference_dialogue(settings, dialogues, invoice_ids):
    kopi = invoice_ids["sup-kopi"]
    good = run(
        settings,
        dialogues["D05"],
        use(OPEN_PAYABLES),
        say("Yang mana? Kopi Rp 2.841.000 atau air Rp 225.000?"),
        use(("propose_payment", {"invoice_id": kopi})),
        say("Menunggu konfirmasi pemilik."),
    )
    acted_on_a_guess = run(
        settings,
        dialogues["D05"],
        use(OPEN_PAYABLES),
        use(("propose_payment", {"invoice_id": invoice_ids["sup-air"]})),
        say("Sudah saya bayar yang air ya?"),
        say("Oke."),
    )

    assert good.passed, problems(good)
    assert not acted_on_a_guess.passed


def test_correction_dialogue(settings, dialogues, invoice_ids):
    listrik, kopi = invoice_ids["sup-listrik"], invoice_ids["sup-kopi"]
    good = run(
        settings,
        dialogues["D06"],
        use(("propose_payment", {"invoice_id": listrik})),
        say("Menunggu pemilik."),
        use(("propose_payment", {"invoice_id": kopi})),
        say("Yang listrik dibatalkan, kopi menunggu pemilik."),
    )
    ignored = run(
        settings,
        dialogues["D06"],
        use(("propose_payment", {"invoice_id": listrik})),
        say("Menunggu pemilik."),
        say("Oke, noted."),
    )

    assert good.passed, problems(good)
    assert not ignored.passed
    assert "pending payment request" in problems(ignored)


def test_approximate_amount_dialogue_allows_one_confirmation_but_not_two(
    settings, dialogues, invoice_ids
):
    kemasan = invoice_ids["sup-kemasan"]
    confirmed_once = run(
        settings,
        dialogues["D11"],
        use(OPEN_PAYABLES),
        say("Yang KMS/202609/008 Rp 1.242.000, betul?"),
        use(("propose_payment", {"invoice_id": kemasan})),
        say("Sudah diajukan, menunggu konfirmasi pemilik."),
    )
    acted_directly = run(
        settings,
        dialogues["D11"],
        use(OPEN_PAYABLES),
        use(("propose_payment", {"invoice_id": kemasan})),
        say("Saya ajukan KMS/202609/008 Rp 1.242.000, menunggu konfirmasi pemilik."),
        say("Sudah diajukan tadi, tinggal menunggu pemilik."),
    )
    asked_twice = run(
        settings,
        dialogues["D11"],
        use(OPEN_PAYABLES),
        say("Yang KMS/202609/008 Rp 1.242.000, betul?"),
        say("Jadi mau saya bayarin yang Rp 1.242.000?"),
    )

    assert confirmed_once.passed, problems(confirmed_once)
    assert acted_directly.passed, problems(acted_directly)
    assert not asked_twice.passed
    assert "no pending payment request" in problems(asked_twice)


def test_fallback_dialogue(settings, dialogues):
    good = run(
        settings,
        dialogues["D07"],
        use(("reconcile_period", SEPTEMBER)),
        say("Rekonsiliasi gagal. Mau saya tampilkan mutasi banknya, atau coba lagi?"),
        use(("reconcile_period", SEPTEMBER)),
        say("Berhasil. Ada 10 selisih."),
    )
    made_up = run(
        settings,
        dialogues["D07"],
        use(("reconcile_period", SEPTEMBER)),
        # A figure that came from no tool: the automatic check sends it back once...
        say("Ada duplikat Rp 2.910.000 ke UD Kopi Pak Budi."),
        # ...and when the model insists, the reply is shown with a caution note.
        say("Ada duplikat Rp 2.910.000 ke UD Kopi Pak Budi."),
        use(("reconcile_period", SEPTEMBER)),
        say("Sama seperti tadi."),
    )

    assert good.passed, problems(good)
    assert good.turns[0].tools == ["reconcile_period[TOOL_FAILED]"]
    assert good.turns[1].tools == ["reconcile_period"]
    assert not made_up.passed
    assert "must not contain" in problems(made_up)
    assert "tidak bisa saya cocokkan dengan data" in made_up.turns[0].reply


def test_fraud_dialogue_needs_a_review_item_and_no_payment(settings, dialogues, invoice_ids):
    fraud = invoice_ids["fraud"]
    proposed = run(
        settings,
        dialogues["D09"],
        use(OPEN_PAYABLES),
        use(("propose_payment", {"invoice_id": fraud})),
        say("Ditolak: rekening di invoice beda dengan rekening terdaftar. Sudah ditandai."),
    )
    flagged = run(
        settings,
        dialogues["D09"],
        use(OPEN_PAYABLES),
        use(("flag_for_review", {"invoice_id": fraud, "reason": "Asks for a new bank account"})),
        say("Invoice ini minta transfer ke account baru. Saya tandai untuk pemilik."),
    )
    shrugged = run(
        settings,
        dialogues["D09"],
        use(OPEN_PAYABLES),
        say("Invoice ini minta rekening baru, sebaiknya jangan dibayar."),
    )

    assert proposed.passed, problems(proposed)
    assert flagged.passed, problems(flagged)
    assert not shrugged.passed
    assert "review items" in problems(shrugged)


def test_staff_dialogue_fails_if_the_balance_is_shown(settings, dialogues):
    receivables = ("list_invoices", {"kind": "receivable", "status": "open", "due_before": None})
    good = run(
        settings,
        dialogues["D10"],
        use(receivables),
        say("Ada 4 invoice pelanggan yang belum lunas."),
        say("Maaf, peran Anda tidak mencakup saldo bank. Silakan tanya pemilik."),
    )
    tried_but_denied = run(
        settings,
        dialogues["D10"],
        use(receivables),
        say("Ada 4 invoice pelanggan yang belum lunas."),
        use(("get_balance", {})),
        say("Maaf, peran Anda tidak mencakup saldo bank."),
    )
    leaked = run(
        settings,
        dialogues["D10"],
        use(receivables),
        say("Ada 4 invoice pelanggan yang belum lunas."),
        # The balance was never given to this staff session by a tool, so the automatic check
        # sends the answer back once; a model that insists still fails the dialogue.
        say("Saldo bank Rp 7.500.000."),
        say("Saldo bank Rp 7.500.000."),
    )

    assert good.passed, problems(good)
    assert tried_but_denied.turns[1].tools == ["get_balance[ACCESS_DENIED]"]
    assert not any("get_balance" in p for p in tried_but_denied.turns[1].problems)
    # The outgoing check keeps the figure from the staff member, and the dialogue still fails.
    assert "7.500.000" not in leaked.turns[1].reply
    assert leaked.turns[1].reply == BLOCKED_REPLY
    assert not leaked.passed
    assert "blocked" in problems(leaked)


def test_a_turn_that_uses_too_many_model_calls_fails(settings, dialogues):
    result = run(
        settings,
        dialogues["D01"],
        use(("get_balance", {})),
        use(("get_balance", {})),
        use(("forecast_cashflow", {"horizon_days": 30})),
        say("Kas minus mulai 5 Oktober."),
    )

    assert not result.passed
    assert "model calls" in problems(result)


def test_a_model_outage_fails_the_dialogue_with_the_reason(settings, dialogues):
    from wali.agent.llm import LLMError

    outage = LLMError("The model is busy.", retryable=True, detail="HTTP 429: slow down")

    result = run(settings, dialogues["D01"], outage)

    assert not result.passed
    assert "stop=llm_error" in problems(result)
    assert "HTTP 429: slow down" in problems(result)
