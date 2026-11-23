from __future__ import annotations

from pathlib import Path

import pytest

from saicode.ai.base import Reply, ToolCall, ToolResult, Usage


@pytest.fixture(autouse=True)
def isolated_config(tmp_path, monkeypatch):
    """Never read the real ~/.saicode or /etc/saicode during tests."""
    monkeypatch.setenv("SAICODE_USER_CONFIG", str(tmp_path / "home" / "config.toml"))
    monkeypatch.setenv("SAICODE_SYSTEM_POLICY", str(tmp_path / "system" / "policy.toml"))
    return tmp_path


@pytest.fixture
def project(tmp_path) -> Path:
    p = tmp_path / "project"
    p.mkdir()
    (p / "app.py").write_text("print('hi')\n")
    (p / ".env").write_text("SECRET=1\n")
    return p


def write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)
    return path


class FakeChat:
    def __init__(self, replies):
        self.replies = list(replies)
        self.sent: list = []

    def _next(self):
        item = self.replies.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def send(self, message: str) -> Reply:
        self.sent.append(message)
        return self._next()

    def send_tool_results(self, results: list[ToolResult]) -> Reply:
        self.sent.append(results)
        return self._next()

    def history(self):
        return ["history"]


class FakeProvider:
    name = "fake"

    def __init__(self, replies):
        self.chat = FakeChat(replies)
        self.started: list[str] = []

    def start_chat(self, model, system, tools, history=None):
        self.started.append(model)
        return self.chat

    def list_models(self):
        return ["m1", "m2"]

    def check_model(self, model):
        return None


def reply(text: str = "", calls: list[tuple[str, dict]] | None = None) -> Reply:
    return Reply(text=text, tool_calls=[ToolCall(n, a) for n, a in (calls or [])], usage=Usage(10, 5))
