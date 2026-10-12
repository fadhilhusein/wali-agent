"""Generate the guard's Ed25519 signing key pair.

Usage:
    uv run python scripts/gen_guard_key.py --write-env        # writes both keys to .env
    uv run python scripts/gen_guard_key.py --write-env PATH   # writes to another env file
    uv run python scripts/gen_guard_key.py                    # prints both lines to stdout

With ``--write-env`` the private key is written to the file and never printed. An existing key
is not replaced unless ``--force`` is given, because replacing it invalidates every signed
mandate and approval.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from wali.guard.keys import generate_keypair

PRIVATE_VAR = "WALI_GUARD_PRIVATE_KEY"
PUBLIC_VAR = "WALI_GUARD_PUBLIC_KEY"


def _is_assignment(line: str, name: str) -> bool:
    return line.strip().startswith(f"{name}=")


def _is_key_line(line: str) -> bool:
    return _is_assignment(line, PRIVATE_VAR) or _is_assignment(line, PUBLIC_VAR)


def write_env(path: Path, private: str, public: str, force: bool) -> None:
    lines = path.read_text(encoding="utf-8").splitlines() if path.is_file() else []
    has_key = any(_is_key_line(ln) and ln.partition("=")[2].strip() for ln in lines)
    if has_key and not force:
        raise FileExistsError(f"{path} already holds a guard key. Use --force to replace it.")
    kept = [ln for ln in lines if not _is_key_line(ln)]
    kept += [f"{PRIVATE_VAR}={private}", f"{PUBLIC_VAR}={public}"]
    path.write_text("\n".join(kept) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the guard's Ed25519 key pair.")
    parser.add_argument(
        "--write-env",
        nargs="?",
        const=".env",
        default=None,
        metavar="PATH",
        help="write the keys to an env file (default .env) instead of printing them",
    )
    parser.add_argument("--force", action="store_true", help="replace an existing key")
    args = parser.parse_args(argv)

    private, public = generate_keypair()
    if args.write_env is None:
        print(f"{PRIVATE_VAR}={private}")
        print(f"{PUBLIC_VAR}={public}")
        return 0

    target = Path(args.write_env)
    try:
        write_env(target, private, public, args.force)
    except FileExistsError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Guard key written to {target}. Public key: {public}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
