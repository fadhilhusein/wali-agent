"""Comparing a report with the stored baseline of its own model."""

import json

import pytest
from eval.compare import against_baseline, compare, save, slug, summarise

GOOD = {
    "task_success_rate": 1.0,
    "tool_call_accuracy": 1.0,
    "attack_success_count": 0,
    "false_refusal_rate": 0.0,
    "dialogue_pass_rate": 1.0,
}


def report(
    model="openai/gpt-oss-20b",
    *,
    tasks=None,
    attacks=None,
    metrics=None,
    sentinel_model="openai/gpt-oss-20b",
    runs=1,
):
    tasks = {"T001": True, "T002": True} if tasks is None else tasks
    attacks = {"A001": False} if attacks is None else attacks
    run = {
        "tasks": [{"id": i, "passed": p} for i, p in tasks.items()],
        "dialogues": [],
        "attacks": [{"id": i, "succeeded": s} for i, s in attacks.items()],
        "sentinel": None,
        "screening_model": {"model_calls": 2, "model_failures": 1},
    }
    return {
        "label": "SIMULATION",
        "generated_at": "2026-10-15T10:00:00+00:00",
        "config": {
            "agent_model": model,
            "sentinel_model": sentinel_model,
            "provider": "openai_compatible",
            "temperature": 0.0,
            "sentinel_strict_turn": False,
            "code": "abc1234",
        },
        "repeat": runs,
        "metrics": GOOD if metrics is None else metrics,
        "runs": [run] * runs,
    }


def test_a_model_id_becomes_a_safe_file_name():
    assert slug("openai/gpt-oss-20b") == "openai-gpt-oss-20b"
    assert slug("nvidia/Nemotron 3 Super:120B") == "nvidia-nemotron-3-super-120b"
    assert slug("gemini-3.5-flash") == "gemini-3.5-flash"


def test_a_case_keeps_the_share_of_runs_it_passed():
    two = report(runs=2)
    two["runs"] = [
        {**two["runs"][0], "tasks": [{"id": "T001", "passed": True}]},
        {**two["runs"][0], "tasks": [{"id": "T001", "passed": False}]},
    ]

    summary = summarise(two)

    assert summary["cases"]["tasks"] == {"T001": 0.5}
    assert summary["cases"]["attacks"] == {"A001": 1.0}
    assert summary["screening_model"] == {"model_calls": 4, "model_failures": 2}


def test_a_model_without_a_baseline_is_judged_on_the_targets_alone():
    lines, all_met = compare(summarise(report("new/model")), None)

    assert all_met
    assert any("No baseline for this model yet" in line for line in lines)
    assert not any(line.startswith("Worse than") for line in lines)


def test_a_missed_target_fails_with_or_without_a_baseline():
    bad = report(metrics={**GOOD, "attack_success_count": 1})

    assert compare(summarise(bad), None)[1] is False
    assert compare(summarise(bad), summarise(report()))[1] is False


def test_cases_that_got_worse_or_better_are_named():
    baseline = summarise(report(tasks={"T001": True, "T002": False}))
    now = summarise(report(tasks={"T001": False, "T002": True, "T011": True}))

    lines, _ = compare(now, baseline)

    assert "Worse than the baseline: T001 (1 -> 0)" in lines
    assert "Better than the baseline: T002 (0 -> 1)" in lines
    assert "Not in the baseline: T011" in lines


def test_metric_changes_are_shown_against_the_baseline():
    baseline = summarise(report(metrics={**GOOD, "task_success_rate": 0.9}))

    lines, _ = compare(summarise(report()), baseline)

    assert "| task_success_rate | 1 | >= 0.9 | yes | 0.9 | 0.1 |" in lines


def test_settings_that_change_the_meaning_and_partial_runs_are_warned_about():
    baseline = summarise(report())
    now = summarise(report(sentinel_model="none (rules only)", tasks={"T001": True}))

    lines, _ = compare(now, baseline)

    assert any(line.startswith("WARNING: sentinel_model differs") for line in lines)
    assert any("tasks ran 1 of the 2 baseline cases" in line for line in lines)


def test_each_model_is_compared_with_its_own_baseline(tmp_path):
    save(report("model/a", tasks={"T001": True, "T002": True}), replace=False, folder=tmp_path)

    own, _ = against_baseline(report("model/a", tasks={"T001": False, "T002": True}), tmp_path)
    other, _ = against_baseline(report("model/b"), tmp_path)

    assert "Worse than the baseline: T001 (1 -> 0)" in own
    assert any("No baseline for this model yet" in line for line in other)


def test_a_baseline_is_only_overwritten_when_asked(tmp_path):
    first = save(report(tasks={"T001": True}), replace=False, folder=tmp_path)

    with pytest.raises(FileExistsError):
        save(report(tasks={"T001": False}), replace=False, folder=tmp_path)
    assert json.loads(first.read_text("utf-8"))["cases"]["tasks"] == {"T001": 1.0}

    save(report(tasks={"T001": False}), replace=True, folder=tmp_path)
    assert json.loads(first.read_text("utf-8"))["cases"]["tasks"] == {"T001": 0.0}
