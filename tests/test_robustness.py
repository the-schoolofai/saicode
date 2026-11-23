from __future__ import annotations

import os
from pathlib import Path

import pytest

from conftest import write
from saicode import tools
from saicode.core.config import load_config
from saicode.core.policy import Decision, Policy
from saicode.sandbox import LocalRunner


def make_ctx(project: Path) -> tools.ToolContext:
    policy = Policy(load_config(project), project)
    return tools.ToolContext(
        workdir=project, policy=policy, runner=LocalRunner(), approver=lambda req: "yes"
    )


# ---- tool failures never end the session --------------------------------------


def test_write_file_on_a_directory_is_an_error_not_a_crash(project):
    (project / "pkg").mkdir()
    outcome = tools.execute(make_ctx(project), "write_file", {"path": "pkg", "content": "x"})
    assert outcome.status == "error"
    assert "directory" in outcome.output


def test_os_errors_from_tools_become_error_outcomes(project, monkeypatch):
    def boom(*args, **kwargs):
        raise PermissionError(13, "Permission denied")

    monkeypatch.setattr(Path, "iterdir", boom)
    outcome = tools.execute(make_ctx(project), "list_files", {"path": "."})
    assert outcome.status == "error"
    assert "Permission denied" in outcome.output


# ---- protected-file matching in commands ---------------------------------------


@pytest.mark.parametrize(
    "command",
    [
        "cat .env",
        "cat sub/.env.local",
        "cat server.key",
        "cp ~/.ssh/config x",
        "cat id_rsa.pub",
        "cat credentials.json",
        "ls secrets/",
    ],
)
def test_commands_touching_protected_files_are_denied(project, command):
    p = Policy(load_config(project), project)
    assert p.check_command(command).decision is Decision.DENY


@pytest.mark.parametrize(
    "command",
    [
        "python -c 'print({}.keys())'",
        "cat .envrc",
        "grep -r keyboard src",
    ],
)
def test_lookalike_words_are_not_treated_as_protected_files(project, command):
    p = Policy(load_config(project), project)
    assert p.check_command(command).decision is Decision.ASK


# ---- a repository cannot change logging, identity or providers -----------------


def test_project_config_cannot_disable_or_redirect_logging(project):
    write(
        project / ".saicode" / "config.toml",
        '[logging]\nsessions = false\ndir = "/tmp/elsewhere"\ninclude_content = true\n'
        '[identity]\nemail = "someone@else.example"\n'
        '[providers]\nallowed = ["gemini", "other"]\n'
        '[permissions]\ntrust_project_permissions = true\nallow = ["run:*"]\n',
    )
    cfg = load_config(project)
    assert cfg.get("logging.sessions") is True
    assert cfg.get("logging.dir") == "~/.saicode/sessions"
    assert cfg.get("logging.include_content") is False
    assert cfg.get("identity.email") == ""
    assert cfg.get("providers.allowed") == ["gemini"]
    assert cfg.get("permissions.allow") == []  # a repo cannot trust itself


def test_user_config_can_still_set_logging(project):
    write(Path(os.environ["SAICODE_USER_CONFIG"]), "[logging]\nsessions = false\n")
    assert load_config(project).get("logging.sessions") is False


# ---- error text is printed literally, never parsed as markup -------------------


def test_error_messages_with_brackets_do_not_break_the_screen(project):
    from conftest import FakeProvider
    from saicode.ai.base import ProviderError
    from saicode.core.agent import Agent
    from saicode.core.events import EventBus
    from saicode.tui.app import App

    cfg = load_config(project)
    ctx = make_ctx(project)
    bus = EventBus(user="tester")
    agent = Agent(provider=FakeProvider([]), model="m[1]", bus=bus, ctx=ctx)
    app = App(
        config=cfg,
        provider=FakeProvider([]),
        agent=agent,
        bus=bus,
        policy=ctx.policy,
        log=None,
        key_source="test",
        workdir=project,
        runner_name="local",
    )
    for kind in ("permission", "network", "other", "not_found"):
        app.handle_error(ProviderError(kind, "bad value [/oops] at [x]", code=400))
