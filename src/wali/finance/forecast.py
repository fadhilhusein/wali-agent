"""Project the cash balance day by day.

The projection is deliberately simple and conservative, so it can be explained in one breath:

- An open payable leaves on its due date. One that is already overdue leaves on the first day.
- An open receivable arrives on its due date. One that is already overdue is NOT counted,
  because money that is already late cannot be relied on.
- Recurring items (for example average daily sales, monthly payroll) are added on their days.
- Invoices that are not open are ignored.
"""

from __future__ import annotations

import calendar
import datetime as dt
from collections import defaultdict
from collections.abc import Sequence
from decimal import Decimal

from wali.models import (
    BookEntry,
    CashflowForecast,
    DailyBalance,
    Invoice,
    Money,
    RecurringItem,
)

MAX_HORIZON_DAYS = 366
CENT = Decimal("0.01")


def _last_day(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def occurs_on(item: RecurringItem, day: dt.date) -> bool:
    if item.frequency == "daily":
        return True
    return day.day == min(item.day_of_month, _last_day(day.year, day.month))


def _open_invoices(invoices: Sequence[Invoice], kind: str, currency: str) -> list[Invoice]:
    for invoice in invoices:
        if invoice.kind != kind:
            raise ValueError(f"Invoice {invoice.id} is not a {kind}")
        if invoice.currency != currency:
            raise ValueError(f"Invoice {invoice.id} is not in {currency}")
    return [invoice for invoice in invoices if invoice.status == "open"]


def forecast(
    balance: Money,
    payables: Sequence[Invoice],
    receivables: Sequence[Invoice],
    recurring: Sequence[RecurringItem],
    horizon_days: int,
    *,
    start: dt.date,
    shortfall_below: Decimal = Decimal("0"),
) -> CashflowForecast:
    """Forecast end-of-day balances for ``horizon_days`` days, the first being ``start``.

    ``balance`` is the balance before anything happens on ``start``. A day counts as a shortfall
    day when its balance is below ``shortfall_below``.
    """
    if not 1 <= horizon_days <= MAX_HORIZON_DAYS:
        raise ValueError(f"horizon_days must be between 1 and {MAX_HORIZON_DAYS}")

    flows: dict[dt.date, Decimal] = defaultdict(Decimal)
    for invoice in _open_invoices(payables, "payable", balance.currency):
        flows[max(invoice.due_date, start)] -= invoice.amount
    for invoice in _open_invoices(receivables, "receivable", balance.currency):
        if invoice.due_date >= start:
            flows[invoice.due_date] += invoice.amount

    running = balance.amount
    daily = []
    for offset in range(horizon_days):
        day = start + dt.timedelta(days=offset)
        running += flows.get(day, Decimal("0"))
        for item in recurring:
            if occurs_on(item, day):
                running += item.amount if item.direction == "in" else -item.amount
        daily.append(DailyBalance(date=day, balance=running))

    lowest = min(daily, key=lambda d: (d.balance, d.date))
    return CashflowForecast(
        horizon_days=horizon_days,
        daily_balance=daily,
        lowest_balance=lowest.balance,
        lowest_date=lowest.date,
        shortfall_days=[d.date for d in daily if d.balance < shortfall_below],
    )


def detect_recurring(
    entries: Sequence[BookEntry],
    as_of: dt.date,
    *,
    lookback_days: int = 90,
    daily_min_share: Decimal = Decimal("0.4"),
) -> list[RecurringItem]:
    """Find repeating cash flows in the books that no invoice covers.

    Entries linked to an invoice are skipped, because invoices are forecast separately. The
    remaining entries are grouped by category and direction. A group seen on at least
    ``daily_min_share`` of the days becomes a daily item with the average amount per calendar
    day. A group seen on the same day of the month (or always on the last day) in at least two
    months becomes a monthly item with the average monthly total. Anything else is treated as a
    one-off and ignored.
    """
    if lookback_days < 1:
        raise ValueError("lookback_days must be at least 1")
    recent = [
        e for e in entries if e.invoice_id is None and 0 <= (as_of - e.date).days < lookback_days
    ]
    if not recent:
        return []
    span_days = (as_of - min(e.date for e in recent)).days + 1

    groups: dict[tuple[str, str], list[BookEntry]] = defaultdict(list)
    for entry in recent:
        groups[(entry.category, entry.direction)].append(entry)

    items = []
    for (category, direction), group in sorted(groups.items()):
        total = sum((e.amount for e in group), Decimal("0"))
        active_days = {e.date for e in group}
        if len(active_days) >= daily_min_share * span_days:
            amount = (total / span_days).quantize(CENT)
            if amount > 0:
                items.append(
                    RecurringItem(
                        label=category, amount=amount, direction=direction, frequency="daily"
                    )
                )
            continue

        months: dict[tuple[int, int], set[int]] = defaultdict(set)
        for entry in group:
            months[(entry.date.year, entry.date.month)].add(entry.date.day)
        if len(months) < 2 or any(len(days) != 1 for days in months.values()):
            continue
        days_of_month = [next(iter(days)) for days in months.values()]
        always_month_end = all(
            day == _last_day(year, month)
            for (year, month), day in zip(months, days_of_month, strict=True)
        )
        if always_month_end:
            day_of_month = 31
        elif max(days_of_month) - min(days_of_month) <= 1:
            day_of_month = max(days_of_month)
        else:
            continue
        items.append(
            RecurringItem(
                label=category,
                amount=(total / len(months)).quantize(CENT),
                direction=direction,
                frequency="monthly",
                day_of_month=day_of_month,
            )
        )
    return items
