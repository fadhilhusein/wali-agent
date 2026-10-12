"""Rule-based recommendation candidates from a cash-flow forecast.

Each candidate carries a plain reason and the estimated change to the lowest forecast balance if
it were done. The agent phrases them and the owner decides; nothing here is executed.

Rules:

- chase_receivable: every overdue open receivable. The forecast does not count overdue money,
  so collecting it is pure upside.
- prioritise_payable: every overdue open payable that bears late fees.
- delay_payable (only when the forecast shows a shortfall): open payables without late fees that
  fall due on or before the lowest point and are not overdue yet.
- split_payment (only when the forecast shows a shortfall): the largest open payable with late
  fees that falls due on or before the lowest point. Half is paid on time and half later.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Sequence
from decimal import Decimal

from wali.models import CashflowForecast, Invoice, Recommendation

_KIND_ORDER = ("prioritise_payable", "chase_receivable", "delay_payable", "split_payment")


def _effect(
    forecast: CashflowForecast, amount: Decimal, first: dt.date, until: dt.date | None
) -> Decimal:
    """Change in the lowest balance if ``amount`` more cash is held from ``first`` up to but not
    including ``until`` (or to the end of the forecast)."""
    adjusted = min(
        day.balance + (amount if day.date >= first and (until is None or day.date < until) else 0)
        for day in forecast.daily_balance
    )
    return adjusted - forecast.lowest_balance


def _candidate(
    kind: str, invoice: Invoice, reason: str, effect: Decimal, **extra
) -> Recommendation:
    return Recommendation(
        kind=kind,
        invoice_id=invoice.id,
        invoice_number=invoice.number,
        counterparty_name=invoice.counterparty_name,
        amount=invoice.amount,
        reason=reason,
        effect_on_lowest_balance=effect,
        **extra,
    )


def recommend(
    forecast: CashflowForecast,
    payables: Sequence[Invoice],
    receivables: Sequence[Invoice],
    *,
    delay_days: int = 7,
    collect_in_days: int = 3,
) -> list[Recommendation]:
    """Return candidates, the one with the largest effect on the lowest balance first.

    ``delay_days`` is how long a payment is assumed to be postponed. ``collect_in_days`` is how
    soon a chased receivable is assumed to arrive.
    """
    if delay_days < 1 or collect_in_days < 0:
        raise ValueError("delay_days must be at least 1 and collect_in_days at least 0")
    start = forecast.daily_balance[0].date
    has_shortfall = bool(forecast.shortfall_days)
    delay = dt.timedelta(days=delay_days)
    open_payables = [i for i in payables if i.kind == "payable" and i.status == "open"]
    open_receivables = [i for i in receivables if i.kind == "receivable" and i.status == "open"]
    candidates = []

    for invoice in open_receivables:
        days_overdue = (start - invoice.due_date).days
        if days_overdue <= 0:
            continue
        arrives = start + dt.timedelta(days=collect_in_days)
        candidates.append(
            _candidate(
                "chase_receivable",
                invoice,
                f"Overdue by {days_overdue} days. The forecast does not count on this money, "
                f"so collecting it within {collect_in_days} days adds it to your cash.",
                _effect(forecast, invoice.amount, arrives, None),
                days_overdue=days_overdue,
            )
        )

    for invoice in open_payables:
        days_overdue = (start - invoice.due_date).days
        if days_overdue > 0 and invoice.late_fee_bearing:
            candidates.append(
                _candidate(
                    "prioritise_payable",
                    invoice,
                    f"Overdue by {days_overdue} days and late fees may apply. Pay this first.",
                    Decimal("0"),
                    days_overdue=days_overdue,
                )
            )

    if has_shortfall:
        before_low = [i for i in open_payables if start <= i.due_date <= forecast.lowest_date]
        for invoice in before_low:
            if invoice.late_fee_bearing:
                continue
            effect = _effect(forecast, invoice.amount, invoice.due_date, invoice.due_date + delay)
            if effect > 0:
                candidates.append(
                    _candidate(
                        "delay_payable",
                        invoice,
                        f"Due before the lowest point of the forecast and carries no late fee. "
                        f"Paying it {delay_days} days later keeps the cash through that point.",
                        effect,
                        delay_days=delay_days,
                    )
                )

        with_late_fee = [i for i in before_low if i.late_fee_bearing]
        if with_late_fee:
            invoice = max(with_late_fee, key=lambda i: (i.amount, i.id))
            half = invoice.amount / 2
            effect = _effect(forecast, half, invoice.due_date, invoice.due_date + delay)
            if effect > 0:
                candidates.append(
                    _candidate(
                        "split_payment",
                        invoice,
                        f"The largest payment before the lowest point. It carries late fees, so "
                        f"ask the supplier first: pay half on the due date and half "
                        f"{delay_days} days later.",
                        effect,
                        delay_days=delay_days,
                    )
                )

    return sorted(
        candidates,
        key=lambda c: (-c.effect_on_lowest_balance, _KIND_ORDER.index(c.kind), c.invoice_id),
    )
