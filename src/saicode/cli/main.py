"""Command line entry point: `saicode`, `saicode login`, `saicode logout`, `saicode config`."""

from __future__ import annotations

import argparse
import getpass
import sys
from pathlib import Path

from saicode import __version__


def _fail(title: str, body: str) -> None:
    from rich.markup import escape

    from saicode.tui.app import ERR, notice
    # Bodies include error text and paths, so they are printed literally, not as markup.
    notice(title, escape(body), ERR)
    sys.exit(1)


def cmd_login(provider: str) -> None:
    from saicode.core.credentials import store_api_key
    from saicode.tui.app import OK, console
    key = getpass.getpass(f"Paste your {provider} API key (input is hidden): ").strip()
    if not key:
        _fail("No key entered", "Nothing was saved.")
    try:
        store_api_key(provider, key)
    except Exception as e:  # noqa: BLE001
        _fail("Could not save the key",
              f"{e}\n\nYou can set it as an environment variable instead, for example in ~/.zshrc:\n"
              f"  export GEMINI_API_KEY=\"...\"")
    console.print(f"[{OK}]Saved.[/] Your {provider} key is in the system keychain.")


def cmd_logout(provider: str) -> None:
    from saicode.core.credentials import delete_api_key
    from saicode.tui.app import console
    removed = delete_api_key(provider)
    console.print("Removed the key from the keychain." if removed else "No stored key was found.")


def cmd_config(workdir: Path) -> None:
    from rich.markup import escape

    from saicode.core.config import ConfigError, load_config
    from saicode.tui.app import console
    try:
        config = load_config(workdir)
    except ConfigError as e:
        _fail("Configuration error", str(e))
    for key, value, source in config.flat():
        lock = " (locked)" if config.is_locked(key) else ""
        console.print(f"{escape(key)} = {escape(repr(value))}  [grey50]# {source}{lock}[/]")


def run_interactive(workdir: Path, model_override: str | None) -> None:
    from saicode.ai import MissingCredentials, ProviderNotAllowed, create_provider
    from saicode.core.agent import Agent
    from saicode.core.config import ConfigError, load_config
    from saicode.core.credentials import get_api_key
    from saicode.core.events import EventBus, SessionLog, session_metadata
    from saicode.core.policy import Policy
    from saicode.sandbox import create_runner
    from saicode.tools import ToolContext
    from saicode.tui.app import App, Renderer, approver

    try:
        config = load_config(workdir)
    except ConfigError as e:
        _fail("Configuration error", str(e))

    if model_override:
        if config.is_locked("model.name"):
            _fail("Model is set by your organization",
                  f"Your organization's policy fixes the model to {config.get('model.name')}.")
        config.data["model"]["name"] = model_override

    try:
        provider = create_provider(config)
    except MissingCredentials as e:
        _fail("API key missing",
              f"No {e} API key was found.\n\nStore one securely with:\n  saicode login\n\n"
              "or set an environment variable, for example GEMINI_API_KEY.")
    except ProviderNotAllowed as e:
        _fail("Provider not allowed", str(e))

    try:
        runner = create_runner(config.get("sandbox.mode", "off"))
    except ValueError as e:
        _fail("Sandbox not available", str(e))

    _, key_source = get_api_key(provider.name)
    email = config.get("identity.email", "")
    bus = EventBus(user=email or getpass.getuser())
    log = None
    if config.get("logging.sessions", True):
        log = SessionLog(Path(config.get("logging.dir")), bus.session_id,
                         bool(config.get("logging.include_content", False)))
        bus.subscribe(log)
    bus.subscribe(Renderer())

    policy = Policy(config, workdir)
    ctx = ToolContext(workdir=workdir, policy=policy, runner=runner, approver=approver)
    model = config.get("model.name")
    agent = Agent(provider=provider, model=model, bus=bus, ctx=ctx,
                  max_steps=int(config.get("ui.max_tool_steps", 40)))

    bus.emit("session_start", **session_metadata(
        workdir, model, provider.name,
        [f"{l.name}:{l.path}" if l.path else l.name for l in config.layers], email))
    app = App(config=config, provider=provider, agent=agent, bus=bus, policy=policy, log=log,
              key_source=key_source, workdir=workdir, runner_name=runner.name)
    try:
        app.run()
    finally:
        bus.emit("session_end", tokens_in=agent.tokens_in, tokens_out=agent.tokens_out)
        if log:
            log.close()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="saicode", description="saicode - terminal coding agent")
    parser.add_argument("--version", action="version", version=f"saicode {__version__}")
    parser.add_argument("--model", help="model to use for this session")
    sub = parser.add_subparsers(dest="command")
    p_login = sub.add_parser("login", help="store an API key in the system keychain")
    p_login.add_argument("provider", nargs="?", default="gemini")
    p_logout = sub.add_parser("logout", help="remove a stored API key")
    p_logout.add_argument("provider", nargs="?", default="gemini")
    sub.add_parser("config", help="show effective settings and where each comes from")
    args = parser.parse_args(argv)

    workdir = Path.cwd().resolve()
    if args.command == "login":
        cmd_login(args.provider)
    elif args.command == "logout":
        cmd_logout(args.provider)
    elif args.command == "config":
        cmd_config(workdir)
    else:
        run_interactive(workdir, args.model)


if __name__ == "__main__":
    main()
