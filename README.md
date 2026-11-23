# SAI Code

A terminal coding agent: small core, safe by default, built on enterprise-ready foundations.

Version 0.3.0 completes roadmap phase **A1 (Foundation)**.

> **Safety note.** saicode reads files, edits files and runs shell commands in your project.
> It asks before every change and command, but in 0.3.x approved commands run **without an
> OS sandbox**, with your own permissions. Review each command before you approve it.

## Install

Requires Python 3.11 or newer on macOS, Linux or Windows.

```bash
uv tool install saicode       # recommended
# or
pipx install saicode
```

Upgrade with `uv tool upgrade saicode` (or `pipx upgrade saicode`).

### From source

```bash
git clone https://github.com/the-schoolofai/saicode.git
cd saicode
uv tool install .
```

## Store your API key (once)

```bash
saicode login
```

The key goes into the system keychain (macOS Keychain). You can also use the
`GEMINI_API_KEY` environment variable; it takes priority over the keychain.

## Use

```bash
cd ~/your-project
saicode
saicode --model gemini-3-flash-preview
```

Inside saicode: `/help`, `/model`, `/models`, `/status`, `/config`, `/clear`, `/exit`.

Other commands:

```bash
saicode config      # effective settings and where each one comes from
saicode logout      # remove the stored key
saicode --version
```

## Configuration layers

Later layers win. The system policy always wins and cannot be overridden.

| Layer   | File |
| ------- | ---- |
| default | built in |
| user    | `~/.saicode/config.toml` |
| project | `<project>/.saicode/config.toml` |
| system  | macOS `/Library/Application Support/saicode/policy.toml`, Linux `/etc/saicode/policy.toml`, Windows `%ProgramData%\saicode\policy.toml` |

Rules that make the layers safe:

- `permissions.deny` and `permissions.deny_read` are combined across all layers. No layer can remove a rule.
- A project config comes from the repository, so its `permissions.allow`, `permissions.mode` and
  `permissions.allow_always` are ignored unless your user config sets `trust_project_permissions = true`
  (and the system policy does not forbid it).
- A project config can never change `logging.*`, `identity.email` or `providers.allowed`, so a
  cloned repository cannot switch off or redirect your session log.

Example user config:

```toml
[model]
name = "gemini-3-flash-preview"

[permissions]
allow = ["run:git status*", "run:pytest*"]

[identity]
email = "you@example.com"
```

Example system policy (set by an administrator):

```toml
[providers]
allowed = ["gemini"]

[permissions]
mode = "ask"               # or "read-only"
allow_always = false       # users must approve every change
deny = ["run:git push*"]

[logging]
sessions = true
include_content = false
```

## Permissions

| Action | Default |
| ------ | ------- |
| list and read files | allowed |
| protected files (`.env`, keys, `.ssh`, `secrets/`, ...) | always blocked |
| anything outside the project folder | always blocked |
| write or edit files | asks, with a diff |
| run commands | asks; dangerous patterns blocked |

Rules use the form `run:<command glob>`, `write:<path glob>`, `read:<path glob>`.

## Session logs

Every session is written to `~/.saicode/sessions/<date>/<session id>.jsonl`, one event per line,
each with a session ID, turn ID, event ID, user and timestamp. File contents and command output are
left out unless `logging.include_content = true`.

## Project layout

```
src/saicode/
  ai/        providers behind one interface (Gemini today), provider allowlist
  core/      config layers, policy engine, events and session log, credentials, agent loop
  tools/     list, read, write, edit, run - each checks the policy first
  sandbox/   command runner interface (OS sandbox arrives in phase A2)
  tui/       the terminal screen; the only package that draws
  cli/       the `saicode` command
tests/       pytest suite
```

The core never imports the UI. Editor integrations (ACP, VS Code) and headless mode will reuse the same core.

## Development

```bash
uv sync --extra dev          # install saicode and the dev tools
uv run pytest                # tests
uv run ruff check            # lint
uv run ruff format           # format
uv run mypy                  # type check
```

CI runs all of these on every push and pull request, testing Python 3.11 to 3.14 on
Linux, macOS and Windows. A pull request should keep every check green.

Maintainers: the release process is described in [RELEASING.md](https://github.com/the-schoolofai/saicode/blob/main/RELEASING.md).

## Known limits in 0.3.0

- Commands run without an OS sandbox (phase A2). Set `sandbox.required = true` to refuse commands until then.
- Blocking protected files inside shell commands is best-effort text matching until the sandbox ships.
- Gemini is the only provider (phase A3 adds more).

## Security

Please report vulnerabilities privately. See [SECURITY.md](https://github.com/the-schoolofai/saicode/blob/main/SECURITY.md).

## Changelog

See [CHANGELOG.md](https://github.com/the-schoolofai/saicode/blob/main/CHANGELOG.md).

## License

Licensed under the [Apache License, Version 2.0](https://github.com/the-schoolofai/saicode/blob/main/LICENSE). Copyright 2026 SAI Code Team.
