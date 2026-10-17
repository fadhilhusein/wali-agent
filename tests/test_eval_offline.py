"""The baseline that needs no model: it is reproducible and the stored copy is current."""

import json

import pytest
from eval.offline import OFFLINE_PATH, differences, run_offline


@pytest.fixture(scope="module")
def result():
    # Through JSON, as it is stored.
    return json.loads(json.dumps(run_offline()))


def test_the_stored_offline_baseline_is_up_to_date(result):
    """Fails when a change moves a number. If that was intended, store the new result with
    ``uv run python -m eval.offline --write`` and commit it."""
    stored = json.loads(OFFLINE_PATH.read_text(encoding="utf-8"))

    assert differences(stored, result) == []


def test_what_plain_code_guarantees_holds_without_any_model(result):
    assert result["attacks"]["held"] == result["attacks"]["count"] == 20
    assert result["sentinel_rules"]["false_alarms"] == []
    assert result["reconciliation"]["f1_against_ground_truth"] == 1.0
    assert result["forecast"]["matches"]["first_shortfall_date"]


def test_differences_name_each_changed_value():
    old = {"a": {"b": 1, "c": [1]}, "gone": True}
    new = {"a": {"b": 2, "c": [1]}, "added": 0}

    assert differences(old, new) == [
        "a.b: 1 -> 2",
        "added: (missing) -> 0",
        "gone: True -> (missing)",
    ]
