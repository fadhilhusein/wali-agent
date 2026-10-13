"""The single thin wrapper around the Anthropic SDK.

Everything else talks to the small ``LLMClient`` protocol, so tests use a scripted fake and no
other module imports the SDK.

Notes on current Claude models that shape this wrapper:

- No sampling parameters. Current models do not accept ``temperature``, so none is sent.
- No ``thinking`` parameter. Thinking is adaptive by default; depth is steered with ``effort``.
- No forced tool choice. It is rejected by current models; tool use is steered by the prompt
  and by strict tool schemas.
- The assistant's content must be sent back exactly as received on later turns, including
  thinking blocks. ``LLMResponse.content`` carries it opaquely for that purpose.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

import anthropic

REFUSAL_FALLBACK_BETA = "server-side-fallback-2026-07-01"


class LLMError(RuntimeError):
    """The model could not be reached or refused the request shape. ``user_message`` is safe
    to show; it never contains a key or a raw server response."""

    def __init__(self, user_message: str, *, retryable: bool) -> None:
        super().__init__(user_message)
        self.user_message = user_message
        self.retryable = retryable


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]


@dataclass(frozen=True)
class LLMResponse:
    # end_turn | tool_use | max_tokens | refusal | pause_turn | stop_sequence
    stop_reason: str
    text: str
    tool_calls: tuple[ToolCall, ...]
    # The assistant content exactly as received. Append it to the history unchanged.
    content: Any


class LLMClient(Protocol):
    def complete(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse: ...


class AnthropicLLM:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        max_tokens: int = 16000,
        effort: str | None = None,
        refusal_fallback: bool | None = None,
        timeout_seconds: float = 120.0,
        client: anthropic.Anthropic | None = None,
    ) -> None:
        if not model:
            raise LLMError(
                "No model is configured. Set WALI_AGENT_MODEL in the .env file.", retryable=False
            )
        self._model = model
        self._max_tokens = max_tokens
        self._effort = effort
        # Only Anthropic's own endpoint is known to support the fallback beta.
        self._refusal_fallback = base_url is None if refusal_fallback is None else refusal_fallback
        self._client = client or anthropic.Anthropic(
            api_key=api_key, base_url=base_url, timeout=timeout_seconds
        )

    def complete(
        self, *, system: str, messages: list[dict[str, Any]], tools: list[dict[str, Any]]
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "model": self._model,
            "max_tokens": self._max_tokens,
            "system": system,
            "messages": messages,
        }
        if tools:
            request["tools"] = tools
        if self._effort:
            request["output_config"] = {"effort": self._effort}
        try:
            if self._refusal_fallback:
                message = self._client.beta.messages.create(
                    betas=[REFUSAL_FALLBACK_BETA], fallbacks="default", **request
                )
            else:
                message = self._client.messages.create(**request)
        except anthropic.AuthenticationError:
            raise LLMError(
                "The model rejected the API key. Check ANTHROPIC_API_KEY in the .env file.",
                retryable=False,
            ) from None
        except anthropic.PermissionDeniedError:
            raise LLMError(
                "This API key is not allowed to use the configured model.", retryable=False
            ) from None
        except anthropic.NotFoundError:
            raise LLMError(
                "The configured model was not found. Check WALI_AGENT_MODEL.", retryable=False
            ) from None
        except anthropic.BadRequestError:
            raise LLMError(
                "The model did not accept the request. This is a configuration problem, "
                "not something you did.",
                retryable=False,
            ) from None
        except anthropic.RateLimitError:
            raise LLMError(
                "The model is busy right now. Please try again in a moment.", retryable=True
            ) from None
        except anthropic.APIStatusError:
            raise LLMError(
                "The model service had a problem. Please try again in a moment.", retryable=True
            ) from None
        except anthropic.APIConnectionError:
            raise LLMError(
                "I could not reach the model service. Please check the connection and try again.",
                retryable=True,
            ) from None
        except (anthropic.AnthropicError, TypeError):
            # For example no credentials at all, which the SDK reports before sending anything.
            raise LLMError(
                "The model client is not set up correctly. Check ANTHROPIC_API_KEY and the "
                "model settings in the .env file.",
                retryable=False,
            ) from None

        text_parts: list[str] = []
        tool_calls: list[ToolCall] = []
        for block in message.content:
            if block.type == "text":
                text_parts.append(block.text)
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, input=dict(block.input or {}))
                )
        return LLMResponse(
            stop_reason=message.stop_reason or "end_turn",
            text="\n".join(part for part in text_parts if part).strip(),
            tool_calls=tuple(tool_calls),
            content=message.content,
        )
