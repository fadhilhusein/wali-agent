"""The Anthropic wrapper, tested against a fake HTTP transport. No network, no real key."""

import json

import anthropic
import httpx2
import pytest

from wali.agent.llm import REFUSAL_FALLBACK_BETA, AnthropicLLM, LLMError
from wali.tools.registry import TOOL_SCHEMAS

API_KEY = "sk-test-not-a-real-key-123456"
MESSAGES = [{"role": "user", "content": "saldo berapa?"}]


def reply(content, stop_reason="end_turn") -> dict:
    return {
        "id": "msg_test",
        "type": "message",
        "role": "assistant",
        "model": "test-model",
        "content": content,
        "stop_reason": stop_reason,
        "stop_sequence": None,
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }


def make(handler, **options) -> AnthropicLLM:
    client = anthropic.Anthropic(
        api_key=API_KEY,
        max_retries=0,
        http_client=anthropic.DefaultHttpxClient(transport=httpx2.MockTransport(handler)),
    )
    options.setdefault("model", "test-model")
    return AnthropicLLM(client=client, **options)


def capture(response_body, status=200):
    """A transport handler that records the request and answers with ``response_body``."""
    seen = {}

    def handler(request: httpx2.Request) -> httpx2.Response:
        seen["url"] = str(request.url)
        seen["headers"] = dict(request.headers)
        seen["body"] = json.loads(request.content)
        return httpx2.Response(status, json=response_body)

    return seen, handler


TEXT = [{"type": "text", "text": "Saldo Anda Rp 7.500.000."}]


def test_request_carries_model_system_messages_and_tools():
    seen, handler = capture(reply(TEXT))

    make(handler, max_tokens=4000).complete(system="SYSTEM", messages=MESSAGES, tools=TOOL_SCHEMAS)

    body = seen["body"]
    assert body["model"] == "test-model"
    assert body["max_tokens"] == 4000
    assert body["system"] == "SYSTEM"
    assert body["messages"] == MESSAGES
    assert [t["name"] for t in body["tools"]] == [t["name"] for t in TOOL_SCHEMAS]
    assert all(t["strict"] is True for t in body["tools"])
    assert seen["headers"]["x-api-key"] == API_KEY


def test_no_sampling_thinking_or_forced_tool_choice_is_sent():
    seen, handler = capture(reply(TEXT))

    make(handler).complete(system="S", messages=MESSAGES, tools=TOOL_SCHEMAS)

    for absent in ("temperature", "top_p", "top_k", "thinking", "tool_choice", "output_config"):
        assert absent not in seen["body"], absent


def test_effort_is_sent_only_when_configured():
    seen, handler = capture(reply(TEXT))

    make(handler, effort="low").complete(system="S", messages=MESSAGES, tools=[])

    assert seen["body"]["output_config"] == {"effort": "low"}
    assert "tools" not in seen["body"]


def test_refusal_fallback_is_on_for_anthropics_own_endpoint():
    seen, handler = capture(reply(TEXT))

    make(handler).complete(system="S", messages=MESSAGES, tools=[])

    assert seen["body"]["fallbacks"] == "default"
    assert REFUSAL_FALLBACK_BETA in seen["headers"]["anthropic-beta"]


@pytest.mark.parametrize(
    "options", [{"refusal_fallback": False}, {"base_url": "https://llm.example.test"}]
)
def test_refusal_fallback_is_off_when_disabled_or_on_another_endpoint(options):
    seen, handler = capture(reply(TEXT))

    make(handler, **options).complete(system="S", messages=MESSAGES, tools=[])

    assert "fallbacks" not in seen["body"]
    assert REFUSAL_FALLBACK_BETA not in seen["headers"].get("anthropic-beta", "")


def test_fallback_can_be_forced_on_for_another_endpoint():
    seen, handler = capture(reply(TEXT))

    make(handler, base_url="https://llm.example.test", refusal_fallback=True).complete(
        system="S", messages=MESSAGES, tools=[]
    )

    assert seen["body"]["fallbacks"] == "default"


def test_a_text_answer_is_parsed():
    _, handler = capture(reply(TEXT))

    response = make(handler).complete(system="S", messages=MESSAGES, tools=[])

    assert (response.stop_reason, response.text) == ("end_turn", "Saldo Anda Rp 7.500.000.")
    assert response.tool_calls == ()
    assert [block.type for block in response.content] == ["text"]


def test_tool_calls_are_parsed_and_reasoning_is_kept_for_replay():
    content = [
        {"type": "thinking", "thinking": "", "signature": "sig-abc"},
        {"type": "text", "text": "Saya cek dulu."},
        {"type": "tool_use", "id": "toolu_1", "name": "get_balance", "input": {}},
        {
            "type": "tool_use",
            "id": "toolu_2",
            "name": "list_invoices",
            "input": {"kind": "payable", "status": "open", "due_before": None},
        },
    ]
    _, handler = capture(reply(content, "tool_use"))

    response = make(handler).complete(system="S", messages=MESSAGES, tools=TOOL_SCHEMAS)

    assert response.stop_reason == "tool_use"
    assert response.text == "Saya cek dulu."
    assert [(c.id, c.name, c.input) for c in response.tool_calls] == [
        ("toolu_1", "get_balance", {}),
        ("toolu_2", "list_invoices", {"kind": "payable", "status": "open", "due_before": None}),
    ]
    assert [block.type for block in response.content] == [
        "thinking",
        "text",
        "tool_use",
        "tool_use",
    ]
    assert response.content[0].signature == "sig-abc"


def test_received_content_can_be_sent_straight_back():
    """The loop appends ``response.content`` unchanged; the SDK must accept it as input."""
    content = [
        {"type": "thinking", "thinking": "", "signature": "sig-abc"},
        {"type": "tool_use", "id": "toolu_1", "name": "get_balance", "input": {}},
    ]
    seen, handler = capture(reply(content, "tool_use"))
    llm = make(handler)
    first = llm.complete(system="S", messages=MESSAGES, tools=TOOL_SCHEMAS)

    history = [
        *MESSAGES,
        {"role": "assistant", "content": first.content},
        {
            "role": "user",
            "content": [{"type": "tool_result", "tool_use_id": "toolu_1", "content": "{}"}],
        },
    ]
    llm.complete(system="S", messages=history, tools=TOOL_SCHEMAS)

    echoed = seen["body"]["messages"][1]["content"]
    assert [block["type"] for block in echoed] == ["thinking", "tool_use"]
    assert echoed[0]["signature"] == "sig-abc"
    assert echoed[1] == {"type": "tool_use", "id": "toolu_1", "name": "get_balance", "input": {}}


def test_a_refusal_is_passed_through_as_a_stop_reason():
    _, handler = capture(reply([], "refusal"))

    response = make(handler).complete(system="S", messages=MESSAGES, tools=[])

    assert (response.stop_reason, response.text, response.tool_calls) == ("refusal", "", ())


@pytest.mark.parametrize(
    ("status", "error_type", "retryable", "hint"),
    [
        (401, "authentication_error", False, "API key"),
        (403, "permission_error", False, "not allowed"),
        (404, "not_found_error", False, "WALI_AGENT_MODEL"),
        (400, "invalid_request_error", False, "configuration problem"),
        (429, "rate_limit_error", True, "busy"),
        (500, "api_error", True, "try again"),
        (529, "overloaded_error", True, "try again"),
    ],
)
def test_api_errors_become_plain_messages_without_secrets(status, error_type, retryable, hint):
    body = {"type": "error", "error": {"type": error_type, "message": f"raw detail {API_KEY}"}}
    _, handler = capture(body, status)

    with pytest.raises(LLMError) as excinfo:
        make(handler).complete(system="S", messages=MESSAGES, tools=[])

    assert excinfo.value.retryable is retryable
    assert hint in excinfo.value.user_message
    assert API_KEY not in excinfo.value.user_message
    assert "raw detail" not in str(excinfo.value)


@pytest.mark.parametrize("failure", [httpx2.ConnectError, httpx2.ReadTimeout])
def test_network_failures_are_retryable(failure):
    def handler(request):
        raise failure("no route", request=request)

    with pytest.raises(LLMError) as excinfo:
        make(handler).complete(system="S", messages=MESSAGES, tools=[])

    assert excinfo.value.retryable is True
    assert "could not reach" in excinfo.value.user_message


def test_a_missing_model_name_is_a_setup_problem():
    with pytest.raises(LLMError, match="WALI_AGENT_MODEL"):
        AnthropicLLM(model="", api_key=API_KEY)
