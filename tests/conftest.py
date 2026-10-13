import csv
import datetime as dt
import importlib.util
import itertools
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from wali.agent.llm import LLMResponse, ToolCall
from wali.app import WaliApp
from wali.guard.audit import AuditLog
from wali.guard.keys import generate_keypair, load_private_key
from wali.guard.service import GuardService, MandateRequest
from wali.guard.signing import sign_payload
from wali.guard.store import GuardStore
from wali.models import GuardApproval, Invoice, Principal, Supplier
from wali.tools.registry import ToolRegistry
from wali.tools.sim_env import SimEnvironment

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = REPO_ROOT / "data" / "seed"
JAKARTA = dt.timezone(dt.timedelta(hours=7))


def read_csv(name: str, seed_dir: Path = SEED_DIR) -> list[dict[str, str]]:
    with (seed_dir / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def truth_discrepancy_keys(ground_truth: dict, period=None) -> set[tuple[str, ...]]:
    """The planted reconciliation problems as keys comparable with ``discrepancy_keys``.
    Timing differences are not problems: a correct reconciliation matches them."""
    recon = ground_truth["reconciliation"]
    dated = (
        [(("duplicate_bank", i["duplicate"]), i["date"]) for i in recon["duplicate_bank"]]
        + [
            (("amount_mismatch", i["bank_id"], i["book_id"]), i["date"])
            for i in recon["amount_mismatches"]
        ]
        + [(("unmatched_bank", i["bank_id"]), i["date"]) for i in recon["unmatched_bank"]]
        + [(("unmatched_books", i["book_id"]), i["date"]) for i in recon["unmatched_books"]]
    )
    return {
        key
        for key, day in dated
        if period is None or period[0] <= dt.date.fromisoformat(day) <= period[1]
    }


def precision_recall_f1(found: set, expected: set) -> tuple[float, float, float]:
    hits = len(found & expected)
    precision = hits / len(found) if found else 1.0
    recall = hits / len(expected) if expected else 1.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return precision, recall, f1


def flagged_invoice_ids(ground_truth: dict) -> set[str]:
    """Invoices planted with a problem the guard must refuse or question."""
    planted = ground_truth["invoices"]
    single = ("account_change_fraud", "unverified_supplier", "amount_anomaly")
    ids = {item["invoice_id"] for key in single for item in planted[key]}
    for pair in planted["duplicate_invoices"]:
        ids |= {pair["original"], pair["duplicate"]}
    return ids


def verified_supplier_ids() -> list[str]:
    return [row["id"] for row in read_csv("suppliers") if row["account_verified"] == "true"]


def mandate_request(**overrides) -> MandateRequest:
    """The mandate from the specification's example, covering every verified supplier."""
    fields = {
        "per_payment": "5000000",
        "per_week": "15000000",
        "confirm_above": "1000000",
        "min_cash_buffer": "3000000",
        "allowed_suppliers": verified_supplier_ids(),
        "valid_days": 30,
        "bookkeeper_can_propose": True,
        "bookkeeper_max_propose": "5000000",
    }
    fields.update(overrides)
    return MandateRequest(**fields)


def activate_mandate(guard: GuardService, owner: Principal, request: MandateRequest | None = None):
    """Draft a mandate and confirm it as the owner, the way an interface would."""
    drafted = guard.draft_mandate(owner, request or mandate_request())
    assert drafted.status == "needs_confirmation", drafted
    (confirmation,) = guard.collect_confirmation_requests()
    activated = guard.confirm_mandate(owner, confirmation.token)
    assert activated.status == "active", activated
    return activated


def say(text: str, stop_reason: str = "end_turn") -> LLMResponse:
    """A scripted final answer from the model."""
    return LLMResponse(
        stop_reason=stop_reason,
        text=text,
        tool_calls=(),
        content=[{"type": "text", "text": text}] if text else [],
    )


def use(*calls: tuple[str, dict], thinking: bool = False) -> LLMResponse:
    """A scripted model turn that calls tools: ``use(("get_balance", {}), ...)``."""
    counter = use.counter = getattr(use, "counter", 0) + 1
    tool_calls = tuple(
        ToolCall(id=f"toolu_{counter}_{n}", name=name, input=arguments)
        for n, (name, arguments) in enumerate(calls)
    )
    content = [{"type": "thinking", "thinking": "", "signature": "sig"}] if thinking else []
    content += [
        {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in tool_calls
    ]
    return LLMResponse(stop_reason="tool_use", text="", tool_calls=tool_calls, content=content)


class ScriptedLLM:
    """A stand-in for the model that replays a script. Each step is a response, an exception
    to raise, or a function of the request that returns a response. Every request is recorded."""

    def __init__(self, *steps) -> None:
        self.steps = list(steps)
        self.requests: list[dict] = []

    def complete(self, *, system, messages, tools) -> LLMResponse:
        self.requests.append({"system": system, "messages": list(messages), "tools": tools})
        if not self.steps:
            raise AssertionError("The scripted model was asked for more turns than scripted")
        step = self.steps.pop(0)
        if isinstance(step, Exception):
            raise step
        if callable(step):
            return step(self.requests[-1])
        return step


def tool_results(request: dict) -> list[dict]:
    """The decoded tool results in the last message of a recorded request."""
    return [json.loads(block["content"]) for block in request["messages"][-1]["content"]]


class Clock:
    """A clock the test controls."""

    def __init__(self, start: dt.datetime) -> None:
        self.now = start

    def __call__(self) -> dt.datetime:
        return self.now

    def advance(self, **delta) -> None:
        self.now += dt.timedelta(**delta)


@pytest.fixture
def clock(now) -> Clock:
    return Clock(now)


@pytest.fixture
def audit_log(tmp_path) -> AuditLog:
    return AuditLog(tmp_path / "audit.jsonl")


@pytest.fixture
def world(make_env, guard_keys, clock, audit_log):
    """A simulated environment and a guard wired together on one controllable clock."""
    env = make_env(clock=clock)
    store = GuardStore()

    def make_guard(**options) -> GuardService:
        return GuardService(
            env,
            guard_keys[0],
            audit_log,
            business_id=env.business_id,
            currency=env.currency,
            store=store,
            clock=clock,
            **options,
        )

    guard = make_guard()

    def make_registry(principal: Principal, **options) -> ToolRegistry:
        return ToolRegistry(env, guard, principal, today=lambda: clock().date(), **options)

    def make_app(llm, **options) -> WaliApp:
        return WaliApp(
            env=env,
            guard=guard,
            llm=llm,
            business_id=env.business_id,
            currency=env.currency,
            clock=clock,
            **options,
        )

    return SimpleNamespace(
        env=env,
        store=store,
        audit=audit_log,
        clock=clock,
        guard=guard,
        make_guard=make_guard,
        make_registry=make_registry,
        make_app=make_app,
    )


@pytest.fixture
def ready(world, owner):
    """A world with the standard mandate active."""
    activate_mandate(world.guard, owner)
    return world


@pytest.fixture(scope="session")
def seed_generator():
    """The seed generator script, imported as a module."""
    path = REPO_ROOT / "scripts" / "gen_seed_data.py"
    spec = importlib.util.spec_from_file_location("gen_seed_data", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="session")
def guard_keys() -> tuple[str, str]:
    """A (private, public) guard key pair for the test session."""
    return generate_keypair()


@pytest.fixture(scope="session")
def ground_truth() -> dict:
    return json.loads((SEED_DIR / "ground_truth.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="session")
def principals() -> dict[str, Principal]:
    """One principal per role, read from the seed users so no id is hard-coded in tests."""
    return {
        row["role"]: Principal(user_id=row["id"], role=row["role"], business_id=row["business_id"])
        for row in read_csv("users")
    }


@pytest.fixture
def owner(principals) -> Principal:
    return principals["owner"]


@pytest.fixture
def bookkeeper(principals) -> Principal:
    return principals["bookkeeper"]


@pytest.fixture
def staff(principals) -> Principal:
    return principals["staff"]


@pytest.fixture
def now() -> dt.datetime:
    """The simulated current time: the morning after the last day of seed data."""
    return dt.datetime(2026, 10, 1, 9, 0, tzinfo=JAKARTA)


@pytest.fixture
def make_env(guard_keys, now):
    """Build fresh in-memory environments from the committed seed data."""
    created = []

    def factory(**options) -> SimEnvironment:
        options.setdefault("clock", lambda: now)
        env = SimEnvironment.create(SEED_DIR, guard_keys[1], **options)
        created.append(env)
        return env

    yield factory
    for env in created:
        env.close()


@pytest.fixture
def env(make_env) -> SimEnvironment:
    return make_env()


@pytest.fixture
def make_approval(guard_keys, now, owner):
    """Build a signed approval for an invoice the way the guard would, with optional overrides
    applied before signing. ``private_key`` signs with a different key."""
    counter = itertools.count(1)

    def factory(
        invoice: Invoice, supplier: Supplier, *, private_key: str | None = None, **overrides
    ) -> GuardApproval:
        fields = {
            "approval_id": f"ap-test-{next(counter):04d}",
            "proposal_hash": "test-proposal-hash",
            "business_id": owner.business_id,
            "invoice_id": invoice.id,
            "supplier_id": supplier.id,
            "amount": invoice.amount,
            "currency": invoice.currency,
            "destination_account": supplier.verified_account,
            "expires_at": now + dt.timedelta(minutes=5),
        }
        fields.update(overrides)
        unsigned = GuardApproval(**fields, signature="")
        key = load_private_key(private_key or guard_keys[0])
        signature = sign_payload(key, unsigned.signing_payload())
        return unsigned.model_copy(update={"signature": signature})

    return factory
