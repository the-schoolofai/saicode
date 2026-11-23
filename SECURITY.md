# Security Policy

saicode is a coding agent: it reads files, edits files and runs shell commands
on the user's computer. We take reports about bypassing its safety controls
seriously.

## Supported versions

| Version | Supported |
| ------- | --------- |
| 0.3.x   | Yes       |
| < 0.3   | No        |

## Reporting a vulnerability

Please **do not** open a public issue for a security problem.

Report it privately through GitHub: open the repository's **Security** tab and
choose **Report a vulnerability**. Include:

- the saicode version (`saicode --version`), operating system and Python version
- the steps or the configuration needed to reproduce the problem
- what you expected to happen and what happened instead

We aim to acknowledge a report within 3 working days and to agree on a fix and
disclosure timeline with you.

## What counts as a vulnerability

Examples of issues we want to hear about:

- reading, writing or running anything outside the project folder
- reading or changing a protected file (`permissions.deny_read`)
- a change or command that runs without the approval the policy requires
- a project config (`.saicode/config.toml`) loosening permissions or changing
  logging, identity or the provider allowlist
- an API key being written to disk or into the session log

## Known limits

These are documented and are not treated as vulnerabilities in 0.3.x:

- Commands run without an OS sandbox until roadmap phase A2. A command the user
  approves runs with the user's own permissions.
- Blocking protected files inside shell commands is best-effort text matching
  until the sandbox ships.
