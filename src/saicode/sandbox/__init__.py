"""Command execution behind one interface.

Phase A1 ships the interface and an unsandboxed local runner. Phase A2 adds
an OS-level sandbox (andbox-runtime) behind the same interface,
so no other code changes when it arrives.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


@dataclass
class RunResult:
    exit_code: int
    output: str
    timed_out: bool = False


class Runner(Protocol):
    name: str
    isolated: bool

    def run(self, command: str, cwd: Path, timeout: int = 300) -> RunResult: ...


class LocalRunner:
    """Runs commands directly on this computer. No isolation."""

    name = "local"
    isolated = False

    def run(self, command: str, cwd: Path, timeout: int = 300) -> RunResult:
        try:
            # Shell is intentional: this runner executes the agent's shell tool commands.
            r = subprocess.run(
                command,
                shell=True,
                cwd=cwd,
                capture_output=True,  # nosec B602
                text=True,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return RunResult(exit_code=-1, output=f"timed out after {timeout}s", timed_out=True)
        return RunResult(exit_code=r.returncode, output=(r.stdout + r.stderr).strip())


def create_runner(mode: str) -> Runner:
    if mode in ("off", "", None):
        return LocalRunner()
    raise ValueError(
        f"Sandbox mode '{mode}' is not available in this version (coming in phase A2)."
    )
