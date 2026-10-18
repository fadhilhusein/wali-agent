"""The deterministic helpers behind the dialogue behaviours, and how the app uses them."""

import datetime as dt
import json

import pytest

from conftest import ScriptedLLM, flagged_invoice_ids, say, tool_results, use
from wali.agent.dialogue import (
    fallback_hint,
    guess_language,
    is_correction,
    period_hints,
    plain_text,
    render_period_hints,
    reply_problems,
    ungrounded_figures,
)
from wali.agent.prompts import build_system_prompt
from wali.tools.registry import TOOL_NAMES

SEPTEMBER = {"start": "2026-09-01", "end": "2026-09-30"}


def d(text: str) -> dt.date:
    return dt.date.fromisoformat(text)


def invoice_of(world, owner, supplier_id, ground_truth):
    flagged = flagged_invoice_ids(ground_truth)
    return next(
        i
        for i in world.env.list_invoices(owner, "payable", status="open")
        if i.counterparty_id == supplier_id and i.id not in flagged
    )


# --- Periods ---------------------------------------------------------------------------------


def test_periods_for_the_demo_date():
    hints = period_hints(d("2026-10-01"))  # a Thursday

    assert hints == {
        "today": (d("2026-10-01"), d("2026-10-01")),
        "yesterday": (d("2026-09-30"), d("2026-09-30")),
        "this week": (d("2026-09-28"), d("2026-10-01")),
        "last week": (d("2026-09-21"), d("2026-09-27")),
        "this month": (d("2026-10-01"), d("2026-10-01")),
        "last month": (d("2026-09-01"), d("2026-09-30")),
        "last 7 days": (d("2026-09-25"), d("2026-10-01")),
        "last 30 days": (d("2026-09-02"), d("2026-10-01")),
    }


@pytest.mark.parametrize(
    ("today", "last_month", "last_week"),
    [
        ("2026-01-15", ("2025-12-01", "2025-12-31"), ("2026-01-05", "2026-01-11")),
        ("2026-03-31", ("2026-02-01", "2026-02-28"), ("2026-03-23", "2026-03-29")),
        ("2028-03-01", ("2028-02-01", "2028-02-29"), ("2028-02-21", "2028-02-27")),
        ("2026-10-05", ("2026-09-01", "2026-09-30"), ("2026-09-28", "2026-10-04")),
    ],
)
def test_periods_across_year_ends_leap_years_and_mondays(today, last_month, last_week):
    hints = period_hints(d(today))

    assert hints["last month"] == (d(last_month[0]), d(last_month[1]))
    assert hints["last week"] == (d(last_week[0]), d(last_week[1]))
    assert hints["last week"][0].weekday() == 0
    assert hints["this week"][0].weekday() == 0
    assert hints["this week"][1] == d(today)


def test_period_hints_are_in_the_system_prompt():
    prompt = build_system_prompt(role="bookkeeper", currency="IDR", today=d("2026-10-01"))

    assert "Today is Thursday, 2026-10-01" in prompt
    assert "- last month: 2026-09-01 to 2026-09-30" in prompt
    assert "- yesterday: 2026-09-30" in prompt
    assert render_period_hints(d("2026-10-01")) in prompt


# --- Corrections -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "eh salah, bayar yang kopi aja",
        "Eh Salah. yang susu",
        "maksudku yang kemasan",
        "maksud saya invoice kopi",
        "bukan yang itu, yang gula",
        "bukan itu",
        "ralat: yang 1,2 juta",
        "ganti jadi kopi",
        "sorry, wrong one, the coffee invoice",
        "I meant the milk invoice",
        "not that one",
        "pay the coffee one instead",
        "keliru, harusnya kopi",
    ],
)
def test_corrections_are_recognised(text):
    assert is_correction(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "bayar yang kopi aja",
        "bayarin si pak Budi yg kopi itu ya",
        "sekalian bayar susu juga",
        "bayar salah satu tagihan susu dulu",
        "kas gue aman ga sampe akhir bulan?",
        "pay the coffee invoice",
        "tolong rekonsiliasi September",
        "berapa selisihnya?",
        "",
    ],
)
def test_ordinary_requests_are_not_corrections(text):
    assert is_correction(text) is False


def test_a_correction_withdraws_the_earlier_request_and_makes_the_new_one(
    ready, owner, bookkeeper, ground_truth
):
    kemasan = invoice_of(ready, owner, "sup-kemasan", ground_truth)
    kopi = invoice_of(ready, owner, "sup-kopi", ground_truth)
    llm = ScriptedLLM(
        use(("propose_payment", {"invoice_id": kemasan.id})),
        say("Menunggu pemilik."),
        use(("propose_payment", {"invoice_id": kopi.id})),
        say("Diganti ke kopi."),
    )
    app = ready.make_app(llm)

    app.chat(bookkeeper, "bayar tagihan kemasan")
    (old_request,) = app.pending(owner)
    corrected = app.chat(bookkeeper, "eh salah, bayar yang kopi aja")

    decision = tool_results(llm.requests[3])[0]["untrusted_data"]
    assert decision["status"] == "needs_confirmation"
    assert decision["earlier_requests_withdrawn"] == [
        {
            "supplier_name": old_request.summary.supplier_name,
            "invoice_number": kemasan.number,
            "amount": str(kemasan.amount),
        }
    ]
    (new_request,) = corrected.new_confirmations
    assert new_request.summary.invoice_number == kopi.number
    assert app.pending(owner) == [new_request]
    assert ready.guard.confirm_payment(owner, old_request.token).reason_code == (
        "CONFIRMATION_INVALID"
    )
    assert "proposal_withdrawn" in [e["event"] for e in ready.audit.entries()]

    assert app.confirm(owner).status == "executed"
    assert [p.invoice_id for p in ready.env.list_payments()] == [kopi.id]


def test_a_correction_that_names_two_payments_keeps_both(ready, owner, bookkeeper, ground_truth):
    kemasan = invoice_of(ready, owner, "sup-kemasan", ground_truth)
    kopi = invoice_of(ready, owner, "sup-kopi", ground_truth)
    air = invoice_of(ready, owner, "sup-air", ground_truth)
    llm = ScriptedLLM(
        use(("propose_payment", {"invoice_id": kemasan.id})),
        say("Menunggu pemilik."),
        use(
            ("propose_payment", {"invoice_id": kopi.id}),
            ("propose_payment", {"invoice_id": air.id}),
        ),
        say("Diganti ke kopi dan air."),
    )
    app = ready.make_app(llm)

    app.chat(bookkeeper, "bayar tagihan kemasan")
    app.chat(bookkeeper, "eh salah, bayar kopi dan air")

    waiting = [r.summary.invoice_number for r in app.pending(owner)]
    paid = [p.invoice_id for p in ready.env.list_payments()]
    assert kopi.number in waiting
    assert kemasan.number not in waiting
    assert air.number in waiting or air.id in paid


def test_a_second_request_that_is_not_a_correction_keeps_both(
    ready, owner, bookkeeper, ground_truth
):
    kemasan = invoice_of(ready, owner, "sup-kemasan", ground_truth)
    kopi = invoice_of(ready, owner, "sup-kopi", ground_truth)
    llm = ScriptedLLM(
        use(("propose_payment", {"invoice_id": kemasan.id})),
        say("Menunggu pemilik."),
        use(("propose_payment", {"invoice_id": kopi.id})),
        say("Dua-duanya menunggu."),
    )
    app = ready.make_app(llm)

    app.chat(bookkeeper, "bayar tagihan kemasan")
    app.chat(bookkeeper, "sekalian bayar kopi juga")

    assert "earlier_requests_withdrawn" not in tool_results(llm.requests[3])[0]["untrusted_data"]
    assert len(app.pending(owner)) == 2


def test_a_correction_without_a_new_payment_withdraws_nothing(
    ready, owner, bookkeeper, ground_truth
):
    kopi = invoice_of(ready, owner, "sup-kopi", ground_truth)
    llm = ScriptedLLM(
        use(("propose_payment", {"invoice_id": kopi.id})), say("Menunggu."), say("Yang mana?")
    )
    app = ready.make_app(llm)

    app.chat(bookkeeper, "bayar kopi")
    app.chat(bookkeeper, "eh salah deh")

    assert len(app.pending(owner)) == 1


def test_a_correction_cannot_withdraw_someone_elses_request(ready, owner, bookkeeper, ground_truth):
    kemasan = invoice_of(ready, owner, "sup-kemasan", ground_truth)
    kopi = invoice_of(ready, owner, "sup-kopi", ground_truth)
    llm = ScriptedLLM(
        use(("propose_payment", {"invoice_id": kemasan.id})),
        say("Menunggu."),
        use(("propose_payment", {"invoice_id": kopi.id})),
        say("Menunggu."),
    )
    app = ready.make_app(llm)

    app.chat(bookkeeper, "bayar kemasan")
    app.chat(owner, "eh salah, bayar yang kopi aja")

    assert len(app.pending(owner)) == 2


def test_requests_already_settled_are_not_reported_as_withdrawn(
    ready, owner, bookkeeper, ground_truth
):
    kemasan = invoice_of(ready, owner, "sup-kemasan", ground_truth)
    kopi = invoice_of(ready, owner, "sup-kopi", ground_truth)
    llm = ScriptedLLM(
        use(("propose_payment", {"invoice_id": kemasan.id})),
        say("Menunggu."),
        use(("propose_payment", {"invoice_id": kopi.id})),
        say("Menunggu."),
    )
    app = ready.make_app(llm)

    app.chat(bookkeeper, "bayar kemasan")
    assert app.confirm(owner).status == "executed"
    app.chat(bookkeeper, "eh salah, bayar yang kopi aja")

    assert "earlier_requests_withdrawn" not in tool_results(llm.requests[3])[0]["untrusted_data"]
    assert [p.invoice_id for p in ready.env.list_payments()] == [kemasan.id]


def test_the_inbox_drops_requests_that_are_no_longer_pending(
    ready, owner, bookkeeper, ground_truth
):
    kopi = invoice_of(ready, owner, "sup-kopi", ground_truth)
    llm = ScriptedLLM(
        use(("propose_payment", {"invoice_id": kopi.id})),
        say("Menunggu."),
        use(("propose_payment", {"invoice_id": kopi.id})),
        say("Menunggu."),
    )
    app = ready.make_app(llm)

    app.chat(bookkeeper, "bayar kopi")
    app.chat(bookkeeper, "bayar kopi sekali lagi")

    assert len(app.pending(owner)) == 1
    assert app.confirm(owner).status == "executed"


# --- Fallback --------------------------------------------------------------------------------


def test_every_read_tool_has_a_fallback_hint():
    for name in ("reconcile_period", "forecast_cashflow", "list_transactions", "list_invoices"):
        assert fallback_hint(name)
    assert "list_transactions" in fallback_hint("reconcile_period")
    assert "Do not estimate" in fallback_hint("forecast_cashflow")
    assert fallback_hint("propose_payment") is None
    assert all(fallback_hint(n) is None or n in TOOL_NAMES for n in TOOL_NAMES)


def test_a_failed_tool_tells_the_model_what_to_offer(ready, bookkeeper):
    tools = ready.make_registry(bookkeeper)
    ready.env.inject_failure("get_book_entries", times=2)

    failed = tools.execute("reconcile_period", SEPTEMBER)
    error = json.loads(failed.content)["error"]

    assert error["code"] == "TOOL_FAILED"
    assert "Do not call this tool again in this turn" in error["message"]
    assert error["what_to_offer"] == fallback_hint("reconcile_period")
    assert json.loads(tools.execute("list_transactions", SEPTEMBER).content)["untrusted_data"]


def test_other_errors_carry_no_fallback_hint(ready, staff):
    denied = json.loads(ready.make_registry(staff).execute("get_balance", {}).content)

    assert "what_to_offer" not in denied["error"]


def test_the_alternative_works_after_a_failed_reconciliation(ready, bookkeeper):
    ready.env.inject_failure("get_book_entries", times=2)
    llm = ScriptedLLM(
        use(("reconcile_period", SEPTEMBER)),
        use(("list_transactions", SEPTEMBER)),
        say("Rekonsiliasi gagal, ini mutasi banknya."),
    )

    result = ready.make_app(llm).chat(bookkeeper, "rekonsiliasi september")

    assert [(t.name, t.error_code) for t in result.reply.tool_calls] == [
        ("reconcile_period", "TOOL_FAILED"),
        ("list_transactions", None),
    ]
    assert result.reply.stop == "answered"


# --- Plain text ------------------------------------------------------------------------------


def test_markdown_markup_is_removed_and_everything_else_is_kept():
    reply = (
        "### 🔴 Duplikat di Bank (3)\n"
        "1. **UD Kopi Pak Budi** — Rp 2.910.000, tanggal 13 Sep (`bt-0180`).\n"
        "\n---\n\n"
        "## Saran\n"
        "- Cek mutasi __asli__ bank.\n"
        "\n\n\n"
        "➡️ **Saran:** catat biaya admin."
    )

    assert plain_text(reply) == (
        "🔴 Duplikat di Bank (3)\n"
        "1. UD Kopi Pak Budi — Rp 2.910.000, tanggal 13 Sep (bt-0180).\n"
        "\n"
        "Saran\n"
        "- Cek mutasi asli bank.\n"
        "\n"
        "➡️ Saran: catat biaya admin."
    )


@pytest.mark.parametrize(
    "text",
    [
        "Saldo kas sekarang Rp 7.500.000.",
        "- satu\n- dua\n1. tiga",
        "2 * 3 = 6 dan 4 * 5 = 20",
        "nama_file_dengan_garis_bawah",
        "Selisih -Rp 5.614 (bank - buku)",
        "",
    ],
)
def test_plain_text_leaves_ordinary_text_alone(text):
    assert plain_text(text) == text


def test_typographic_spaces_and_hyphens_become_plain_characters():
    """Seen with gpt-oss-20b: "5 Okt" written with a narrow no-break space never matched."""
    reply = "Mulai 5\u202fOkt 2026 sampai 15\u00a0Okt, rentang 5\u201115 Okt, Rp\u20097.500.000."

    assert plain_text(reply) == "Mulai 5 Okt 2026 sampai 15 Okt, rentang 5-15 Okt, Rp 7.500.000."


def test_a_masked_account_is_not_mistaken_for_bold_markup():
    """Seen with the real model: "***9589" next to bold labels was turned into "*9589"."""
    reply = (
        "- **Rekening terdaftar:** ***9589\n"
        "- **Saldo setelah bayar:** Rp 5.694.000\n"
        "- Rekening ***2697 (terverifikasi)"
    )

    assert plain_text(reply) == (
        "- Rekening terdaftar: ***9589\n"
        "- Saldo setelah bayar: Rp 5.694.000\n"
        "- Rekening ***2697 (terverifikasi)"
    )
    assert plain_text("**a** dan **b**") == "a dan b"
    assert plain_text("**tebal\nbeda baris**") == "**tebal\nbeda baris**"


def test_italic_markers_are_removed_without_touching_arithmetic_or_masks():
    assert plain_text("*Flagged as possible duplicate — needs checking.*") == (
        "Flagged as possible duplicate — needs checking."
    )
    assert plain_text("ini *penting* ya") == "ini penting ya"
    assert plain_text("2 * 3 = 6 dan 4 * 5 = 20") == "2 * 3 = 6 dan 4 * 5 = 20"
    assert plain_text("ke rekening ***3389") == "ke rekening ***3389"
    assert plain_text("- **Rekening:** ***9589 *terverifikasi*") == (
        "- Rekening: ***9589 terverifikasi"
    )


def test_replies_are_shown_as_plain_text_but_history_keeps_the_original(ready, owner):
    llm = ScriptedLLM(say("**Catatan:** semua aman"), say("ok"))
    app = ready.make_app(llm)

    shown = app.chat(owner, "aman?").reply.text
    app.chat(owner, "lagi")

    assert shown == "Catatan: semua aman"
    assert llm.requests[1]["messages"][1]["content"] == [
        {"type": "text", "text": "**Catatan:** semua aman"}
    ]


# --- Figures must come from a tool or from the person ----------------------------------------

TOOL_RESULT = {
    "role": "user",
    "content": [
        {
            "type": "tool_result",
            "tool_use_id": "t1",
            "content": json.dumps(
                {
                    "untrusted_data": {
                        "amount": "2841000",
                        "lowest_balance": "-6530874.38",
                        "ending": "6441627.50",
                        "message": "Per-payment limit: 5,000,000 IDR",
                        "number": "KOPI/202609/014",
                        "due_date": "2026-10-04",
                    }
                }
            ),
        }
    ],
}


@pytest.mark.parametrize(
    "reply",
    [
        "Tagihan kopi Rp 2.841.000, jatuh tempo 4 Oktober.",
        "The coffee invoice is IDR 2,841,000.",
        "Saldo terendah Rp -6.530.874 dan akhir bulan Rp 6.441.628.",
        "Akhir bulan sekitar Rp 6.441.627.",
        "Batas per pembayaran 5.000.000.",
        "Invoice KOPI/202609/014 (inv-0090) ke rekening ***2697, jatuh tempo 2026-10-04.",
        "Nilainya 2841000.",
        "Kira-kira 2,8 juta, telat 11 hari, ada 3 invoice.",
    ],
)
def test_figures_taken_from_a_tool_result_are_accepted(reply):
    assert ungrounded_figures(reply, [TOOL_RESULT]) == []


@pytest.mark.parametrize(
    ("reply", "unknown"),
    [
        ("PT Sumber Berkah - Rp 4.200.000, jatuh tempo 2026-09-25", ["4.200.000"]),
        ("Totalnya Rp 9.999.999 dan Rp 2.841.000", ["9.999.999"]),
        ("The total is 1,234,567.", ["1,234,567"]),
        ("Saldonya 7500000 ya", ["7500000"]),
    ],
)
def test_figures_from_nowhere_are_caught(reply, unknown):
    assert ungrounded_figures(reply, [TOOL_RESULT]) == unknown


@pytest.mark.parametrize(
    ("said", "reply"),
    [
        ("15 ribu, tanggal 30 september", "Dicatat Rp 15.000."),
        ("bayar yang 860rb dong", "Yang Rp 860.000 ya."),
        ("tagihan kemasan yang 1,2 juta", "Sekitar Rp 1.200.000."),
        ("batasnya 5jt aja", "Batas Rp 5.000.000."),
        ("catat 25000 buat parkir", "Dicatat Rp 25.000."),
        ("transfer 2.350.000 itu dari siapa?", "Transfer Rp 2.350.000 itu belum jelas."),
    ],
)
def test_figures_the_person_typed_are_accepted(said, reply):
    assert ungrounded_figures(reply, [{"role": "user", "content": said}]) == []


def test_what_the_model_said_earlier_does_not_make_a_figure_known():
    history = [
        {"role": "user", "content": "halo"},
        {"role": "assistant", "content": "Tagihan Rp 4.200.000"},
        {"role": "assistant", "content": [{"type": "text", "text": "Rp 4.200.000"}]},
        {"role": "user", "content": "[automatic check] Your reply states 4.200.000 ..."},
    ]

    assert ungrounded_figures("Jadi Rp 4.200.000", history) == ["4.200.000"]


# --- Language --------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "language"),
    [
        ("Which supplier invoices are overdue right now?", "en"),
        ("Please reconcile September and tell me what does not match.", "en"),
        ("kas gue aman ga sampe akhir bulan?", "id"),
        ("tolong cek yg ga cocok sama mutasi bank", "id"),
        ("Ada 3 invoice yang overdue per hari ini, mau bayar yang mana?", "id"),
        ("Three supplier invoices are overdue: Layanan Listrik is 11 days late.", "en"),
        ("pay the gula invoice yang 860rb dong", None),
        ("halo", None),
        ("ok", None),
        ("", None),
        ("KOPI/202609/014 Rp 2.841.000", None),
    ],
)
def test_language_is_guessed_only_when_it_is_clear(text, language):
    assert guess_language(text) == language


def test_reply_problems_names_each_problem_once():
    english = "Which supplier invoices are overdue right now?"
    indonesian_reply = "Ada 3 invoice yang overdue, totalnya Rp 4.200.000, mau bayar yang mana?"

    problems = reply_problems(english, indonesian_reply, [{"role": "user", "content": english}])

    assert len(problems) == 2
    assert "4.200.000" in problems[0]
    assert "English" in problems[1]
    assert reply_problems(english, "Three invoices are overdue.", []) == []
    assert reply_problems("saldo berapa?", "Saldo belum bisa saya cek.", []) == []


# --- Confirming a reading is left to the model ------------------------------------------------


@pytest.mark.parametrize(
    ("said", "reply"),
    [
        (
            "bayar tagihan kemasan yang 1,2 juta",
            "Yang 1,2 juta cocoknya KMS/202609/008 Rp 1.242.000. Mau saya bayarin yang itu?",
        ),
        ("bayar tagihan kemasan yang 1,2 juta", "Yang KMS/202609/008 Rp 1.242.000, betul?"),
        (
            "please pay the packaging invoice, the one for about 1.2 million",
            "It matches invoice KMS/202609/008 for Rp 1,242,000. Shall I go ahead and pay it?",
        ),
    ],
)
def test_a_confirming_question_before_paying_is_never_sent_back(said, reply):
    """Asking before paying is the safe direction, so no check pushes the model past it."""
    history = [
        {"role": "user", "content": said},
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "t1",
                    "content": '{"untrusted_data": {"amount": "1242000"}}',
                }
            ],
        },
    ]

    assert reply_problems(said, reply, history) == []


# --- One automatic correction per turn -------------------------------------------------------


def test_an_answer_with_made_up_figures_is_sent_back_once_and_never_shown(ready, bookkeeper):
    made_up = say("Ada tagihan PT Sumber Berkah Rp 4.200.000. Yang mana?")
    llm = ScriptedLLM(
        made_up,
        use(("list_invoices", {"kind": "payable", "status": "open", "due_before": None})),
        say("Yang mana? UD Kopi Pak Budi Rp 2.841.000 atau Depot Air Tirta Rp 225.000?"),
    )

    result = ready.make_app(llm).chat(bookkeeper, "bayar yang biasa itu")

    assert result.reply.text == (
        "Yang mana? UD Kopi Pak Budi Rp 2.841.000 atau Depot Air Tirta Rp 225.000?"
    )
    assert result.reply.corrected is True
    assert "4.200.000" not in result.reply.text
    check = llm.requests[1]["messages"][-1]
    assert check["role"] == "user"
    assert check["content"].startswith("[automatic check]")
    assert "4.200.000" in check["content"]
    assert llm.requests[1]["messages"][-2] == {"role": "assistant", "content": made_up.content}


def test_a_second_answer_that_still_has_unknown_figures_carries_a_visible_note(ready, bookkeeper):
    llm = ScriptedLLM(say("Tagihan Rp 4.200.000."), say("Tagihan Rp 4.300.000."))

    result = ready.make_app(llm).chat(bookkeeper, "berapa tagihannya?")

    assert result.reply.text.startswith("Tagihan Rp 4.300.000.")
    assert "tidak bisa saya cocokkan dengan data" in result.reply.text
    assert "please double-check: 4.300.000" in result.reply.text
    assert result.reply.corrected is True
    assert len(llm.requests) == 2


def test_an_english_question_answered_in_indonesian_is_sent_back(ready, owner):
    llm = ScriptedLLM(
        say("Ada tiga invoice yang sudah jatuh tempo dan belum dibayar."),
        say("Three supplier invoices are overdue and have not been paid."),
    )

    result = ready.make_app(llm).chat(owner, "Which supplier invoices are overdue right now?")

    assert result.reply.text == "Three supplier invoices are overdue and have not been paid."
    assert "Write your whole reply in English" in llm.requests[1]["messages"][-1]["content"]


def test_a_good_answer_is_not_sent_back(ready, owner):
    llm = ScriptedLLM(use(("get_balance", {})), say("Saldo Rp 7.500.000."))

    result = ready.make_app(llm).chat(owner, "saldo berapa?")

    assert result.reply.corrected is False
    assert len(llm.requests) == 2


def test_the_check_message_does_not_count_as_something_the_person_said(ready, bookkeeper):
    llm = ScriptedLLM(say("Tagihan Rp 4.200.000."), say("Maaf, saya cek dulu ya."), say("ok"))
    app = ready.make_app(llm)

    app.chat(bookkeeper, "berapa?")
    app.chat(bookkeeper, "eh salah, yang lain")

    typed = [
        m["content"]
        for m in llm.requests[2]["messages"]
        if m["role"] == "user" and isinstance(m["content"], str)
    ]
    assert [t for t in typed if not t.startswith("[automatic check]")] == [
        "berapa?",
        "eh salah, yang lain",
    ]
