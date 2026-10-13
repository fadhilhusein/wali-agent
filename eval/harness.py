"""A fresh, isolated copy of the whole application for one evaluation case.

Each case gets its own temporary folder (database, guard store, audit log) and its own throwaway
guard key, with the demo mandate already active. Nothing touches the developer's ``data/`` files.
"""

from __future__ import annotations

import json
import tempfile
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pydantic import SecretStr

from wali.agent.llm import LLMClient, LLMError
from wali.app import WaliApp, build_app
from wali.config import Settings
from wali.guard.keys import generate_keypair
from wali.guard.service import MandateRequest
from wali.interfaces.cli import DEMO_MANDATE, verified_supplier_ids
from wali.models import Principal


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


@dataclass
class EvalWorld:
    app: WaliApp
    principals: dict[str, Principal]
    llm: CountingLLM
    audit_path: Path

    def audit_events(self) -> list[str]:
        """The event names in the audit log, in order."""
        if not self.audit_path.is_file():
            return []
        with self.audit_path.open(encoding="utf-8") as handle:
            return [json.loads(line)["event"] for line in handle]


@contextmanager
def fresh_world(
    settings: Settings, llm: LLMClient, *, with_mandate: bool = True
) -> Iterator[EvalWorld]:
    """Build an isolated application. ``llm`` may be the real client or a scripted stand-in."""
    counting = llm if isinstance(llm, CountingLLM) else CountingLLM(llm)
    with tempfile.TemporaryDirectory(prefix="wali-eval-", ignore_cleanup_errors=True) as folder:
        state = Path(folder)
        scratch = settings.model_copy(
            update={
                "guard_private_key": SecretStr(generate_keypair()[0]),
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
            yield EvalWorld(app, principals, counting, state / "audit.jsonl")
        finally:
            app.env.close()
