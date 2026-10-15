"""Run the evaluation against the simulated environment with the REAL configured model.

    uv run python -m eval.run_eval --suite all
    uv run python -m eval.run_eval --suite attacks --repeat 2
    uv run python -m eval.run_eval --suite dialogues --only D06 D07

Suites: tasks, dialogues, attacks, sentinel, or all of them. Every case runs in its own temporary
folder on the fixed seed data. A run writes ``eval/reports/<timestamp>.json`` and a short ``.md``.
The exit code is 1 when any attack got through, in any run.

This spends model credit: a full run is roughly 150 to 200 model calls.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import sys
import time
from typing import Any

from eval.attacks import AttackResult, load_attacks, run_attack, seed_edits
from eval.compare import against_baseline
from eval.dialogues import DialogueResult, load_dialogues, run_dialogue
from eval.harness import CountingLLM, fresh_world
from eval.report import build_report, meets, run_metrics, write_reports
from eval.sentinel import run_seeds
from eval.tasks import TaskResult, load_tasks, run_task
from wali.agent.prompts import SENTINEL_PROMPT
from wali.app import SENTINEL_MAX_TOKENS, SetupError, build_llm
from wali.config import ConfigError, Settings, load_settings
from wali.guard.sentinel import Sentinel

SUITES = ("tasks", "dialogues", "attacks", "sentinel", "all")
MAX_SHOWN_CHARS = 700


def _shown(text: str, full: bool) -> str:
    return text if full or len(text) <= MAX_SHOWN_CHARS else text[:MAX_SHOWN_CHARS] + " [...]"


def show_dialogue(result: DialogueResult, *, full: bool) -> None:
    print(f"\n=== {result.id} {'PASS' if result.passed else 'FAIL'}  {result.title} ===")
    for turn in result.turns:
        print(f"user> {turn.user}")
        print(f"wali> {_shown(turn.reply, full)}")
        print(
            f"      tools: {turn.tools or 'none'} | stop={turn.stop} | "
            f"model calls: {turn.model_calls} | {turn.seconds:.1f}s"
        )
        for problem in turn.problems:
            print(f"      FAIL: {problem}")
    for problem in result.problems:
        print(f"      FAIL (final state): {problem}")


def show_task(result: TaskResult, user: list[str], *, full: bool) -> None:
    print(f"\n=== {result.id} {'PASS' if result.passed else 'FAIL'}  {result.title} ===")
    for text, reply in zip(user, result.replies, strict=False):
        print(f"user> {text}")
        print(f"wali> {_shown(reply, full)}")
    print(
        f"      tools: {result.tools or 'none'} | turns: {result.turns} | "
        f"model calls: {result.model_calls} | {result.seconds:.1f}s"
    )
    for problem in result.problems:
        print(f"      FAIL: {problem}")


def show_attack(result: AttackResult, *, full: bool) -> None:
    verdict = "GOT THROUGH" if result.succeeded else "held"
    print(f"\n=== {result.id} {verdict}  [{result.category}] {result.title} ===")
    for reply in result.replies:
        print(f"wali> {_shown(reply, full)}")
    print(f"      tools: {result.tools or 'none'} | defences: {result.defences}")
    for name, problems in result.violations.items():
        for problem in problems:
            print(f"      BROKEN {name}: {problem}")


def git_commit() -> str:
    try:
        commit = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, check=True
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"], capture_output=True, text=True, check=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"
    return f"{commit}{' (with uncommitted changes)' if dirty else ''}"


def ground_truth(settings: Settings) -> dict[str, Any]:
    return json.loads((settings.seed_dir / "ground_truth.json").read_text(encoding="utf-8"))


def run_once(settings: Settings, llm, suites: set[str], only: list[str], *, full: bool) -> dict:
    """One run of the chosen suites. Returns the results and the run's metrics."""
    truth = ground_truth(settings)
    tasks: list[TaskResult] = []
    dialogues: list[DialogueResult] = []
    attacks: list[AttackResult] = []
    screening = {"model_calls": 0, "model_failures": 0, "not_sent_to_model": 0}

    def tally(world) -> None:
        for name, count in world.app.guard.screening_stats().items():
            screening[name] = screening.get(name, 0) + count

    if "tasks" in suites:
        for task in load_tasks():
            if only and task.id not in only:
                continue
            with fresh_world(settings, llm) as world:
                result = run_task(task, world, truth)
                tally(world)
            show_task(result, [task.user, task.followup or ""], full=full)
            tasks.append(result)

    if "dialogues" in suites:
        for dialogue in load_dialogues():
            if only and dialogue.id not in only:
                continue
            with fresh_world(settings, llm) as world:
                result = run_dialogue(dialogue, world)
                tally(world)
            show_dialogue(result, full=full)
            dialogues.append(result)

    if "attacks" in suites:
        for attack in load_attacks():
            if only and attack.id not in only:
                continue
            edits = seed_edits(attack, settings.seed_dir)
            with fresh_world(settings, llm, seed_edits=edits) as world:
                result = run_attack(attack, world)
                tally(world)
            show_attack(result, full=full)
            attacks.append(result)

    sentinel = None
    if "sentinel" in suites:
        sentinel = run_sentinel(settings)

    metrics = run_metrics(
        tasks, dialogues, attacks, minutes_per_item=settings.manual_minutes_per_item
    )
    return {
        "metrics": metrics,
        "tasks": tasks,
        "dialogues": dialogues,
        "attacks": attacks,
        "sentinel": sentinel,
        "screening_model": screening,
    }


def run_sentinel(settings: Settings) -> dict[str, Any]:
    """Screen the seed texts with the rules and, when configured, the screening model."""
    if settings.sentinel_model:
        capped = settings.model_copy(
            update={"llm_max_tokens": min(settings.llm_max_tokens, SENTINEL_MAX_TOKENS)}
        )
        sentinel = Sentinel(
            CountingLLM(build_llm(capped, settings.sentinel_model)), prompt=SENTINEL_PROMPT
        )
    else:
        sentinel = Sentinel()
    report = run_seeds(sentinel)
    print("\n=== sentinel seeds ===")
    for result in report.results:
        expected = result.kind == "injection"
        outcome = "ok  " if result.flagged == expected else "MISS" if expected else "FALSE ALARM"
        layer = "rules" if result.by_rules else "model" if result.flagged else "-"
        print(f"{outcome} {result.id} {result.kind:<9} by={layer:<5} {list(result.categories)}")
    return {
        "injections": report.injections,
        "caught": report.caught,
        "caught_by_rules": report.caught_by_rules,
        "missed": report.missed,
        "benign": report.benign,
        "false_alarms": report.false_alarms,
        "unscreened": [r.id for r in report.results if r.unscreened],
        "model_calls": report.model_calls,
    }


def summarise(report: dict[str, Any]) -> None:
    print("\n--- summary ---")
    for name, value in report["metrics"].items():
        if name.endswith("_worst") or value is None:
            continue
        worst = report["metrics"].get(f"{name}_worst")
        extra = f" (worst run {worst})" if report["repeat"] > 1 else ""
        print(f"{name}: {value}{extra} [{meets(name, value)}]")
    for number, run in enumerate(report["runs"], start=1):
        failed = [t["id"] for t in run["tasks"] if not t["passed"]]
        failed += [d["id"] for d in run["dialogues"] if not d["passed"]]
        through = [a["id"] for a in run["attacks"] if a["succeeded"]]
        print(
            f"run {number}: failed {failed or 'none'}; attacks through {through or 'none'}; "
            f"screening model {run['screening_model']}"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the agent with the real model.")
    parser.add_argument("--suite", choices=SUITES, default="all")
    parser.add_argument("--only", nargs="*", default=[], help="run only these case ids")
    parser.add_argument("--repeat", type=int, default=1, help="run everything this many times")
    parser.add_argument("--full", action="store_true", help="print replies in full")
    parser.add_argument("--no-report", action="store_true", help="do not write report files")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    if args.repeat < 1:
        parser.error("--repeat must be at least 1")

    try:
        settings = load_settings()
        llm = CountingLLM(build_llm(settings, settings.agent_model))
    except (SetupError, ConfigError) as error:
        print(f"Cannot start: {error}")
        return 2
    suites = {"tasks", "dialogues", "attacks", "sentinel"} if args.suite == "all" else {args.suite}
    config = {
        "suites": ", ".join(sorted(suites)),
        "provider": settings.llm_provider,
        "agent_model": settings.agent_model,
        "sentinel_model": settings.sentinel_model or "none (rules only)",
        "temperature": settings.llm_temperature,
        "sentinel_strict_turn": settings.sentinel_strict_turn,
        "seed_data": str(settings.seed_dir),
        "manual_minutes_per_item": f"{settings.manual_minutes_per_item} (PLACEHOLDER)",
        "code": git_commit(),
    }
    print(f"model: {settings.agent_model} ({settings.llm_provider})")
    print(f"screening model: {config['sentinel_model']}")

    started_at = dt.datetime.now(dt.UTC)
    began = time.perf_counter()
    runs = []
    for number in range(1, args.repeat + 1):
        if args.repeat > 1:
            print(f"\n######## run {number} of {args.repeat} ########")
        runs.append(run_once(settings, llm, suites, args.only, full=args.full))
    config["seconds"] = round(time.perf_counter() - began)
    config["agent_model_calls"] = llm.calls

    report = build_report(
        generated_at=started_at.isoformat(timespec="seconds"), config=config, runs=runs
    )
    summarise(report)
    if not args.no_report:
        stamp = started_at.strftime("%Y%m%dT%H%M%SZ")
        for path in write_reports(report, stamp):
            print(f"report: {path}")
    print("\n--- against this model's baseline ---")
    print("\n".join(against_baseline(report)[0]))
    through = report["metrics"].get("attack_success_count")
    return 1 if through else 0


if __name__ == "__main__":
    raise SystemExit(main())
