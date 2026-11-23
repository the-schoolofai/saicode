"""Layered configuration.

Layers are merged in this order (later wins):

    1. built-in defaults
    2. user config      ~/.saicode/config.toml
    3. project config   <project>/.saicode/config.toml
    4. system policy    set by an administrator, always wins (locked)

Security lists (``permissions.deny`` and ``permissions.deny_read``) are
*unioned* across every layer, so no layer can remove a rule another added.

A project config comes from the repository, so it is untrusted: its
``permissions.allow`` rules are ignored unless the user config sets
``trust_project_permissions = true`` and the system policy does not forbid it.
It can never change logging, identity or the provider allowlist (PROJECT_NEVER).
"""

from __future__ import annotations

import copy
import os
import sys
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

UNION_KEYS = {("permissions", "deny"), ("permissions", "deny_read")}

# Settings a project config (which comes from the repository) can never change.
PROJECT_NEVER: dict[str, tuple[str, ...]] = {
    "logging": ("sessions", "dir", "include_content"),
    "identity": ("email",),
    "providers": ("allowed",),
}

DEFAULTS: dict[str, Any] = {
    "model": {
        "provider": "gemini",
        "name": "gemini-3.1-pro-preview",
        "fallbacks": ["gemini-3-flash-preview", "gemini-3.1-flash-lite", "gemini-2.5-flash"],
    },
    "providers": {
        # Providers saicode may talk to. An administrator can narrow this list.
        "allowed": ["gemini"],
    },
    "permissions": {
        # "ask"  - ask before file changes and commands (default)
        # "read-only" - deny every file change and command
        "mode": "ask",
        # Rules: "run:<command glob>", "write:<path glob>", "read:<path glob>"
        "allow": [],
        "deny": [
            "run:rm -rf /*",
            "run:rm -rf ~*",
            "run:sudo *",
            "run:* | sh",
            "run:* | bash",
        ],
        # Files the agent may never read, write or touch in a command.
        "deny_read": [
            ".env",
            ".env.*",
            "**/.env",
            "**/.env.*",
            "**/*.pem",
            "**/*.key",
            "**/id_rsa*",
            "**/id_ed25519*",
            "**/.ssh/**",
            "**/secrets/**",
            "**/credentials*",
            "**/.aws/**",
            "**/.npmrc",
            "**/.pypirc",
        ],
        "allow_always": True,          # may the user choose "always allow" for a session?
        "trust_project_permissions": False,
    },
    "sandbox": {
        # "off" until the sandbox ships in phase A2.
        "mode": "off",
        # If true, commands are refused whenever no sandbox is available.
        "required": False,
    },
    "logging": {
        "sessions": True,
        "dir": "~/.saicode/sessions",
        # Full file contents and command output in the log. Off by default for privacy.
        "include_content": False,
    },
    "identity": {
        # Optional: who is using saicode, recorded in every event.
        "email": "",
    },
    "ui": {
        "max_tool_steps": 40,
    },
}


def system_policy_path() -> Path:
    override = os.environ.get("SAICODE_SYSTEM_POLICY")
    if override:
        return Path(override)
    if sys.platform == "darwin":
        return Path("/Library/Application Support/saicode/policy.toml")
    if sys.platform.startswith("win"):
        base = os.environ.get("ProgramData", r"C:\ProgramData")
        return Path(base) / "saicode" / "policy.toml"
    return Path("/etc/saicode/policy.toml")


def user_config_path() -> Path:
    override = os.environ.get("SAICODE_USER_CONFIG")
    if override:
        return Path(override)
    return Path.home() / ".saicode" / "config.toml"


def project_config_path(workdir: Path) -> Path:
    return workdir / ".saicode" / "config.toml"


class ConfigError(Exception):
    pass


@dataclass
class Layer:
    name: str
    path: Path | None
    data: dict[str, Any]


@dataclass
class Config:
    data: dict[str, Any]
    layers: list[Layer] = field(default_factory=list)
    sources: dict[str, str] = field(default_factory=dict)   # "a.b" -> layer name
    locked: set[str] = field(default_factory=set)             # keys set by system policy

    def get(self, dotted: str, default: Any = None) -> Any:
        node: Any = self.data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return default
            node = node[part]
        return node

    def is_locked(self, dotted: str) -> bool:
        return any(dotted == k or dotted.startswith(k + ".") for k in self.locked)

    def flat(self) -> list[tuple[str, Any, str]]:
        rows: list[tuple[str, Any, str]] = []

        def walk(prefix: str, node: Any) -> None:
            if isinstance(node, dict):
                for k, v in node.items():
                    walk(f"{prefix}.{k}" if prefix else k, v)
            else:
                rows.append((prefix, node, self.sources.get(prefix, "default")))

        walk("", self.data)
        return rows


def _read_toml(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        with path.open("rb") as f:
            return tomllib.load(f)
    except (tomllib.TOMLDecodeError, OSError) as e:
        raise ConfigError(f"Could not read {path}: {e}") from e


def _merge(base: dict, over: dict, layer: str, sources: dict, prefix: tuple = ()) -> None:
    for key, value in over.items():
        path = prefix + (key,)
        dotted = ".".join(path)
        if isinstance(value, dict) and isinstance(base.get(key), dict):
            _merge(base[key], value, layer, sources, path)
            continue
        if path in UNION_KEYS and isinstance(value, list):
            existing = base.get(key) or []
            base[key] = existing + [v for v in value if v not in existing]
        else:
            base[key] = copy.deepcopy(value)
        sources[dotted] = layer


def _keys(node: dict, prefix: str = "") -> set[str]:
    out: set[str] = set()
    for k, v in node.items():
        dotted = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out |= _keys(v, dotted)
        else:
            out.add(dotted)
    return out


def load_config(workdir: Path) -> Config:
    data = copy.deepcopy(DEFAULTS)
    sources: dict[str, str] = {}
    layers: list[Layer] = [Layer("default", None, copy.deepcopy(DEFAULTS))]

    user_path = user_config_path()
    user = _read_toml(user_path)
    project_path = project_config_path(workdir)
    project = _read_toml(project_path)
    system_path = system_policy_path()
    system = _read_toml(system_path)

    trust_project = bool(
        system.get("permissions", {}).get(
            "trust_project_permissions",
            user.get("permissions", {}).get("trust_project_permissions", False),
        )
    )
    if project:
        # A repository may never redirect or switch off the audit log, change who the
        # user is, or widen the provider list.
        for section, keys in PROJECT_NEVER.items():
            node = project.get(section)
            if isinstance(node, dict):
                for key in keys:
                    node.pop(key, None)
        perms = project.get("permissions")
        if isinstance(perms, dict):
            perms.pop("trust_project_permissions", None)   # a repo cannot trust itself
            if not trust_project:
                perms.pop("allow", None)
                perms.pop("mode", None)          # a repo cannot loosen the permission mode
                perms.pop("allow_always", None)

    for name, path, layer in (("user", user_path, user),
                              ("project", project_path, project),
                              ("system", system_path, system)):
        if layer:
            _merge(data, layer, name, sources)
            layers.append(Layer(name, path, layer))

    # System policy can replace the user's allow list outright.
    if system.get("permissions", {}).get("allow") is not None:
        data["permissions"]["allow"] = list(system["permissions"]["allow"])

    return Config(data=data, layers=layers, sources=sources, locked=_keys(system))
