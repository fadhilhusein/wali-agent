"""Compare an evaluation report with the stored baseline of the same model.

    uv run python -m eval.compare                    # the newest report in eval/reports/
    uv run python -m eval.compare REPORT.json
    uv run python -m eval.compare REPORT.json --save # store it as that model's baseline

A model's behaviour does not carry over to another model, so each agent model has its own
baseline in ``docs/baseline/models/<model>.json``. A report is always judged against the fixed
targets in ``eval.report.METRICS``. When its model has a baseline, every metric and every case
is also compared with it; when it has none, the targets alone apply. Trying a new model never
means running an old one again.

The exit code is 1 when a metric misses its target, 2 when the input is unusable.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

from eval.report import METRICS, REPORTS_DIR, meets

REPO_ROOT = Path(__file__).resolve().parent.parent
MODELS_DIR = REPO_ROOT / "docs" / "baseline" / "models"
SUITES = ("tasks", "dialogues", "attacks")
# Settings that change what a number means. A baseline that differs in one is still shown,
# with a warning.
COMPARABLE_SETTINGS = ("provider", "sentinel_model", "temperature", "sentinel_strict_turn")


def slug(model: str) -> str:
    """A file name for a model id: ``openai/gpt-oss-20b`` -> ``openai-gpt-oss-20b``."""
    return re.sub(r"[^a-z0-9.]+", "-", model.lower()).strip("-")


def baseline_path(model: str, folder: Path = MODELS_DIR) -> Path:
    return folder / f"{slug(model)}.json"


def _passed(suite: str, case: dict[str, Any]) -> bool:
    return not case["succeeded"] if suite == "attacks" else case["passed"]


def summarise(report: dict[str, Any]) -> dict[str, Any]:
    """What a baseline keeps from a report: settings, metrics, and per case the share of runs
    it passed (for attacks: the share of runs in which it was held)."""
    runs = report["runs"]
    cases: dict[str, dict[str, float]] = {}
    for suite in SUITES:
        results: dict[str, list[bool]] = {}
        for run in runs:
            for case in run.get(suite) or []:
                results.setdefault(case["id"], []).append(_passed(suite, case))
        cases[suite] = {i: round(sum(r) / len(r), 4) for i, r in sorted(results.items())}
    screening: dict[str, int] = {}
    for run in runs:
        for name, count in (run.get("screening_model") or {}).items():
            screening[name] = screening.get(name, 0) + count
    return {
        "label": report.get("label", ""),
        "recorded": report["generated_at"],
        "config": report["config"],
        "repeat": report["repeat"],
        "metrics": report["metrics"],
        "cases": cases,
        "sentinel": next((run["sentinel"] for run in runs if run.get("sentinel")), None),
        "screening_model": screening,
    }


def _number(value: Any) -> str:
    return "-" if value is None else f"{value:g}" if isinstance(value, float) else str(value)


def compare(current: dict[str, Any], baseline: dict[str, Any] | None) -> tuple[list[str], bool]:
    """Readable lines, and whether every metric with a target met it."""
    model = current["config"]["agent_model"]
    lines = [f"Model: {model}"]
    if baseline is None:
        lines.append(
            f"No baseline for this model yet ({baseline_path(model).relative_to(REPO_ROOT)}). "
            "Judged against the targets only. To keep this run as its baseline: "
            "uv run python -m eval.compare <report> --save"
        )
    else:
        lines.append(
            f"Baseline: recorded {baseline['recorded']}, code {baseline['config'].get('code')}, "
            f"{baseline['repeat']} run(s)."
        )
        for name in COMPARABLE_SETTINGS:
            now, then = current["config"].get(name), baseline["config"].get(name)
            if now != then:
                lines.append(f"WARNING: {name} differs ({then} in the baseline, {now} now).")
        for suite in SUITES:
            ran, kept = set(current["cases"][suite]), set(baseline["cases"][suite])
            if ran and ran != kept:
                lines.append(
                    f"WARNING: {suite} ran {len(ran & kept)} of the {len(kept)} baseline cases, "
                    "so its metrics are not comparable."
                )

    lines += [
        "",
        "| Metric | Now | Target | Met | Baseline | Change |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    all_met = True
    for name, (_, target, higher_is_better) in METRICS.items():
        value = current["metrics"].get(name)
        if value is None:
            continue
        verdict = meets(name, value)
        all_met = all_met and verdict != "NO"
        shown_target = "-" if target is None else f"{'>=' if higher_is_better else '<='} {target}"
        then = baseline["metrics"].get(name) if baseline else None
        change = "-" if then is None else _number(round(value - then, 4))
        lines.append(
            f"| {name} | {_number(value)} | {shown_target} | {verdict} | {_number(then)} | "
            f"{change} |"
        )

    if baseline is not None:
        better, worse, new = [], [], []
        for suite in SUITES:
            for case_id, now in current["cases"][suite].items():
                then = baseline["cases"][suite].get(case_id)
                if then is None:
                    new.append(case_id)
                elif now < then:
                    worse.append(f"{case_id} ({then:g} -> {now:g})")
                elif now > then:
                    better.append(f"{case_id} ({then:g} -> {now:g})")
        lines += ["", f"Worse than the baseline: {', '.join(worse) or 'none'}"]
        lines.append(f"Better than the baseline: {', '.join(better) or 'none'}")
        if new:
            lines.append(f"Not in the baseline: {', '.join(new)}")
    return lines, all_met


def against_baseline(report: dict[str, Any], folder: Path = MODELS_DIR) -> tuple[list[str], bool]:
    """Compare a report with the stored baseline of its model, if there is one."""
    current = summarise(report)
    path = baseline_path(current["config"]["agent_model"], folder)
    baseline = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else None
    return compare(current, baseline)


def save(report: dict[str, Any], *, replace: bool, folder: Path = MODELS_DIR) -> Path:
    """Store a report as its model's baseline. Refuses to overwrite one unless ``replace``."""
    summary = summarise(report)
    path = baseline_path(summary["config"]["agent_model"], folder)
    if path.exists() and not replace:
        raise FileExistsError(f"{path} exists. Add --replace to overwrite it.")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def newest_report(folder: Path = REPORTS_DIR) -> Path | None:
    reports = sorted(folder.glob("*.json"))
    return reports[-1] if reports else None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Compare a report with its model's baseline.")
    parser.add_argument("report", nargs="?", type=Path, help="default: the newest in eval/reports")
    parser.add_argument("--save", action="store_true", help="store it as the model's baseline")
    parser.add_argument("--replace", action="store_true", help="with --save: overwrite")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    path = args.report or newest_report()
    if path is None or not path.is_file():
        print("No report found. Run: uv run python -m eval.run_eval")
        return 2
    report = json.loads(path.read_text(encoding="utf-8"))
    print(f"Report: {path}")
    if args.save:
        try:
            saved = save(report, replace=args.replace)
        except FileExistsError as error:
            print(error)
            return 2
        print(f"Saved as the baseline of {report['config']['agent_model']}: {saved}")
        return 0
    lines, all_met = against_baseline(report)
    print("\n".join(lines))
    return 0 if all_met else 1


if __name__ == "__main__":
    raise SystemExit(main())
