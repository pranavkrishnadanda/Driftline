from typing import Any

import anthropic
from anthropic.types import Message as SdkMessage
from anthropic.types import MessageParam

from driftline.clock import Clock, SystemClock
from driftline.llm.types import (
    CompletionRequest,
    CompletionResult,
    DeltaHandler,
    ProviderError,
    Role,
    Usage,
)

RETRYABLE_STATUS = {408, 409, 429}


def _is_retryable(status: int) -> bool:
    # 5xx covers 529 (overloaded).
    return status in RETRYABLE_STATUS or status >= 500


def _result_text(message: SdkMessage) -> str:
    text = "".join(block.text for block in message.content if block.type == "text")
    if not text:
        raise ProviderError(
            f"empty response from anthropic (stop_reason={message.stop_reason})", retryable=False
        )
    return text


def request_kwargs(model: str, request: CompletionRequest) -> dict[str, Any]:
    """Messages API arguments for a request (shared by `complete` and `stream`)."""
    system = "\n".join(m.content for m in request.messages if m.role is Role.system)
    messages: list[MessageParam] = [
        {"role": "user" if m.role is Role.user else "assistant", "content": m.content}
        for m in request.messages
        if m.role is not Role.system
    ]
    # request.temperature is deliberately not sent: current Claude models reject
    # non-default sampling parameters with a 400.
    kwargs: dict[str, Any] = {
        "model": model,
        "max_tokens": request.max_output_tokens,
        "messages": messages,
    }
    if system:
        kwargs["system"] = system
    if request.response_schema is not None:
        # Structured outputs (output_config.format) constrain decoding to the schema.
        # Forced tool_choice is rejected by Sonnet 5.5, so tools are not used for this.
        # transform_schema drops what the API does not support (minLength, ...) and
        # sets additionalProperties: false; the router still validates the reply.
        kwargs["output_config"] = {
            "format": {
                "type": "json_schema",
                "schema": anthropic.transform_schema(request.response_schema),
            }
        }
    return kwargs


def _usage(message: SdkMessage) -> Usage:
    return Usage(input_tokens=message.usage.input_tokens, output_tokens=message.usage.output_tokens)


class AnthropicAdapter:
    name = "anthropic"

    def __init__(self, api_key: str, *, clock: Clock | None = None) -> None:
        # Retries belong to the router; the SDK must not retry underneath it.
        self._client = anthropic.AsyncAnthropic(api_key=api_key, max_retries=0)
        self._clock = clock or SystemClock()

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult:
        start = self._clock.now()
        try:
            message = await self._client.messages.create(**request_kwargs(model, request))
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                str(exc), retryable=_is_retryable(exc.status_code), status=exc.status_code
            ) from exc
        except anthropic.APIConnectionError as exc:  # includes APITimeoutError
            raise ProviderError(f"transport error: {exc}", retryable=True) from exc
        return CompletionResult(
            text=_result_text(message),
            model=model,
            provider=self.name,
            usage=_usage(message),
            latency_ms=(self._clock.now() - start) * 1000,
        )

    async def stream(
        self, model: str, request: CompletionRequest, on_delta: DeltaHandler
    ) -> CompletionResult:
        """Stream text deltas (thinking blocks are not forwarded)."""
        start = self._clock.now()
        try:
            async with self._client.messages.stream(**request_kwargs(model, request)) as stream:
                async for text in stream.text_stream:
                    if text:
                        await on_delta(text)
                message = await stream.get_final_message()
        except anthropic.APIStatusError as exc:
            raise ProviderError(
                str(exc), retryable=_is_retryable(exc.status_code), status=exc.status_code
            ) from exc
        except anthropic.APIConnectionError as exc:
            raise ProviderError(f"transport error: {exc}", retryable=True) from exc
        return CompletionResult(
            text=_result_text(message),
            model=model,
            provider=self.name,
            usage=_usage(message),
            latency_ms=(self._clock.now() - start) * 1000,
        )

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]:
        raise ProviderError("anthropic does not provide embeddings", retryable=False)
