"""Boundary and rounding behaviour of the money logic, locked as it is today.

Covers the policy limits, the mandate's own validation, the forecast, the recommendations and
the reconciliation tolerances at 0, exactly on a limit, one unit either side, negative and very
large values.
"""

import datetime as dt
from decimal import Decimal

import pytest
from pydantic import ValidationError

from test_forecast import START, balances, daily, idr, monthly, on
from test_forecast import invoice as fc_invoice
from test_policy import (
    BOOKKEEPER,
    OWNER,
    code,
    decide,
    invoice,
    mandate,
    supplier,
    warnings,
)
from test_policy import (
    idr as pidr,
)
from test_reconcile import day, entry, tx
from wali.finance.forecast import detect_recurring, forecast
from wali.finance.recommend import recommend
from wali.finance.reconcile import ReconcileConfig, reconcile
from wali.guard.mandate import Limits, MandateTerms, RoleAuthority
from wali.guard.policy import PaymentTerms, amount_above_usual
from wali.models import BookEntry, Invoice, Money, NewBookEntry, RecurringItem

HUGE = Decimal("9" * 20)


def clean(amount, **view):
    """A payment from a supplier whose average is the amount itself, so only limits matter."""
    return decide(
        OWNER,
        invoice=invoice(amount=amount),
        supplier=supplier(avg_invoice_amount=Decimal(amount)),
        **view,
    )


# --- Policy: per-payment limit ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "outcome"),
    [
        (4_999_999, "confirm"),
        (5_000_000, "confirm"),
        (5_000_001, "OVER_PAYMENT_LIMIT"),
    ],
)
def test_the_per_payment_limit_is_inclusive_and_one_rupiah_over_is_denied(amount, outcome):
    decision = clean(amount, balance=pidr(50_000_000))

    if outcome == "confirm":
        assert "ABOVE_CONFIRM_THRESHOLD" in warnings(decision)
    else:
        assert code(decision) == outcome


# --- Policy: weekly limit --------------------------------------------------------------------


@pytest.mark.parametrize(
    ("already_paid", "allowed"),
    [(14_499_999, True), (14_500_000, True), (14_500_001, False)],
)
def test_the_weekly_limit_counts_what_was_paid_plus_this_payment(already_paid, allowed):
    decision = decide(paid_last_7_days=Decimal(already_paid))

    if allowed:
        assert type(decision).__name__ == "Allow"
    else:
        assert code(decision) == "OVER_WEEK_LIMIT"


def test_a_week_already_at_the_limit_refuses_even_the_smallest_payment():
    decision = decide(
        invoice=invoice(amount=1), supplier=supplier(avg_invoice_amount=1),
        paid_last_7_days=Decimal(15_000_000),
    )  # fmt: skip

    assert code(decision) == "OVER_WEEK_LIMIT"


# --- Policy: confirm_above -------------------------------------------------------------------


@pytest.mark.parametrize(
    ("amount", "needs_owner"),
    [(999_999, False), (1_000_000, False), (1_000_001, True)],
)
def test_confirm_above_is_exclusive(amount, needs_owner):
    decision = decide(
        invoice=invoice(amount=amount), supplier=supplier(avg_invoice_amount=Decimal(amount))
    )

    assert (type(decision).__name__ == "NeedsConfirmation") is needs_owner


def test_confirm_above_zero_makes_every_payment_wait_for_the_owner():
    signed = mandate(confirm_above=pidr(0))

    decision = decide(signed=signed, invoice=invoice(amount=1), supplier=supplier(
        avg_invoice_amount=1))  # fmt: skip

    assert warnings(decision) == {"ABOVE_CONFIRM_THRESHOLD"}


# --- Policy: balance and cash buffer ---------------------------------------------------------


@pytest.mark.parametrize(
    ("balance", "buffer_warning"),
    [(3_499_999, True), (3_500_000, False), (3_500_001, False)],
)
def test_the_cash_buffer_warns_only_when_the_balance_after_paying_is_below_it(
    balance, buffer_warning
):
    decision = decide(balance=pidr(balance))

    if buffer_warning:
        assert warnings(decision) == {"BELOW_CASH_BUFFER"}
    else:
        assert type(decision).__name__ == "Allow"


def test_a_balance_that_covers_the_payment_exactly_is_a_warning_not_a_denial():
    decision = decide(balance=pidr(500_000))

    assert warnings(decision) == {"BELOW_CASH_BUFFER"}
    assert decision.balance_after == 0


def test_a_balance_one_unit_short_is_denied_with_the_cash_buffer_code():
    assert code(decide(balance=pidr(499_999))) == "BELOW_CASH_BUFFER"


def test_a_zero_balance_denies_any_payment():
    assert code(decide(balance=pidr(0))) == "BELOW_CASH_BUFFER"


def test_a_negative_balance_denies_any_payment():
    assert code(decide(balance=pidr(-1))) == "BELOW_CASH_BUFFER"


def test_a_zero_buffer_never_warns_while_the_balance_covers_the_payment():
    signed = mandate(min_cash_buffer=pidr(0))

    assert type(decide(signed=signed, balance=pidr(500_000))).__name__ == "Allow"


# --- Policy: 30 percent over the supplier's average ------------------------------------------


@pytest.mark.parametrize(
    ("amount", "average", "unusual"),
    [
        (130, 100, False),
        (131, 100, True),
        (129, 100, False),
        (1, 1, False),
        (2, 1, True),
        (650_000, 500_000, False),
        (650_001, 500_000, True),
    ],
)
def test_the_unusual_amount_threshold_is_exactly_130_percent(amount, average, unusual):
    result = amount_above_usual(
        invoice(amount=amount), supplier(avg_invoice_amount=Decimal(average))
    )

    assert result is unusual


def test_an_average_with_cents_is_compared_without_rounding():
    average = Decimal("100.10")
    just_at = average * Decimal("1.3")

    assert not amount_above_usual(invoice(amount=just_at), supplier(avg_invoice_amount=average))
    assert amount_above_usual(
        invoice(amount=just_at + Decimal("0.01")), supplier(avg_invoice_amount=average)
    )


# --- Policy: rate limit ----------------------------------------------------------------------


@pytest.mark.parametrize(("seen", "limited"), [(9, False), (10, True), (11, True)])
def test_the_hourly_proposal_limit_denies_from_the_limit_itself(seen, limited):
    decision = decide(proposals_last_hour=seen)

    assert (type(decision).__name__ == "Deny") is limited


# --- Policy: role limit ----------------------------------------------------------------------


@pytest.mark.parametrize(("amount", "allowed"), [(4_999_999, True), (5_000_000, True)])
def test_a_role_limit_equal_to_the_payment_limit_allows_up_to_it(amount, allowed):
    decision = decide(
        BOOKKEEPER,
        invoice=invoice(amount=amount),
        supplier=supplier(avg_invoice_amount=Decimal(amount)),
        balance=pidr(50_000_000),
    )

    assert type(decision).__name__ == "NeedsConfirmation"


def test_one_unit_above_a_lower_role_limit_is_refused_for_the_bookkeeper_only():
    signed = mandate(
        role_authority={
            "owner": RoleAuthority(can_propose=True, can_confirm=True),
            "bookkeeper": RoleAuthority(can_propose=True, max_propose=Decimal(1_000_000)),
            "staff": RoleAuthority(),
        }
    )
    over = {
        "invoice": invoice(amount=1_000_001),
        "supplier": supplier(avg_invoice_amount=1_000_001),
    }

    assert code(decide(BOOKKEEPER, signed=signed, **over)) == "ROLE_NOT_ALLOWED"
    assert type(decide(OWNER, signed=signed, **over)).__name__ == "NeedsConfirmation"


# --- Policy: amounts with cents and very large amounts ---------------------------------------


def test_fractional_amounts_are_compared_exactly_with_the_limit():
    just_over = Decimal("5000000.01")

    decision = clean(just_over, balance=pidr(50_000_000))

    assert code(decision) == "OVER_PAYMENT_LIMIT"


def test_fractional_balance_after_is_exact_decimal_arithmetic():
    decision = decide(
        invoice=invoice(amount=Decimal("0.10")),
        supplier=supplier(avg_invoice_amount=Decimal("0.10")),
        balance=pidr(Decimal("0.30")),
        signed=mandate(min_cash_buffer=pidr(0)),
    )

    assert decision.balance_after == Decimal("0.20")


def test_a_very_large_invoice_is_over_the_limit_not_a_crash():
    decision = clean(HUGE, balance=Money(amount=HUGE * 2, currency="IDR"))

    assert code(decision) == "OVER_PAYMENT_LIMIT"


def test_a_very_large_weekly_total_is_over_the_weekly_limit_not_a_crash():
    assert code(decide(paid_last_7_days=HUGE)) == "OVER_WEEK_LIMIT"


@pytest.mark.parametrize("amount", ["0", "-1", "-0.01"])
def test_an_invoice_must_have_an_amount_above_zero(amount):
    with pytest.raises(ValidationError):
        invoice(amount=Decimal(amount))


# --- Payment terms digest --------------------------------------------------------------------


def _terms(amount) -> PaymentTerms:
    return PaymentTerms(
        business_id="biz-1",
        mandate_id="m-1",
        invoice_id="inv-1",
        supplier_id="sup-a",
        amount=Decimal(amount),
        currency="IDR",
        destination_account="SIM-1",
        proposed_by="u-1",
    )


@pytest.mark.parametrize("same", ["500000.0", "500000.00", "5E+5", "0500000"])
def test_the_digest_treats_every_spelling_of_one_amount_alike(same):
    assert _terms(same).digest() == _terms("500000").digest()


def test_the_digest_tells_one_cent_apart():
    assert _terms("500000.01").digest() != _terms("500000").digest()


def test_the_digest_of_a_very_large_amount_is_exact():
    assert _terms(HUGE).digest() != _terms("1" + "0" * 20).digest()


# --- Mandate validation ----------------------------------------------------------------------


def _terms_with(**changes) -> MandateTerms:
    signed = mandate()
    fields = signed.model_dump(exclude={"signature"})
    fields.update(changes)
    return MandateTerms(**fields)


def test_per_payment_equal_to_per_week_is_a_valid_mandate():
    _terms_with(limits=Limits(per_payment=pidr(15_000_000), per_week=pidr(15_000_000)),
                role_authority=mandate().role_authority)  # fmt: skip


def test_per_payment_one_unit_over_per_week_is_refused():
    with pytest.raises(ValidationError, match="cannot exceed the weekly limit"):
        _terms_with(limits=Limits(per_payment=pidr(15_000_001), per_week=pidr(15_000_000)))


@pytest.mark.parametrize("field", ["confirm_above", "min_cash_buffer"])
def test_zero_is_allowed_for_confirm_above_and_the_buffer_but_negative_is_not(field):
    _terms_with(**{field: pidr(0)})

    with pytest.raises(ValidationError, match="cannot be negative"):
        _terms_with(**{field: pidr(-1)})


@pytest.mark.parametrize("limit", ["per_payment", "per_week"])
def test_a_zero_limit_is_refused(limit):
    values = {"per_payment": pidr(1), "per_week": pidr(15_000_000)}
    values[limit] = pidr(0)

    with pytest.raises(ValidationError, match="greater than zero"):
        _terms_with(limits=Limits(**values))


def test_mixed_currencies_are_refused():
    with pytest.raises(ValidationError, match="one currency"):
        _terms_with(min_cash_buffer=Money(amount=Decimal(1), currency="USD"))


def test_a_role_limit_equal_to_the_payment_limit_is_valid_and_one_over_is_not():
    for limit, valid in ((5_000_000, True), (5_000_001, False)):
        authority = {
            "owner": RoleAuthority(can_propose=True, can_confirm=True),
            "bookkeeper": RoleAuthority(can_propose=True, max_propose=Decimal(limit)),
            "staff": RoleAuthority(),
        }
        if valid:
            _terms_with(role_authority=authority)
        else:
            with pytest.raises(ValidationError, match="cannot exceed the per-payment limit"):
                _terms_with(role_authority=authority)


def test_a_zero_role_limit_is_refused_by_the_model():
    with pytest.raises(ValidationError):
        RoleAuthority(can_propose=True, max_propose=Decimal(0))


# --- Forecast --------------------------------------------------------------------------------


def test_a_forecast_with_cents_stays_exact():
    result = forecast(
        idr("0.10"), [], [fc_invoice("r", "receivable", "0.20", on(1))], [], 3, start=START
    )

    assert [d.balance for d in result.daily_balance] == [
        Decimal("0.10"), Decimal("0.30"), Decimal("0.30"),
    ]  # fmt: skip


def test_many_small_flows_accumulate_without_float_drift():
    payables = [fc_invoice(f"p{n}", "payable", "0.10", on(1)) for n in range(30)]

    result = forecast(idr("3.00"), payables, [], [], 2, start=START)

    assert result.daily_balance[1].balance == Decimal("0.00")
    assert result.shortfall_days == []


def test_a_balance_of_exactly_the_threshold_is_not_a_shortfall():
    result = forecast(
        idr(1000), [fc_invoice("p", "payable", 400, on(1))], [], [], 3, start=START,
        shortfall_below=Decimal(600),
    )  # fmt: skip

    assert result.shortfall_days == []
    assert forecast(
        idr(1000), [fc_invoice("p", "payable", 401, on(1))], [], [], 3, start=START,
        shortfall_below=Decimal(600),
    ).shortfall_days == [on(1), on(2)]  # fmt: skip


def test_a_negative_opening_balance_is_forecast_without_error():
    result = forecast(idr(-500), [], [], [daily(100)], 3, start=START)

    assert balances(result) == [-400, -300, -200]
    assert result.lowest_date == START


def test_a_zero_balance_with_nothing_happening_is_flat_and_not_a_shortfall_by_default():
    result = forecast(idr(0), [], [], [], 2, start=START)

    assert balances(result) == [0, 0]
    assert result.shortfall_days == []


def test_horizon_limits_are_inclusive():
    assert len(forecast(idr(0), [], [], [], 1, start=START).daily_balance) == 1
    assert len(forecast(idr(0), [], [], [], 366, start=START).daily_balance) == 366
    with pytest.raises(ValueError):
        forecast(idr(0), [], [], [], 367, start=START)
    with pytest.raises(ValueError):
        forecast(idr(0), [], [], [], 0, start=START)


def test_very_large_amounts_do_not_overflow_or_lose_digits():
    result = forecast(
        Money(amount=HUGE, currency="IDR"),
        [fc_invoice("p", "payable", 1, on(0))], [], [], 1, start=START,
    )  # fmt: skip

    assert result.daily_balance[0].balance == HUGE - 1


def test_a_payable_due_on_the_start_day_and_one_due_the_day_before_both_leave_on_day_one():
    payables = [fc_invoice("a", "payable", 10, on(0)), fc_invoice("b", "payable", 20, on(-1))]

    assert balances(forecast(idr(100), payables, [], [], 2, start=START)) == [70, 70]


def test_a_receivable_due_on_the_start_day_counts_and_the_day_before_does_not():
    on_day = fc_invoice("a", "receivable", 10, on(0))
    late = fc_invoice("b", "receivable", 20, on(-1))

    assert balances(forecast(idr(0), [], [on_day, late], [], 1, start=START)) == [10]


def test_a_monthly_item_on_the_29th_falls_on_the_28th_in_a_common_february():
    result = forecast(idr(0), [], [], [monthly(100, 29)], 3, start=dt.date(2027, 2, 27))

    assert balances(result) == [0, -100, -100]


def test_a_monthly_item_on_the_29th_falls_on_the_29th_in_a_leap_february():
    result = forecast(idr(0), [], [], [monthly(100, 29)], 3, start=dt.date(2028, 2, 27))

    assert balances(result) == [0, 0, -100]


# --- detect_recurring rounding ---------------------------------------------------------------


def _entry(id, on_day, amount, category="sales", direction="in"):
    return BookEntry(
        id=id, date=on_day, amount=Decimal(amount), direction=direction,
        category=category, description="",
    )  # fmt: skip


@pytest.mark.parametrize(
    ("total", "average"), [("0.05", "0.01"), ("0.09", "0.02"), ("0.07", "0.02")]
)
def test_a_daily_average_is_rounded_to_the_cent_half_to_even(total, average):
    # Over 4 calendar days: 0.05 / 4 = 0.0125, 0.09 / 4 = 0.0225, 0.07 / 4 = 0.0175.
    as_of = dt.date(2026, 10, 4)
    share = Decimal(total) / 4
    entries = [_entry(f"a{n}", dt.date(2026, 10, n), share) for n in (1, 2, 3, 4)]

    (item,) = detect_recurring(entries, as_of)

    assert item.amount == Decimal(average)


def test_a_daily_group_whose_average_rounds_to_zero_is_dropped():
    as_of = dt.date(2026, 10, 4)
    entries = [_entry(f"a{n}", dt.date(2026, 10, n), "0.001") for n in (1, 2, 3, 4)]

    assert detect_recurring(entries, as_of) == []


def test_a_group_seen_on_exactly_the_share_of_days_is_daily():
    as_of = dt.date(2026, 10, 10)  # span 10 days, share 0.4 -> 4 active days needed
    four = [_entry(f"a{n}", dt.date(2026, 10, n), 100) for n in (1, 4, 7, 10)]
    three = four[:3]  # with as_of moved to the 7th the span is 7 days: 3 / 7 > 0.4
    assert detect_recurring(four, as_of)[0].frequency == "daily"
    assert detect_recurring(three, dt.date(2026, 10, 7))[0].frequency == "daily"


def test_a_group_one_active_day_short_of_the_share_is_not_daily():
    as_of = dt.date(2026, 10, 10)
    three = [_entry(f"a{n}", dt.date(2026, 10, n), 100) for n in (1, 5, 10)]

    assert detect_recurring(three, as_of) == []


def test_lookback_is_exclusive_at_the_far_end_and_inclusive_today():
    as_of = dt.date(2026, 10, 10)
    edge = _entry("old", as_of - dt.timedelta(days=90), 100)
    today = _entry("now", as_of, 100)

    assert detect_recurring([edge], as_of) == []
    assert detect_recurring([today], as_of)[0].amount == Decimal("100.00")


def test_a_future_entry_is_ignored():
    assert detect_recurring([_entry("f", dt.date(2026, 10, 11), 100)], dt.date(2026, 10, 10)) == []


def test_lookback_below_one_is_refused():
    with pytest.raises(ValueError):
        detect_recurring([], dt.date(2026, 10, 10), lookback_days=0)


def test_monthly_average_of_uneven_months_is_rounded_to_the_cent():
    entries = [
        _entry("m1", dt.date(2026, 8, 25), "100.00", "rent", "out"),
        _entry("m2", dt.date(2026, 9, 25), "100.01", "rent", "out"),
    ]

    (item,) = detect_recurring(entries, dt.date(2026, 10, 1))

    assert (item.frequency, item.day_of_month) == ("monthly", 25)
    assert item.amount == Decimal("100.00")  # 100.005 rounds half-even to 100.00


def test_monthly_days_one_apart_use_the_later_day_and_two_apart_are_dropped():
    one_apart = [
        _entry("m1", dt.date(2026, 8, 25), 100, "rent", "out"),
        _entry("m2", dt.date(2026, 9, 26), 100, "rent", "out"),
    ]
    two_apart = [one_apart[0], _entry("m3", dt.date(2026, 9, 27), 100, "rent", "out")]

    assert detect_recurring(one_apart, dt.date(2026, 10, 1))[0].day_of_month == 26
    assert detect_recurring(two_apart, dt.date(2026, 10, 1)) == []


# --- Recommendations -------------------------------------------------------------------------


def _recs(balance, payables, receivables, **kwargs):
    result = forecast(idr(balance), payables, receivables, [], 14, start=START,
                      shortfall_below=Decimal(0))  # fmt: skip
    return recommend(result, payables, receivables, **kwargs)


def test_split_payment_halves_an_odd_amount_exactly():
    payables = [fc_invoice("p", "payable", 101, on(2), late_fee=True)]
    arrives_after_the_delay = [fc_invoice("r", "receivable", 1000, on(9))]

    (split,) = [
        r for r in _recs(50, payables, arrives_after_the_delay) if r.kind == "split_payment"
    ]

    assert split.amount == Decimal(101)
    assert split.effect_on_lowest_balance == Decimal("50.5")


def test_a_split_that_gains_nothing_is_not_offered():
    payables = [fc_invoice("p", "payable", 100, on(2), late_fee=True)]

    assert _recs(1_000_000, payables, []) == []


def test_collect_in_days_zero_adds_the_money_from_the_first_day():
    late = [fc_invoice("r", "receivable", 100, on(-3))]
    payables = [fc_invoice("p", "payable", 150, on(0))]

    (chase,) = _recs(100, payables, late, collect_in_days=0)

    assert chase.kind == "chase_receivable"
    assert chase.effect_on_lowest_balance == Decimal(100)
    assert chase.days_overdue == 3


def test_a_receivable_due_today_is_not_overdue_and_not_chased():
    assert _recs(100, [], [fc_invoice("r", "receivable", 100, on(0))]) == []


def test_delay_days_below_one_and_negative_collect_days_are_refused():
    result = forecast(idr(0), [], [], [], 2, start=START)

    for kwargs in ({"delay_days": 0}, {"collect_in_days": -1}):
        with pytest.raises(ValueError):
            recommend(result, [], [], **kwargs)


def test_a_payable_due_on_the_lowest_day_is_a_candidate_and_one_after_it_is_not():
    on_low = fc_invoice("a", "payable", 100, on(3))
    after = fc_invoice("b", "payable", 10, on(4))
    recovery = fc_invoice("r", "receivable", 200, on(4))

    kinds = [(r.kind, r.invoice_id) for r in _recs(50, [on_low, after], [recovery])]

    assert ("delay_payable", "a") in kinds
    assert ("delay_payable", "b") not in kinds


def test_a_delay_does_not_count_as_help_when_the_balance_stays_low_afterwards():
    payables = [fc_invoice("a", "payable", 100, on(3))]

    assert _recs(50, payables, []) == []


# --- Reconciliation tolerances ---------------------------------------------------------------


def _pair(bank_amount, book_amount, **config):
    return reconcile(
        [tx("b", day(10), bank_amount)],
        [entry("e", day(10), book_amount)],
        ReconcileConfig(**config) if config else None,
    )


def test_a_difference_of_exactly_five_percent_of_the_larger_amount_is_a_mismatch():
    report = _pair(950, 1000)

    assert [m.difference for m in report.amount_mismatches] == [Decimal(-50)]


def test_a_difference_just_over_five_percent_is_two_unmatched_items():
    report = _pair("949.99", 1000)

    assert report.amount_mismatches == []
    assert len(report.unmatched_bank) == len(report.unmatched_books) == 1


def test_the_ratio_is_taken_against_the_larger_amount_in_both_directions():
    assert len(_pair(1000, 950).amount_mismatches) == 1
    assert _pair(1000, "949.99").amount_mismatches == []


def test_a_tolerance_equal_to_the_difference_matches_and_one_cent_less_does_not():
    assert _pair(1005, 1000, amount_tolerance=Decimal(5)).matched
    report = _pair(1005, 1000, amount_tolerance=Decimal("4.99"))

    assert not report.matched and len(report.amount_mismatches) == 1


def test_a_mismatch_ratio_of_zero_turns_mismatches_into_unmatched_items():
    report = _pair(1001, 1000, mismatch_max_ratio=Decimal(0))

    assert report.amount_mismatches == []
    assert len(report.unmatched_bank) == 1


@pytest.mark.parametrize(("offset", "matched"), [(2, True), (3, True), (4, False)])
def test_the_default_date_window_is_three_days_inclusive(offset, matched):
    report = reconcile([tx("b", day(10), 100)], [entry("e", day(10 + offset), 100)])

    assert bool(report.matched) is matched


def test_a_zero_day_window_matches_only_the_same_day():
    config = ReconcileConfig(date_window_days=0)

    assert reconcile([tx("b", day(10), 100)], [entry("e", day(10), 100)], config).matched
    assert not reconcile([tx("b", day(10), 100)], [entry("e", day(11), 100)], config).matched


def test_cents_and_very_large_amounts_match_exactly():
    report = reconcile(
        [tx("b1", day(10), "0.01"), tx("b2", day(10), HUGE)],
        [entry("e1", day(10), "0.01"), entry("e2", day(10), HUGE)],
    )

    assert {(m.bank_id, m.book_id) for m in report.matched} == {("b1", "e1"), ("b2", "e2")}


def test_a_period_includes_both_boundary_days():
    bank = [tx("b1", day(1), 100), tx("b2", day(30), 200), tx("b3", day(31, 8), 300)]

    report = reconcile(bank, [], period=(day(1), day(30)))

    assert sorted(t.id for t in report.unmatched_bank) == ["b1", "b2"]


# --- Money fields on the shared models -------------------------------------------------------


@pytest.mark.parametrize("amount", ["0", "-1"])
def test_bank_and_book_amounts_must_be_above_zero(amount):
    with pytest.raises(ValidationError):
        tx("b", day(1), amount)
    with pytest.raises(ValidationError):
        entry("e", day(1), amount)
    with pytest.raises(ValidationError):
        NewBookEntry(
            date=day(1), amount=Decimal(amount), direction="in", category="c", description=""
        )


def test_a_recurring_item_must_have_an_amount_above_zero():
    with pytest.raises(ValidationError):
        RecurringItem(label="x", amount=Decimal(0), direction="in", frequency="daily")


@pytest.mark.parametrize("currency", ["idr", "ID", "IDRR", "", "12A"])
def test_currency_must_be_three_capital_letters(currency):
    with pytest.raises(ValidationError):
        Money(amount=Decimal(1), currency=currency)
    with pytest.raises(ValidationError):
        Invoice(
            id="i",
            kind="payable",
            counterparty_id="c",
            counterparty_name="c",
            number="n",
            amount=Decimal(1),
            currency=currency,
            issue_date=dt.date(2026, 1, 1),
            due_date=dt.date(2026, 1, 2),
            status="open",
        )
