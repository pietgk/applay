# Project agent memory

This file is the project's committed home for project-intrinsic agent knowledge: build, test, release, architecture, and sharp-edge notes that should travel with the code.

- **Environment.** `mise`/`uv` project. Run `mise trust` first in a fresh worktree, then reach tools as `mise exec -- uv run ...` (`uv` is not on PATH by default). `mise run verify` is the full gate: skills-check, fmt-check, lint, basedpyright, unittest.
- **Design record before code.** `docs/intent/<screen>.md` owns each screen's behaviour and Info copy; `docs/domain-model.md` is the glossary and authoritative link index; `docs/adr/` holds the binding constraints (0006 CLI/core/UI boundary, 0007 metadata evolution, 0008 chat/UI command queue, 0009 UI-hosted ACP sessions). Read the relevant one before changing a shape they describe.
- **`meta.yaml` writes are owned by field.** `applications.update_meta` owns ordinary flat fields; `applications.append_event` owns non-status events and payload files; `applications.set_status` alone owns `status`, `date_applied`, and their matching `status_changed` append in one atomic replacement. See ADR-0007's application-events amendment.
- **Derived, never stored.** `last_activity_at` is computed on read from the flat dated fields plus event `when`s; do not add it as a field.
- **Command queue enqueue only.** The UI drops `state: queued` request files under top-level `queue/` via `apply.queue.enqueue` (ADR-0008) and never drains them, calls a provider, or writes the request into `events:`.
- **Real user data lives in the repo.** `applications/` holds tracked, in-flight applications. Treat those files as production data: keep readers back-compatible instead of rewriting folders in place.

## Commands

`mise run verify` is the gate: skills validation, format check, ruff, basedpyright, and the offline
test suite. `mise run test` alone for the tests. All tasks are declared in `mise.toml`.

## Local UI

`src/apply/local_ui.py` is a thin Flask adapter over the core modules (ADR-0006).
It never calls an AI provider. The older "never invokes a skill" rule is
superseded by the ADR-0008 amendment and ADR-0009: exactly one skill
implementation still binds, and UI-hosted ACP sessions are accepted design but
not yet built. See [ADR-0009](docs/adr/0009-local-ui-hosts-acp-agent-sessions.md).

The interactive screens (Jobs, Applications, Application) are built on one shared 70vw two-pane shell:
`templates/local_ui/two_pane.html` owns the layout and documents its blocks; a screen adopts it with
`{% extends "two_pane.html" %}` and must not re-declare the layout markup. Rail rows come from the
macros in `templates/local_ui/_shell.html`. `GET /shell` renders the shell standalone for a look at
it in isolation.

Place-keeping is fragments + PRG anchors, not htmx and not an SPA: rows link to their own
`#anchor` (built with `local_ui.anchor_id`) and writes redirect to the anchored URL
(`local_ui.anchored_url`), so a reload scrolls the row back into view inside the rail scroller.
The reasoning, and what adopting htmx later would change, is in
`docs/research/2026-07-22-jobs-list-refresh-scroll-options.md`.

## Maintaining this file

Keep this file for knowledge useful to almost every future agent session in this project.
Do not repeat what the codebase already shows; point to the authoritative file or command instead.
Prefer rewriting or pruning existing entries over appending new ones.
When updating this file, preserve this bar for all agents and keep entries concise.
