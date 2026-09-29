# ADR 0005: Keep AI assistance inside a human approval boundary

- Status: accepted
- Date: 2026-07-10

## Decision

AI may help extract job signals, propose a positioning angle, and assemble a
CV draft from the master profile. A human remains responsible for factual
approval, the choice to apply, final PDF review, and status changes in
`meta.yaml`.

## Context

The repository contains a prompt-driven tailoring workflow, but no automated
submission or approval service. ATS linting is a suggestion and quality gate,
not evidence that a claim is true.

## Consequences

Automation can reduce repetitive editing without granting it authority to
invent facts or send an application. The human review step must remain visible
in the workflow.
