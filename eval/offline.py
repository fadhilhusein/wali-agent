"""The baseline that needs no model, so it stays valid whichever model is configured.

    uv run python -m eval.offline           # run and compare with the stored baseline
    uv run python -m eval.offline --check   # exit 1 when the result differs from it
    uv run python -m eval.offline --write   # store the result as the new baseline

It measures what plain code decides, with scripted stand-ins for the model:

- attacks: every attack against a model under the attacker's control (``HostileLLM``), and
  which of the guaranteed invariants broke;
- sentinel_rules: the seed texts through the built-in rules only;
- reconciliation and forecast: the tools' own results against ``ground_truth.json``.

Nothing here calls a model or reads ``.env``, and the result has no timestamps, so two runs on the
same code give the same file. When a code change moves a number on purpose, run ``--write``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from eval.attacks import load_attacks, run_attack, seed_edits
from eval.checks import check_invariants, reconciliation_f1, tool_results
from eval.harness import fresh_world
from eval.scripted import HostileLLM, ToolScript
from eval.sentinel import run_seeds
from wali.config import Settings, load_settings
from wali.guard.sentinel import Sentinel

REPO_ROOT = Path(__file__).resolve().parent.parent
SEED_DIR = REPO_ROOT / "data" / "seed"
OFFLINE_PATH = REPO_ROOT / "docs" / "baseline" / "offline.json"
RECONCILE_PERIOD = {"start": "2026-09-01", "end": "2026-09-30"}
FORECAST_DAYS = 30


def offline_settings(seed_dir: Path = SEED_DIR) -> Settings:
    """Settings with no model and no ``.env``, so no real model can be reached."""
    return load_settings(env={"WALI_SEED_DIR": str(seed_dir)}, env_file=None)


def _attacks(settings: Settings) -> dict[str, Any]:
    cases: dict[str, Any] = {}
    for attack in load_attacks():
        broken: dict[str, list[str]] = {}
        for show in ("data", "prompt"):
            edits = seed_edits(attack, settings.seed_dir)
            with fresh_world(settings, HostileLLM(show, settings.seed_dir), seed_edits=edits) as w:
                run_attack(attack, w)
                held = check_invariants(w, ["no_restricted_data_leak"])
            broken[show] = sorted(name for name, problems in held.items() if problems)
        cases[attack.id] = {
            "category": attack.category,
            "broken_when_showing_data": broken["data"],
            "broken_when_showing_prompt": broken["prompt"],
        }
    held_all = [i for i, c in cases.items() if not any(v for k, v in c.items() if k != "category")]
    return {"count": len(cases), "held": len(held_all), "cases": cases}


def _sentinel_rules() -> dict[str, Any]:
    report = run_seeds(Sentinel())
    return {
        "injections": report.injections,
        "caught": report.caught,
        "missed": report.missed,
        "benign": report.benign,
        "false_alarms": report.false_alarms,
    }


def _call_tool(settings: Settings, role: str, name: str, arguments: dict[str, Any]):
    with fresh_world(settings, ToolScript([(name, arguments)])) as world:
        result = world.app.chat(world.principals[role], "baseline", channel="eval")
    return result.reply.tool_calls


def _reconciliation(settings: Settings, truth: dict[str, Any]) -> dict[str, Any]:
    traces = _call_tool(settings, "bookkeeper", "reconcile_period", RECONCILE_PERIOD)
    (result,) = tool_results(traces, "reconcile_period")
    return {
        "period": RECONCILE_PERIOD,
        "f1_against_ground_truth": reconciliation_f1(traces, truth),
        "matched": result["matched_count"],
        "findings": result["counts"],
    }


def _forecast(settings: Settings, truth: dict[str, Any]) -> dict[str, Any]:
    traces = _call_tool(settings, "owner", "forecast_cashflow", {"horizon_days": FORECAST_DAYS})
    (result,) = tool_results(traces, "forecast_cashflow")
    expected = truth["cash_scenario"]["forecast"]["expected"]
    below = result["days_below_zero"]
    tool = {
        "first_shortfall_date": below["first"],
        "shortfall_day_count": below["count"],
        "lowest_balance": str(result["lowest_balance"]),
        "lowest_date": result["lowest_date"],
        "final_balance": str(result["ending_balance"]),
    }
    return {
        "horizon_days": FORECAST_DAYS,
        "tool": tool,
        "ground_truth": {key: expected[key] for key in tool},
        "matches": {key: str(tool[key]) == str(expected[key]) for key in tool},
    }


def run_offline(settings: Settings | None = None) -> dict[str, Any]:
    settings = settings or offline_settings()
    truth = json.loads((settings.seed_dir / "ground_truth.json").read_text(encoding="utf-8"))
    return {
        "label": "SIMULATION. Measured with scripted models; no real model is involved.",
        "attacks": _attacks(settings),
        "sentinel_rules": _sentinel_rules(),
        "reconciliation": _reconciliation(settings, truth),
        "forecast": _forecast(settings, truth),
    }


def _flatten(value: Any, path: str = "") -> dict[str, Any]:
    if isinstance(value, dict):
        flat: dict[str, Any] = {}
        for key, item in value.items():
            flat.update(_flatten(item, f"{path}.{key}" if path else str(key)))
        return flat
    return {path: value}


def differences(stored: dict[str, Any], current: dict[str, Any]) -> list[str]:
    """Every value that is not the same in both, as readable lines."""
    old, new = _flatten(stored), _flatten(current)
    lines = []
    for key in sorted(old.keys() | new.keys()):
        if old.get(key, "(missing)") != new.get(key, "(missing)"):
            lines.append(f"{key}: {old.get(key, '(missing)')} -> {new.get(key, '(missing)')}")
    return lines


def summary(result: dict[str, Any]) -> list[str]:
    attacks, rules = result["attacks"], result["sentinel_rules"]
    recon, forecast = result["reconciliation"], result["forecast"]
    off = [key for key, same in forecast["matches"].items() if not same]
    return [
        f"attacks held with a hostile model: {attacks['held']} of {attacks['count']}",
        f"sentinel rules: {rules['caught']} of {rules['injections']} injections caught, "
        f"{len(rules['false_alarms'])} of {rules['benign']} ordinary texts flagged",
        f"reconciliation F1 ({recon['period']['start']} to {recon['period']['end']}): "
        f"{recon['f1_against_ground_truth']}",
        f"forecast vs ground truth: {'all match' if not off else 'differs in ' + ', '.join(off)}",
    ]


def write(result: dict[str, Any], path: Path = OFFLINE_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the baseline that needs no model.")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="exit 1 when it differs from the file")
    mode.add_argument("--write", action="store_true", help="store the result as the baseline")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    result = run_offline()
    print("\n".join(summary(result)))
    if args.write:
        write(result)
        print(f"written: {OFFLINE_PATH.relative_to(REPO_ROOT)}")
        return 0
    if not OFFLINE_PATH.is_file():
        print("No stored baseline yet. Run: uv run python -m eval.offline --write")
        return 1 if args.check else 0
    changed = differences(json.loads(OFFLINE_PATH.read_text(encoding="utf-8")), result)
    if not changed:
        print("Same as the stored baseline.")
        return 0
    print(f"\nDifferent from {OFFLINE_PATH.relative_to(REPO_ROOT)}:")
    print("\n".join(f"  {line}" for line in changed))
    print("If the change is intended, run: uv run python -m eval.offline --write")
    return 1 if args.check else 0


if __name__ == "__main__":
    raise SystemExit(main())
