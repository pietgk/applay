# ADR 0002: Treat the master profile as the factual source

- Status: accepted
- Date: 2026-07-10

## Decision

Tailoring selects and lightly rewrites facts from
`profile/master-profile.yaml`. New proof points are added there before being
used in future CVs. A job description may guide emphasis and wording but may
not create experience, skills, metrics, or credentials.

## Context

The profile already consolidates source material and tags achievements for
matching. `tools/cv-tailor.md` explicitly instructs the workflow never to
invent facts outside it.

## Consequences

Truthful tailoring is reviewable from one source and improves future
applications. The profile must be maintained when a genuinely new fact is
confirmed.
