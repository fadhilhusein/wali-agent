import datetime as dt
import json
import subprocess
import sys
from decimal import Decimal

import pytest

from wali.guard.audit import (
    GENESIS_HASH,
    AuditError,
    AuditLog,
    ChainStatus,
    entry_hash,
    verify_chain,
)
from wali.models import Money, Principal

T0 = dt.datetime(2026, 10, 1, 9, 0, tzinfo=dt.UTC)
OWNER = Principal(user_id="user-owner", role="owner", business_id="biz")


@pytest.fixture
def path(tmp_path):
    return tmp_path / "logs" / "audit.jsonl"


def fill(path, count=5) -> AuditLog:
    log = AuditLog(path)
    for n in range(count):
        log.append(
            ts=T0 + dt.timedelta(minutes=n),
            event="payment_proposed",
            principal=OWNER,
            data={"n": n, "amount": Decimal("1500000.50")},
            session_id="s-1",
        )
    return log


def lines(path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


def rewrite(path, new_lines) -> None:
    path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def test_missing_and_empty_logs_are_valid(path):
    assert verify_chain(path) == ChainStatus(ok=True, entries=0, last_hash=GENESIS_HASH)
    AuditLog(path)
    assert verify_chain(path).ok


def test_entries_have_the_required_fields_and_chain_together(path):
    log = fill(path, 3)
    first, second, third = log.entries()

    assert set(first) == {"ts", "session_id", "principal", "event", "data", "prev_hash", "hash"}
    assert first["prev_hash"] == GENESIS_HASH
    assert second["prev_hash"] == first["hash"]
    assert third["prev_hash"] == second["hash"]
    assert first["principal"] == {"user_id": "user-owner", "role": "owner", "business_id": "biz"}
    assert first["data"] == {"n": 0, "amount": "1500000.50"}
    assert first["session_id"] == "s-1"

    status = verify_chain(path)
    assert (status.ok, status.entries, status.last_hash) == (True, 3, third["hash"])


def test_values_are_converted_and_floats_are_refused(path):
    log = AuditLog(path)
    entry = log.append(
        ts=T0,
        event="x",
        principal="guard",
        data={
            "money": Money(amount=Decimal("5"), currency="IDR"),
            "day": dt.date(2026, 10, 1),
            "tags": {"b", "a"},
            "nested": [{"amount": Decimal("1.10")}],
        },
    )

    assert entry["principal"] == "guard"
    assert entry["data"] == {
        "money": {"amount": "5", "currency": "IDR"},
        "day": "2026-10-01",
        "tags": ["a", "b"],
        "nested": [{"amount": "1.10"}],
    }
    with pytest.raises(TypeError):
        log.append(ts=T0, event="x", data={"amount": 1.5})
    with pytest.raises(ValueError):
        log.append(ts=dt.datetime(2026, 10, 1, 9, 0), event="x")
    assert verify_chain(path).entries == 1


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event", "payment_executed"),
        ("data", {"n": 2, "amount": "1.00"}),
        ("principal", {"user_id": "user-staff", "role": "owner", "business_id": "biz"}),
        ("ts", "2026-10-01T00:00:00+00:00"),
        ("session_id", "s-2"),
    ],
)
def test_changing_any_field_of_an_entry_is_detected(path, field, value):
    fill(path)
    rows = lines(path)
    entry = json.loads(rows[2])
    entry[field] = value
    rows[2] = json.dumps(entry, sort_keys=True)
    rewrite(path, rows)

    status = verify_chain(path)
    assert (status.ok, status.bad_line) == (False, 3)
    assert status.entries == 2


def test_recomputing_one_hash_after_a_change_is_still_detected(path):
    """An attacker who fixes the hash of the changed entry breaks the link to the next one."""
    fill(path)
    rows = lines(path)
    entry = json.loads(rows[1])
    entry["data"] = {"n": 1, "amount": "9"}
    body = {k: v for k, v in entry.items() if k != "hash"}
    entry["hash"] = entry_hash(entry["prev_hash"], body)
    rows[1] = json.dumps(entry, sort_keys=True)
    rewrite(path, rows)

    status = verify_chain(path)
    assert (status.ok, status.bad_line) == (False, 3)


def test_an_entry_that_lies_about_its_predecessor_is_detected(path):
    """The stored ``prev_hash`` must itself be right, even when the entry's own hash was
    computed from the true previous hash."""
    log = fill(path, 2)
    true_prev = log.entries()[-1]["hash"]
    body = {
        "ts": T0.isoformat(),
        "session_id": "",
        "principal": None,
        "event": "forged",
        "data": {},
        "prev_hash": "f" * 64,
    }
    forged = {**body, "hash": entry_hash(true_prev, body)}
    rewrite(path, [*lines(path), json.dumps(forged, sort_keys=True)])

    status = verify_chain(path)
    assert (status.ok, status.bad_line) == (False, 3)
    assert status.problem == "does not follow the previous entry"


def test_removing_reordering_or_inserting_entries_is_detected(path):
    fill(path)
    original = lines(path)

    rewrite(path, original[:2] + original[3:])
    assert verify_chain(path).bad_line == 3

    rewrite(path, [original[1], original[0], *original[2:]])
    assert verify_chain(path).bad_line == 1

    rewrite(path, [*original[:2], original[1], *original[2:]])
    assert verify_chain(path).bad_line == 3

    rewrite(path, original)
    assert verify_chain(path).ok


@pytest.mark.parametrize("junk", ["not json", "[]", '{"event": "x"}', ""])
def test_malformed_lines_are_detected(path, junk):
    fill(path, 2)
    rewrite(path, [*lines(path), junk])

    status = verify_chain(path)
    assert (status.ok, status.bad_line, status.entries) == (False, 3, 2)


def test_a_reopened_log_continues_the_same_chain(path):
    fill(path, 2)
    reopened = AuditLog(path)
    reopened.append(ts=T0, event="later", principal=None)

    status = verify_chain(path)
    assert (status.ok, status.entries) == (True, 3)
    assert reopened.entries()[2]["prev_hash"] == reopened.entries()[1]["hash"]


def test_a_damaged_log_is_not_continued(path):
    fill(path, 3)
    rows = lines(path)
    rows[1] = rows[1].replace("payment_proposed", "payment_executed")
    rewrite(path, rows)

    with pytest.raises(AuditError, match="line 2"):
        AuditLog(path)


def test_two_logs_on_one_file_keep_a_single_chain(path):
    """The web page, CLI and Telegram bot may share one data folder, each with its own log."""
    first, second = AuditLog(path), AuditLog(path)

    for n in range(3):
        first.append(ts=T0, event="from_first", data={"n": n})
        second.append(ts=T0, event="from_second", data={"n": n})

    status = verify_chain(path)
    assert (status.ok, status.entries) == (True, 6)


WRITER = """
import datetime as dt, sys
from wali.guard.audit import AuditLog
log = AuditLog(sys.argv[1])
for n in range(400):
    log.append(ts=dt.datetime(2026, 10, 1, tzinfo=dt.UTC), event=sys.argv[2], data={"n": n})
"""


def test_processes_writing_at_the_same_time_keep_a_single_chain(path):
    AuditLog(path)
    writers = [
        subprocess.Popen([sys.executable, "-c", WRITER, str(path), name])
        for name in ("a", "b", "c")
    ]
    assert [writer.wait(timeout=60) for writer in writers] == [0, 0, 0]

    status = verify_chain(path)
    assert (status.ok, status.entries) == (True, 1200)


def test_a_log_cut_in_the_middle_of_a_line_is_not_continued(path):
    log = fill(path, 2)
    with path.open("a", encoding="utf-8") as handle:
        handle.write('{"ts": "2026-')

    with pytest.raises(AuditError):
        log.append(ts=T0, event="later")
