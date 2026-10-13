"""Deterministic helpers behind the dialogue behaviours.

The model decides what to say. These helpers take over the parts that should not depend on a
model getting them right:

- ``period_hints``: the dates behind "this week", "last month" and so on, worked out by code
  and given to the model, so that a period is never guessed.
- ``is_correction``: recognises "eh salah, bayar yang kopi aja", so an earlier pending payment
  request can be withdrawn when the corrected one is proposed.
- ``fallback_hint``: what else can be offered when a tool keeps failing.
- ``plain_text``: removes Markdown markup from a reply, because chat apps show it literally.

The remaining behaviours (one clarifying question, confirming a vague reference before acting)
are prompt rules; see ``wali.agent.prompts``.
"""

from __future__ import annotations

import datetime as dt
import re

ONE_DAY = dt.timedelta(days=1)

Period = tuple[dt.date, dt.date]


def period_hints(today: dt.date) -> dict[str, Period]:
    """Common periods as (first day, last day), both inclusive. Weeks run Monday to Sunday.
    "This week" and "this month" end today, because later days have not happened yet."""
    week_start = today - dt.timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    last_month_end = month_start - ONE_DAY
    return {
        "today": (today, today),
        "yesterday": (today - ONE_DAY, today - ONE_DAY),
        "this week": (week_start, today),
        "last week": (week_start - dt.timedelta(days=7), week_start - ONE_DAY),
        "this month": (month_start, today),
        "last month": (last_month_end.replace(day=1), last_month_end),
        "last 7 days": (today - dt.timedelta(days=6), today),
        "last 30 days": (today - dt.timedelta(days=29), today),
    }


def render_period_hints(today: dt.date) -> str:
    """The period table as lines for the system prompt."""
    lines = [
        f"- {name}: {start.isoformat()} to {end.isoformat()}"
        if start != end
        else f"- {name}: {start.isoformat()}"
        for name, (start, end) in period_hints(today).items()
    ]
    return "\n".join(lines)


# Words that mark a message as correcting what was just asked. Kept specific on purpose: a
# plain "aja" or "saja" is not enough, because "bayar yang susu aja" is often a new request.
_CORRECTION_PATTERNS = (
    r"\bsalah\b(?!\s+satu)",  # "salah satu" means "one of", not "wrong"
    r"\bkeliru\b",
    r"\bralat\b",
    r"\bkoreksi\b",
    r"\brevisi\b",
    r"\bmaksud(?:ku|nya|ny|\s+(?:saya|aku|gue|gw))\b",
    r"\bbukan\s+(?:yang|yg)\b",
    r"\bbukan\s+itu\b",
    r"\bganti\b",
    r"\btukar\b",
    r"\bwrong\b",
    r"\bmistake\b",
    r"\bi\s+meant\b",
    r"\bnot\s+that\b",
    r"\binstead\b",
    r"\bcorrection\b",
    r"\btypo\b",
)
_CORRECTION = re.compile("|".join(_CORRECTION_PATTERNS), re.IGNORECASE)


def is_correction(text: str) -> bool:
    """True when the message reads as a correction of the previous request."""
    return bool(_CORRECTION.search(text))


_FALLBACK_HINTS = {
    "reconcile_period": (
        "Offer to show the bank transactions for the period with list_transactions so the "
        "person can check them by eye, or to try the reconciliation again in a moment."
    ),
    "forecast_cashflow": (
        "Offer the current balance with get_balance and the open supplier invoices due soon "
        "with list_invoices, or to try the forecast again in a moment. Do not estimate a "
        "forecast yourself."
    ),
    "list_transactions": "Offer to try again in a moment, or to look at a shorter period.",
    "list_invoices": "Offer to try again in a moment.",
    "get_balance": "Offer to try again in a moment.",
    "get_supplier": "Offer to try again in a moment.",
}


def fallback_hint(tool_name: str) -> str | None:
    """What to offer the person when this tool has failed even after a retry."""
    return _FALLBACK_HINTS.get(tool_name)


# --- Checking a reply before it is shown ---------------------------------------------------

AUTOMATIC_CHECK_PREFIX = "[automatic check]"
UNVERIFIED_FIGURES_NOTE = (
    "\n\n(Catatan: angka berikut tidak bisa saya cocokkan dengan data, mohon dicek ulang: "
    "{figures}. / Note: I could not match these figures to the data, please double-check: "
    "{figures}.)"
)

_GROUPED_NUMBER = re.compile(r"(?<![\w.,])\d{1,3}(?:[.,]\d{3})+(?![\d])")
_LONG_NUMBER = re.compile(r"(?<![\w/.,-])\d{5,}(?![\w/-])")
_PLAIN_LITERAL = re.compile(r"\d+(?:\.\d+)?")
_SPOKEN_AMOUNT = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(rb|ribu|k|jt|juta|m|miliar|milyar)\b", re.IGNORECASE
)
_MULTIPLIERS = {
    "rb": 1_000,
    "ribu": 1_000,
    "k": 1_000,
    "jt": 1_000_000,
    "juta": 1_000_000,
    "m": 1_000_000,
    "miliar": 1_000_000_000,
    "milyar": 1_000_000_000,
}


def _grouped_to_int(text: str) -> int:
    return int(text.replace(".", "").replace(",", ""))


def figures_in(text: str) -> dict[int, str]:
    """Money-like figures written in a reply: numbers with thousands separators (2.910.000,
    8,214) and plain runs of five or more digits. Invoice numbers, ids, dates, and masked
    accounts are not matched. Returns value -> the text as written."""
    found: dict[int, str] = {}
    for match in _GROUPED_NUMBER.finditer(text):
        found.setdefault(_grouped_to_int(match.group()), match.group())
    for match in _LONG_NUMBER.finditer(text):
        found.setdefault(int(match.group()), match.group())
    return found


def _numbers_in_data(text: str) -> set[int]:
    """Every number in a tool result, as the whole-unit values a reply might show."""
    values = {_grouped_to_int(m.group()) for m in _GROUPED_NUMBER.finditer(text)}
    for match in _PLAIN_LITERAL.finditer(text):
        literal = match.group()
        whole, _, fraction = literal.partition(".")
        value = int(whole)
        values.add(value)
        if fraction and int(fraction[0]) >= 5:
            values.add(value + 1)  # the same figure rounded up
    return values


def _numbers_from_person(text: str) -> set[int]:
    """Amounts a person typed, including "15 ribu", "860rb", and "1,2 juta"."""
    values = _numbers_in_data(text)
    for number, unit in _SPOKEN_AMOUNT.findall(text):
        values.add(round(float(number.replace(",", ".")) * _MULTIPLIERS[unit.lower()]))
    return values


def known_figures(messages: list[dict]) -> set[int]:
    """Figures a reply may state: those in tool results and those the person typed. What the
    model itself said earlier does not count."""
    known: set[int] = set()
    for message in messages:
        if message["role"] != "user":
            continue
        content = message["content"]
        if isinstance(content, str):
            if not content.startswith(AUTOMATIC_CHECK_PREFIX):
                known |= _numbers_from_person(content)
            continue
        for block in content:
            if isinstance(block, dict) and block.get("type") == "tool_result":
                known |= _numbers_in_data(str(block.get("content", "")))
    return known


def ungrounded_figures(reply: str, messages: list[dict]) -> list[str]:
    """Figures in ``reply`` that appear in no tool result and no message from the person."""
    known = known_figures(messages)
    return [shown for value, shown in figures_in(reply).items() if value not in known]


_INDONESIAN_WORDS = frozenset(
    [
        "yang",
        "dan",
        "di",
        "ini",
        "itu",
        "tidak",
        "ga",
        "gak",
        "nggak",
        "udah",
        "sudah",
        "belum",
        "ada",
        "untuk",
        "dengan",
        "dari",
        "ke",
        "atau",
        "bisa",
        "mau",
        "saya",
        "kamu",
        "lo",
        "gue",
        "ya",
        "dong",
        "aja",
        "juga",
        "karena",
        "jadi",
        "tapi",
        "kalau",
        "kalo",
        "nih",
        "berapa",
        "apa",
        "mana",
        "tagihan",
        "bayar",
        "saldo",
        "jatuh",
        "tempo",
        "masih",
        "buat",
        "sama",
        "lagi",
        "dulu",
    ]
)
_ENGLISH_WORDS = frozenset(
    [
        "the",
        "is",
        "are",
        "and",
        "of",
        "to",
        "for",
        "with",
        "which",
        "what",
        "how",
        "please",
        "can",
        "you",
        "your",
        "this",
        "that",
        "have",
        "has",
        "not",
        "been",
        "will",
        "right",
        "now",
        "it",
        "on",
        "be",
        "or",
        "as",
        "by",
        "at",
        "from",
        "but",
        "there",
        "they",
        "we",
        "was",
        "were",
        "do",
        "does",
        "my",
        "our",
        "any",
        "all",
        "should",
        "would",
        "could",
    ]
)
_WORD = re.compile(r"[a-z']+")


def guess_language(text: str) -> str | None:
    """ "id", "en", or None when the text is mixed, too short, or unclear. Deliberately
    cautious: it only answers when one language clearly dominates."""
    words = _WORD.findall(text.lower())
    indonesian = sum(word in _INDONESIAN_WORDS for word in words)
    english = sum(word in _ENGLISH_WORDS for word in words)
    if english >= 2 and english >= 3 * indonesian:
        return "en"
    if indonesian >= 2 and indonesian >= 3 * english:
        return "id"
    return None


def reply_problems(user_text: str, reply: str, messages: list[dict]) -> list[str]:
    """Instructions for the model when a reply should not be shown as it is. Empty when the
    reply is fine. Used for one automatic correction per turn.

    Only facts are checked here (figures and language). Whether to ask before paying is a
    judgement left to the model: confirming an uncertain reading is the safe direction, and
    code must not push the model to pay sooner."""
    problems = []
    unknown = ungrounded_figures(reply, messages)
    if unknown:
        problems.append(
            "Your reply states amounts that are in no tool result in this conversation and "
            f"were not given by the person: {', '.join(unknown)}. Never state amounts from "
            "memory or as examples, and do not add amounts up yourself. Call the tools you "
            "need (for example list_invoices) and answer again using only their results."
        )
    asked, answered = guess_language(user_text), guess_language(reply)
    if asked and answered and asked != answered:
        language = {"en": "English", "id": "Indonesian"}[asked]
        problems.append(
            f"The person wrote in {language}. Write your whole reply in {language}; keep "
            "names, invoice numbers, and amounts as they are."
        )
    return problems


_HEADING = re.compile(r"^[ \t]{0,3}#{1,6}[ \t]+", re.MULTILINE)
_RULE = re.compile(r"^[ \t]*([-*_])(?:[ \t]*\1){2,}[ \t]*$\n?", re.MULTILINE)
# Bold markers on one line, with no other asterisk or underscore inside or next to them, so a
# masked account like ***9589 is never mistaken for markup.
_BOLD_STARS = re.compile(r"(?<!\*)\*\*(?![\s*])([^*\n]+?)(?<![\s*])\*\*(?!\*)")
_BOLD_UNDERSCORES = re.compile(r"(?<![\w_])__(?![\s_])([^_\n]+?)(?<![\s_])__(?![\w_])")
# Italic markers. A lone asterisk between spaces ("2 * 3") or inside a word is left alone.
_ITALIC_STARS = re.compile(r"(?<![\w*])\*(?![\s*])([^*\n]+?)(?<![\s*])\*(?![\w*])")
_CODE = re.compile(r"`([^`\n]+)`")
_BLANK_RUNS = re.compile(r"\n{3,}")


def plain_text(text: str) -> str:
    """Remove Markdown markup that chat apps would show literally: headings, bold markers,
    horizontal rules, and inline code ticks. Words, numbers, list markers, and line breaks are
    kept exactly as they are."""
    text = _RULE.sub("", text)
    text = _HEADING.sub("", text)
    text = _BOLD_STARS.sub(r"\1", text)
    text = _BOLD_UNDERSCORES.sub(r"\1", text)
    text = _ITALIC_STARS.sub(r"\1", text)
    text = _CODE.sub(r"\1", text)
    return _BLANK_RUNS.sub("\n\n", text).strip()
