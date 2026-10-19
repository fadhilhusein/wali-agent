"""Append-only, hash-chained audit log (JSON Lines).

Each entry stores the hash of the entry before it, and its own hash covers that value together
with its content: ``hash = sha256(prev_hash + canonical_json(entry_without_hash))``. Changing,
removing, or reordering any earlier entry therefore breaks every hash after it.

Limit: a chain alone cannot show that entries were cut off the END of the file. Detecting that
needs the latest hash to be kept somewhere else, which is out of scope here.

Callers must never put secrets (keys, signatures, confirmation tokens) into an entry.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import hashlib
import json
import os
import threading
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from wali.guard.signing import canonical_json
from wali.models import Principal

if os.name == "nt":
    import msvcrt
else:
    import fcntl

GENESIS_HASH = "0" * 64
_FIELDS = {"ts", "session_id", "principal", "event", "data", "prev_hash", "hash"}


class AuditError(RuntimeError):
    """The audit log is damaged or cannot be written."""


@dataclass(frozen=True)
class ChainStatus:
    ok: bool
    entries: int
    last_hash: str
    bad_line: int | None = None
    problem: str | None = None


def _jsonable(value: Any) -> Any:
    """Convert to plain JSON values. Floats are refused: money must be Decimal or str."""
    if value is None or isinstance(value, str | bool | int):
        return value
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dt.datetime | dt.date):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        items = [_jsonable(item) for item in value]
        return sorted(items, key=str) if isinstance(value, set | frozenset) else items
    raise TypeError(f"Cannot write a value of type {type(value).__name__} to the audit log")


def entry_hash(prev_hash: str, body: Mapping[str, Any]) -> str:
    return hashlib.sha256(prev_hash.encode("ascii") + canonical_json(dict(body))).hexdigest()


def verify_chain(path: Path | str) -> ChainStatus:
    """Check every entry of the log at ``path``. A missing file is an empty, valid log."""
    path = Path(path)
    prev = GENESIS_HASH
    count = 0
    if not path.is_file():
        return ChainStatus(ok=True, entries=0, last_hash=prev)

    def bad(line: int, problem: str) -> ChainStatus:
        return ChainStatus(ok=False, entries=count, last_hash=prev, bad_line=line, problem=problem)

    with path.open(encoding="utf-8") as handle:
        for line_number, raw in enumerate(handle, start=1):
            try:
                entry = json.loads(raw)
            except json.JSONDecodeError:
                return bad(line_number, "not valid JSON")
            if not isinstance(entry, dict) or set(entry) != _FIELDS:
                return bad(line_number, "unexpected fields")
            if entry["prev_hash"] != prev:
                return bad(line_number, "does not follow the previous entry")
            body = {key: value for key, value in entry.items() if key != "hash"}
            try:
                expected = entry_hash(prev, body)
            except TypeError:
                return bad(line_number, "content cannot be hashed")
            if entry["hash"] != expected:
                return bad(line_number, "content does not match its hash")
            prev = expected
            count += 1
    return ChainStatus(ok=True, entries=count, last_hash=prev)


@contextlib.contextmanager
def _locked(handle: Any) -> Iterator[None]:
    """An OS lock on the open log, so processes that share the file take turns."""
    if os.name == "nt":
        handle.seek(0)
        msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        try:
            yield
        finally:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
    else:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _last_hash(handle: Any) -> str:
    """The hash of the file's last entry, read from its end."""
    end = handle.seek(0, os.SEEK_END)
    if end == 0:
        return GENESIS_HASH
    tail, position = b"", end
    while position > 0:
        step = min(4096, position)
        position -= step
        handle.seek(position)
        tail = handle.read(step) + tail
        if tail.count(b"\n") >= 2 or position == 0:
            break
    if not tail.endswith(b"\n"):
        raise AuditError("The audit log ends in the middle of an entry.")
    last = tail[:-1].rsplit(b"\n", 1)[-1]
    try:
        found = json.loads(last)["hash"]
    except (ValueError, KeyError, TypeError):
        raise AuditError("The last entry of the audit log cannot be read.") from None
    if not isinstance(found, str):
        raise AuditError("The last entry of the audit log cannot be read.")
    return found


class AuditLog:
    def __init__(self, path: Path | str) -> None:
        """Open or create the log. Refuses to continue a log whose chain is already broken."""
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        status = verify_chain(self._path)
        if not status.ok:
            raise AuditError(
                f"Audit log {self._path} is damaged at line {status.bad_line}: {status.problem}"
            )

    @property
    def path(self) -> Path:
        return self._path

    def append(
        self,
        *,
        ts: dt.datetime,
        event: str,
        principal: Principal | str | None = None,
        data: Mapping[str, Any] | None = None,
        session_id: str = "",
    ) -> dict[str, Any]:
        """Write one entry and return it. Another process may share the file, so the previous
        hash is read from the file under a lock rather than remembered."""
        if ts.tzinfo is None:
            raise ValueError("Audit timestamps must be timezone-aware")
        content = {
            "ts": ts.isoformat(),
            "session_id": session_id,
            "principal": _jsonable(principal),
            "event": event,
            "data": _jsonable(data or {}),
        }
        with self._lock, self._path.open("a+b") as handle, _locked(handle):
            prev_hash = _last_hash(handle)
            body = {**content, "prev_hash": prev_hash}
            entry = {**body, "hash": entry_hash(prev_hash, body)}
            line = json.dumps(entry, sort_keys=True, ensure_ascii=False)
            handle.write(line.encode("utf-8") + b"\n")
            handle.flush()  # before the lock is released
            return entry

    def entries(self) -> list[dict[str, Any]]:
        if not self._path.is_file():
            return []
        with self._path.open(encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]
