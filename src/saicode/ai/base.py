"""Provider interface. The core only talks to these types, never to a vendor SDK."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema object


@dataclass
class ToolCall:
    name: str
    args: dict[str, Any]
    id: str | None = None


@dataclass
class ToolResult:
    call: ToolCall
    output: str


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0


@dataclass
class Reply:
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


class ProviderError(Exception):
    """A provider failure, translated into kinds the core understands.

    kind: "quota" | "auth" | "permission" | "not_found" | "server" | "network" | "other"
    """

    def __init__(
        self,
        kind: str,
        message: str,
        *,
        retry_after: int | None = None,
        free_tier: bool = False,
        no_quota: bool = False,
        daily: bool = False,
        code: int | None = None,
    ):
        super().__init__(message)
        self.kind = kind
        self.message = message
        self.retry_after = retry_after
        self.free_tier = free_tier
        self.no_quota = no_quota
        self.daily = daily
        self.code = code


class ChatSession(Protocol):
    def send(self, message: str) -> Reply: ...
    def send_tool_results(self, results: list[ToolResult]) -> Reply: ...
    def history(self) -> Any: ...


class Provider(Protocol):
    name: str

    def start_chat(
        self, model: str, system: str, tools: list[ToolSpec], history: Any = None
    ) -> ChatSession: ...
    def list_models(self) -> list[str]: ...
    def check_model(self, model: str) -> None: ...
