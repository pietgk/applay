---
name: apply-mark-applied
description: Record a human-confirmed job application submission in meta.yaml through the deterministic applied command. Use when the user says they applied, submitted, or sent an application, or asks to mark a specific application as applied.
---

# Mark an application applied

Record one completed human submission. The command owns the metadata transition;
do not hand-edit `meta.yaml`.

## Steps

1. Require an explicit statement that the application was submitted. A finalized
   CV, an opened Apply link, or catalog `triage: applied` is not confirmation.
2. Resolve exactly one folder under `applications/`:
   - Use an exact folder/path when supplied.
   - Otherwise match the company or role against folder names and `meta.yaml`.
   - If no folder or more than one folder matches, ask the user to choose; never
     guess.
3. Run:

   ```bash
   mise run applied -- applications/<folder>
   ```

   If the user supplied a submission date, pass it explicitly:

   ```bash
   mise run applied -- applications/<folder> --date YYYY-MM-DD
   ```

   With no explicit date, the command records today. It is idempotent and
   preserves an existing `date_applied`.
4. Relay the command result, including the application folder and recorded date.
   If it refuses a conflicting date or a later status, explain the error and do
   not edit around the guardrail.

## Boundaries

- Never submit an application or infer that submission happened.
- Never use catalog triage as the authoritative application lifecycle status.
- Never modify CV or cover-letter artifacts.
