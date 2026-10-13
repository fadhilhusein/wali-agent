"""Run the evaluation against the simulated environment with the REAL configured model.

    uv run python -m eval.run_eval --suite dialogues
    uv run python -m eval.run_eval --suite dialogues --only D06 D07

This spends model credit. Each case runs in its own temporary folder. Only the ``dialogues``
suite exists so far; tasks, attacks, and written reports are added in phase 8.
"""

from __future__ import annotations

import argparse
import sys
import time

from eval.dialogues import DialogueResult, load_dialogues, run_dialogue
from eval.harness import fresh_world
from wali.app import SetupError, build_llm
from wali.config import ConfigError, load_settings

SUITES = ("dialogues",)
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


def run_dialogues(settings, llm, only: list[str], *, full: bool) -> list[DialogueResult]:
    dialogues = [d for d in load_dialogues() if not only or d.id in only]
    results = []
    for dialogue in dialogues:
        with fresh_world(settings, llm) as world:
            result = run_dialogue(dialogue, world)
        show(result, full=full)
        results.append(result)
    return results


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
        llm = build_llm(settings, settings.agent_model)
    except (SetupError, ConfigError) as error:
        print(f"Cannot start: {error}")
        return 2
    print(f"model: {settings.agent_model} ({settings.llm_provider})")

    started = time.perf_counter()
    results = run_dialogues(settings, llm, args.only, full=args.full)
    seconds = time.perf_counter() - started

    passed = [r for r in results if r.passed]
    turns = sum(len(r.turns) for r in results)
    calls = sum(r.model_calls for r in results)
    print("\n--- summary ---")
    print(f"dialogues passed: {len(passed)} of {len(results)}")
    print(f"failed: {[r.id for r in results if not r.passed] or 'none'}")
    if results:
        print(f"user turns: {turns}, model calls: {calls} ({calls / turns:.1f} per turn)")
    print(f"time: {seconds:.0f}s")
    return 0 if len(passed) == len(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
