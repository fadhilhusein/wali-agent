import dataclasses
import json
from types import SimpleNamespace

import pytest

from conftest import ScriptedLLM, flagged_invoice_ids, say, tool_results, use
from wali.agent.llm import LLMError
from wali.agent.loop import (
    ACTIONS_MAY_HAVE_RUN,
    EMPTY_REPLY,
    REFUSAL_REPLY,
    STEP_LIMIT_REPLY,
    TRUNCATED_REPLY,
    Agent,
    Session,
    trim_history,
)
from wali.agent.prompts import build_system_prompt
from wali.tools.registry import TOOL_SCHEMAS

SEPTEMBER = {"start": "2026-09-01", "end": "2026-09-30"}


@pytest.fixture
def session(owner, ready) -> Session:
    prompt = build_system_prompt(role="owner", currency="IDR", today=ready.clock().date())
    return Session(session_id="s-1", principal=owner, system_prompt=prompt)


@pytest.fixture
def tools(ready, owner):
    return ready.make_registry(owner, session_id="s-1")


def small_invoice(world, owner, ground_truth):
    flagged = flagged_invoice_ids(ground_truth)
    return min(
        (
            i
            for i in world.env.list_invoices(owner, "payable", status="open")
            if i.id not in flagged and i.due_date >= world.env.as_of_date
        ),
        key=lambda i: i.amount,
    )


def roles(session) -> list[str]:
    return [m["role"] for m in session.messages]


# --- The loop --------------------------------------------------------------------------------


def test_a_plain_answer_takes_one_model_call(session, tools):
    llm = ScriptedLLM(say("Halo! Ada yang bisa dibantu?"))

    reply = Agent(llm).respond(session, tools, "halo")

    assert (reply.text, reply.stop, reply.steps) == ("Halo! Ada yang bisa dibantu?", "answered", 1)
    assert reply.tool_calls == ()
    assert roles(session) == ["user", "assistant"]
    (request,) = llm.requests
    assert request["system"] == session.system_prompt
    assert request["tools"] is TOOL_SCHEMAS
    assert request["messages"] == [{"role": "user", "content": "halo"}]


def test_tool_results_go_back_to_the_model_wrapped_as_untrusted_data(session, tools, ground_truth):
    asked = use(("get_balance", {}))
    llm = ScriptedLLM(asked, say("Saldo Rp 7.500.000."))

    reply = Agent(llm).respond(session, tools, "saldo berapa?")

    assert (reply.text, reply.stop, reply.steps) == ("Saldo Rp 7.500.000.", "answered", 2)
    assert [(t.name, t.is_error) for t in reply.tool_calls] == [("get_balance", False)]
    assert roles(session) == ["user", "assistant", "user", "assistant"]

    second = llm.requests[1]["messages"]
    assert second[1] == {"role": "assistant", "content": asked.content}
    assert second[1]["content"] is asked.content
    (result,) = second[2]["content"]
    assert result["type"] == "tool_result"
    assert result["tool_use_id"] == asked.tool_calls[0].id
    assert "is_error" not in result
    assert json.loads(result["content"]) == {
        "untrusted_data": {
            "amount": ground_truth["business"]["closing_balance"],
            "currency": "IDR",
        }
    }


def test_several_tool_calls_in_one_turn_come_back_in_one_message(session, tools):
    asked = use(("get_balance", {}), ("reconcile_period", SEPTEMBER), ("no_such_tool", {}))
    llm = ScriptedLLM(asked, say("Selesai."))

    reply = Agent(llm).respond(session, tools, "cek semuanya")

    results = llm.requests[1]["messages"][-1]["content"]
    assert [r["tool_use_id"] for r in results] == [c.id for c in asked.tool_calls]
    assert [r.get("is_error", False) for r in results] == [False, False, True]
    assert [(t.name, t.error_code) for t in reply.tool_calls] == [
        ("get_balance", None),
        ("reconcile_period", None),
        ("no_such_tool", "UNKNOWN_TOOL"),
    ]
    assert roles(session) == ["user", "assistant", "user", "assistant"]


def test_a_failed_tool_is_reported_to_the_model_which_can_carry_on(session, tools, ready):
    ready.env.inject_failure("get_balance", times=2)
    llm = ScriptedLLM(use(("get_balance", {})), use(("get_balance", {})), say("Saldo ada."))

    reply = Agent(llm).respond(session, tools, "saldo?")

    assert [t.error_code for t in reply.tool_calls] == ["TOOL_FAILED", None]
    assert tool_results(llm.requests[1])[0]["error"]["code"] == "TOOL_FAILED"
    assert reply.stop == "answered"


def test_the_loop_stops_at_the_step_limit_with_an_apology(session, tools):
    llm = ScriptedLLM(*[use(("get_balance", {})) for _ in range(3)])

    reply = Agent(llm, max_steps=3).respond(session, tools, "terus aja")

    assert (reply.text, reply.stop, reply.steps) == (STEP_LIMIT_REPLY, "step_limit", 3)
    assert len(llm.requests) == 3
    assert len(reply.tool_calls) == 3
    assert session.messages[-1] == {"role": "assistant", "content": STEP_LIMIT_REPLY}
    assert roles(session)[-2:] == ["user", "assistant"]


def test_the_default_step_limit_is_eight(session, tools):
    llm = ScriptedLLM(*[use(("get_balance", {})) for _ in range(8)])

    reply = Agent(llm).respond(session, tools, "terus aja")

    assert (reply.stop, reply.steps) == ("step_limit", 8)
    with pytest.raises(ValueError):
        Agent(llm, max_steps=0)


def test_the_conversation_continues_after_a_step_limit(session, tools):
    llm = ScriptedLLM(use(("get_balance", {})), say("Oke."))
    agent = Agent(llm, max_steps=1)

    agent.respond(session, tools, "pertama")
    reply = agent.respond(session, tools, "kedua")

    assert reply.text == "Oke."
    assert roles(session) == ["user", "assistant", "user", "assistant", "user", "assistant"]


def test_a_refusal_is_answered_safely(session, tools):
    llm = ScriptedLLM(say("", stop_reason="refusal"))

    reply = Agent(llm).respond(session, tools, "sesuatu")

    assert (reply.text, reply.stop) == (REFUSAL_REPLY, "refusal")
    assert session.messages[-1] == {"role": "assistant", "content": REFUSAL_REPLY}


def test_a_cut_off_turn_runs_no_tools(session, tools, ready, owner, ground_truth):
    invoice = small_invoice(ready, owner, ground_truth)
    cut_off = dataclasses.replace(
        use(("propose_payment", {"invoice_id": invoice.id})), stop_reason="max_tokens"
    )
    llm = ScriptedLLM(cut_off)

    reply = Agent(llm).respond(session, tools, "bayar")

    assert (reply.text, reply.stop) == (TRUNCATED_REPLY, "truncated")
    assert reply.tool_calls == ()
    assert ready.env.list_payments() == []
    assert roles(session) == ["user", "assistant"]


def test_an_empty_answer_gets_a_fallback(session, tools):
    reply = Agent(ScriptedLLM(say(""))).respond(session, tools, "?")

    assert (reply.text, reply.stop) == (EMPTY_REPLY, "answered")


def test_a_model_outage_is_explained_and_nothing_is_lost(session, tools):
    outage = LLMError("The model is busy right now. Please try again.", retryable=True)
    llm = ScriptedLLM(outage, say("Sudah normal lagi."))
    agent = Agent(llm)

    failed = agent.respond(session, tools, "halo")
    recovered = agent.respond(session, tools, "halo lagi")

    assert (failed.text, failed.stop) == (outage.user_message, "llm_error")
    assert recovered.text == "Sudah normal lagi."
    assert [m["content"] for m in llm.requests[1]["messages"]] == [
        "halo",
        outage.user_message,
        "halo lagi",
    ]


def test_an_outage_after_an_action_says_the_action_may_have_happened(
    session, tools, ready, owner, ground_truth
):
    invoice = small_invoice(ready, owner, ground_truth)
    outage = LLMError("I could not reach the model service.", retryable=True)
    llm = ScriptedLLM(use(("propose_payment", {"invoice_id": invoice.id})), outage)

    reply = Agent(llm).respond(session, tools, "bayar air")

    assert reply.stop == "llm_error"
    assert reply.text == outage.user_message + ACTIONS_MAY_HAVE_RUN
    assert [p.invoice_id for p in ready.env.list_payments()] == [invoice.id]


def test_an_outage_after_only_reading_adds_no_such_note(session, tools):
    outage = LLMError("I could not reach the model service.", retryable=True)
    llm = ScriptedLLM(use(("get_balance", {})), outage)

    assert Agent(llm).respond(session, tools, "saldo").text == outage.user_message


# --- History ---------------------------------------------------------------------------------


def test_history_only_ever_grows_and_the_prompt_and_tools_never_change(session, tools):
    llm = ScriptedLLM(
        use(("get_balance", {}), thinking=True),
        say("Satu."),
        use(("reconcile_period", SEPTEMBER), thinking=True),
        use(("get_balance", {})),
        say("Dua."),
    )
    agent = Agent(llm)

    agent.respond(session, tools, "pertama")
    agent.respond(session, tools, "kedua")

    assert len(llm.requests) == 5
    for earlier, later in zip(llm.requests, llm.requests[1:], strict=False):
        prefix = later["messages"][: len(earlier["messages"])]
        assert len(later["messages"]) > len(earlier["messages"])
        assert all(a is b for a, b in zip(earlier["messages"], prefix, strict=True))
        assert later["system"] == earlier["system"]
        assert later["tools"] is earlier["tools"]


def test_the_outgoing_screen_sees_every_reply(session, tools):
    seen = []

    def screen(text, principal):
        seen.append((text, principal.role))
        return "[screened]"

    agent = Agent(ScriptedLLM(say("Jawaban asli."), say("", "refusal")), screen_outgoing=screen)

    assert agent.respond(session, tools, "a").text == "[screened]"
    assert agent.respond(session, tools, "b").text == "[screened]"
    assert seen == [("Jawaban asli.", "owner"), (REFUSAL_REPLY, "owner")]


# --- Trimming --------------------------------------------------------------------------------


def turn(n: int, with_tool: bool = False) -> list[dict]:
    messages = [{"role": "user", "content": f"q{n}"}]
    if with_tool:
        messages += [
            {
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "", "signature": f"s{n}"},
                    {"type": "tool_use", "id": f"t{n}", "name": "get_balance", "input": {}},
                ],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": f"t{n}", "content": "{}"}],
            },
        ]
    messages.append(
        {
            "role": "assistant",
            "content": [
                SimpleNamespace(type="thinking", thinking="", signature=f"a{n}"),
                SimpleNamespace(type="text", text=f"a{n}"),
            ],
        }
    )
    return messages


def test_a_short_history_is_left_alone():
    history = turn(1) + turn(2, with_tool=True)

    assert trim_history(history, max_turns=2) is history


def test_a_long_history_keeps_the_recent_half_and_starts_at_a_user_message():
    history = [m for n in range(1, 8) for m in turn(n, with_tool=n % 2 == 0)]

    trimmed = trim_history(history, max_turns=6)

    typed = [m["content"] for m in trimmed if isinstance(m["content"], str)]
    assert typed == ["q5", "q6", "q7"]
    assert trimmed[0] == {"role": "user", "content": "q5"}


def test_trimming_removes_reasoning_but_keeps_tool_calls_with_their_results():
    history = [m for n in range(1, 8) for m in turn(n, with_tool=True)]

    trimmed = trim_history(history, max_turns=6)

    types = [
        getattr(b, "type", None) or b["type"]
        for m in trimmed
        if not isinstance(m["content"], str)
        for b in m["content"]
    ]
    assert "thinking" not in types
    assert types.count("tool_use") == types.count("tool_result") == 3
    assert types.count("text") == 3
    for index, message in enumerate(trimmed):
        first = message["content"][0]
        if isinstance(first, dict) and first["type"] == "tool_use":
            assert trimmed[index + 1]["content"][0]["tool_use_id"] == first["id"]


def test_trimming_does_not_change_the_original_messages():
    history = [m for n in range(1, 8) for m in turn(n, with_tool=True)]
    before = [
        list(m["content"]) if isinstance(m["content"], list) else m["content"] for m in history
    ]

    trim_history(history, max_turns=6)

    after = [
        list(m["content"]) if isinstance(m["content"], list) else m["content"] for m in history
    ]
    assert after == before


def test_a_turn_that_was_only_reasoning_is_dropped_when_trimming():
    history = [m for n in range(1, 8) for m in turn(n)]
    history.append({"role": "user", "content": "q8"})
    history.append({"role": "assistant", "content": [{"type": "thinking", "thinking": ""}]})

    trimmed = trim_history(history, max_turns=6)

    assert trimmed[-1] == {"role": "user", "content": "q8"}


def test_the_agent_trims_before_answering(session, tools):
    session.messages.extend(m for n in range(1, 8) for m in turn(n, with_tool=True))
    llm = ScriptedLLM(say("Oke."))

    Agent(llm, history_max_turns=6).respond(session, tools, "q8")

    sent = llm.requests[0]["messages"]
    assert [m["content"] for m in sent if isinstance(m["content"], str)] == ["q5", "q6", "q7", "q8"]
    assert all(
        (getattr(b, "type", None) or b["type"]) != "thinking"
        for m in sent
        if not isinstance(m["content"], str)
        for b in m["content"]
    )
