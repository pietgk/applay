# Email-capture options for application communications

Research for [wayfinder ticket #29](https://github.com/pietgk/apply/issues/29), part of the
[application communication & UI rework map](https://github.com/pietgk/apply/issues/26).

## Question

How can incoming application email (an ATS reply arriving via Teamtailor) get into the
per-application record? Inventory the realistic options with their constraints (auth, privacy,
effort per email) and recommend one.

## Key empirical finding

The ticket assumed application replies arrive at `grop@me.com`. They don't — the ATS mail found
lands at `piet.groot.kormelink@gmail.com`, the Gmail account already connected to Claude via the
claude.ai Gmail connector. Verified live via Gmail search on 2026-07-22. Individual sender
addresses and subjects stay in the private working repo.

Two capabilities confirmed hands-on:

- **Search** works with plain Gmail query syntax; `from:*teamtailor-mail.com`, a company name, or
  `newer_than:7d` reliably isolates application traffic (Teamtailor senders always use the
  `@<company>.teamtailor-mail.com` domain).
- **Full-body pull** works and returns a clean `plaintextBody` —
  no HTML scraping needed before recording the content.

## Options inventory

### 1. Manual paste (chat or file)

Piet copies the email text into the chat (or straight into a file) and the agent records it.

- **Auth**: none. **Privacy**: fully under human control.
- **Effort per email**: ~1–2 minutes; transcription/formatting errors possible; metadata (date,
  sender) must be re-typed.
- **Reach**: universal — also covers LinkedIn DMs, phone-call notes, anything that isn't email.

### 2. Gmail MCP search/pull in chat — recommended

In a Claude session, Piet says e.g. "check for a Sellpy reply"; the agent runs a targeted Gmail
search, shows the message, and on approval records it in the application folder.

- **Auth**: none new — the Gmail connector is already authorized in Claude Code sessions.
- **Privacy**: read-only access; the agent queries narrowly (company/ATS-domain filters); the body
  enters the repo only after Piet approves — consistent with the truthful human-approved workflow.
- **Effort per email**: seconds, with exact metadata (sender, date, subject) captured for free.
- **Constraints**: only covers this Gmail account, and only works inside Claude sessions with the
  connector — the local Flask UI cannot pull email itself. That matches the standing preference:
  interaction lives in the chat, the UI just shows the recorded events.

### 3. Forwarding conventions

- **iCloud → Gmail auto-forward**: one-time setup in iCloud Mail settings; afterwards option 2
  covers `grop@me.com` traffic too. Only worth doing if application mail ever actually arrives
  there — none found so far.
- **Manual per-email forward** to the Gmail account: no setup, but per-email effort and mangled
  sender/date headers. Strictly worse than paste or auto-forward; not recommended.

### 4. Local IMAP polling script

An `apply ingest-email` command polling Gmail/iCloud over IMAP with an app-specific password,
writing files deterministically.

- **Auth**: new credential to create and store locally. **Effort per email**: zero once running.
- **Why not now**: matching an email to the right application folder is fuzzy (sender domains,
  role names in prose) — exactly the judgment the chat LLM is good at and a deterministic script
  is not; unattended ingestion also bypasses the human-approval step. Revisit only if volume makes
  chat-driven capture tedious.

### 5. Third-party automation (Zapier, mail-webhook services)

Rejected outright: routes private job-search correspondence through an external service, against
the file-backed local-first philosophy, for no capability the Gmail MCP doesn't already provide.

## Recommendation

**Gmail MCP search/pull in chat as the primary capture channel; manual paste as the universal
fallback** for anything outside that Gmail account (LinkedIn messages, calls, other inboxes).

Working flow: Piet asks in chat (or a periodic "check for replies" habit) → agent runs a targeted
Gmail search → shows the candidate message(s) → on approval, records the communication in the
application folder. If `grop@me.com` ever starts receiving application mail, add an iCloud→Gmail
auto-forward rather than a second capture path.

How a captured email is stored (event shape, file layout) is deliberately not decided here — that
belongs to the per-application communication & event model
([ticket #28](https://github.com/pietgk/apply/issues/28)).
