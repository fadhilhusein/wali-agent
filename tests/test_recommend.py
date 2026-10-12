import datetime as dt
from decimal import Decimal

import pytest

from wali.finance.forecast import forecast
from wali.finance.recommend import recommend
from wali.models import Invoice, Money, RecurringItem

START = dt.date(2026, 10, 1)
DELAY_DAYS = 7
COLLECT_IN_DAYS = 3


def idr(amount) -> Money:
    return Money(amount=Decimal(amount), currency="IDR")


def invoice(id, kind, amount, due, late_fee=False, status="open") -> Invoice:
    return Invoice(
        id=id,
        kind=kind,
        counterparty_id="cp-1",
        counterparty_name=f"Counterparty {id}",
        number=f"N-{id}",
        amount=Decimal(amount),
        currency="IDR",
        issue_date=due - dt.timedelta(days=7),
        due_date=due,
        status=status,
        late_fee_bearing=late_fee,
    )


def on(offset: int) -> dt.date:
    return START + dt.timedelta(days=offset)


def run(balance, payables, receivables, recurring=(), horizon=14):
    result = forecast(idr(balance), payables, receivables, list(recurring), horizon, start=START)
    return result, recommend(result, payables, receivables)


def kinds(recommendations) -> list[tuple[str, str]]:
    return [(r.kind, r.invoice_id) for r in recommendations]


def lowest_if(inputs: dict, payables, receivables) -> Decimal:
    """Re-run the whole forecast with changed invoices: the slow, obvious way to get an effect."""
    changed = {**inputs, "payables": payables, "receivables": receivables}
    return forecast(**changed).lowest_balance


def moved(inv: Invoice, due: dt.date, **changes) -> Invoice:
    return inv.model_copy(update={"due_date": due, **changes})


# --- Rules -----------------------------------------------------------------------------------


def test_healthy_cash_and_nothing_overdue_gives_no_recommendations():
    payables = [invoice("p1", "payable", 100, on(2))]
    receivables = [invoice("r1", "receivable", 100, on(3))]

    result, recommendations = run(1000, payables, receivables)

    assert result.shortfall_days == []
    assert recommendations == []


def test_overdue_receivables_are_always_worth_chasing():
    receivables = [invoice("r1", "receivable", 400, on(-8)), invoice("r2", "receivable", 50, on(4))]

    _, recommendations = run(1000, [], receivables)

    (chase,) = recommendations
    assert (chase.kind, chase.invoice_id) == ("chase_receivable", "r1")
    assert chase.days_overdue == 8
    assert chase.amount == Decimal(400)
    assert chase.effect_on_lowest_balance == Decimal(0)
    assert "8 days" in chase.reason


def test_chasing_helps_when_the_low_point_comes_after_the_money_arrives():
    payables = [invoice("p1", "payable", 1500, on(5), late_fee=True)]
    receivables = [invoice("r1", "receivable", 400, on(-8))]

    result, recommendations = run(1000, payables, receivables)

    assert result.lowest_balance == Decimal(-500)
    chase = next(r for r in recommendations if r.kind == "chase_receivable")
    assert chase.effect_on_lowest_balance == Decimal(400)


def test_overdue_payables_with_late_fees_are_flagged_to_pay_first():
    payables = [
        invoice("p1", "payable", 100, on(-3), late_fee=True),
        invoice("p2", "payable", 100, on(-3), late_fee=False),
    ]

    _, recommendations = run(1000, payables, [])

    assert kinds(recommendations) == [("prioritise_payable", "p1")]
    assert recommendations[0].days_overdue == 3
    assert recommendations[0].effect_on_lowest_balance == Decimal(0)


def test_delay_is_offered_only_in_a_shortfall_for_payables_without_late_fees():
    payables = [
        invoice("p1", "payable", 800, on(1)),
        invoice("p2", "payable", 700, on(2), late_fee=True),
        invoice("p3", "payable", 300, on(9)),
    ]
    receivables = [invoice("r1", "receivable", 2000, on(4))]

    result, recommendations = run(1000, payables, receivables)

    assert result.lowest_date == on(2)
    assert ("delay_payable", "p1") in kinds(recommendations)
    assert ("delay_payable", "p2") not in kinds(recommendations)
    assert ("delay_payable", "p3") not in kinds(recommendations)
    delay = next(r for r in recommendations if r.kind == "delay_payable")
    assert delay.delay_days == DELAY_DAYS
    assert delay.effect_on_lowest_balance > 0


def test_no_delay_or_split_without_a_shortfall():
    payables = [invoice("p1", "payable", 800, on(1)), invoice("p2", "payable", 100, on(2), True)]

    result, recommendations = run(1000, payables, [])

    assert result.shortfall_days == []
    assert recommendations == []


def test_already_overdue_payables_are_not_suggested_for_further_delay():
    payables = [invoice("p1", "payable", 1500, on(-2))]

    result, recommendations = run(1000, payables, [])

    assert result.shortfall_days
    assert recommendations == []


def test_split_is_offered_for_the_largest_late_fee_payable_before_the_low_point():
    payables = [
        invoice("p1", "payable", 600, on(1), late_fee=True),
        invoice("p2", "payable", 1000, on(2), late_fee=True),
    ]
    receivables = [invoice("r1", "receivable", 3000, on(4))]

    result, recommendations = run(1000, payables, receivables)

    assert result.lowest_balance == Decimal(-600)
    (split,) = recommendations
    assert (split.kind, split.invoice_id) == ("split_payment", "p2")
    assert split.delay_days == DELAY_DAYS
    assert split.effect_on_lowest_balance == Decimal(500)


def test_a_delay_that_would_not_lift_the_low_point_is_not_suggested():
    """Paying p1 a week later only moves the same trough to a later day."""
    payables = [invoice("p1", "payable", 1500, on(1))]

    result, recommendations = run(1000, payables, [], horizon=30)

    assert result.lowest_balance == Decimal(-500)
    assert recommendations == []


def test_recommendations_are_ordered_by_effect():
    payables = [
        invoice("p1", "payable", 300, on(1)),
        invoice("p2", "payable", 900, on(1)),
        invoice("p3", "payable", 100, on(-4), late_fee=True),
    ]
    receivables = [invoice("r1", "receivable", 5000, on(5))]

    _, recommendations = run(1000, payables, receivables)

    effects = [r.effect_on_lowest_balance for r in recommendations]
    assert effects == sorted(effects, reverse=True)
    assert kinds(recommendations) == [
        ("delay_payable", "p2"),
        ("delay_payable", "p1"),
        ("prioritise_payable", "p3"),
    ]


def test_invoices_that_are_not_open_are_ignored():
    payables = [invoice("p1", "payable", 5000, on(-3), late_fee=True, status="paid")]
    receivables = [invoice("r1", "receivable", 400, on(-8), status="void")]

    _, recommendations = run(1000, payables, receivables)

    assert recommendations == []


def test_arguments_are_validated():
    result = forecast(idr(1000), [], [], [], 5, start=START)

    with pytest.raises(ValueError):
        recommend(result, [], [], delay_days=0)
    with pytest.raises(ValueError):
        recommend(result, [], [], collect_in_days=-1)


# --- Against the seed data -------------------------------------------------------------------


@pytest.fixture
def seed_inputs(env, owner, ground_truth) -> dict:
    scenario = ground_truth["cash_scenario"]["forecast"]
    return {
        "balance": env.get_balance(owner),
        "payables": env.list_invoices(owner, "payable", status="open"),
        "receivables": env.list_invoices(owner, "receivable", status="open"),
        "recurring": [RecurringItem.model_validate(item) for item in scenario["recurring"]],
        "horizon_days": scenario["horizon_days"],
        "start": dt.date.fromisoformat(scenario["start"]),
    }


@pytest.fixture
def seed_result(seed_inputs):
    result = forecast(**seed_inputs)
    return result, recommend(result, seed_inputs["payables"], seed_inputs["receivables"])


def test_seed_squeeze_produces_every_kind_of_recommendation(seed_result, seed_inputs, ground_truth):
    _, recommendations = seed_result
    by_kind: dict[str, list[str]] = {}
    for item in recommendations:
        by_kind.setdefault(item.kind, []).append(item.invoice_id)
    late_fee_overdue = [
        i.id
        for i in seed_inputs["payables"]
        if i.late_fee_bearing and i.due_date < seed_inputs["start"]
    ]

    assert sorted(by_kind["chase_receivable"]) == sorted(
        ground_truth["invoices"]["overdue_receivables"]
    )
    assert late_fee_overdue
    assert sorted(by_kind["prioritise_payable"]) == sorted(late_fee_overdue)
    assert len(by_kind["delay_payable"]) >= 3
    assert len(by_kind["split_payment"]) == 1


def test_seed_delay_and_split_candidates_respect_the_rules(seed_result, seed_inputs):
    result, recommendations = seed_result
    payables = {i.id: i for i in seed_inputs["payables"]}

    for item in recommendations:
        if item.kind == "delay_payable":
            invoice = payables[item.invoice_id]
            assert not invoice.late_fee_bearing
            assert seed_inputs["start"] <= invoice.due_date <= result.lowest_date
        if item.kind == "split_payment":
            invoice = payables[item.invoice_id]
            assert invoice.late_fee_bearing
            assert invoice.amount == max(
                i.amount
                for i in payables.values()
                if i.late_fee_bearing and seed_inputs["start"] <= i.due_date <= result.lowest_date
            )


def test_every_seed_effect_equals_a_full_re_forecast(seed_result, seed_inputs):
    """Check each estimated effect by actually changing the invoice and forecasting again."""
    result, recommendations = seed_result
    payables, receivables = seed_inputs["payables"], seed_inputs["receivables"]
    delay = dt.timedelta(days=DELAY_DAYS)
    assert recommendations

    for item in recommendations:
        if item.kind == "chase_receivable":
            arrives = seed_inputs["start"] + dt.timedelta(days=COLLECT_IN_DAYS)
            changed = [moved(i, arrives) if i.id == item.invoice_id else i for i in receivables]
            new_lowest = lowest_if(seed_inputs, payables, changed)
        elif item.kind == "delay_payable":
            changed = [
                moved(i, i.due_date + delay) if i.id == item.invoice_id else i for i in payables
            ]
            new_lowest = lowest_if(seed_inputs, changed, receivables)
        elif item.kind == "split_payment":
            changed = []
            for i in payables:
                if i.id == item.invoice_id:
                    half = i.amount / 2
                    changed.append(moved(i, i.due_date, amount=half))
                    changed.append(moved(i, i.due_date + delay, amount=half, id=f"{i.id}-b"))
                else:
                    changed.append(i)
            new_lowest = lowest_if(seed_inputs, changed, receivables)
        else:
            new_lowest = result.lowest_balance

        assert new_lowest - result.lowest_balance == item.effect_on_lowest_balance, item


def test_seed_recommendations_are_ordered_by_effect(seed_result):
    _, recommendations = seed_result
    effects = [r.effect_on_lowest_balance for r in recommendations]

    assert effects == sorted(effects, reverse=True)
    assert effects[0] > 0
