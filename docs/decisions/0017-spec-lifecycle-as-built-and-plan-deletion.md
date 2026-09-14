# 0017 — Specifications close with an As-built record; plans are deleted at merge

## Context

Each build stage gets a design specification (`docs/specs/`) and an implementation plan
(`docs/plans/`), both written and committed by Claude Code using the superpowers skills.
Implementation departs from a specification in small ways, and those departures are rarely
written down. Left alone, the specification and the code disagree within weeks, with no record
of why — the same failure 0008 exists to prevent for decisions. A plan is a task checklist:
once the stage merges, it no longer describes anything that is still true.

## Decision

**Lifecycle.**

- A specification carries one status line: `Draft`, `Approved`, `Implemented` or `Superseded`.
- While a stage is built, its specification is not edited to follow the code. A significant
  departure gets a decision record. The plan's tasks are ticked in the same commit as the code
  they cover, and the plan keeps a **Deviations** log.
- The pull request that finishes a stage **closes it out**: the specification's status becomes
  `Implemented` (date and pull request), and an **As built** section is appended with five
  parts — *Delivered*; *Done means, with evidence* (the test, script or output file behind each
  condition); *Departures from this specification* (the plan's Deviations log, moved here);
  *Decisions taken during the stage*; *Implementation record* (the pull request, and a permalink
  to the plan at its last commit). The roadmap's stage entry is marked done. **The plan file is
  deleted.**

**Enforcement, three layers.**

1. **A pull-request template** with the close-out checklist.
2. **`scripts/check_docs.py` in continuous integration**, failing when: a decision file and the
   index disagree on existence or status; a decision reference or relative document link
   resolves to nothing; a specification has no valid status line; an `Implemented`
   specification lacks any of the five As-built parts; a plan exists for an `Implemented`
   specification; a plan has no Deviations section.
3. **A project skill, `close-stage`** (`.claude/skills/close-stage/`), that drafts the As-built
   section from the specification, the plan, the git log and the decision records added during
   the stage, updates the statuses, deletes the plan and runs the check.

The check script, template and skill are built in S0.

## Why

1. **Intent and outcome are both kept, and kept apart.** The specification body stays the record
   of what was intended and approved; the As-built section is the record of what happened. A
   reader can see both and the difference between them, which a continuously edited
   specification would erase.
2. **Nothing stale remains in the tree.** A completed plan is a list of finished tasks that
   reads as live instructions. Git history keeps it, and the permalink makes it one click away.
3. **Each layer covers a different failure.** The template reminds, the skill makes the work
   cheap, and the check fails the build when the work was skipped. The check cannot judge
   whether the As-built section is accurate; review does that. It guarantees the section exists
   and every link resolves.

## What this rules out

- **Living specifications, edited as the code changes.** Always current. Rejected because the
  approved intent disappears, and departures become invisible instead of recorded.
- **Keeping completed plans, marked Complete.** The build history stays readable in the tree.
  Rejected (Andy, 2026-09-13) because the As-built section should carry what matters and a
  finished plan invites being read as current.
- **A checklist, or a skill, alone.** Cheaper. Rejected because nothing fails when either is
  skipped; the S0 roadmap already holds that a check which is not enforced is no check.

## Status

Accepted, 2026-09-13.
