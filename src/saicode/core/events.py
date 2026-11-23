"""Events: everything the agent does is an event with stable IDs.

The UI subscribes to events to draw the screen. The session log writes them
to disk. Later, saicode Server can receive the same events for central audit.
"""

from __future__ import annotations

import getpass
import json
import socket
import uuid
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from saicode import __version__

# Fields that may hold file contents or command output. Dropped from the
# session log unless logging.include_content is true.
CONTENT_FIELDS = {"content", "output", "text", "diff", "old_text", "new_text", "result"}


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


@dataclass
class Event:
    type: str
    data: dict[str, Any]
    id: str
    session_id: str
    user: str
    seq: int
    ts: str
    turn_id: str | None = None
    parent_id: str | None = None

    def to_record(self, include_content: bool) -> dict[str, Any]:
        record = asdict(self)
        if not include_content:
            record["data"] = {
                k: (f"<{len(str(v))} chars omitted>" if k in CONTENT_FIELDS and v else v)
                for k, v in self.data.items()
            }
        return record


Listener = Callable[[Event], None]


@dataclass
class EventBus:
    session_id: str = field(default_factory=lambda: new_id("ses"))
    user: str = field(default_factory=lambda: getpass.getuser())
    listeners: list[Listener] = field(default_factory=list)
    seq: int = 0
    turn_id: str | None = None

    def subscribe(self, listener: Listener) -> None:
        self.listeners.append(listener)

    def emit(self, type: str, parent_id: str | None = None, **data: Any) -> Event:
        self.seq += 1
        event = Event(
            type=type,
            data=data,
            id=new_id("evt"),
            session_id=self.session_id,
            user=self.user,
            seq=self.seq,
            ts=_now(),
            turn_id=self.turn_id,
            parent_id=parent_id,
        )
        for listener in list(self.listeners):
            listener(event)
        return event


class SessionLog:
    """Append-only JSONL file: one event per line."""

    def __init__(self, directory: Path, session_id: str, include_content: bool):
        day = datetime.now(UTC).strftime("%Y-%m-%d")
        self.path = directory.expanduser() / day / f"{session_id}.jsonl"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.include_content = include_content
        self._file = self.path.open("a", encoding="utf-8")

    def __call__(self, event: Event) -> None:
        self._file.write(json.dumps(event.to_record(self.include_content), default=str) + "\n")
        self._file.flush()

    def close(self) -> None:
        self._file.close()


def session_metadata(
    workdir: Path, model: str, provider: str, config_sources: list[str], identity_email: str
) -> dict[str, Any]:
    return {
        "saicode_version": __version__,
        "host": socket.gethostname(),
        "workdir": str(workdir),
        "provider": provider,
        "model": model,
        "config_layers": config_sources,
        "identity_email": identity_email or None,
    }
