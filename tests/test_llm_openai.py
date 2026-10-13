"""The OpenAI-compatible backend, tested against a fake HTTP transport. No network, no key."""

import json

import httpx
import pytest

from conftest import flagged_invoice_ids
from wali.agent.llm import LLMError
from wali.agent.llm_openai import (
    UNPARSEABLE_ARGUMENTS,
    OpenAICompatibleLLM,
    to_openai_messages,
    to_openai_tools,
)
from wali.agent.loop import Agent, Session
from wali.app import SetupError, build_llm
from wali.config import load_settings
from wali.tools.registry import TOOL_SCHEMAS

API_KEY = "sk-compat-not-a-real-key-987654"
BASE_URL = "https://llm.example.test/v1/"
MESSAGES = [{"role": "user", "content": "saldo berapa?"}]


def answer(message: dict, finish_reason: str = "stop") -> dict:
    return {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "model": "test-model",
        "choices": [{"index": 0, "message": message, "finish_reason": finish_reason}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    }


def tool_call(id: str, name: str, arguments) -> dict:
    raw = arguments if isinstance(arguments, str) else json.dumps(arguments)
    return {"id": id, "type": "function", "function": {"name": name, "arguments": raw}}


class Transport:
    """Replays scripted HTTP responses and records every request."""

    def __init__(self, *responses) -> None:
        self.responses = list(responses)
        self.requests: list[dict] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(
            {
                "url": str(request.url),
                "headers": dict(request.headers),
                "body": json.loads(request.content),
            }
        )
        step = self.responses.pop(0)
        if isinstance(step, Exception):
            raise step
        status, body = step if isinstance(step, tuple) else (200, step)
        if isinstance(body, str):
            return httpx.Response(status, text=body)
        return httpx.Response(status, json=body)


def make(transport: Transport, **options) -> OpenAICompatibleLLM:
    options.setdefault("model", "test-model")
    options.setdefault("base_url", BASE_URL)
    options.setdefault("api_key", API_KEY)
    slept = options.pop("slept", [])
    return OpenAICompatibleLLM(
        client=httpx.Client(transport=httpx.MockTransport(transport)),
        sleep=slept.append,
        **options,
    )


TEXT = answer({"role": "assistant", "content": "Saldo Anda Rp 7.500.000."})


# --- Request shape ---------------------------------------------------------------------------


def test_request_goes_to_chat_completions_with_a_bearer_key():
    transport = Transport(TEXT)

    make(transport, max_tokens=4000).complete(system="SYSTEM", messages=MESSAGES, tools=[])

    (request,) = transport.requests
    assert request["url"] == "https://llm.example.test/v1/chat/completions"
    assert request["headers"]["authorization"] == f"Bearer {API_KEY}"
    assert request["body"] == {
        "model": "test-model",
        "max_tokens": 4000,
        "messages": [
            {"role": "system", "content": "SYSTEM"},
            {"role": "user", "content": "saldo berapa?"},
        ],
    }


def test_temperature_is_sent_only_when_configured():
    without, with_zero = Transport(TEXT), Transport(TEXT)

    make(without).complete(system="S", messages=MESSAGES, tools=[])
    make(with_zero, temperature=0).complete(system="S", messages=MESSAGES, tools=[])

    assert "temperature" not in without.requests[0]["body"]
    assert with_zero.requests[0]["body"]["temperature"] == 0


def test_tools_are_sent_as_functions_without_the_strict_flag():
    transport = Transport(TEXT)

    make(transport).complete(system="S", messages=MESSAGES, tools=TOOL_SCHEMAS)

    sent = transport.requests[0]["body"]["tools"]
    assert [t["function"]["name"] for t in sent] == [t["name"] for t in TOOL_SCHEMAS]
    assert all(t["type"] == "function" for t in sent)
    assert all(set(t["function"]) == {"name", "description", "parameters"} for t in sent)
    assert sent[0]["function"]["parameters"] == TOOL_SCHEMAS[0]["input_schema"]
    assert to_openai_tools([]) == []


def test_history_is_translated_including_tool_calls_and_their_results():
    history = [
        {"role": "user", "content": "cek saldo dan tagihan"},
        {
            "role": "assistant",
            "content": [
                {"type": "thinking", "thinking": "", "signature": "ignored"},
                {"type": "text", "text": "Saya cek dulu."},
                {"type": "tool_use", "id": "c1", "name": "get_balance", "input": {}},
                {
                    "type": "tool_use",
                    "id": "c2",
                    "name": "list_invoices",
                    "input": {"kind": "payable", "status": "open", "due_before": None},
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "c1", "content": '{"untrusted_data": 1}'},
                {
                    "type": "tool_result",
                    "tool_use_id": "c2",
                    "content": '{"untrusted_data": null, "error": {}}',
                    "is_error": True,
                },
            ],
        },
        {"role": "assistant", "content": "Jawaban teks biasa."},
        {"role": "user", "content": "oke"},
    ]

    assert to_openai_messages("SYS", history) == [
        {"role": "system", "content": "SYS"},
        {"role": "user", "content": "cek saldo dan tagihan"},
        {
            "role": "assistant",
            "content": "Saya cek dulu.",
            "tool_calls": [
                tool_call("c1", "get_balance", "{}"),
                tool_call(
                    "c2",
                    "list_invoices",
                    '{"kind": "payable", "status": "open", "due_before": null}',
                ),
            ],
        },
        {"role": "tool", "tool_call_id": "c1", "content": '{"untrusted_data": 1}'},
        {"role": "tool", "tool_call_id": "c2", "content": '{"untrusted_data": null, "error": {}}'},
        {"role": "assistant", "content": "Jawaban teks biasa."},
        {"role": "user", "content": "oke"},
    ]


def test_an_assistant_turn_with_only_tool_calls_has_no_text():
    history = [
        {
            "role": "assistant",
            "content": [{"type": "tool_use", "id": "c1", "name": "get_balance", "input": {}}],
        }
    ]

    assert to_openai_messages("S", history)[1]["content"] is None


# --- Response parsing ------------------------------------------------------------------------


def test_a_text_answer_is_parsed():
    response = make(Transport(TEXT)).complete(system="S", messages=MESSAGES, tools=[])

    assert (response.stop_reason, response.text) == ("end_turn", "Saldo Anda Rp 7.500.000.")
    assert response.tool_calls == ()
    assert response.content == [{"type": "text", "text": "Saldo Anda Rp 7.500.000."}]


def test_tool_calls_are_parsed():
    message = {
        "role": "assistant",
        "content": None,
        "reasoning_content": "provider-specific reasoning that is not kept",
        "tool_calls": [
            tool_call("c1", "get_balance", {}),
            tool_call("c2", "propose_payment", {"invoice_id": "inv-0090"}),
        ],
    }
    transport = Transport(answer(message, "tool_calls"))

    response = make(transport).complete(system="S", messages=MESSAGES, tools=TOOL_SCHEMAS)

    assert (response.stop_reason, response.text) == ("tool_use", "")
    assert [(c.id, c.name, c.input) for c in response.tool_calls] == [
        ("c1", "get_balance", {}),
        ("c2", "propose_payment", {"invoice_id": "inv-0090"}),
    ]
    assert response.content == [
        {"type": "tool_use", "id": "c1", "name": "get_balance", "input": {}},
        {
            "type": "tool_use",
            "id": "c2",
            "name": "propose_payment",
            "input": {"invoice_id": "inv-0090"},
        },
    ]
    assert "reasoning" not in json.dumps(response.content)


def test_tool_calls_count_even_when_the_finish_reason_says_stop():
    message = {"role": "assistant", "content": "", "tool_calls": [tool_call("c1", "x", {})]}

    response = make(Transport(answer(message, "stop"))).complete(
        system="S", messages=MESSAGES, tools=TOOL_SCHEMAS
    )

    assert response.stop_reason == "tool_use"


@pytest.mark.parametrize("raw", ["{not json", '"a string"', "[1, 2]", "null"])
def test_arguments_that_are_not_a_json_object_are_marked_unparseable(raw):
    message = {"role": "assistant", "content": None, "tool_calls": [tool_call("c1", "x", raw)]}

    response = make(Transport(answer(message, "tool_calls"))).complete(
        system="S", messages=MESSAGES, tools=TOOL_SCHEMAS
    )

    assert list(response.tool_calls[0].input) == [UNPARSEABLE_ARGUMENTS]


def test_missing_arguments_and_ids_are_tolerated():
    message = {
        "role": "assistant",
        "content": None,
        "tool_calls": [{"type": "function", "function": {"name": "get_balance"}}],
    }

    response = make(Transport(answer(message, "tool_calls"))).complete(
        system="S", messages=MESSAGES, tools=TOOL_SCHEMAS
    )

    (call,) = response.tool_calls
    assert (call.id, call.name, call.input) == ("call_0", "get_balance", {})


@pytest.mark.parametrize(
    ("finish_reason", "expected"),
    [
        ("stop", "end_turn"),
        ("length", "max_tokens"),
        ("content_filter", "refusal"),
        (None, "end_turn"),
    ],
)
def test_finish_reasons_are_mapped(finish_reason, expected):
    body = answer({"role": "assistant", "content": "x"}, finish_reason)

    response = make(Transport(body)).complete(system="S", messages=MESSAGES, tools=[])

    assert response.stop_reason == expected


def test_a_reply_can_be_sent_straight_back():
    first_message = {
        "role": "assistant",
        "content": "Saya cek.",
        "tool_calls": [tool_call("c1", "get_balance", {})],
    }
    transport = Transport(answer(first_message, "tool_calls"), TEXT)
    llm = make(transport)

    first = llm.complete(system="S", messages=MESSAGES, tools=TOOL_SCHEMAS)
    history = [
        *MESSAGES,
        {"role": "assistant", "content": first.content},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "{}"}],
        },
    ]
    llm.complete(system="S", messages=history, tools=TOOL_SCHEMAS)

    assert transport.requests[1]["body"]["messages"][2:] == [
        {
            "role": "assistant",
            "content": "Saya cek.",
            "tool_calls": [tool_call("c1", "get_balance", "{}")],
        },
        {"role": "tool", "tool_call_id": "c1", "content": "{}"},
    ]


# --- Errors and retries ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("status", "hint"),
    [
        (401, "WALI_LLM_API_KEY"),
        (403, "not allowed"),
        (404, "WALI_LLM_BASE_URL"),
        (400, "configuration problem"),
        (422, "configuration problem"),
    ],
)
def test_client_errors_are_plain_final_and_keep_the_key_out(status, hint):
    provider_text = json.dumps({"error": {"message": f"bad thing, key was {API_KEY}"}})
    transport = Transport((status, provider_text))

    with pytest.raises(LLMError) as excinfo:
        make(transport).complete(system="S", messages=MESSAGES, tools=[])

    error = excinfo.value
    assert error.retryable is False
    assert hint in error.user_message
    assert len(transport.requests) == 1
    assert API_KEY not in error.user_message
    assert "bad thing" not in error.user_message
    assert error.detail.startswith(f"HTTP {status}:")
    assert "bad thing" in error.detail
    assert API_KEY not in error.detail


@pytest.mark.parametrize("status", [429, 500, 503])
def test_overload_and_server_errors_are_retried_then_succeed(status):
    slept: list[float] = []
    transport = Transport((status, "busy"), (status, "busy"), TEXT)

    response = make(transport, slept=slept).complete(system="S", messages=MESSAGES, tools=[])

    assert response.text == "Saldo Anda Rp 7.500.000."
    assert len(transport.requests) == 3
    assert slept == [0.5, 1.5]


def test_retries_give_up_with_a_retryable_error():
    slept: list[float] = []
    transport = Transport((429, "busy"), (500, "down"), (503, "still down"))

    with pytest.raises(LLMError) as excinfo:
        make(transport, slept=slept).complete(system="S", messages=MESSAGES, tools=[])

    assert excinfo.value.retryable is True
    assert "try again" in excinfo.value.user_message
    assert len(transport.requests) == 3


def test_network_failures_are_retried():
    transport = Transport(httpx.ConnectError("no route"), httpx.ReadTimeout("slow"), TEXT)

    response = make(transport).complete(system="S", messages=MESSAGES, tools=[])

    assert response.stop_reason == "end_turn"
    assert len(transport.requests) == 3


def test_a_network_that_stays_down_is_reported():
    transport = Transport(*[httpx.ConnectError("no route")] * 3)

    with pytest.raises(LLMError) as excinfo:
        make(transport).complete(system="S", messages=MESSAGES, tools=[])

    assert excinfo.value.retryable is True
    assert "could not reach" in excinfo.value.user_message


@pytest.mark.parametrize("body", ["<html>gateway</html>", {"unexpected": "shape"}, {"choices": []}])
def test_unreadable_answers_are_errors_not_crashes(body):
    transport = Transport(*[body] * 3)

    with pytest.raises(LLMError) as excinfo:
        make(transport).complete(system="S", messages=MESSAGES, tools=[])

    assert "could not read" in excinfo.value.user_message


@pytest.mark.parametrize(
    ("options", "setting"),
    [
        ({"model": ""}, "WALI_AGENT_MODEL"),
        ({"base_url": ""}, "WALI_LLM_BASE_URL"),
        ({"api_key": ""}, "WALI_LLM_API_KEY"),
    ],
)
def test_missing_settings_are_named(options, setting):
    with pytest.raises(LLMError, match=setting):
        make(Transport(), **options)


# --- Choosing the backend from settings ------------------------------------------------------


def settings(**env):
    return load_settings(env=env, env_file=None)


def test_build_llm_picks_the_backend_from_the_provider_setting():
    compatible = build_llm(
        settings(
            WALI_LLM_PROVIDER="openai_compatible",
            WALI_LLM_BASE_URL="https://llm.example.test/v1",
            WALI_LLM_API_KEY=API_KEY,
            WALI_LLM_TEMPERATURE="0",
        ),
        "some-model",
    )
    default = build_llm(settings(ANTHROPIC_API_KEY="sk-ant-test"), "claude-test")

    assert type(compatible).__name__ == "OpenAICompatibleLLM"
    assert compatible._temperature == 0
    assert type(default).__name__ == "AnthropicLLM"


@pytest.mark.parametrize(
    ("env", "message"),
    [
        ({"WALI_LLM_API_KEY": API_KEY}, "WALI_LLM_BASE_URL"),
        ({"WALI_LLM_BASE_URL": "https://llm.example.test/v1"}, "WALI_LLM_API_KEY"),
    ],
)
def test_build_llm_names_the_missing_setting(env, message):
    with pytest.raises(SetupError, match=message):
        build_llm(settings(WALI_LLM_PROVIDER="openai_compatible", **env), "some-model")


def test_build_llm_needs_a_model_and_a_known_provider():
    with pytest.raises(SetupError, match="WALI_AGENT_MODEL"):
        build_llm(settings(), None)
    with pytest.raises(ValueError, match="WALI_LLM_PROVIDER"):
        settings(WALI_LLM_PROVIDER="something_else")


def test_the_key_is_not_shown_in_settings():
    loaded = settings(WALI_LLM_API_KEY=API_KEY)

    assert API_KEY not in repr(loaded)
    assert API_KEY not in loaded.model_dump_json()


# --- Through the whole loop ------------------------------------------------------------------


def test_the_agent_loop_works_end_to_end_on_this_backend(ready, owner, bookkeeper, ground_truth):
    """A payment proposed through this backend goes through the same guard as any other."""
    flagged = flagged_invoice_ids(ground_truth)
    invoice = min(
        (
            i
            for i in ready.env.list_invoices(owner, "payable", status="open")
            if i.id not in flagged and i.due_date >= ready.env.as_of_date
        ),
        key=lambda i: i.amount,
    )
    transport = Transport(
        answer(
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [tool_call("c1", "propose_payment", {"invoice_id": invoice.id})],
            },
            "tool_calls",
        ),
        answer({"role": "assistant", "content": "Sudah dibayar."}),
    )
    session = Session(session_id="s", principal=bookkeeper, system_prompt="SYSTEM")

    reply = Agent(make(transport)).respond(
        session, ready.make_registry(bookkeeper), "bayar tagihan air"
    )

    assert (reply.text, reply.stop, reply.steps) == ("Sudah dibayar.", "answered", 2)
    assert [p.invoice_id for p in ready.env.list_payments()] == [invoice.id]
    tool_message = transport.requests[1]["body"]["messages"][-1]
    assert tool_message["role"] == "tool"
    assert json.loads(tool_message["content"])["untrusted_data"]["status"] == "executed"
