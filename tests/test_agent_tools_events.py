from __future__ import annotations

import json

from conftest import FakeProvider, reply

from saicode.ai.base import ProviderError
from saicode.core.agent import Agent
from saicode.core.config import load_config
from saicode.core.events import EventBus, SessionLog
from saicode.core.policy import Policy
from saicode.sandbox import LocalRunner
from saicode.tools import ToolContext


def make_agent(project, replies, answers=("yes",), log_dir=None, include_content=False):
    cfg = load_config(project)
    bus = EventBus(user="tester")
    events = []
    bus.subscribe(events.append)
    log = None
    if log_dir is not None:
        log = SessionLog(log_dir, bus.session_id, include_content)
        bus.subscribe(log)
    answers = list(answers)
    asked = []

    def approver(req):
        asked.append(req)
        return answers.pop(0) if answers else "no"

    policy = Policy(cfg, project)
    ctx = ToolContext(workdir=project, policy=policy, runner=LocalRunner(), approver=approver)
    provider = FakeProvider(replies)
    agent = Agent(provider=provider, model="m1", bus=bus, ctx=ctx, sleep=lambda s: None)
    return agent, events, asked, provider, log


def types(events):
    return [e.type for e in events]


def test_plain_answer(project):
    agent, events, _, _, _ = make_agent(project, [reply("Hello")])
    agent.run_turn("hi")
    assert types(events) == ["user_message", "thinking", "assistant_message", "turn_end"]
    assert len({e.turn_id for e in events}) == 1 and events[0].turn_id.startswith("turn_")


def test_edit_is_approved_and_applied(project):
    replies = [reply(calls=[("edit_file", {"path": "app.py", "old_text": "hi", "new_text": "hello"})]),
               reply("Done")]
    agent, events, asked, _, _ = make_agent(project, replies, answers=["yes"])
    agent.run_turn("change greeting")
    assert (project / "app.py").read_text() == "print('hello')\n"
    assert asked[0].kind == "write" and asked[0].detail_format == "diff"
    result = next(e for e in events if e.type == "tool_result")
    call = next(e for e in events if e.type == "tool_call")
    assert result.parent_id == call.id and result.data["status"] == "ok"


def test_denied_edit_leaves_file(project):
    replies = [reply(calls=[("edit_file", {"path": "app.py", "old_text": "hi", "new_text": "bye"})]),
               reply("ok")]
    agent, events, _, provider, _ = make_agent(project, replies, answers=["no"])
    agent.run_turn("change")
    assert (project / "app.py").read_text() == "print('hi')\n"
    sent_results = provider.chat.sent[1]
    assert "denied" in sent_results[0].output


def test_protected_file_never_reaches_model(project):
    replies = [reply(calls=[("read_file", {"path": ".env"})]), reply("ok")]
    agent, events, asked, provider, _ = make_agent(project, replies)
    agent.run_turn("read env")
    output = provider.chat.sent[1][0].output
    assert "SECRET" not in output and output.startswith("Not allowed")
    assert asked == []


def test_always_skips_later_prompts(project):
    replies = [reply(calls=[("run_command", {"command": "echo one"})]),
               reply(calls=[("run_command", {"command": "echo two"})]),
               reply("done")]
    agent, events, asked, _, _ = make_agent(project, replies, answers=["always"])
    agent.run_turn("run")
    assert len(asked) == 1
    outputs = [e.data["content"] for e in events if e.type == "tool_result"]
    assert outputs == ["one", "two"]


def test_rate_limit_waits_then_retries(project):
    err = ProviderError("quota", "slow down", retry_after=5)
    agent, events, _, _, _ = make_agent(project, [err, reply("ok")])
    agent.run_turn("hi")
    assert "waiting" in types(events) and types(events)[-1] == "turn_end"


def test_quota_error_can_switch_model_and_retry(project):
    err = ProviderError("quota", "limit: 0", free_tier=True, no_quota=True, daily=True)
    agent, events, _, provider, _ = make_agent(project, [err, reply("ok")])

    def on_error(e):
        agent.switch_model("m2")
        return "retry"

    agent.on_error = on_error
    agent.run_turn("hi")
    assert agent.model == "m2" and provider.started == ["m1", "m2"]
    assert types(events)[-1] == "turn_end"


def test_unrecoverable_error_stops_turn(project):
    agent, events, _, _, _ = make_agent(project, [ProviderError("auth", "bad key", code=400)])
    agent.run_turn("hi")
    assert types(events)[-1] == "error"


def test_session_log_omits_content_by_default(project, tmp_path):
    replies = [reply(calls=[("read_file", {"path": "app.py"})]), reply("ok")]
    agent, events, _, _, log = make_agent(project, replies, log_dir=tmp_path / "logs")
    agent.run_turn("read app")
    log.close()
    records = [json.loads(l) for l in log.path.read_text().splitlines()]
    assert all(r["session_id"] == agent.bus.session_id and r["user"] == "tester" for r in records)
    assert [r["seq"] for r in records] == sorted(r["seq"] for r in records)
    result = next(r for r in records if r["type"] == "tool_result")
    assert "print('hi')" not in json.dumps(result)
    assert "chars omitted" in result["data"]["content"]


def test_session_log_can_include_content(project, tmp_path):
    replies = [reply(calls=[("read_file", {"path": "app.py"})]), reply("ok")]
    agent, _, _, _, log = make_agent(project, replies, log_dir=tmp_path / "logs", include_content=True)
    agent.run_turn("read app")
    log.close()
    assert "print('hi')" in log.path.read_text()


def test_step_limit(project):
    loop = [reply(calls=[("list_files", {"path": "."})]) for _ in range(5)]
    agent, events, _, _, _ = make_agent(project, loop)
    agent.max_steps = 2
    agent.run_turn("loop")
    assert types(events)[-1] == "step_limit"


def test_core_does_not_import_tui():
    import pathlib
    core = pathlib.Path(__file__).parents[1] / "src" / "saicode"
    for pkg in ("core", "ai", "tools", "sandbox"):
        for f in (core / pkg).rglob("*.py"):
            for line in f.read_text().splitlines():
                stripped = line.strip()
                if stripped.startswith(("import ", "from ")):
                    assert "saicode.tui" not in stripped, f"{f} imports the UI"
