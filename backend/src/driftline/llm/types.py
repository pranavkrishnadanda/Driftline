from enum import Enum
from typing import Protocol

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
    max_output_tokens: int = 1024


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


class LLMProvider(Protocol):
    name: str

    async def complete(self, model: str, request: CompletionRequest) -> CompletionResult: ...

    async def embed(self, model: str, texts: list[str], dim: int) -> list[list[float]]: ...
