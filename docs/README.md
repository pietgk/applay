# Apply project documentation

This directory documents the current script-based application pipeline and its
local UI. The repository is intentionally still a collection of Python tools and
file-based artifacts rather than an installable package or hosted service.

Start here:

- [Workflow](workflow.md) — how a job moves from discovery to an application.
- [Parkit end-to-end demo](examples/parkit-demo.md) — the real JobTech 31215727 walkthrough.
- [Domain model](domain-model.md) — glossary and authoritative link index for
  durable concepts.
- [Screen intent](intent/) — per-screen behaviour and Info popover copy (Jobs,
  Applications, Application). Agent-dock Info placement is owned by
  [ADR-0009](adr/0009-local-ui-hosts-acp-agent-sessions.md); it is not a fourth
  screen.
- [Development](development.md) — setup, offline checks, and verification
  commands.
- [Architecture decisions](adr/) — the decisions that constrain future work.

The top-level [README](../README.md) remains the quick-start reference. The
documents here are the more stable explanation of why the current files and
commands fit together.
