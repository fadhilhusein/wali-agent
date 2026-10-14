"""The Telegram front end. SIMULATION ONLY.

    uv run python -m wali.interfaces.telegram_bot

Who someone is comes from their Telegram user id, set in ``WALI_TELEGRAM_USERS``, and never from
anything they type. Each listed id is linked to a user of the environment, whose role and
business come from the environment's own user table. Messages from ids that are not listed get
no answer at all.

A payment or mandate that needs the owner is sent to every Telegram account linked to an owner,
with Confirm and Decline buttons. A button carries only the id of the request; the confirmation
token stays inside the application, and the guard checks the person pressing the button again.

``WaliBot`` holds all the behaviour and knows nothing about Telegram's network API, so it is
tested directly. The functions at the bottom connect it to ``python-telegram-bot``.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import re
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from wali.app import SetupError, WaliApp, build_app
from wali.config import ConfigError, load_settings
from wali.guard.service import ConfirmationRequest, MandateDecision, PaymentDecision
from wali.interfaces.common import SIMULATION_NOTE, describe, draft_demo_mandate
from wali.models import Principal
from wali.tools.base import ToolFailure

log = logging.getLogger("wali.telegram")

CHANNEL = "telegram"
CONFIRM, DECLINE = "ok", "no"
# Telegram allows 4096 characters per message; leave room for the parts we add.
MAX_CHARS = 4000
MAX_FAILURES_INJECTED = 5

HELP = """Commands:
/pending  show what is waiting for you, with buttons
/mandate  draft the demo spending mandate (owner only)
/review   show invoices flagged for review (owner only)
/reset    start a fresh conversation
/as ROLE  switch between the users linked to your Telegram account
/simfail METHOD [N]  make the next N calls of METHOD in the simulation fail (owner only)
/help     show this help

Anything else you type goes to the assistant."""


class UserMapError(ValueError):
    """``WALI_TELEGRAM_USERS`` is not valid. The message says what is wrong."""


def parse_user_map(text: str | None) -> dict[int, tuple[str, ...]]:
    """Read ``"111=user-owner, 222=user-bookkeeper|user-staff"``: Telegram user ids and the
    user ids they act as. The first user listed for an id is the one it starts as."""
    mapping: dict[int, tuple[str, ...]] = {}
    for number, entry in enumerate(re.split(r"[,;\n]", text or ""), start=1):
        entry = entry.strip()
        if not entry:
            continue
        telegram_id, separator, users = entry.partition("=")
        telegram_id = telegram_id.strip()
        if not separator or not telegram_id.isdigit() or int(telegram_id) <= 0:
            raise UserMapError(
                f"WALI_TELEGRAM_USERS entry {number} must look like 123456789=user-owner"
            )
        user_ids = tuple(u.strip() for u in users.split("|"))
        if not all(user_ids) or len(set(user_ids)) != len(user_ids):
            raise UserMapError(f"WALI_TELEGRAM_USERS entry {number} has an empty or repeated user")
        if int(telegram_id) in mapping:
            raise UserMapError(f"WALI_TELEGRAM_USERS lists Telegram id {telegram_id} twice")
        mapping[int(telegram_id)] = user_ids
    return mapping


def resolve_users(
    mapping: Mapping[int, Sequence[str]], known: Mapping[str, Principal]
) -> dict[int, tuple[Principal, ...]]:
    """Turn user ids into principals, using the environment's own record of each user's role
    and business. A user id the environment does not know is an error, not a guess."""
    unknown = sorted({u for users in mapping.values() for u in users if u not in known})
    if unknown:
        raise UserMapError(f"WALI_TELEGRAM_USERS names users that do not exist: {unknown}")
    return {tid: tuple(known[u] for u in users) for tid, users in mapping.items()}


@dataclass(frozen=True)
class Button:
    label: str
    data: str


@dataclass(frozen=True)
class Outgoing:
    """One message to send to one Telegram account."""

    chat_id: int
    text: str
    buttons: tuple[Button, ...] = ()


@dataclass(frozen=True)
class ButtonResult:
    """What pressing a button leads to: a short notice for the presser, a line to add to the
    message that held the buttons (which then loses them), and messages for others."""

    notice: str
    resolution: str | None = None
    messages: tuple[Outgoing, ...] = ()


def label(request: ConfirmationRequest) -> str:
    """A one-line name for a request."""
    summary = request.summary
    if summary is None:
        return f"{request.kind} {request.subject_id}"
    return (
        f"payment of {summary.amount:,} {summary.currency} to {summary.supplier_name} "
        f"for invoice {summary.invoice_number}"
    )


def split_text(text: str, limit: int = MAX_CHARS) -> list[str]:
    """Cut a long text into messages Telegram accepts, at line breaks where possible."""
    parts: list[str] = []
    while len(text) > limit:
        cut = text.rfind("\n", 0, limit)
        cut = cut if cut > 0 else limit
        parts.append(text[:cut])
        text = text[cut:].lstrip("\n")
    parts.append(text)
    return parts


class WaliBot:
    def __init__(self, app: WaliApp, users: Mapping[int, Sequence[Principal]]) -> None:
        if not users:
            raise UserMapError("WALI_TELEGRAM_USERS lists nobody, so the bot would answer no one")
        self._app = app
        self._users = {tid: tuple(principals) for tid, principals in users.items()}
        self._active = {tid: principals[0] for tid, principals in self._users.items()}

    def knows(self, telegram_id: int) -> bool:
        return telegram_id in self._users

    def principal_of(self, telegram_id: int) -> Principal | None:
        """Who this Telegram account is acting as right now."""
        return self._active.get(telegram_id)

    # --- Messages ------------------------------------------------------------------------

    def on_message(self, telegram_id: int, text: str) -> list[Outgoing]:
        """Handle a text message. Returns nothing at all for an account that is not listed."""
        principal = self.principal_of(telegram_id)
        text = (text or "").strip()
        if principal is None or not text:
            return []
        if text.startswith("/"):
            return self._command(telegram_id, principal, text)
        result = self._app.chat(principal, text, channel=CHANNEL)
        replies = [Outgoing(telegram_id, part) for part in split_text(result.reply.text)]
        return replies + self._announce(result.new_confirmations, telegram_id)

    def _say(self, telegram_id: int, text: str) -> list[Outgoing]:
        return [Outgoing(telegram_id, part) for part in split_text(text)]

    def _command(self, telegram_id: int, principal: Principal, text: str) -> list[Outgoing]:
        command, _, argument = text.partition(" ")
        command = command.split("@", 1)[0].lower()  # "/help@SomeBot" in some clients
        argument = argument.strip()

        if command in ("/start", "/help"):
            return self._say(telegram_id, f"{self._whoami(telegram_id)}\n\n{HELP}")
        if command == "/pending":
            return self._show_pending(telegram_id, principal)
        if command == "/as":
            return self._switch(telegram_id, argument)
        if command == "/reset":
            self._app.reset(principal, channel=CHANNEL)
            return self._say(telegram_id, "Started a fresh conversation.")
        if command == "/mandate":
            return self._mandate(telegram_id, principal)
        if command == "/review":
            return self._review(telegram_id, principal)
        if command == "/simfail":
            return self._simfail(telegram_id, principal, argument)
        return self._say(telegram_id, "Unknown command. Type /help.")

    def _whoami(self, telegram_id: int) -> str:
        principal = self._active[telegram_id]
        lines = [f"Wali. {SIMULATION_NOTE}", f"You are: {principal.role} ({principal.user_id})"]
        if not self._app.sentinel_model_enabled:
            lines.append("Screening of outside text runs on built-in rules only.")
        if len(self._users[telegram_id]) > 1:
            roles = ", ".join(p.role for p in self._users[telegram_id])
            lines.append(f"This Telegram account may act as: {roles}. Switch with /as ROLE.")
        return "\n".join(lines)

    def _switch(self, telegram_id: int, role: str) -> list[Outgoing]:
        """Switch among the users configured for this account. Nothing typed can add one."""
        linked = self._users[telegram_id]
        chosen = next((p for p in linked if p.role == role.lower()), None)
        if chosen is None:
            roles = ", ".join(p.role for p in linked)
            return self._say(telegram_id, f"This Telegram account may act as: {roles}.")
        self._active[telegram_id] = chosen
        replies = self._say(telegram_id, f"You are now: {chosen.role} ({chosen.user_id})")
        return replies + self._show_pending(telegram_id, chosen, quiet=True)

    def _show_pending(
        self, telegram_id: int, principal: Principal, *, quiet: bool = False
    ) -> list[Outgoing]:
        waiting = self._app.pending(principal)
        if not waiting:
            return [] if quiet else self._say(telegram_id, "Nothing is waiting for you.")
        return [self._request_message(telegram_id, request) for request in waiting]

    def _mandate(self, telegram_id: int, principal: Principal) -> list[Outgoing]:
        if principal.role != "owner":
            return self._say(telegram_id, "Only the owner can set the mandate.")
        try:
            decision = draft_demo_mandate(self._app, principal)
        except (PermissionError, ToolFailure):
            return self._say(telegram_id, "The mandate could not be drafted. Please try again.")
        replies = self._say(telegram_id, decision.user_message)
        drafted = [r for r in self._app.pending(principal) if r.subject_id == decision.mandate_id]
        return replies + self._announce(drafted, telegram_id)

    def _review(self, telegram_id: int, principal: Principal) -> list[Outgoing]:
        items = self._app.guard.review_items(principal)
        if not items:
            return self._say(telegram_id, "Nothing is flagged (or your role cannot see the list).")
        lines = [f"- {i.invoice_id} [{i.reason_code}] {i.reason}" for i in items]
        return self._say(telegram_id, "Flagged for review:\n" + "\n".join(lines))

    def _simfail(self, telegram_id: int, principal: Principal, argument: str) -> list[Outgoing]:
        """For the demo of a failing tool. Works only on the simulated environment."""
        inject = getattr(self._app.env, "inject_failure", None)
        if principal.role != "owner" or inject is None:
            return self._say(telegram_id, "Only the owner can do this, and only in the simulation.")
        method, _, times = argument.partition(" ")
        count = int(times) if times.strip().isdigit() else 1
        if not 1 <= count <= MAX_FAILURES_INJECTED:
            return self._say(telegram_id, f"Give a number from 1 to {MAX_FAILURES_INJECTED}.")
        try:
            inject(method.strip(), count)
        except ValueError:
            return self._say(
                telegram_id,
                "Unknown method. Try list_transactions, get_book_entries, list_invoices, "
                "get_balance, or get_supplier.",
            )
        return self._say(
            telegram_id,
            f"Simulation: the next {count} call(s) of {method.strip()} will fail. A tool retries "
            "once, so use 2 to see a tool give up.",
        )

    # --- Confirmation requests -----------------------------------------------------------

    def _request_message(self, telegram_id: int, request: ConfirmationRequest) -> Outgoing:
        text = describe(request)
        active = self._active[telegram_id]
        if active.role != request.required_role:
            text += f"\n(You are acting as {active.role}. Use /as {request.required_role} first.)"
        buttons = (
            Button("Confirm", f"{CONFIRM}:{request.subject_id}"),
            Button("Decline", f"{DECLINE}:{request.subject_id}"),
        )
        return Outgoing(telegram_id, text, buttons)

    def _accounts_with(self, role: str, business_id: str) -> list[int]:
        return [
            tid
            for tid, principals in self._users.items()
            if any(p.role == role and p.business_id == business_id for p in principals)
        ]

    def _accounts_of(self, user_id: str) -> list[int]:
        return [
            tid
            for tid, principals in self._users.items()
            if any(p.user_id == user_id for p in principals)
        ]

    def _announce(self, requests: Sequence[ConfirmationRequest], requester: int) -> list[Outgoing]:
        """Send each new request, with buttons, to everyone who may confirm it, and tell the
        person who asked where it went."""
        messages: list[Outgoing] = []
        for request in requests:
            recipients = self._accounts_with(request.required_role, request.business_id)
            messages += [self._request_message(tid, request) for tid in recipients]
            if not recipients:
                messages.append(
                    Outgoing(
                        requester,
                        f"No {request.required_role} is linked to this bot, so nobody can "
                        "confirm this request. Nothing was paid or changed.",
                    )
                )
            elif requester not in recipients:
                messages.append(
                    Outgoing(
                        requester,
                        f"Sent to the {request.required_role} for confirmation. "
                        "Nothing has happened yet.",
                    )
                )
        return messages

    def on_button(self, telegram_id: int, data: str) -> ButtonResult | None:
        """Handle a button press. Returns None for an account that is not listed. The data
        comes from the client and is treated as a claim: it only names a request, and only a
        request waiting for this person's current role can be acted on."""
        principal = self.principal_of(telegram_id)
        if principal is None:
            return None
        action, _, subject_id = (data or "").partition(":")
        if action not in (CONFIRM, DECLINE) or not subject_id:
            return ButtonResult("This button is not valid.")
        request = next(
            (r for r in self._app.pending(principal) if r.subject_id == subject_id), None
        )
        if request is None:
            return ButtonResult(
                f"Nothing is waiting for you under this button (you are acting as "
                f"{principal.role}). It may be done, declined, expired, or for another role."
            )

        if action == DECLINE:
            declined = self._app.cancel(principal, channel=CHANNEL, subject_id=subject_id)
            if not declined:
                return ButtonResult("This request could not be declined. It may have expired.")
            outcome = f"Declined by {principal.role}. Nothing was paid or changed."
            return ButtonResult(
                "Declined.",
                f"\n\n{outcome}",
                tuple(self._tell_requester(request, principal, outcome)),
            )

        decision = self._app.confirm(principal, channel=CHANNEL, subject_id=subject_id)
        if decision is None:
            return ButtonResult("This request is no longer waiting.")
        outcome = f"{principal.role.capitalize()} pressed Confirm. Guard: {decision.user_message}"
        messages = self._tell_requester(request, principal, outcome)
        if self._asks_again(decision):
            # The situation changed since the request was made; the guard asks again.
            again = [r for r in self._app.pending(principal) if r.subject_id == subject_id]
            messages += self._announce(again, telegram_id)
        return ButtonResult(self._short(decision), f"\n\n{outcome}", tuple(messages))

    @staticmethod
    def _asks_again(decision: PaymentDecision | MandateDecision) -> bool:
        return decision.status == "needs_confirmation"

    @staticmethod
    def _short(decision: PaymentDecision | MandateDecision) -> str:
        return {
            "executed": "Paid.",
            "active": "Mandate is active.",
            "needs_confirmation": "Please look again: the guard asks for a new confirmation.",
        }.get(decision.status, "Not done. See the message.")

    def _tell_requester(
        self, request: ConfirmationRequest, decider: Principal, outcome: str
    ) -> list[Outgoing]:
        if request.requested_by == decider.user_id:
            return []
        return [
            Outgoing(tid, f"Your request: {label(request)}\n{outcome}")
            for tid in self._accounts_of(request.requested_by)
        ]


# --- python-telegram-bot ------------------------------------------------------------------


def _keyboard(buttons: Sequence[Button]):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup

    if not buttons:
        return None
    return InlineKeyboardMarkup(
        [[InlineKeyboardButton(b.label, callback_data=b.data) for b in buttons]]
    )


async def send(telegram, message: Outgoing) -> None:
    """Send one message. A recipient who never opened a chat with the bot cannot be reached;
    that is logged and skipped."""
    from telegram.error import TelegramError

    try:
        await telegram.send_message(
            chat_id=message.chat_id, text=message.text, reply_markup=_keyboard(message.buttons)
        )
    except TelegramError as error:
        log.warning("Could not send to Telegram id %s: %s", message.chat_id, error)


def make_handlers(bot: WaliBot):
    """The two update handlers, as plain coroutines so they can be tested without Telegram."""
    from telegram.constants import ChatAction

    async def on_text(update, context) -> None:
        user, message = update.effective_user, update.message
        if user is None or message is None or message.text is None:
            return
        if not bot.knows(user.id):
            log.info("Ignored a message from Telegram id %s (not in WALI_TELEGRAM_USERS)", user.id)
            return
        await context.bot.send_chat_action(chat_id=message.chat_id, action=ChatAction.TYPING)
        # The application blocks while the model thinks; keep the event loop free meanwhile.
        for outgoing in await asyncio.to_thread(bot.on_message, user.id, message.text):
            await send(context.bot, outgoing)

    async def on_press(update, context) -> None:
        query = update.callback_query
        if query is None:
            return
        result = await asyncio.to_thread(bot.on_button, query.from_user.id, query.data or "")
        if result is None:
            await query.answer()
            return
        await query.answer(result.notice[:200])
        if result.resolution and query.message is not None:
            text = (getattr(query.message, "text", None) or "") + result.resolution
            await query.edit_message_text(text=split_text(text)[0])
        for outgoing in result.messages:
            await send(context.bot, outgoing)

    return on_text, on_press


def build_application(bot: WaliBot, token: str):
    from telegram.ext import Application, CallbackQueryHandler, MessageHandler, filters

    application = Application.builder().token(token).build()
    on_text, on_press = make_handlers(bot)
    # Private chats only: in a group, replies would reach people who are not the principal.
    application.add_handler(MessageHandler(filters.TEXT & filters.ChatType.PRIVATE, on_text))
    application.add_handler(CallbackQueryHandler(on_press))
    return application


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Wali as a Telegram bot (simulation only).")
    parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    # The HTTP client logs every request URL, and those URLs contain the bot token.
    logging.getLogger("httpx").setLevel(logging.WARNING)

    try:
        settings = load_settings()
        if settings.telegram_bot_token is None:
            raise SetupError("Set WALI_TELEGRAM_BOT_TOKEN in the .env file (from @BotFather).")
        app = build_app(settings)
        users_of = getattr(app.env, "users", None)
        if users_of is None:
            raise SetupError("This environment cannot list its users for the Telegram mapping.")
        users = resolve_users(parse_user_map(settings.telegram_users), users_of())
        bot = WaliBot(app, users)
    except (SetupError, ConfigError, UserMapError) as error:
        print(f"Cannot start: {error}", file=sys.stderr)
        return 1

    for tid, principals in users.items():
        print(f"Telegram id {tid}: {', '.join(f'{p.role} ({p.user_id})' for p in principals)}")
    print(f"{SIMULATION_NOTE} Bot running; press Ctrl+C to stop.")
    build_application(bot, settings.telegram_bot_token.get_secret_value()).run_polling(
        allowed_updates=["message", "callback_query"]
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
