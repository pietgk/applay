# ADR 0009: Let the local UI host ACP agent sessions

- Status: accepted
- Date: 2026-07-27

## Decision

The localhost-only Flask UI may host Agent Client Protocol (ACP) v1 agent
sessions. Flask owns each agent subprocess and presents the session through a
persistent agent dock. This is runtime adapter behavior under ADR-0006, not a
new implementation of application workflow or of any skill.

The UI makes no AI-provider call and holds no provider credentials. It starts
an agent subprocess that uses the user's existing agent-harness authentication,
sets the repository root as its working directory, and invokes the project's
existing skills. Exactly one implementation of each skill remains authoritative.

Sessions use the command queue's target vocabulary as their identity:

- target `none` maps to the campaign session used by Jobs and Applications;
- target `app: <folder>` maps to that Application's session;
- target `job: <id>` remains a valid command target, but job-targeted work uses
  the campaign session because chat has campaign and per-Application scopes,
  not a third per-Job scope.

Several scopes may run concurrently, but at most one turn may be in flight for
one target scope. A cross-surface writer cannot be prevented by the local host;
after a matching turn ends, the UI offers an explicit refresh instead of
reloading and risking unsaved edits.

The Flask process owns session lifetime:

- sessions start lazily on first use and run with the repository root as
  `cwd`, so project instructions and skills remain available;
- one in-process host maps scopes to subprocesses, so the UI must run as one
  Flask process without an auto-reloader or multiple WSGI workers;
- idle subprocesses may be closed when the agent advertises that capability,
  while their session identity and transcript remain on disk;
- permission mode is selected per session and ships as `default` (Manual),
  rather than inheriting an external editor's `bypassPermissions` setting.

Every protocol update, turn boundary, permission request and answer, and
synthetic process event is appended to a gitignored local transcript. A small
session record stores the ACP session id and lifecycle metadata. The designed
layout is `sessions/<scope>.jsonl` for the sequenced transcript and
`sessions/<scope>.yaml` for the session record. These files are runtime records,
not Application metadata or events; durable workflow results still reach the
UI through the files governed by ADR-0001 and ADR-0007.

Server-to-browser updates use Server-Sent Events (SSE). Prompts, permission
answers, cancellation, and other mutations remain ordinary form POSTs. SSE is
the preferred adapter because ACP updates are one-way, browser reconnects carry
`Last-Event-ID`, and the transcript sequence can replay missed updates without
introducing a client-side application. Polling the same transcript by sequence
is the fallback if SSE later proves unsuitable.

On a page reload, the Flask process and subprocess remain alive, the dock is
rendered from the local transcript, and the browser reconnects to the stream.
On an SSE reconnect, replay resumes after `Last-Event-ID`. After a Flask or
agent restart, the host starts a fresh subprocess and attempts `session/load`
with the stored ACP session id.

If an agent exits during a turn, the host records the exit, marks the turn
interrupted, preserves the output already captured locally, and presents an
error state with a reconnect action. Reloading does not claim to resume the
interrupted turn, and filesystem side effects are not rolled back. A blocked
permission remains visible with a cancellation path; the approval policy and
durable decision record are deliberately left for a later ADR after Stage 3.

The always-visible **Agent status chip** reports agent state with this closed,
priority-ordered enum: `Decision needed`, `Working`, `Queued`, `Error`,
`Idle`. A **Permission card** is the in-surface rendering of a blocked ACP
permission request. It shows the proposed action, the available decisions,
how long the request has been waiting, and a cancellation path.

## Context

ADR-0008 made the file queue the only request path in order to keep provider
calls and duplicate skill implementations out of the UI. Interactive queue
work has no token stream, permission surface, or cancellation path, and a
claimed request can appear inert until it finishes. ACP permits a live path
without giving up the stronger parts of that boundary: one command vocabulary,
one skill implementation, and file-backed durable application state.

The queue therefore survives for deferred and unattended work. **Run now**
delivers a command to the live session for its target; **Queue** writes the
existing request file. The queue's drain skill and hooks remain the bridge to
Claude Code and Zed when the local UI is closed.

## Measured evidence

The following facts were measured on this machine against installed ACP v1
agents and a throwaway Flask prototype on 2026-07-27:

- all three installed agents answered the ACP initialization handshake with
  protocol version 1;
- a Claude ACP session rooted at the apply repository advertised the existing
  `apply-*` skills, and a new session became live in 1.59 to 1.62 seconds;
- a plain Flask process streamed ACP output over SSE, with the first token at
  the browser 1.15 seconds after the prompt POST;
- an ACP permission request blocked the turn, appeared through SSE, and was
  answered successfully by a later HTTP POST;
- cancellation returned `stopReason: "cancelled"` in 0.01 seconds at the wire;
- `session/load` from a fresh process completed in 1.95 to 2.03 seconds,
  replayed the full stored agent history, and accepted another prompt;
- when an agent was killed mid-turn, a later load replayed the user message but
  not the partial assistant output.

The chosen process model, scope mapping, one-turn-per-scope rule, transcript
layout, SSE replay contract, idle policy, UI recovery states, and polling
fallback are design decisions grounded in those measurements. Long sessions,
multi-hour parked permissions, concurrent cross-surface writes, idle reaping,
and agent behavior beyond the exercised Claude path were not measured.

## Consequences

The local UI is stateful at runtime and gains a single-process operating
constraint. It remains a thin, provider-free adapter with no workflow logic,
prompt templates, or duplicate skill implementations.

The agent dock is shared chrome, not a fourth screen. Jobs, Applications, and
Application remain the three canonical screen names. Its Info copy belongs in
`docs/intent/agent.md`, a fourth intent file loaded alongside the current
screen's intent.

The command queue remains available and is narrowed to deferred and unattended
work. This choice is to be revisited after Stage 2: if **Queue** is never used,
the queue may be removed through a later decision; if the dock is never used,
the ACP host may be dropped while retaining queue visibility.

Timeline events may gain optional session and turn provenance only at Stage 5
through a deliberate ADR-0007 schema extension. ADR-0001, ADR-0005, and
ADR-0007 are unchanged by this decision.

A later ADR is proposed after Stage 3 to record what is learned about
surface-agnostic approval and durable pending decisions. This ADR does not
pre-commit that policy or create ADR-0010.
