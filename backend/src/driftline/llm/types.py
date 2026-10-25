from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any, Protocol

from pydantic import BaseModel


class Role(str, Enum):
    system = "system"
    user = "user"
    assistant = "assistant"


class Message(BaseModel):
    role: Role
    content: str


class CompletionRequest(BaseModel):
    messages: list[Message]
    temperature: float = 0.0
    # Keep in step with Settings.default_max_output_tokens: thinking tokens count against it.
    max_output_tokens: int = 2048
    # Structured output: a JSON Schema (as produced by Pydantic's model_json_schema) the
    # reply must match, and a short name for it. Providers that cannot constrain output
    # ignore it; the router validates every structured reply either way.
    response_schema: dict[str, Any] | None = None
    schema_name: str | None = None


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0


class CompletionResult(BaseModel):
    text: str
    model: str
    provider: str
    usage: Usage
    latency_ms: float
    degraded: bool = False


class ProviderError(Exception):
    def __init__(self, message: str, *, retryable: bool, status: int | None = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.status = status


# Receives each streamed text fragment, in order.
DeltaHandler = Callable[[str], Awaitable[None]]


class LLMProvider(Protocol):
    name: str

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult: ...

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]: ...


class StreamingProvider(LLMProvider, Protocol):
    """A provider that can stream text deltas. The router falls back to `complete`
    (one delta with the whole text) for providers without `stream`."""

    async def stream(
        self, model: str, request: CompletionRequest, on_delta: DeltaHandler
    ) -> CompletionResult: ...
