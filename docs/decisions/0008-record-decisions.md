# 0008 — Record every significant decision

## Context

Work on this project runs across many short sessions, with gaps between them. The spike
already showed the pattern: its value turned out to be the assumptions register and the
report, more than the scripts. Choices made without a written justification get
re-litigated later, or quietly reversed by someone who never saw the constraint that
produced them.

## Decision

Every significant architecture, scope, tooling and methodology decision is written to
`docs/decisions/` as a numbered record with context, decision, reasoning, and what the
decision rules out. Records are append-only: a superseded decision gets a new record
naming the one it replaces, and the old one stays. Recorded as rule 8 in `CLAUDE.md`.

## Why

1. The reasoning is the substance of this project. A reader who disagrees with a choice
   should be able to find the argument for it and say precisely where it fails, rather
   than infer what was considered from the code that survived.
2. Rejected alternatives are the part that disappears fastest and matters most. A record
   with nothing under "what this rules out" usually means the decision was not real.
3. Continuity across sessions. The cost of re-deriving a constraint is higher than the
   cost of writing it down once.

## What this rules out

- **Decisions captured in commit messages alone.** Discoverable in principle, unreadable
  in practice, and they record what changed rather than what was weighed.
- **A single running decision log file.** Less ceremony, but it makes superseding a
  decision an edit rather than an addition, which loses the history of what was believed
  and when.

## Status

Accepted.
