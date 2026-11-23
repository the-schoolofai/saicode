"""Terminal front end. Draws events from the core and asks the user for approvals."""

from __future__ import annotations

from pathlib import Path

from prompt_toolkit import PromptSession
from prompt_toolkit.history import FileHistory
from rich.console import Console, Group
from rich.markdown import Markdown
from rich.markup import escape
from rich.panel import Panel
from rich.rule import Rule
from rich.status import Status
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from saicode import __version__
from saicode.ai.base import Provider, ProviderError
from saicode.core.agent import Agent
from saicode.core.config import Config
from saicode.core.events import Event, EventBus, SessionLog
from saicode.core.policy import Policy
from saicode.tools import ApprovalRequest

ACCENT = "#7aa2f7"
MUTED = "grey50"
OK = "#9ece6a"
WARN = "#e0af68"
ERR = "#f7768e"

LOGO = r"""
 ███████╗  █████╗  ██╗  ██████╗  ██████╗  ██████╗  ███████╗
 ██╔════╝ ██╔══██╗ ██║ ██╔════╝ ██╔═══██╗ ██╔══██╗ ██╔════╝
 ███████╗ ███████║ ██║ ██║      ██║   ██║ ██║  ██║ █████╗
 ╚════██║ ██╔══██║ ██║ ██║      ██║   ██║ ██║  ██║ ██╔══╝
 ███████║ ██║  ██║ ██║ ╚██████╗ ╚██████╔╝ ██████╔╝ ███████╗
 ╚══════╝ ╚═╝  ╚═╝ ╚═╝  ╚═════╝  ╚═════╝  ╚═════╝  ╚══════╝
"""
GRADIENT = ["#7dcfff", "#7aa2f7", "#7aa2f7", "#9a8cf7", "#bb9af7", "#bb9af7"]

console = Console(highlight=False)


def short_home(path: Path | str) -> str:
    home, s = str(Path.home()), str(path)
    return "~" + s[len(home) :] if s.startswith(home) else s


def notice(title: str, body: str, style: str = WARN) -> None:
    console.print(
        Panel(
            body,
            title=f"[bold {style}]{title}[/]",
            title_align="left",
            border_style=style,
            padding=(1, 2),
        )
    )


# ---- event renderer ------------------------------------------------------------


class Renderer:
    """Turns core events into screen output."""

    def __init__(self) -> None:
        self.status: Status | None = None

    def _stop(self) -> None:
        if self.status is not None:
            self.status.stop()
            self.status = None

    def _spin(self, message: str) -> None:
        self._stop()
        self.status = console.status(message, spinner="dots")
        self.status.start()

    def __call__(self, e: Event) -> None:
        d = e.data
        t = e.type
        if t == "thinking":
            self._spin(f"[{MUTED}]thinking...[/]")
            return
        if t == "waiting":
            self._spin(f"[{WARN}]{d['reason']}, retrying in {d['seconds']}s[/]")
            return
        if t == "running":
            self._spin(f"[{MUTED}]running...[/]")
            return
        self._stop()
        if t == "assistant_message":
            console.print()
            console.print(Markdown(d["text"]))
            console.print()
        elif t == "tool_call":
            console.print(
                Text.assemble(("● ", ACCENT), (d["action"], "bold"), ("  " + str(d["target"]), ""))
            )
        elif t == "tool_result":
            style = {"ok": MUTED, "denied": ERR, "error": ERR}.get(d["status"], MUTED)
            if d["tool"] in ("write_file", "edit_file") and d["status"] == "ok":
                style = OK
            if d["tool"] == "run_command" and d["status"] == "ok":
                style = OK
            console.print(Text("  └ " + d["summary"], style=style))
            if d["tool"] == "run_command" and d.get("content"):
                for line in str(d["content"]).splitlines()[-8:]:
                    console.print(Text("    " + line, style=MUTED))
        elif t == "turn_end":
            console.print(
                Text(f"  {d['tokens_in']:,} in · {d['tokens_out']:,} out (session)", style=MUTED)
            )
        elif t == "cancelled":
            console.print(Text("  cancelled", style=WARN))
        elif t == "step_limit":
            notice("Stopped", f"Reached the limit of {d['limit']} tool steps for one request.")
        elif t == "model_switched":
            console.print(
                Text.assemble(("  model switched to ", MUTED), (d["new"], f"bold {ACCENT}"))
            )
        elif t == "conversation_reset":
            console.print(Text("  new conversation started", style=MUTED))


# ---- approvals -----------------------------------------------------------------


def approver(req: ApprovalRequest) -> str:
    if req.detail_format == "diff":
        body = Syntax(req.detail, "diff", theme="ansi_dark")
    elif req.detail_format.startswith("file:"):
        path = req.detail_format[5:]
        lines = req.detail.splitlines()
        shown = "\n".join(lines[:60]) + ("\n..." if len(lines) > 60 else "")
        body = Syntax(
            shown, Syntax.guess_lexer(path, code=req.detail), theme="ansi_dark", line_numbers=True
        )
    else:
        body = Syntax(req.detail, "bash", theme="ansi_dark")
    console.print(Panel(body, border_style=MUTED, padding=(0, 1)))
    kind_name = "file changes" if req.kind == "write" else "commands"
    options = "(y) yes  (n) no" + (f"  (a) always for {kind_name}" if req.can_always else "")
    while True:
        answer = console.input(f"  [bold]Allow?[/] [{MUTED}]{options}[/] ").strip().lower()
        if answer in ("y", "yes"):
            return "yes"
        if answer in ("n", "no", ""):
            return "no"
        if answer in ("a", "always") and req.can_always:
            console.print(Text(f"  {kind_name} auto-approved for this session", style=MUTED))
            return "always"


# ---- the app -------------------------------------------------------------------


class App:
    def __init__(
        self,
        *,
        config: Config,
        provider: Provider,
        agent: Agent,
        bus: EventBus,
        policy: Policy,
        log: SessionLog | None,
        key_source: str,
        workdir: Path,
        runner_name: str,
    ):
        self.config = config
        self.provider = provider
        self.agent = agent
        self.bus = bus
        self.policy = policy
        self.log = log
        self.key_source = key_source
        self.workdir = workdir
        self.runner_name = runner_name
        agent.on_error = self.handle_error

    # ---- errors ----------------------------------------------------------------

    def pick(self, candidates: list[str], prompt: str) -> str | None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        for i, name in enumerate(candidates, 1):
            table.add_row(f"[{ACCENT}]{i}[/]", name)
        console.print(table)
        choice = console.input(
            f"  [bold]{prompt}[/] [{MUTED}](number, Enter to cancel)[/] "
        ).strip()
        if choice.isdigit() and 1 <= int(choice) <= len(candidates):
            return candidates[int(choice) - 1]
        return None

    def handle_error(self, e: ProviderError) -> str | None:
        # Model names and API messages are outside text: escape them before using rich markup.
        model = escape(self.agent.model)
        detail = escape(e.message or "")
        if e.kind == "quota":
            if e.no_quota and e.free_tier:
                reason = (
                    f"[bold]{model}[/] is not available on the Gemini API free tier.\n"
                    "Your API key's project has no billing attached, so this model has zero quota."
                )
            elif e.daily:
                reason = f"The daily quota for [bold]{model}[/] has been used up."
                if e.retry_after:
                    h, rem = divmod(e.retry_after, 3600)
                    reason += f" It resets in about {h}h {rem // 60}m."
            else:
                reason = f"The quota for [bold]{model}[/] has been reached."
            notice(
                "Quota exceeded",
                reason + "\n\n"
                f"[{MUTED}]To use paid models: aistudio.google.com → API keys → Set up billing "
                "for this key's project.[/]",
            )
            options = [m for m in self.config.get("model.fallbacks", []) if m != model]
            chosen = self.pick(options, "Switch to another model and retry?") if options else None
            if chosen:
                self.agent.switch_model(chosen)
                return "retry"
            return None
        messages = {
            "auth": (
                "Invalid API key",
                "The provider rejected the API key.\n"
                f"[{MUTED}]Run [bold]saicode login[/bold] to store a new key.[/]",
            ),
            "permission": (
                "Permission denied",
                f"This key cannot use this model.\n[{MUTED}]{detail[:300]}[/]",
            ),
            "not_found": (
                "Model not found",
                f"[bold]{model}[/] is not available for this key.\n"
                f"[{MUTED}]Type /model to choose one from the list.[/]",
            ),
            "network": (
                "Connection problem",
                "Could not reach the model service. Check your connection.\n"
                f"[{MUTED}]{detail[:300]}[/]",
            ),
        }
        title, body = messages.get(
            e.kind, (f"API error {e.code or ''}".strip(), f"[{MUTED}]{detail[:500]}[/]")
        )
        notice(title, body, ERR)
        return None

    # ---- screens -------------------------------------------------------------------

    def check_connection(self) -> tuple[str, str]:
        try:
            with console.status(f"[{MUTED}]connecting...[/]", spinner="dots"):
                self.provider.check_model(self.agent.model)
            return "connected", OK
        except ProviderError as e:
            return {
                "not_found": "model not found - type /model",
                "auth": "invalid API key",
                "permission": "permission denied for this key",
                "network": "offline",
            }.get(e.kind, f"error {e.code or ''}".strip()), ERR

    def welcome(self) -> None:
        console.clear()
        logo = Text()
        for i, line in enumerate(LOGO.strip("\n").splitlines()):
            logo.append(line + "\n", style=f"bold {GRADIENT[i % len(GRADIENT)]}")
        status, style = self.check_connection()
        info = Table.grid(padding=(0, 2))
        info.add_column(style=MUTED, justify="right")
        info.add_column()
        info.add_row("version", __version__)
        info.add_row("model", Text(self.agent.model, style=f"bold {ACCENT}"))
        info.add_row("workspace", short_home(self.workdir))
        info.add_row(
            "permissions",
            self.policy.mode
            + (" (set by your organization)" if self.config.is_locked("permissions.mode") else ""),
        )
        info.add_row("status", Text(status, style=style))
        tips = Text.assemble(
            ("/help", ACCENT),
            (" commands   ", MUTED),
            ("/model", ACCENT),
            (" switch model   ", MUTED),
            ("/status", ACCENT),
            (" session info   ", MUTED),
            ("/exit", ACCENT),
            (" quit", MUTED),
        )
        console.print(logo)
        console.print(
            Panel(
                Group(info, Text(""), tips),
                title="[bold]saicode[/]",
                title_align="left",
                subtitle=f"[{MUTED}]terminal coding agent[/]",
                subtitle_align="right",
                border_style=ACCENT,
                padding=(1, 2),
            )
        )
        if any(layer.name == "system" for layer in self.config.layers):
            console.print(
                Text("  Your organization's policy is active. Type /config to see it.", style=MUTED)
            )
        console.print()

    def show_help(self) -> None:
        table = Table(show_header=False, box=None, padding=(0, 2))
        table.add_column(style=ACCENT)
        table.add_column()
        for cmd, desc in [
            ("/help", "show this help"),
            ("/model", "choose a model from the list"),
            ("/model <name>", "switch to a model by name"),
            ("/models", "list available models"),
            ("/status", "session, log file, key and policy"),
            ("/config", "effective settings and where each comes from"),
            ("/clear", "start a new conversation"),
            ("/exit", "quit saicode"),
        ]:
            table.add_row(cmd, desc)
        console.print(
            Panel(
                table,
                title="[bold]commands[/]",
                title_align="left",
                border_style=MUTED,
                padding=(1, 2),
            )
        )

    def show_status(self) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style=MUTED, justify="right")
        table.add_column()
        table.add_row("session", self.bus.session_id)
        table.add_row("user", self.bus.user)
        table.add_row("provider", self.provider.name)
        table.add_row("model", self.agent.model)
        table.add_row("api key", self.key_source)
        table.add_row("permissions", self.policy.mode)
        table.add_row("commands run", f"{self.runner_name} (sandbox arrives in phase A2)")
        table.add_row("session log", short_home(self.log.path) if self.log else "off")
        table.add_row(
            "config layers",
            ", ".join(
                layer.name + (f" ({short_home(layer.path)})" if layer.path else "")
                for layer in self.config.layers
            ),
        )
        console.print(
            Panel(
                table,
                title="[bold]status[/]",
                title_align="left",
                border_style=MUTED,
                padding=(1, 2),
            )
        )

    def show_config(self) -> None:
        table = Table(box=None, padding=(0, 2), header_style=MUTED)
        table.add_column("setting", style=ACCENT)
        table.add_column("value")
        table.add_column("from", style=MUTED)
        for key, value, source in self.config.flat():
            shown = ", ".join(map(str, value)) if isinstance(value, list) else str(value)
            lock = " (locked)" if self.config.is_locked(key) else ""
            table.add_row(key, shown or "-", source + lock)
        console.print(
            Panel(
                table,
                title="[bold]config[/]",
                title_align="left",
                border_style=MUTED,
                padding=(1, 1),
            )
        )

    # ---- commands ------------------------------------------------------------------

    def models(self) -> list[str]:
        with console.status(f"[{MUTED}]loading models...[/]", spinner="dots"):
            return self.provider.list_models()

    def command(self, line: str) -> bool:
        cmd, _, arg = line.partition(" ")
        cmd, arg = cmd.lower(), arg.strip()
        if cmd in ("/exit", "/quit"):
            return False
        try:
            if cmd == "/help":
                self.show_help()
            elif cmd == "/status":
                self.show_status()
            elif cmd == "/config":
                self.show_config()
            elif cmd == "/clear":
                self.agent.reset()
            elif cmd == "/models":
                for name in self.models():
                    marker = "●" if name == self.agent.model else " "
                    console.print(Text.assemble((f"  {marker} ", ACCENT), name))
            elif cmd == "/model":
                chosen = arg or self.pick(self.models(), "Choose a model")
                if chosen:
                    self.agent.switch_model(chosen)
            else:
                console.print(Text(f"  unknown command {cmd} - type /help", style=WARN))
        except ProviderError as e:
            self.handle_error(e)
        return True

    def run(self) -> None:
        self.welcome()
        history = Path.home() / ".saicode" / "history"
        history.parent.mkdir(parents=True, exist_ok=True)
        session: PromptSession[str] = PromptSession(history=FileHistory(str(history)))

        def toolbar():
            return [
                (
                    "class:bottom-toolbar",
                    f" {self.agent.model}  ·  {short_home(self.workdir)}"
                    f"  ·  {self.policy.mode}  ·  /help ",
                )
            ]

        while True:
            try:
                line = session.prompt([("bold", "› ")], bottom_toolbar=toolbar).strip()
            except KeyboardInterrupt:
                continue
            except EOFError:
                break
            if not line:
                continue
            if line.lower() in ("exit", "quit"):
                break
            if line.startswith("/"):
                if not self.command(line):
                    break
                continue
            console.print(Rule(style="grey23"))
            self.agent.run_turn(line)
            console.print()
        console.print(Text("  goodbye", style=MUTED))
