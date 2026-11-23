"""The agent loop. Knows nothing about the screen: it only emits events.

Event types emitted:
    session_start, user_message, thinking, assistant_message, tool_call,
    running, tool_result, waiting, error, cancelled, turn_end, model_switched,
    conversation_reset, step_limit
"""

from __future__ import annotations

import functools
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from saicode import tools
from saicode.ai.base import Provider, ProviderError, Reply, ToolResult
from saicode.core.events import EventBus, new_id

MAX_AUTO_WAIT = 90
SERVER_RETRIES = 3

ErrorHandler = Callable[[ProviderError], str | None]  # return "retry" to try again


def system_prompt(workdir: Path) -> str:
    return (
        f"You are saicode, a coding agent working in the project folder: {workdir}\n"
        "Use the tools to inspect files before changing them. Prefer edit_file for small "
        "changes and write_file for new files. Run tests or commands to verify your work.\n"
        "Some files and commands are blocked by policy; if a tool says 'Not allowed', do not "
        "try to work around it, tell the user instead.\n"
        "Be concise and professional. Use Markdown. Summarize what you changed at the end."
    )


@dataclass
class Agent:
    provider: Provider
    model: str
    bus: EventBus
    ctx: tools.ToolContext
    max_steps: int = 40
    on_error: ErrorHandler = lambda e: None
    sleep: Callable[[float], None] = time.sleep
    tokens_in: int = 0
    tokens_out: int = 0
    chat: Any = field(default=None, init=False)

    def __post_init__(self) -> None:
        self.ctx.on_running = self._on_running
        self.chat = self._new_chat()

    def _on_running(self, command: str) -> None:
        self.bus.emit("running", command=command)

    def _send_tool_results(self, results: list[ToolResult]) -> Reply:
        # self.chat is looked up on every call: after a quota error the retry
        # may run on a switched (fallback) model with a new chat.
        return self.chat.send_tool_results(results)

    def _new_chat(self, history: Any = None):
        return self.provider.start_chat(
            self.model, system_prompt(self.ctx.workdir), tools.specs(), history
        )

    # ---- session control ----------------------------------------------------

    def switch_model(self, name: str, keep_history: bool = True) -> None:
        history = self.chat.history() if keep_history else None
        old = self.model
        self.model = name
        self.chat = self._new_chat(history)
        self.bus.emit("model_switched", old=old, new=name)

    def reset(self) -> None:
        self.chat = self._new_chat()
        self.tokens_in = self.tokens_out = 0
        self.bus.emit("conversation_reset")

    # ---- the loop ------------------------------------------------------------

    def _send(self, fn: Callable[[], Reply]) -> Reply | None:
        server_tries = 0
        while True:
            self.bus.emit("thinking", model=self.model)
            try:
                return fn()
            except KeyboardInterrupt:
                self.bus.emit("cancelled")
                return None
            except ProviderError as e:
                if (
                    e.kind == "quota"
                    and not e.no_quota
                    and not e.daily
                    and e.retry_after is not None
                    and e.retry_after <= MAX_AUTO_WAIT
                ):
                    self.bus.emit("waiting", seconds=e.retry_after, reason="rate limit")
                    self.sleep(e.retry_after + 1)
                    continue
                if e.kind == "server" and server_tries < SERVER_RETRIES:
                    server_tries += 1
                    wait = 2**server_tries
                    self.bus.emit("waiting", seconds=wait, reason="the model service is busy")
                    self.sleep(wait)
                    continue
                self.bus.emit(
                    "error", kind=e.kind, code=e.code, message=e.message[:500], model=self.model
                )
                if self.on_error(e) == "retry":
                    continue
                return None

    def run_turn(self, message: str) -> None:
        self.bus.turn_id = new_id("turn")
        self.bus.emit("user_message", text=message)
        reply = self._send(lambda: self.chat.send(message))
        steps = 0
        while reply is not None:
            self.tokens_in += reply.usage.input_tokens
            self.tokens_out += reply.usage.output_tokens
            if reply.text.strip():
                self.bus.emit("assistant_message", text=reply.text)
            if not reply.tool_calls:
                self.bus.emit("turn_end", tokens_in=self.tokens_in, tokens_out=self.tokens_out)
                break
            steps += 1
            if steps > self.max_steps:
                self.bus.emit("step_limit", limit=self.max_steps)
                break
            results = []
            for call in reply.tool_calls:
                action, target = tools.describe(call.name, call.args)
                evt = self.bus.emit(
                    "tool_call",
                    tool=call.name,
                    action=action,
                    target=target,
                    args={
                        k: v
                        for k, v in call.args.items()
                        if k not in ("content", "old_text", "new_text")
                    },
                )
                try:
                    outcome = tools.execute(self.ctx, call.name, call.args)
                except KeyboardInterrupt:
                    outcome = tools.ToolOutcome(
                        "The user cancelled this action.", "cancelled", "denied"
                    )
                self.bus.emit(
                    "tool_result",
                    parent_id=evt.id,
                    tool=call.name,
                    status=outcome.status,
                    summary=outcome.summary,
                    output=outcome.output,
                    content=outcome.content,
                )
                results.append(ToolResult(call, outcome.output))
            reply = self._send(functools.partial(self._send_tool_results, results))
        self.bus.turn_id = None
