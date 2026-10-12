import csv
import datetime as dt
import importlib.util
import itertools
import json
import sys
from pathlib import Path

import pytest

from wali.guard.keys import generate_keypair, load_private_key
from wali.guard.signing import sign_payload
from wali.models import GuardApproval, Invoice, Principal, Supplier
from wali.tools.sim_env import SimEnvironment

REPO_ROOT = Path(__file__).resolve().parents[1]
SEED_DIR = REPO_ROOT / "data" / "seed"
JAKARTA = dt.timezone(dt.timedelta(hours=7))


def read_csv(name: str, seed_dir: Path = SEED_DIR) -> list[dict[str, str]]:
    with (seed_dir / f"{name}.csv").open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


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
