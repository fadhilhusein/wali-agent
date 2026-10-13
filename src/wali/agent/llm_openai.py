"""A second model backend, for endpoints that speak the OpenAI chat-completions format.

It implements the same ``LLMClient`` interface as the Anthropic wrapper, so the loop, the tools,
and the guard do not know or care which one is in use. It uses ``httpx`` directly; no extra
dependency and no agent framework.

The session history is kept in one neutral shape (the Anthropic one: content blocks, with tool
results sent back in a user message). This module translates that shape to and from the OpenAI
one on every request.

What this backend does differently from the Anthropic one:

- ``temperature`` is sent when configured, because these endpoints generally accept it.
- Tool schemas are sent without the ``strict`` flag, which many compatible endpoints reject.
  Arguments are validated by the registry in any case.
- Provider-specific reasoning text is not stored or sent back.
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from typing import Any

import httpx

from wali.agent.llm import LLMError, LLMResponse, ToolCall

RETRY_DELAYS_SECONDS = (0.5, 1.5)
MAX_DETAIL_CHARS = 400
UNPARSEABLE_ARGUMENTS = "unparseable_arguments"


def _block(block: Any, name: str, default: Any = None) -> Any:
    return block.get(name, default) if isinstance(block, dict) else getattr(block, name, default)


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate the neutral history into chat-completions messages."""
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for message in messages:
        role, content = message["role"], message["content"]
        if isinstance(content, str):
            out.append({"role": role, "content": content})
            continue
        if role == "user":
            text_parts = []
            for block in content:
                if _block(block, "type") == "tool_result":
                    out.append(
                        {
                            "role": "tool",
                            "tool_call_id": _block(block, "tool_use_id"),
                            "content": str(_block(block, "content", "")),
                        }
                    )
                elif _block(block, "type") == "text":
                    text_parts.append(_block(block, "text", ""))
            if text_parts:
                out.append({"role": "user", "content": "\n".join(text_parts)})
            continue

        text_parts, tool_calls = [], []
        for block in content:
            if _block(block, "type") == "text":
                text_parts.append(_block(block, "text", ""))
            elif _block(block, "type") == "tool_use":
                tool_calls.append(
                    {
                        "id": _block(block, "id"),
                        "type": "function",
                        "function": {
                            "name": _block(block, "name"),
                            "arguments": json.dumps(
                                _block(block, "input") or {}, ensure_ascii=False
                            ),
                        },
                    }
                )
        assistant: dict[str, Any] = {"role": "assistant", "content": "\n".join(text_parts) or None}
        if tool_calls:
            assistant["tool_calls"] = tool_calls
        out.append(assistant)
    return out


def to_openai_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": tool["name"],
                "description": tool["description"],
                "parameters": tool["input_schema"],
            },
        }
        for tool in tools
    ]


def _stop_reason(finish_reason: str | None, has_tool_calls: bool) -> str:
    if has_tool_calls:
        return "tool_use"
    return {"length": "max_tokens", "content_filter": "refusal"}.get(
        finish_reason or "", "end_turn"
    )


class OpenAICompatibleLLM:
    def __init__(
        self,
        *,
        model: str,
        base_url: str,
        api_key: str,
        max_tokens: int = 16000,
        temperature: float | None = None,
        timeout_seconds: float = 120.0,
        client: httpx.Client | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not model:
            raise LLMError(
                "No model is configured. Set WALI_AGENT_MODEL in the .env file.", retryable=False
            )
        if not base_url:
            raise LLMError(
                "No endpoint is configured. Set WALI_LLM_BASE_URL in the .env file.",
                retryable=False,
            )
        if not api_key:
            raise LLMError(
                "No API key is configured. Set WALI_LLM_API_KEY in the .env file.",
                retryable=False,
            )
        self._model = model
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._api_key = api_key
        self._max_tokens = max_tokens
        self._temperature = temperature
        self._client = client or httpx.Client(timeout=timeout_seconds)
        self._sleep = sleep

    def _detail(self, status: int, text: str) -> str:
        cleaned = " ".join(text.split()).replace(self._api_key, "[key]")
        return f"HTTP {status}: {cleaned[:MAX_DETAIL_CHARS]}"

    def _post(self, body: dict[str, Any]) -> dict[str, Any]:
        """Send one request, retrying on overload, server errors, and network failures."""
        failure: LLMError | None = None
        for delay in (0.0, *RETRY_DELAYS_SECONDS):
            if delay:
                self._sleep(delay)
            try:
                response = self._client.post(self._url, json=body, headers=self._headers)
            except httpx.HTTPError:
                failure = LLMError(
                    "I could not reach the model service. Please check the connection and "
                    "try again.",
                    retryable=True,
                    detail="network error",
                )
                continue
            status = response.status_code
            if status == 200:
                try:
                    return response.json()
                except ValueError:
                    failure = LLMError(
                        "The model service sent an answer I could not read. Please try again.",
                        retryable=True,
                        detail=self._detail(status, response.text),
                    )
                    continue
            detail = self._detail(status, response.text)
            if status == 401:
                raise LLMError(
                    "The model rejected the API key. Check WALI_LLM_API_KEY in the .env file.",
                    retryable=False,
                    detail=detail,
                )
            if status == 403:
                raise LLMError(
                    "This API key is not allowed to use the configured model.",
                    retryable=False,
                    detail=detail,
                )
            if status == 404:
                raise LLMError(
                    "The model or endpoint was not found. Check WALI_AGENT_MODEL and "
                    "WALI_LLM_BASE_URL.",
                    retryable=False,
                    detail=detail,
                )
            if status == 429:
                failure = LLMError(
                    "The model is busy right now. Please try again in a moment.",
                    retryable=True,
                    detail=detail,
                )
                continue
            if status >= 500:
                failure = LLMError(
                    "The model service had a problem. Please try again in a moment.",
                    retryable=True,
                    detail=detail,
                )
                continue
            raise LLMError(
                "The model did not accept the request. This is a configuration problem, "
                "not something you did.",
                retryable=False,
                detail=detail,
            )
        raise failure

    def complete(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        body: dict[str, Any] = {
            "model": self._model,
            "messages": to_openai_messages(system, messages),
            "max_tokens": self._max_tokens,
        }
        if tools:
            body["tools"] = to_openai_tools(tools)
        if self._temperature is not None:
            body["temperature"] = self._temperature

        data = self._post(body)
        try:
            choice = data["choices"][0]
            message = choice["message"]
        except (KeyError, IndexError, TypeError):
            raise LLMError(
                "The model service sent an answer I could not read. Please try again.",
                retryable=True,
                detail="no choices in the response",
            ) from None

        text = (message.get("content") or "").strip() if isinstance(message, dict) else ""
        tool_calls: list[ToolCall] = []
        for index, call in enumerate(message.get("tool_calls") or []):
            function = call.get("function") or {}
            raw = function.get("arguments") or "{}"
            try:
                arguments = json.loads(raw) if isinstance(raw, str) else raw
            except ValueError:
                arguments = None
            if not isinstance(arguments, dict):
                # The registry refuses unknown arguments, so the model is told to try again.
                arguments = {UNPARSEABLE_ARGUMENTS: str(raw)[:200]}
            tool_calls.append(
                ToolCall(
                    id=call.get("id") or f"call_{index}",
                    name=function.get("name") or "",
                    input=arguments,
                )
            )

        content: list[dict[str, Any]] = [{"type": "text", "text": text}] if text else []
        content += [
            {"type": "tool_use", "id": c.id, "name": c.name, "input": c.input} for c in tool_calls
        ]
        return LLMResponse(
            stop_reason=_stop_reason(choice.get("finish_reason"), bool(tool_calls)),
            text=text,
            tool_calls=tuple(tool_calls),
            content=content,
        )
