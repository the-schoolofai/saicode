"""Permission decisions for every tool action.

Order of evaluation (first match wins):

    1. outside the workspace       -> deny
    2. protected file (deny_read)  -> deny
    3. deny rule                   -> deny
    4. read-only mode              -> deny changes and commands
    5. allow rule                  -> allow
    6. reads and listings          -> allow
    7. everything else             -> ask
"""

from __future__ import annotations

import fnmatch
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path, PurePosixPath

from saicode.core.config import Config


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class Verdict:
    decision: Decision
    reason: str = ""


# Action kinds, also used as the "always allow" bucket names.
READ, LIST, WRITE, RUN = "read", "list", "write", "run"


def _glob(pattern: str, value: str) -> bool:
    # fnmatch "*" already crosses "/", so "**/" also needs to match "no directory".
    if fnmatch.fnmatchcase(value, pattern):
        return True
    if pattern.startswith("**/") and fnmatch.fnmatchcase(value, pattern[3:]):
        return True
    return False


_WORD = "A-Za-z0-9_"


def _literal_tokens(pattern: str) -> list[re.Pattern[str]]:
    """Plain words of a glob as regexes, e.g. '**/id_rsa*' -> id_rsa, '**/*.pem' -> .pem.

    A word must stand on its own unless the glob has a wildcard right next to it,
    so '**/*.key' matches 'cat server.key' but not 'python -c "d.keys()"', and
    '**/id_rsa*' still matches 'id_rsa.pub'.
    """
    tokens: list[re.Pattern[str]] = []
    for m in re.finditer(r"[^*?/\[\]]+", pattern):
        word = m.group(0)
        if len(word) < 3:
            continue
        before = pattern[m.start() - 1] if m.start() > 0 else ""
        after = pattern[m.end()] if m.end() < len(pattern) else ""
        left = "" if before in ("*", "?") else f"(?<![{_WORD}])"
        right = "" if after in ("*", "?") else f"(?![{_WORD}])"
        tokens.append(re.compile(left + re.escape(word) + right))
    return tokens


class Policy:
    def __init__(self, config: Config, workdir: Path):
        self.config = config
        self.workdir = workdir.resolve()
        perms = config.get("permissions", {})
        self.mode: str = perms.get("mode", "ask")
        self.allow_rules: list[str] = list(perms.get("allow", []))
        self.deny_rules: list[str] = list(perms.get("deny", []))
        self.deny_read: list[str] = list(perms.get("deny_read", []))
        self.allow_always: bool = bool(perms.get("allow_always", True))
        self.sandbox_required: bool = bool(config.get("sandbox.required", False))
        self.session_always: set[str] = set()

    # ---- paths -------------------------------------------------------------

    def resolve(self, path: str) -> Path | None:
        target = (self.workdir / path).resolve()
        if target == self.workdir or self.workdir in target.parents:
            return target
        return None

    def relative(self, target: Path) -> str:
        try:
            rel = target.relative_to(self.workdir)
        except ValueError:
            return str(target)
        return str(PurePosixPath(*rel.parts)) or "."

    def is_protected(self, target: Path) -> str | None:
        rel = self.relative(target)
        name = target.name
        for pattern in self.deny_read:
            if _glob(pattern, rel) or _glob(pattern, name):
                return pattern
        return None

    # ---- rules -------------------------------------------------------------

    @staticmethod
    def _rule_matches(rules: list[str], kind: str, value: str) -> str | None:
        for rule in rules:
            rkind, _, pattern = rule.partition(":")
            if rkind == kind and _glob(pattern, value):
                return rule
        return None

    # ---- checks ------------------------------------------------------------

    def check_path(self, kind: str, path: str) -> Verdict:
        target = self.resolve(path)
        if target is None:
            return Verdict(Decision.DENY, "path is outside the project folder")
        protected = self.is_protected(target)
        if protected:
            return Verdict(Decision.DENY, f"protected file (matches {protected})")
        rel = self.relative(target)
        rule = self._rule_matches(self.deny_rules, kind, rel)
        if rule:
            return Verdict(Decision.DENY, f"blocked by rule {rule}")
        if kind == WRITE and self.mode == "read-only":
            return Verdict(Decision.DENY, "saicode is in read-only mode")
        rule = self._rule_matches(self.allow_rules, kind, rel)
        if rule:
            return Verdict(Decision.ALLOW, f"allowed by rule {rule}")
        if kind in (READ, LIST):
            return Verdict(Decision.ALLOW)
        if kind in self.session_always:
            return Verdict(Decision.ALLOW, "allowed for this session")
        return Verdict(Decision.ASK)

    def check_command(self, command: str) -> Verdict:
        cmd = " ".join(command.split())
        for pattern in self.deny_read:
            for token in _literal_tokens(pattern):
                found = token.search(cmd)
                if found:
                    return Verdict(Decision.DENY,
                                   f"command touches a protected file ({found.group(0)})")
        rule = self._rule_matches(self.deny_rules, RUN, cmd)
        if rule:
            return Verdict(Decision.DENY, f"blocked by rule {rule}")
        if self.mode == "read-only":
            return Verdict(Decision.DENY, "saicode is in read-only mode")
        if self.sandbox_required and self.config.get("sandbox.mode", "off") == "off":
            return Verdict(Decision.DENY, "policy requires a sandbox and none is available")
        rule = self._rule_matches(self.allow_rules, RUN, cmd)
        if rule:
            return Verdict(Decision.ALLOW, f"allowed by rule {rule}")
        if RUN in self.session_always:
            return Verdict(Decision.ALLOW, "allowed for this session")
        return Verdict(Decision.ASK)

    def remember_always(self, kind: str) -> bool:
        if not self.allow_always:
            return False
        self.session_always.add(kind)
        return True
