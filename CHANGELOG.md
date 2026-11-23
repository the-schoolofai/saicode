# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).
While the version is `0.x`, minor releases may contain breaking changes.

## [Unreleased]

## [0.3.0] - 2026-11-23

First public release. Completes roadmap phase A1 (Foundation).

### Added

- Layered configuration: built-in defaults, user config, project config and
  system policy. The system policy always wins and locks the keys it sets.
- `permissions.deny` and `permissions.deny_read` are combined across all layers,
  so no layer can remove a rule another layer added.
- Policy engine that allows, asks or denies every tool action, confines the agent
  to the project folder and always blocks protected files (`.env`, keys, `.ssh`,
  `secrets/`, ...).
- Event bus with stable session, turn and event IDs, and an append-only JSONL
  session log that leaves out file contents and command output by default.
- API keys read from environment variables or the system keychain
  (`saicode login`, `saicode logout`); keys are never written to config files.
- Provider-neutral agent loop with automatic retry on rate limits and transient
  server errors, and fallback models when a quota is used up.
- Gemini provider behind a common interface and an administrator allowlist.
- Tools: list, read, write, edit and run. Changes and commands ask for approval
  with a diff or command preview.
- Terminal UI with `/help`, `/model`, `/models`, `/status`, `/config`, `/clear`
  and `/exit`, and the `saicode config` command.

### Security

- A project config (which comes from the repository) cannot loosen permissions,
  mark itself as trusted, or change logging, identity or the provider allowlist.

[Unreleased]: https://github.com/the-schoolofai/saicode/compare/v0.3.0...HEAD
[0.3.0]: https://github.com/the-schoolofai/saicode/releases/tag/v0.3.0
