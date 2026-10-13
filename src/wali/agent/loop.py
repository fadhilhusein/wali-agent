"""The hand-written tool-use loop.

One call to ``Agent.respond`` handles one user message:

1. Append the user message to the session history.
2. Ask the model, offering the registry's tools.
3. Run every tool the model called, hand the results back, and ask again.
4. Stop at a final answer, or after ``max_steps`` model calls.
5. Pass the answer through the outgoing screen before returning it.

The history is append-only. The assistant's content goes back to the model exactly as it was
received, because current models tie their reasoning blocks to the conversation that produced
them. The only time earlier turns are dropped is ``trim_history``, which then also removes the
reasoning blocks from the turns it keeps, as that situation requires.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from wali.agent.dialogue import (
    AUTOMATIC_CHECK_PREFIX,
    UNVERIFIED_FIGURES_NOTE,
    plain_text,
    reply_problems,
    ungrounded_figures,
)
from wali.agent.llm import LLMClient, LLMError
from wali.models import Principal
from wali.tools.registry import ToolRegistry

# Fixed replies produced by code, not by the model. The user's language is not known here, so
# they are given in Indonesian and English.
STEP_LIMIT_REPLY = (
    "Maaf, permintaan ini butuh terlalu banyak langkah. Bisa diulang dengan lebih spesifik, "
    "satu hal dulu? / Sorry, this needed too many steps. Could you ask again more "
    "specifically, one thing at a time?"
)
REFUSAL_REPLY = (
    "Maaf, saya tidak bisa membantu permintaan itu. / Sorry, I can't help with that request."
)
TRUNCATED_REPLY = (
    "Maaf, jawaban saya terpotong. Coba minta bagian yang lebih kecil. / Sorry, my answer was "
    "cut off. Please ask for a smaller piece at a time."
)
EMPTY_REPLY = "Maaf, saya tidak punya jawaban untuk itu. / Sorry, I have no answer for that."
ACTIONS_MAY_HAVE_RUN = (
    " Beberapa langkah mungkin sudah dijalankan; tanyakan statusnya ke saya. / Some steps may "
    "already have been carried out; ask me for the current status."
)
ACTION_TOOLS = frozenset(
    {"propose_payment", "propose_mandate", "record_book_entry", "flag_for_review"}
)
_THINKING_TYPES = ("thinking", "redacted_thinking")


@dataclass
class Session:
    """One principal's conversation. ``system_prompt`` is fixed for the life of the session."""

    session_id: str
    principal: Principal
    system_prompt: str
    messages: list[dict[str, Any]] = field(default_factory=list)
    # Payment requests made in this conversation that are still waiting for the owner.
    pending_proposals: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class ToolTrace:
    name: str
    arguments: dict[str, Any]
    is_error: bool
    error_code: str | None


@dataclass(frozen=True)
class AgentReply:
    text: str
    # answered | step_limit | refusal | truncated | llm_error
    stop: str
    steps: int
    tool_calls: tuple[ToolTrace, ...] = ()
    # True when the first answer failed the automatic check and the model was asked to redo it.
    corrected: bool = False


def _block_type(block: Any) -> str | None:
    return block.get("type") if isinstance(block, dict) else getattr(block, "type", None)


def _is_user_turn(message: dict[str, Any]) -> bool:
    """A message the person typed, as opposed to tool results or an automatic check, which are
    also sent with the user role."""
    content = message["content"]
    return (
        message["role"] == "user"
        and isinstance(content, str)
        and not content.startswith(AUTOMATIC_CHECK_PREFIX)
    )


def trim_history(messages: list[dict[str, Any]], max_turns: int) -> list[dict[str, Any]]:
    """Drop the oldest turns once there are more than ``max_turns`` user turns, keeping the most
    recent half. The cut always falls just before a message the person typed, so a tool call is
    never separated from its result. Reasoning blocks are removed from the turns that are kept:
    they were produced with the full history present and are not valid without it."""
    starts = [index for index, message in enumerate(messages) if _is_user_turn(message)]
    if len(starts) <= max_turns:
        return messages
    kept = []
    for message in messages[starts[-(max_turns // 2)] :]:
        content = message["content"]
        if message["role"] == "assistant" and not isinstance(content, str):
            content = [block for block in content if _block_type(block) not in _THINKING_TYPES]
            if not content:
                continue
        kept.append({"role": message["role"], "content": content})
    return kept


class Agent:
    def __init__(
        self,
        llm: LLMClient,
        *,
        max_steps: int = 8,
        history_max_turns: int = 30,
        screen_outgoing: Callable[[str, Principal], str] | None = None,
        reply_check: Callable[[str, str, list[dict[str, Any]]], list[str]] | None = reply_problems,
    ) -> None:
        """``reply_check`` looks at a final answer before it is shown and returns instructions
        when it should be redone (figures that came from no tool, or the wrong language). It is
        called with the person's message, the reply, and the history. The model gets one chance
        per turn to correct itself. Pass None to switch the check off."""
        if max_steps < 1:
            raise ValueError("max_steps must be at least 1")
        self._llm = llm
        self._max_steps = max_steps
        self._history_max_turns = history_max_turns
        self._screen_outgoing = screen_outgoing or (lambda text, principal: text)
        self._reply_check = reply_check

    def respond(self, session: Session, registry: ToolRegistry, user_text: str) -> AgentReply:
        """Answer one user message, running tools as the model asks for them."""
        session.messages[:] = trim_history(session.messages, self._history_max_turns)
        session.messages.append({"role": "user", "content": user_text})
        traces: list[ToolTrace] = []
        corrected = False

        def finish(text: str, stop: str, steps: int, *, record: bool = True) -> AgentReply:
            if record:
                session.messages.append({"role": "assistant", "content": text})
            # The history keeps what the model wrote; only the copy shown to the person is
            # tidied and screened.
            shown = self._screen_outgoing(plain_text(text), session.principal)
            return AgentReply(
                text=shown, stop=stop, steps=steps, tool_calls=tuple(traces), corrected=corrected
            )

        for step in range(1, self._max_steps + 1):
            try:
                response = self._llm.complete(
                    system=session.system_prompt,
                    messages=session.messages,
                    tools=registry.schemas(),
                )
            except LLMError as error:
                note = ACTIONS_MAY_HAVE_RUN if any(t.name in ACTION_TOOLS for t in traces) else ""
                return finish(error.user_message + note, "llm_error", step)

            if response.stop_reason == "refusal":
                return finish(REFUSAL_REPLY, "refusal", step)
            if response.stop_reason == "max_tokens":
                return finish(TRUNCATED_REPLY, "truncated", step)

            if response.tool_calls:
                session.messages.append({"role": "assistant", "content": response.content})
                results = []
                for call in response.tool_calls:
                    outcome = registry.execute(call.name, call.input)
                    traces.append(
                        ToolTrace(call.name, dict(call.input), outcome.is_error, outcome.error_code)
                    )
                    result: dict[str, Any] = {
                        "type": "tool_result",
                        "tool_use_id": call.id,
                        "content": outcome.content,
                    }
                    if outcome.is_error:
                        result["is_error"] = True
                    results.append(result)
                # All results of one model turn go back together, in a single message.
                session.messages.append({"role": "user", "content": results})
                continue

            if not response.text:
                return finish(EMPTY_REPLY, "answered", step)

            if self._reply_check is not None and not corrected:
                problems = self._reply_check(user_text, response.text, session.messages)
                if problems:
                    # Keep the rejected answer in the history and ask for a better one. The
                    # person never sees the rejected answer.
                    corrected = True
                    session.messages.append({"role": "assistant", "content": response.content})
                    session.messages.append(
                        {
                            "role": "user",
                            "content": f"{AUTOMATIC_CHECK_PREFIX} {' '.join(problems)} "
                            "Do not mention this check to the person.",
                        }
                    )
                    continue

            session.messages.append({"role": "assistant", "content": response.content})
            text = response.text
            if corrected:
                # A second answer is shown either way, but never silently with figures that
                # still cannot be traced to the data.
                unverified = ungrounded_figures(text, session.messages)
                if unverified:
                    text += UNVERIFIED_FIGURES_NOTE.format(figures=", ".join(unverified))
            return finish(text, "answered", step, record=False)

        return finish(STEP_LIMIT_REPLY, "step_limit", self._max_steps)
