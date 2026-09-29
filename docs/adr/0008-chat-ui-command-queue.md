# ADR 0008: Chat and the local UI connect through the filesystem via a command queue

- Status: accepted
- Date: 2026-07-22

## Decision

The local UI never calls an AI provider, holds no provider credentials, and
contains no skill implementation, but it may host an ACP agent subprocess and
invoke the project's existing skills through that session (ADR-0009). The
subprocess uses the user's existing agent-harness authentication. There remains
exactly one implementation of each skill. Chat with the LLM stays in the agent
harness and any UI-hosted ACP session — Claude Code / Codex / Cursor / Zed
already hold skills, the CLI, and MCP. Chat and the UI connect **through the
application filesystem for durable results, never by relocating skill
implementations into the UI**, along two flows:

- **Results flow `agent → files → UI`.** Skills write ordinary file-backed
  state (`meta.yaml`, the append-only `events:` list and `events/` payloads from
  ADR-0007 / issue #28). The UI reads those files and reflects them; that is how
  a chat-driven action becomes a timeline event the user can see.
- **Requests flow `UI → command queue → agent` (and interactive `Run now`).**
  Any screen can enqueue a command that requires an LLM without the user typing
  it. The agent drains the queue and executes each command with the right skill.
  Interactive commands may instead use **Run now** through a live ACP session
  (ADR-0009); **Queue** remains the durable deferred/unattended path.

This is an **app-wide mechanism, not a per-screen feature**: the Jobs screen,
the Application screen, and any future screen share the one queue.

### Command queue

- **Location & shape.** A single top-level `queue/` directory of request files.
  Each request names its target (`app: <folder>` | `job: <id>` | none), a
  `type` from a **closed enum**, optional `args`, and a `state`. Structured args
  and any freeform escape hatch are deferred until a concrete need appears.
- **Lifecycle.** `queued → running → done | failed`. The agent **claims** a
  request before running it (like a wayfinder ticket) so a re-drain cannot
  double-execute; a `failed` request is kept with its error, never silently
  lost.
- **Transient, result-is-the-event.** A request is not an `events:` entry.
  Clicking a button must not drop a row in the permanent timeline; only the
  *result* (a draft iteration, an `email`/`note` event, a `status_changed`
  flip) appears there. A skill *may* write a `note` event on failure at its own
  discretion.

### Drain

- **On-demand is the built contract.** An `apply-run-queue` skill (or an
  equivalent phrase) reads pending requests, dispatches each to its skill,
  writes results as #28 events, and moves the request to `done`/`failed`.
- **Ambient detection, no daemon.** `SessionStart`, `UserPromptSubmit`, and
  `Stop` hooks scan `queue/` and inject a "N pending" reminder, so the agent
  notices pending work at the next interaction without the user asking. The
  harness cannot wake on a file appearing while idle; true push would require a
  cron/daemon, which is out of scope for the baseline.
- **Background loop is optional and later.** A `/loop` or scheduled agent that
  drains unattended is a thin wrapper over the same on-demand drain, not part of
  the core spec.

### Approval

Permission and approval are presented in whichever surface hosts the active
work, including the local UI (ADR-0009). The human approval boundary in
ADR-0005 remains unchanged. Commands are one of two flavors:

- **Auto** — safe to drain and write directly (e.g. `refresh-draft`,
  `re-check`).
- **Approval-gated** — the active surface (chat drain or UI permission card)
  shows a preview and writes only on the human's yes (e.g. `capture-email`,
  per issue #34), applying ADR-0005.

Consequence: an unattended background loop can only drain **auto** commands;
approval-gated commands sit `running`/pending until a human-present drain.

### Seed command enum (non-binding)

Enough to prove the loop; the enum grows per need:

- `capture-email` — Application target, approval-gated (#34).
- `refresh-draft`, `re-check` — Application target, auto.
- `fetch-jobs`, `refresh-drafts` — Jobs target, auto.

## Context

Issue #36 asked how LLM chat connects to the reworked Application screen, given
the locked event model (#28) and screen layout (#30). The standing preference is
that typing and skill invocation live in chat while the UI shows the sequence of
events. The UI already writes files directly (status dropdown, interested/skip,
artifact edits), so a pure read-only reflector was never the real shape; the
open question was how the UI triggers *LLM* work without relocating the chat box
into a provider-calling web app.

The command queue keeps chat in one place while making every screen able to
trigger LLM-backed work by clicking rather than typing. The decision generalized
beyond the Application screen during grilling: because a Jobs command has no
application folder to live under, the queue is a single top-level `queue/`, and
the mechanism is screen-agnostic.

## Relationship to other ADRs

- **Extends ADR-0006 (CLI / core / UI boundary).** The queue is a refinement of
  that boundary: the UI enqueues, the agent/CLI executes, and no workflow logic
  or provider call moves into the UI.
- **Applies ADR-0005 (AI + human approval).** Approval-gated commands surface
  their preview in the surface hosting the work and write only on explicit
  human confirmation.

## Consequences

- The UI stays a thin, provider-free adapter; there is exactly one
  implementation of each skill, visible through more than one surface (chat
  harness and, per ADR-0009, the local UI agent dock).
- Screens gain the ability to trigger LLM work asynchronously; the user batches
  clicks and drains once, with hooks making pending work ambient.
- Implementation of the queue, drain skill, hooks, and per-screen command
  catalogs is out of scope for this decision (the map produces specs, not
  builds). Which buttons each screen offers is left to the implementer,
  consistent with the non-binding seed enum.

## ACP agent-session amendment

ADR-0009 amended this decision in two places (incorporated in Decision above):

1. Replaced "never talks to an AI provider and never invokes a skill" with the
   provider-free / one-skill-implementation rule that still allows hosting an
   ACP agent subprocess.
2. Replaced "Approval lives in chat, never in the UI" with surface-agnostic
   permission and approval presentation, without changing ADR-0005.

The original request flow is narrowed, not removed. The command queue remains
the durable path for deferred and unattended work, with its location, request
shape, lifecycle, claim-before-run rule, result-is-the-event rule, drain skill,
and hooks unchanged. Interactive commands may instead use **Run now** to stream
through a live ACP session. **Queue** continues to write the same request file.
Both delivery paths use the same closed command vocabulary and target
vocabulary (`app: <folder>` | `job: <id>` | none).

The results boundary also remains unchanged. Agent work becomes application
state only through files read by the UI. Session messages and protocol updates
are runtime conversation records, not Application events.

The queue remains in force and its long-term value is to be reviewed after
Stage 2 of the ACP rollout against actual use of **Queue**.
