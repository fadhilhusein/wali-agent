"""The sentinel's seed texts and a run over them.

``eval/sentinel_seeds.yaml`` holds injection attempts and ordinary text. ``run_seeds`` screens
them all and reports what each layer caught. With no screening model only the rules run.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict

from wali.guard.sentinel import Sentinel, heuristic_verdict

SEEDS_PATH = Path(__file__).with_name("sentinel_seeds.yaml")


class _Spec(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Injection(_Spec):
    id: str
    where: str
    source: Literal["data", "message"]
    # True when the built-in rules alone must flag this text.
    rules: bool
    text: str


class Benign(_Spec):
    id: str
    source: Literal["data", "message"]
    text: str


class Seeds(_Spec):
    injections: list[Injection]
    benign: list[Benign]


def load_seeds(path: Path = SEEDS_PATH) -> Seeds:
    seeds = Seeds.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
    ids = [seed.id for seed in (*seeds.injections, *seeds.benign)]
    if len(ids) != len(set(ids)):
        raise ValueError("Seed ids must be unique")
    return seeds


@dataclass(frozen=True)
class SeedResult:
    id: str
    kind: Literal["injection", "benign"]
    by_rules: bool
    flagged: bool
    categories: tuple[str, ...]
    # The screening model was asked and gave no usable answer.
    unscreened: bool


@dataclass(frozen=True)
class SeedReport:
    results: list[SeedResult]
    model_calls: int

    def _count(self, kind: str, **where: bool) -> int:
        return sum(
            r.kind == kind and all(getattr(r, name) == value for name, value in where.items())
            for r in self.results
        )

    @property
    def injections(self) -> int:
        return self._count("injection")

    @property
    def caught_by_rules(self) -> int:
        return self._count("injection", by_rules=True)

    @property
    def caught(self) -> int:
        return self._count("injection", flagged=True)

    @property
    def missed(self) -> list[str]:
        return [r.id for r in self.results if r.kind == "injection" and not r.flagged]

    @property
    def benign(self) -> int:
        return self._count("benign")

    @property
    def false_alarms(self) -> list[str]:
        return [r.id for r in self.results if r.kind == "benign" and r.flagged]


def run_seeds(sentinel: Sentinel, seeds: Seeds | None = None) -> SeedReport:
    """Screen every seed. Seeds of one source go in together, as records do in real use."""
    seeds = seeds or load_seeds()
    calls_before = sentinel.stats["model_calls"]
    results: list[SeedResult] = []
    labelled = [("injection", s) for s in seeds.injections] + [("benign", s) for s in seeds.benign]
    for source in ("data", "message"):
        group = [(kind, seed) for kind, seed in labelled if seed.source == source]
        verdicts = sentinel.screen([seed.text for _, seed in group], source=source)
        for (kind, seed), verdict in zip(group, verdicts, strict=True):
            results.append(
                SeedResult(
                    id=seed.id,
                    kind=kind,
                    by_rules=heuristic_verdict(seed.text, source).suspicious,
                    flagged=verdict.suspicious,
                    categories=verdict.categories,
                    unscreened="screening_failed" in verdict.categories,
                )
            )
    results.sort(key=lambda r: r.id)
    return SeedReport(results, sentinel.stats["model_calls"] - calls_before)
