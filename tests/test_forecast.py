import datetime as dt
from decimal import Decimal

import pytest

from wali.finance.forecast import detect_recurring, forecast
from wali.models import BookEntry, Invoice, Money, RecurringItem

START = dt.date(2026, 10, 1)
FAR_PAST = dt.date(2000, 1, 1)
FAR_FUTURE = dt.date(2100, 1, 1)


def idr(amount) -> Money:
    return Money(amount=Decimal(amount), currency="IDR")


def invoice(id, kind, amount, due, status="open", late_fee=False, currency="IDR") -> Invoice:
    return Invoice(
        id=id,
        kind=kind,
        counterparty_id="cp-1",
        counterparty_name="Counterparty",
        number=f"N-{id}",
        amount=Decimal(amount),
        currency=currency,
        issue_date=due - dt.timedelta(days=7),
        due_date=due,
        status=status,
        late_fee_bearing=late_fee,
    )


def on(offset: int) -> dt.date:
    return START + dt.timedelta(days=offset)


def balances(result) -> list[int]:
    return [int(day.balance) for day in result.daily_balance]


def daily(amount, direction="in", label="sales") -> RecurringItem:
    return RecurringItem(
        label=label, amount=Decimal(amount), direction=direction, frequency="daily"
    )


def monthly(amount, day_of_month, direction="out", label="payroll") -> RecurringItem:
    return RecurringItem(
        label=label,
        amount=Decimal(amount),
        direction=direction,
        frequency="monthly",
        day_of_month=day_of_month,
    )


# --- forecast --------------------------------------------------------------------------------


def test_nothing_due_keeps_the_balance_flat():
    result = forecast(idr(1000), [], [], [], 5, start=START)

    assert balances(result) == [1000] * 5
    assert [d.date for d in result.daily_balance] == [on(n) for n in range(5)]
    assert (result.lowest_balance, result.lowest_date) == (Decimal(1000), START)
    assert result.shortfall_days == []
    assert result.horizon_days == 5


def test_payables_leave_on_their_due_date_and_overdue_ones_on_the_first_day():
    payables = [
        invoice("p1", "payable", 300, on(2)),
        invoice("p2", "payable", 100, on(-5)),
        invoice("p3", "payable", 999, on(4)),
    ]
    result = forecast(idr(1000), payables, [], [], 4, start=START)

    assert balances(result) == [900, 900, 600, 600]


def test_receivables_arrive_on_their_due_date_and_overdue_ones_are_not_counted():
    receivables = [
        invoice("r1", "receivable", 300, on(1)),
        invoice("r2", "receivable", 5000, on(-1)),
        invoice("r3", "receivable", 50, on(0)),
    ]
    result = forecast(idr(1000), [], receivables, [], 3, start=START)

    assert balances(result) == [1050, 1350, 1350]


def test_invoices_that_are_not_open_are_ignored():
    payables = [
        invoice("p1", "payable", 300, on(1), status="paid"),
        invoice("p2", "payable", 300, on(1), status="void"),
    ]
    receivables = [invoice("r1", "receivable", 300, on(1), status="paid")]

    assert balances(forecast(idr(1000), payables, receivables, [], 3, start=START)) == [1000] * 3


def test_daily_items_apply_every_day_including_the_first():
    result = forecast(idr(1000), [], [], [daily(100), daily(30, "out", "supplies")], 3, start=START)

    assert balances(result) == [1070, 1140, 1210]


def test_monthly_items_apply_on_their_day():
    result = forecast(idr(1000), [], [], [monthly(400, 3)], 5, start=START)

    assert balances(result) == [1000, 1000, 600, 600, 600]


@pytest.mark.parametrize(
    ("start", "expected_day"),
    [
        (dt.date(2026, 10, 25), dt.date(2026, 10, 31)),
        (dt.date(2026, 11, 25), dt.date(2026, 11, 30)),
        (dt.date(2027, 2, 20), dt.date(2027, 2, 28)),
        (dt.date(2028, 2, 20), dt.date(2028, 2, 29)),
    ],
)
def test_a_monthly_item_on_day_31_falls_on_the_last_day_of_shorter_months(start, expected_day):
    result = forecast(idr(1000), [], [], [monthly(400, 31)], 10, start=start)

    dropped_on = next(d.date for d in result.daily_balance if d.balance == 600)
    assert dropped_on == expected_day
    assert result.daily_balance[-1].balance == 600


def test_lowest_point_is_the_first_day_that_reaches_the_minimum():
    payables = [invoice("p1", "payable", 500, on(1))]
    receivables = [invoice("r1", "receivable", 500, on(3))]
    result = forecast(
        idr(1000), payables, receivables, [monthly(500, 5, label="rent")], 6, start=START
    )

    assert balances(result) == [1000, 500, 500, 1000, 500, 500]
    assert (result.lowest_balance, result.lowest_date) == (Decimal(500), on(1))


def test_shortfall_days_use_the_requested_threshold():
    payables = [invoice("p1", "payable", 1200, on(1))]
    receivables = [invoice("r1", "receivable", 900, on(3))]

    below_zero = forecast(idr(1000), payables, receivables, [], 5, start=START)
    below_buffer = forecast(
        idr(1000), payables, receivables, [], 5, start=START, shortfall_below=Decimal(800)
    )

    assert balances(below_zero) == [1000, -200, -200, 700, 700]
    assert below_zero.shortfall_days == [on(1), on(2)]
    assert below_buffer.shortfall_days == [on(1), on(2), on(3), on(4)]


@pytest.mark.parametrize("horizon", [0, -1, 367])
def test_horizon_must_be_sensible(horizon):
    with pytest.raises(ValueError, match="horizon_days"):
        forecast(idr(1000), [], [], [], horizon, start=START)


def test_wrong_kind_or_currency_is_refused():
    with pytest.raises(ValueError, match="not a payable"):
        forecast(idr(1000), [invoice("r1", "receivable", 1, on(1))], [], [], 3, start=START)
    with pytest.raises(ValueError, match="not a receivable"):
        forecast(idr(1000), [], [invoice("p1", "payable", 1, on(1))], [], 3, start=START)
    with pytest.raises(ValueError, match="not in IDR"):
        forecast(
            idr(1000), [invoice("p1", "payable", 1, on(1), currency="USD")], [], [], 3, start=START
        )


def test_recurring_item_needs_a_day_only_when_monthly():
    with pytest.raises(ValueError):
        RecurringItem(label="x", amount=Decimal(1), direction="in", frequency="monthly")
    with pytest.raises(ValueError):
        RecurringItem(
            label="x", amount=Decimal(1), direction="in", frequency="daily", day_of_month=3
        )


# --- detect_recurring ------------------------------------------------------------------------


def book(id, on_day, amount, category, direction="out", invoice_id=None) -> BookEntry:
    return BookEntry(
        id=id,
        date=on_day,
        amount=Decimal(amount),
        direction=direction,
        category=category,
        description="",
        invoice_id=invoice_id,
    )


AS_OF = dt.date(2026, 9, 30)


def test_no_entries_means_nothing_recurring():
    assert detect_recurring([], AS_OF) == []


def test_frequent_entries_become_a_daily_average_over_calendar_days():
    first = dt.date(2026, 9, 21)
    entries = [
        book(f"e{n}", first + dt.timedelta(days=n), 100, "sales", "in") for n in (0, 1, 2, 4, 6, 9)
    ]

    (item,) = detect_recurring(entries, AS_OF)

    assert (item.label, item.direction, item.frequency) == ("sales", "in", "daily")
    assert item.amount == Decimal("60.00")


def test_same_day_each_month_becomes_a_monthly_total():
    entries = [
        book("e1", dt.date(2026, 7, 28), 400, "payroll"),
        book("e2", dt.date(2026, 7, 28), 600, "payroll"),
        book("e3", dt.date(2026, 8, 28), 400, "payroll"),
        book("e4", dt.date(2026, 8, 28), 600, "payroll"),
        book("e5", dt.date(2026, 9, 28), 400, "payroll"),
        book("e6", dt.date(2026, 9, 28), 600, "payroll"),
    ]

    (item,) = detect_recurring(entries, AS_OF)

    assert (item.label, item.direction, item.frequency) == ("payroll", "out", "monthly")
    assert (item.amount, item.day_of_month) == (Decimal(1000), 28)


def test_last_day_of_each_month_becomes_day_31():
    entries = [
        book("e1", dt.date(2026, 7, 31), 15, "bank_fee"),
        book("e2", dt.date(2026, 8, 31), 15, "bank_fee"),
        book("e3", dt.date(2026, 9, 30), 15, "bank_fee"),
    ]

    (item,) = detect_recurring(entries, AS_OF)

    assert (item.frequency, item.day_of_month, item.amount) == ("monthly", 31, Decimal(15))


def test_one_offs_irregular_days_and_single_months_are_ignored():
    entries = [
        book("e1", dt.date(2026, 9, 6), 600, "maintenance"),
        book("e2", dt.date(2026, 7, 3), 50, "donation"),
        book("e3", dt.date(2026, 8, 19), 50, "donation"),
        book("e4", dt.date(2026, 9, 5), 70, "parking"),
        book("e5", dt.date(2026, 9, 5), 70, "parking"),
    ]

    assert detect_recurring(entries, AS_OF) == []


def test_entries_linked_to_invoices_or_outside_the_lookback_are_ignored():
    entries = [
        book("e1", dt.date(2026, 7, 28), 1000, "rent", invoice_id="inv-1"),
        book("e2", dt.date(2026, 8, 28), 1000, "rent", invoice_id="inv-2"),
        book("e3", dt.date(2026, 5, 28), 1000, "payroll"),
        book("e4", dt.date(2026, 6, 28), 1000, "payroll"),
        book("e5", dt.date(2026, 10, 1), 1000, "payroll"),
    ]

    assert detect_recurring(entries, AS_OF) == []
    with pytest.raises(ValueError):
        detect_recurring(entries, AS_OF, lookback_days=0)


# --- Against the seeded ground truth ---------------------------------------------------------


@pytest.fixture
def scenario(ground_truth) -> dict:
    return ground_truth["cash_scenario"]["forecast"]


@pytest.fixture
def seed_inputs(env, owner, scenario):
    return {
        "balance": env.get_balance(owner),
        "payables": env.list_invoices(owner, "payable", status="open"),
        "receivables": env.list_invoices(owner, "receivable", status="open"),
        "horizon_days": scenario["horizon_days"],
        "start": dt.date.fromisoformat(scenario["start"]),
    }


def test_forecast_reproduces_the_planted_cash_squeeze_exactly(seed_inputs, scenario):
    """The ground truth was computed by the seed generator's own loop, not by this code."""
    recurring = [RecurringItem.model_validate(item) for item in scenario["recurring"]]
    expected = scenario["expected"]

    result = forecast(recurring=recurring, **seed_inputs)

    assert result.lowest_balance == Decimal(expected["lowest_balance"])
    assert result.lowest_date == dt.date.fromisoformat(expected["lowest_date"])
    assert result.shortfall_days[0] == dt.date.fromisoformat(expected["first_shortfall_date"])
    assert len(result.shortfall_days) == expected["shortfall_day_count"]
    assert result.daily_balance[-1].balance == Decimal(expected["final_balance"])


def test_recurring_items_are_detected_from_the_seed_books(env, owner, scenario):
    planted = {item["label"]: item for item in scenario["recurring"]}
    entries = env.get_book_entries(owner, FAR_PAST, FAR_FUTURE)

    detected = {item.label: item for item in detect_recurring(entries, env.as_of_date)}

    payroll = detected["payroll"]
    assert (payroll.direction, payroll.frequency) == ("out", "monthly")
    assert payroll.day_of_month == planted["payroll"]["day_of_month"]
    assert payroll.amount == Decimal(planted["payroll"]["amount"])

    sales = detected["sales"]
    assert (sales.direction, sales.frequency) == ("in", "daily")
    assert abs(sales.amount / Decimal(planted["sales"]["amount"]) - 1) < Decimal("0.02")

    assert set(detected) <= {"payroll", "sales", "bank_fee"}


def test_forecast_from_detected_items_warns_about_the_same_squeeze(
    env, owner, seed_inputs, scenario
):
    """Sales detected from the books are slightly higher than the planted bank figure, because
    the books also hold the planted deposits that never reached the bank. The dates of the
    warning must still agree, and the lowest balance must differ by exactly that daily
    difference accumulated up to the lowest day."""
    entries = env.get_book_entries(owner, FAR_PAST, FAR_FUTURE)
    expected = scenario["expected"]
    detected = detect_recurring(entries, env.as_of_date)

    result = forecast(recurring=detected, **seed_inputs)

    assert result.shortfall_days[0] == dt.date.fromisoformat(expected["first_shortfall_date"])
    assert result.lowest_date == dt.date.fromisoformat(expected["lowest_date"])

    planted_sales = next(
        Decimal(i["amount"]) for i in scenario["recurring"] if i["label"] == "sales"
    )
    detected_sales = next(i.amount for i in detected if i.label == "sales")
    days_to_lowest = (result.lowest_date - seed_inputs["start"]).days + 1
    assert detected_sales > planted_sales
    assert result.lowest_balance - Decimal(expected["lowest_balance"]) == (
        (detected_sales - planted_sales) * days_to_lowest
    )
