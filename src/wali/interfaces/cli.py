"""A local chat for development and demos. SIMULATION ONLY.

    uv run python -m wali.interfaces.cli --role owner

The role is chosen here, at the interface, with ``--role`` or ``/role``. This stands in for real
authentication in the demo. Typing "I am the owner" into the chat changes nothing.

Confirmation is a command, not a chat message: ``/confirm`` and ``/cancel`` go straight to the
guard and never pass through the model.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable, Mapping

from wali.app import SetupError, WaliApp, build_app
from wali.config import ConfigError, load_settings
from wali.interfaces.common import SIMULATION_NOTE, describe, draft_demo_mandate
from wali.models import Principal
from wali.tools.base import ToolFailure

ROLES = ("owner", "bookkeeper", "staff")
HELP = """Commands:
  /role <owner|bookkeeper|staff>   switch who you are (demo stand-in for logging in)
  /pending                         show what is waiting for your confirmation
  /confirm [n]                     confirm item n (default 1)
  /cancel [n]                      decline item n (default 1)
  /mandate                         draft the demo spending mandate (owner only)
  /review                          show invoices flagged for review (owner only)
  /reset                           start a fresh conversation
  /help                            show this help
  /quit                            leave"""


def run_cli(
    app: WaliApp,
    principals: Mapping[str, Principal],
    *,
    role: str = "owner",
    input_fn: Callable[[str], str] = input,
    output_fn: Callable[[str], None] = print,
) -> None:
    """The read-answer loop. ``input_fn`` and ``output_fn`` are replaceable for tests."""
    principal = principals[role]
    # The items as last listed: /confirm 2 means the second item the person saw, even if the
    # list has changed since.
    shown: list[str] = []

    def show_pending(*, announce_empty: bool = False) -> None:
        waiting = app.pending(principal)
        shown[:] = [request.subject_id for request in waiting]
        if not waiting:
            if announce_empty:
                output_fn("Nothing is waiting for your confirmation.")
            return
        for number, request in enumerate(waiting, start=1):
            output_fn(describe(request, number))
        output_fn("Type /confirm or /cancel (add a number to pick one).")

    def number_from(argument: str) -> int | None:
        if not argument:
            return 1
        return int(argument) if argument.isdigit() and int(argument) > 0 else None

    output_fn(f"Wali. {SIMULATION_NOTE} Type /help for commands.")
    output_fn(f"You are: {principal.role} ({principal.user_id})")
    if not app.sentinel_model_enabled:
        output_fn(
            "(Screening of outside text runs on built-in rules only. Set WALI_SENTINEL_MODEL "
            "to add the model check.)"
        )

    while True:
        try:
            line = input_fn(f"{principal.role}> ").strip()
        except (EOFError, KeyboardInterrupt):
            output_fn("")
            return
        if not line:
            continue

        if not line.startswith("/"):
            result = app.chat(principal, line)
            output_fn(f"wali> {result.reply.text}")
            if result.reply.blocked:
                output_fn("(The assistant's answer was blocked by the outgoing check.)")
            for request in result.new_confirmations:
                if request.required_role != principal.role:
                    output_fn(
                        f"(A {request.kind} confirmation was sent to the "
                        f"{request.required_role}. Use /role {request.required_role} to act on it.)"
                    )
            if any(r.required_role == principal.role for r in result.new_confirmations):
                show_pending()
            continue

        command, _, argument = line.partition(" ")
        argument = argument.strip()
        if command in ("/quit", "/exit"):
            return
        if command == "/help":
            output_fn(HELP)
        elif command == "/role":
            if argument not in principals:
                output_fn(f"Choose one of: {', '.join(sorted(principals))}")
                continue
            principal = principals[argument]
            output_fn(f"You are now: {principal.role} ({principal.user_id})")
            show_pending()
        elif command == "/pending":
            show_pending(announce_empty=True)
        elif command in ("/confirm", "/cancel"):
            number = number_from(argument)
            if number is None:
                output_fn("Give the number of the item, for example /confirm 1")
            elif number > len(shown):
                output_fn(
                    "There is no such item waiting for you."
                    if command == "/confirm"
                    else "Nothing to decline."
                )
            elif command == "/confirm":
                decision = app.confirm(principal, subject_id=shown[number - 1])
                output_fn(
                    "That item is no longer waiting. Type /pending to see the list again."
                    if decision is None
                    else f"guard> {decision.user_message}"
                )
                show_pending()
            else:
                declined = app.cancel(principal, subject_id=shown[number - 1])
                output_fn(
                    "Declined."
                    if declined
                    else "That item is no longer waiting. Type /pending to see the list again."
                )
        elif command == "/mandate":
            try:
                decision = draft_demo_mandate(app, principal)
            except (PermissionError, ToolFailure):
                output_fn("Only the owner can set the mandate.")
                continue
            output_fn(f"guard> {decision.user_message}")
            show_pending()
        elif command == "/review":
            items = app.guard.review_items(principal)
            if not items:
                output_fn("Nothing is flagged (or your role cannot see the list).")
            for item in items:
                output_fn(f"- {item.invoice_id} [{item.reason_code}] {item.reason}")
        elif command == "/reset":
            app.reset(principal)
            output_fn("Started a fresh conversation.")
        else:
            output_fn("Unknown command. Type /help.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Chat with Wali locally (simulation only).")
    parser.add_argument("--role", choices=ROLES, default="owner")
    args = parser.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    try:
        app = build_app(load_settings())
    except (SetupError, ConfigError) as error:
        print(f"Cannot start: {error}", file=sys.stderr)
        return 1
    run_cli(app, app.env.principals(), role=args.role)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
