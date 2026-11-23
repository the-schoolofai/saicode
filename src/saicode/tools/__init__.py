"""Built-in tools. Each tool checks the policy before acting.

Tools never draw on the screen. When a change needs the user's approval,
they hand an ApprovalRequest to the approver the front end provides.
"""

from __future__ import annotations

import difflib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from saicode.ai.base import ToolSpec
from saicode.core.policy import LIST, READ, RUN, WRITE, Decision, Policy
from saicode.sandbox import Runner

MAX_READ_CHARS = 100_000
MAX_OUTPUT_CHARS = 20_000
SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv"}


@dataclass
class ApprovalRequest:
    kind: str  # "write" or "run": the bucket for "always allow"
    title: str  # e.g. "Edit src/app.py"
    detail: str  # a diff, new file content, or a command
    detail_format: str  # "diff", "file:<path>" or "shell"
    can_always: bool = True


Approver = Callable[[ApprovalRequest], str]  # returns "yes", "no" or "always"


@dataclass
class ToolOutcome:
    output: str  # what the model sees
    summary: str  # one line for the screen and the audit log
    status: str = "ok"  # "ok" | "denied" | "error"
    content: str | None = None  # full content (logged only if include_content)


@dataclass
class ToolContext:
    workdir: Path
    policy: Policy
    runner: Runner
    approver: Approver
    on_running: Callable[[str], None] = lambda command: None


def _ask(ctx: ToolContext, req: ApprovalRequest) -> bool:
    req.can_always = ctx.policy.allow_always
    answer = ctx.approver(req)
    if answer == "always":
        ctx.policy.remember_always(req.kind)
        return True
    return answer == "yes"


def _denied(reason: str) -> ToolOutcome:
    return ToolOutcome(output=f"Not allowed: {reason}", summary=reason, status="denied")


# ---- tools ------------------------------------------------------------------


def list_files(ctx: ToolContext, path: str = ".") -> ToolOutcome:
    verdict = ctx.policy.check_path(LIST, path)
    if verdict.decision is Decision.DENY:
        return _denied(verdict.reason)
    target = ctx.policy.resolve(path)
    if target is None or not target.is_dir():
        return ToolOutcome(f"Error: {path} is not a directory.", "not a directory", "error")
    items = [
        p.name + ("/" if p.is_dir() else "")
        for p in sorted(target.iterdir())
        if p.name not in SKIP_DIRS
    ]
    return ToolOutcome("\n".join(items) or "(empty folder)", f"{len(items)} items")


def read_file(ctx: ToolContext, path: str) -> ToolOutcome:
    verdict = ctx.policy.check_path(READ, path)
    if verdict.decision is Decision.DENY:
        return _denied(verdict.reason)
    target = ctx.policy.resolve(path)
    try:
        text = target.read_text(encoding="utf-8")  # type: ignore[union-attr]
    except Exception as e:
        return ToolOutcome(f"Error reading {path}: {e}", f"failed: {e}", "error")
    lines = text.count("\n") + 1
    shown = (
        text if len(text) <= MAX_READ_CHARS else text[:MAX_READ_CHARS] + "\n... (file truncated)"
    )
    return ToolOutcome(shown, f"{lines} lines", content=text)


def write_file(ctx: ToolContext, path: str, content: str) -> ToolOutcome:
    verdict = ctx.policy.check_path(WRITE, path)
    if verdict.decision is Decision.DENY:
        return _denied(verdict.reason)
    target = ctx.policy.resolve(path)
    assert target is not None
    if target.is_dir():
        return ToolOutcome(f"Error: {path} is a directory, not a file.", "is a directory", "error")
    exists = target.exists()
    if verdict.decision is Decision.ASK:
        if exists:
            old = target.read_text(encoding="utf-8", errors="replace")
            detail = "".join(
                difflib.unified_diff(
                    old.splitlines(True),
                    content.splitlines(True),
                    fromfile=f"a/{path}",
                    tofile=f"b/{path}",
                )
            )
            req = ApprovalRequest(WRITE, f"Overwrite {path}", detail or "(no changes)", "diff")
        else:
            req = ApprovalRequest(WRITE, f"Create {path}", content, f"file:{path}")
        if not _ask(ctx, req):
            return ToolOutcome("The user denied this write.", "denied by user", "denied")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return ToolOutcome(
        f"Wrote {path}", f"saved ({len(content.splitlines())} lines)", content=content
    )


def edit_file(ctx: ToolContext, path: str, old_text: str, new_text: str) -> ToolOutcome:
    verdict = ctx.policy.check_path(WRITE, path)
    if verdict.decision is Decision.DENY:
        return _denied(verdict.reason)
    target = ctx.policy.resolve(path)
    assert target is not None
    try:
        text = target.read_text(encoding="utf-8")
    except Exception as e:
        return ToolOutcome(f"Error reading {path}: {e}", f"failed: {e}", "error")
    count = text.count(old_text)
    if count != 1:
        return ToolOutcome(
            f"Error: old_text found {count} times; it must appear exactly once.",
            f"text matched {count} times, expected 1",
            "error",
        )
    new_full = text.replace(old_text, new_text)
    diff = "".join(
        difflib.unified_diff(
            text.splitlines(True),
            new_full.splitlines(True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
        )
    )
    if verdict.decision is Decision.ASK and not _ask(
        ctx, ApprovalRequest(WRITE, f"Edit {path}", diff, "diff")
    ):
        return ToolOutcome("The user denied this edit.", "denied by user", "denied")
    target.write_text(new_full, encoding="utf-8")
    return ToolOutcome(f"Edited {path}", "saved", content=diff)


def run_command(ctx: ToolContext, command: str) -> ToolOutcome:
    verdict = ctx.policy.check_command(command)
    if verdict.decision is Decision.DENY:
        return _denied(verdict.reason)
    if verdict.decision is Decision.ASK and not _ask(
        ctx, ApprovalRequest(RUN, "Run command", command, "shell")
    ):
        return ToolOutcome("The user denied this command.", "denied by user", "denied")
    ctx.on_running(command)
    result = ctx.runner.run(command, ctx.workdir)
    lines = result.output.splitlines()
    status = "ok" if result.exit_code == 0 else "error"
    summary = f"exit {result.exit_code} · {len(lines)} lines of output"
    return ToolOutcome(
        f"exit code {result.exit_code}\n{result.output[-MAX_OUTPUT_CHARS:]}",
        summary,
        status,
        content=result.output,
    )


# ---- registry -----------------------------------------------------------------

_STR = {"type": "string"}

Describer = Callable[[dict[str, Any]], tuple[str, str]]  # args -> (action, target)

TOOLS: dict[str, tuple[ToolSpec, Callable[..., ToolOutcome], Describer]] = {
    "list_files": (
        ToolSpec(
            "list_files",
            "List files and folders inside a directory of the project.",
            {
                "type": "object",
                "properties": {
                    "path": {
                        **_STR,
                        "description": (
                            "Directory relative to the project folder. "
                            'Use "." for the project root.'
                        ),
                    }
                },
            },
        ),
        list_files,
        lambda a: ("List", a.get("path", ".")),
    ),
    "read_file": (
        ToolSpec(
            "read_file",
            "Read a text file from the project.",
            {
                "type": "object",
                "properties": {
                    "path": {**_STR, "description": "File path relative to the project folder."}
                },
                "required": ["path"],
            },
        ),
        read_file,
        lambda a: ("Read", a.get("path", "")),
    ),
    "write_file": (
        ToolSpec(
            "write_file",
            "Create a new file or overwrite an existing file with the full content.",
            {
                "type": "object",
                "properties": {
                    "path": {**_STR, "description": "File path relative to the project folder."},
                    "content": {**_STR, "description": "The complete new content of the file."},
                },
                "required": ["path", "content"],
            },
        ),
        write_file,
        lambda a: ("Write", a.get("path", "")),
    ),
    "edit_file": (
        ToolSpec(
            "edit_file",
            "Replace one exact piece of text in a file. old_text must appear exactly once.",
            {
                "type": "object",
                "properties": {
                    "path": {**_STR, "description": "File path relative to the project folder."},
                    "old_text": {
                        **_STR,
                        "description": "The exact text to find, copied from the file.",
                    },
                    "new_text": {**_STR, "description": "The text to put in its place."},
                },
                "required": ["path", "old_text", "new_text"],
            },
        ),
        edit_file,
        lambda a: ("Edit", a.get("path", "")),
    ),
    "run_command": (
        ToolSpec(
            "run_command",
            "Run a shell command in the project folder (tests, git status, installs).",
            {
                "type": "object",
                "properties": {"command": {**_STR, "description": "The shell command to run."}},
                "required": ["command"],
            },
        ),
        run_command,
        lambda a: ("Run", a.get("command", "")),
    ),
}


def specs() -> list[ToolSpec]:
    return [spec for spec, _, _ in TOOLS.values()]


def execute(ctx: ToolContext, name: str, args: dict[str, Any]) -> ToolOutcome:
    entry = TOOLS.get(name)
    if entry is None:
        return ToolOutcome(f"Unknown tool {name}", f"unknown tool {name}", "error")
    _, handler, _ = entry
    try:
        return handler(ctx, **args)
    except TypeError as e:
        return ToolOutcome(f"Bad arguments for {name}: {e}", "bad arguments", "error")
    except (OSError, UnicodeError) as e:
        # A failed file operation (folder instead of file, no permission, disk full, ...)
        # is reported to the model instead of ending the session.
        reason = e.strerror if isinstance(e, OSError) and e.strerror else str(e)
        return ToolOutcome(f"Error: {name} failed: {reason}", f"failed: {reason}", "error")


def describe(name: str, args: dict[str, Any]) -> tuple[str, str]:
    entry = TOOLS.get(name)
    if entry is None:
        return (name, "")
    return entry[2](args)
