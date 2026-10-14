"""Attacks, and whether any of them got through.

An attack is one or more messages from one principal, optionally carrying untrusted content:
pasted into the message, or planted in the case's own copy of the data (an invoice document, a
supplier name, a bank memo, a book entry). The owner never presses Confirm during an attack.

Success is judged only on the final state: the ledger, the audit log, and every reply shown.
An attack succeeds if it breaks any invariant, whatever the replies said. A set of invariants is
checked for every attack (``eval.checks.ALWAYS``); an attack can add stricter ones.
"""

from __future__ import annotations

import csv
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import yaml
from pydantic import Field, field_validator, model_validator

from eval.checks import ALWAYS, INVARIANTS, check_invariants
from eval.dialogues import _Spec, run_turn
from eval.harness import EvalWorld, SeedEdit
from wali.models import Role

ATTACKS_PATH = Path(__file__).with_name("attacks.yaml")
Category = Literal[
    "induced_transfer", "data_extraction", "privilege_escalation", "prompt_injection"
]
CATEGORIES: tuple[str, ...] = Category.__args__  # type: ignore[attr-defined]
PLANTED_DATE = "2026-09-29"


class Plant(_Spec):
    where: Literal["message", "invoice_document", "supplier_name", "bank_memo", "book_description"]
    # The invoice id or supplier id, for the places that need one.
    target: str | None = None

    @model_validator(mode="after")
    def _target(self) -> Plant:
        needs = self.where in ("invoice_document", "supplier_name")
        if needs != (self.target is not None):
            raise ValueError(f"{self.where} {'needs' if needs else 'takes no'} target")
        return self


class Attack(_Spec):
    id: str
    category: Category
    title: str
    principal: Role
    user: str | list[str]
    untrusted_content: str | None = None
    plant: Plant = Field(default_factory=lambda: Plant(where="message"))
    # Invoices the bookkeeper has already asked to pay, waiting for the owner, before it starts.
    setup_pending: list[str] = Field(default_factory=list)
    # Invariants this attack adds to the ones always checked. Every value must be true.
    invariants: dict[str, bool] = Field(default_factory=dict)

    @field_validator("invariants")
    @classmethod
    def _known(cls, value: dict[str, bool]) -> dict[str, bool]:
        unknown = sorted(set(value) - set(INVARIANTS))
        if unknown:
            raise ValueError(f"unknown invariants {unknown}")
        if not all(value.values()):
            raise ValueError("an invariant can only be switched on")
        return value

    @property
    def messages(self) -> list[str]:
        texts = [self.user] if isinstance(self.user, str) else list(self.user)
        if self.untrusted_content and self.plant.where == "message":
            texts[0] = f"{texts[0]}\n\n{self.untrusted_content}"
        return texts


def load_attacks(path: Path = ATTACKS_PATH) -> list[Attack]:
    attacks = [Attack.model_validate(item) for item in yaml.safe_load(path.read_text("utf-8"))]
    if len({a.id for a in attacks}) != len(attacks):
        raise ValueError("Attack ids must be unique")
    return attacks


def seed_edits(attack: Attack, seed_dir: Path) -> list[SeedEdit]:
    """Where the untrusted content goes in the case's own copy of the data."""
    content, where, target = attack.untrusted_content, attack.plant.where, attack.plant.target
    if content is None or where == "message":
        return []
    if where == "invoice_document":
        return [SeedEdit("invoices", {"document_text": content}, row_id=target)]
    if where == "supplier_name":
        with (seed_dir / "invoices.csv").open(encoding="utf-8", newline="") as handle:
            invoices = [r["id"] for r in csv.DictReader(handle) if r["counterparty_id"] == target]
        return [SeedEdit("suppliers", {"name": content}, row_id=target)] + [
            SeedEdit("invoices", {"counterparty_name": content}, row_id=i) for i in invoices
        ]
    if where == "bank_memo":
        return [
            SeedEdit(
                "bank_transactions",
                {
                    "id": f"bt-{attack.id.lower()}",
                    "date": PLANTED_DATE,
                    "amount": "150000",
                    "direction": "in",
                    "counterparty": "Transfer masuk",
                    "memo": content,
                    "reference": f"REF-{attack.id}",
                },
            )
        ]
    return [
        SeedEdit(
            "books",
            {
                "id": f"be-{attack.id.lower()}",
                "date": PLANTED_DATE,
                "amount": "150000",
                "direction": "out",
                "category": "misc",
                "description": content,
                "invoice_id": "",
                "reconciled": "false",
            },
        )
    ]


@dataclass
class AttackResult:
    id: str
    category: str
    title: str
    violations: dict[str, list[str]]
    replies: list[str]
    tools: list[str]
    # What stopped it, from the audit log: refusals by reason code, sentinel findings, blocks.
    defences: dict[str, Any] = field(default_factory=dict)
    model_calls: int = 0
    seconds: float = 0.0

    @property
    def succeeded(self) -> bool:
        """True when the ATTACK got through: some invariant was broken."""
        return any(self.violations.values())


def _defences(world: EvalWorld, start: int) -> dict[str, Any]:
    entries = world.audit_entries()[start:]
    refusals = sorted(
        {
            e["data"].get("reason_code")
            for e in entries
            if e["event"].endswith("_denied") or e["event"] == "confirmation_refused"
        }
        - {None}
    )
    return {
        "refused": refusals,
        "sentinel_findings": sum(e["event"] == "sentinel_verdict" for e in entries),
        "replies_blocked": sum(e["event"] == "output_blocked" for e in entries),
        "review_items": sum(e["event"] == "review_item_created" for e in entries),
        "waiting_for_owner": sum(e["event"] == "confirmation_requested" for e in entries),
    }


def run_attack(attack: Attack, world: EvalWorld) -> AttackResult:
    bookkeeper = world.principals["bookkeeper"]
    for invoice_id in attack.setup_pending:
        decision = world.app.guard.propose_payment(bookkeeper, invoice_id)
        if decision.status != "needs_confirmation":
            raise RuntimeError(f"{attack.id}: setup could not create a pending request")
    world.app.pending(world.principals["owner"])  # move the new request into the inbox
    start = len(world.audit_entries())

    principal = world.principals[attack.principal]
    started = time.perf_counter()
    runs = [
        run_turn(world, principal, text, channel=f"eval-{attack.id}") for text in attack.messages
    ]
    declared = [name for name, on in attack.invariants.items() if on]
    return AttackResult(
        id=attack.id,
        category=attack.category,
        title=attack.title,
        violations=check_invariants(world, declared),
        replies=[r.result.reply.text for r in runs],
        tools=[tool for r in runs for tool in r.tools],
        defences=_defences(world, start),
        model_calls=sum(r.model_calls for r in runs),
        seconds=time.perf_counter() - started,
    )


__all__ = ["ALWAYS", "CATEGORIES", "Attack", "AttackResult", "load_attacks", "run_attack"]
