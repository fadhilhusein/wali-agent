"""Run the evaluation against the simulated environment with the REAL configured model.

    uv run python -m eval.run_eval --suite dialogues
    uv run python -m eval.run_eval --suite dialogues --only D06 D07
    uv run python -m eval.run_eval --suite sentinel

This spends model credit. Each dialogue runs in its own temporary folder. The ``sentinel`` suite
screens the texts in ``eval/sentinel_seeds.yaml`` with the rules and the screening model. Tasks,
attacks, and written reports are added in phase 8.
"""

from __future__ import annotations

import argparse
import sys
import time

from eval.dialogues import DialogueResult, load_dialogues, run_dialogue
from eval.harness import CountingLLM, fresh_world
from eval.sentinel import run_seeds
from wali.agent.prompts import SENTINEL_PROMPT
from wali.app import SENTINEL_MAX_TOKENS, SetupError, build_llm
from wali.config import ConfigError, Settings, load_settings
from wali.guard.sentinel import Sentinel

SUITES = ("dialogues", "sentinel")
MAX_SHOWN_CHARS = 700


def show(result: DialogueResult, *, full: bool) -> None:
    print(f"\n=== {result.id} {'PASS' if result.passed else 'FAIL'}  {result.title} ===")
    for turn in result.turns:
        reply = (
            turn.reply
            if full or len(turn.reply) <= MAX_SHOWN_CHARS
            else (turn.reply[:MAX_SHOWN_CHARS] + " [...]")
        )
        print(f"user> {turn.user}")
        print(f"wali> {reply}")
        print(
            f"      tools: {turn.tools or 'none'} | stop={turn.stop} | "
            f"model calls: {turn.model_calls} | {turn.seconds:.1f}s"
        )
        for problem in turn.problems:
            print(f"      FAIL: {problem}")
    for problem in result.problems:
        print(f"      FAIL (final state): {problem}")


def run_dialogues(
    settings, llm, only: list[str], *, full: bool
) -> tuple[list[DialogueResult], dict[str, int]]:
    """Run the dialogues. Also returns the screening model's counters, summed over them."""
    dialogues = [d for d in load_dialogues() if not only or d.id in only]
    results = []
    screening: dict[str, int] = {}
    for dialogue in dialogues:
        with fresh_world(settings, llm) as world:
            result = run_dialogue(dialogue, world)
            for name, count in world.app.guard.screening_stats().items():
                screening[name] = screening.get(name, 0) + count
        show(result, full=full)
        results.append(result)
    return results, screening


def run_sentinel(settings: Settings) -> int:
    """Screen the seed texts. Fails when an injection gets through both layers, or when the
    screening model could not be asked."""
    if not settings.sentinel_model:
        print("WALI_SENTINEL_MODEL is not set, so only the built-in rules are measured.")
        sentinel, model = Sentinel(), None
    else:
        capped = settings.model_copy(
            update={"llm_max_tokens": min(settings.llm_max_tokens, SENTINEL_MAX_TOKENS)}
        )
        model = CountingLLM(build_llm(capped, settings.sentinel_model))
        sentinel = Sentinel(model, prompt=SENTINEL_PROMPT)
        print(f"screening model: {settings.sentinel_model} ({settings.llm_provider})")

    started = time.perf_counter()
    report = run_seeds(sentinel)
    seconds = time.perf_counter() - started

    for result in report.results:
        expected = result.kind == "injection"
        outcome = "ok  " if result.flagged == expected else "MISS" if expected else "FALSE ALARM"
        layer = "rules" if result.by_rules else "model" if result.flagged else "-"
        print(f"{outcome} {result.id} {result.kind:<9} by={layer:<5} {list(result.categories)}")
    unscreened = [r.id for r in report.results if r.unscreened]
    print("\n--- summary ---")
    print(f"injections flagged by the rules alone: {report.caught_by_rules} of {report.injections}")
    print(f"injections flagged by rules and model:  {report.caught} of {report.injections}")
    print(f"missed: {report.missed or 'none'}")
    print(f"ordinary texts wrongly flagged: {len(report.false_alarms)} of {report.benign}")
    print(f"false alarms: {report.false_alarms or 'none'}")
    print(f"not screened by the model (no usable answer): {unscreened or 'none'}")
    if model is not None and model.last_detail:
        print(f"last model error: {model.last_detail}")
    print(f"model calls: {report.model_calls}, time: {seconds:.0f}s")
    return 1 if report.missed or unscreened else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate the agent with the real model.")
    parser.add_argument("--suite", choices=SUITES, default="dialogues")
    parser.add_argument("--only", nargs="*", default=[], help="run only these case ids")
    parser.add_argument("--full", action="store_true", help="print replies in full")
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")

    try:
        settings = load_settings()
        if args.suite == "sentinel":
            return run_sentinel(settings)
        llm = build_llm(settings, settings.agent_model)
    except (SetupError, ConfigError) as error:
        print(f"Cannot start: {error}")
        return 2
    print(f"model: {settings.agent_model} ({settings.llm_provider})")
    print(f"screening model: {settings.sentinel_model or 'none (built-in rules only)'}")

    started = time.perf_counter()
    results, screening = run_dialogues(settings, llm, args.only, full=args.full)
    seconds = time.perf_counter() - started

    passed = [r for r in results if r.passed]
    turns = sum(len(r.turns) for r in results)
    calls = sum(r.model_calls for r in results)
    print("\n--- summary ---")
    print(f"dialogues passed: {len(passed)} of {len(results)}")
    print(f"failed: {[r.id for r in results if not r.passed] or 'none'}")
    if results:
        print(f"user turns: {turns}, model calls: {calls} ({calls / turns:.1f} per turn)")
    print(
        f"screening model calls: {screening.get('model_calls', 0)} "
        f"(no usable answer: {screening.get('model_failures', 0)}, "
        f"texts left to the rules only: {screening.get('not_sent_to_model', 0)})"
    )
    print(f"time: {seconds:.0f}s")
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
