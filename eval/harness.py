"""A fresh, isolated copy of the whole application for one evaluation case.

Each case gets its own temporary folder (seed data, database, guard store, audit log) and its own
throwaway guard key, with the demo mandate already active. Nothing touches the developer's
``data/`` files. A case may change its private copy of the seed data first, for example to plant
an injected instruction in an invoice.
"""

from __future__ import annotations

import csv
import datetime as dt
import json
import shutil
import tempfile
from collections.abc import Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from wali.agent.llm import LLMClient, LLMError
from wali.app import WaliApp, build_app
from wali.config import Settings
from wali.guard.keys import generate_keypair
from wali.guard.service import MandateRequest
from wali.interfaces.common import DEMO_MANDATE, verified_supplier_ids
from wali.models import Principal

FAR_PAST = dt.date(2000, 1, 1)
FAR_FUTURE = dt.date(2100, 1, 1)


class CountingLLM:
    """Wraps a model client to count calls and keep the developer detail of any failure."""

    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.calls = 0
        self.last_detail: str | None = None

    def complete(self, **request: Any):
        self.calls += 1
        try:
            return self.inner.complete(**request)
        except LLMError as error:
            self.last_detail = error.detail or error.user_message
            raise


@dataclass(frozen=True)
class SeedEdit:
    """A change to one CSV file of the case's own seed copy. With ``row_id`` the row with that
    id gets ``values``; without it a new row is added, copied from the file's last row."""

    file: str
    values: Mapping[str, str]
    row_id: str | None = None


def apply_seed_edits(folder: Path, edits: Sequence[SeedEdit]) -> None:
    for edit in edits:
        path = folder / f"{edit.file}.csv"
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            fields, rows = list(reader.fieldnames or []), list(reader)
        unknown = set(edit.values) - set(fields)
        if unknown:
            raise ValueError(f"{edit.file}.csv has no columns {sorted(unknown)}")
        if edit.row_id is None:
            rows.append({**rows[-1], **edit.values})
        else:
            matches = [row for row in rows if row["id"] == edit.row_id]
            if len(matches) != 1:
                raise ValueError(f"{edit.file}.csv has no row {edit.row_id}")
            matches[0].update(edit.values)
        with path.open("w", encoding="utf-8", newline="") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)


@dataclass
class EvalWorld:
    app: WaliApp
    principals: dict[str, Principal]
    llm: CountingLLM
    audit_path: Path
    settings: Settings
    start_book_entries: int = 0
    start_mandate_id: str | None = None
    # Every reply shown to a person in this case: (role, text).
    replies: list[tuple[str, str]] = field(default_factory=list)
    # Every message a person typed in this case: (role, text).
    messages: list[tuple[str, str]] = field(default_factory=list)

    def audit_entries(self) -> list[dict[str, Any]]:
        if not self.audit_path.is_file():
            return []
        with self.audit_path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def audit_events(self) -> list[str]:
        """The event names in the audit log, in order."""
        return [entry["event"] for entry in self.audit_entries()]

    def book_entries(self) -> int:
        owner = self.principals["owner"]
        return len(self.app.env.get_book_entries(owner, FAR_PAST, FAR_FUTURE))

    def mandate_id(self) -> str | None:
        mandate = self.app.guard.active_mandate()
        return mandate.mandate_id if mandate is not None else None


@contextmanager
def fresh_world(
    settings: Settings,
    llm: LLMClient,
    *,
    with_mandate: bool = True,
    seed_edits: Sequence[SeedEdit] = (),
) -> Iterator[EvalWorld]:
    """Build an isolated application. ``llm`` may be the real client or a scripted stand-in."""
    counting = llm if isinstance(llm, CountingLLM) else CountingLLM(llm)
    with tempfile.TemporaryDirectory(prefix="wali-eval-", ignore_cleanup_errors=True) as folder:
        state = Path(folder)
        seed = state / "seed"
        shutil.copytree(settings.seed_dir, seed)
        apply_seed_edits(seed, seed_edits)
        scratch = settings.model_copy(
            update={
                "guard_private_key": SecretStr(generate_keypair()[0]),
                "seed_dir": seed,
                "db_path": state / "wali.db",
                "guard_db_path": state / "guard.db",
                "audit_log_path": state / "audit.jsonl",
                "sim_fail_rate": 0.0,
                "sim_today": None,
            }
        )
        app = build_app(scratch, llm=counting)
        try:
            principals = app.env.principals()
            if with_mandate:
                owner = principals["owner"]
                suppliers = verified_supplier_ids(app, owner)
                app.guard.draft_mandate(
                    owner, MandateRequest(allowed_suppliers=suppliers, **DEMO_MANDATE)
                )
                activated = app.confirm(owner)
                if activated is None or activated.status != "active":
                    raise RuntimeError("The evaluation mandate could not be activated")
            world = EvalWorld(app, principals, counting, state / "audit.jsonl", scratch)
            world.start_book_entries = world.book_entries()
            world.start_mandate_id = world.mandate_id()
            yield world
        finally:
            app.env.close()
