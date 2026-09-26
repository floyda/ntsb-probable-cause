# 0067 — Watched cases are Part 91 plus those with the regulation empty; regulation changes are counted at 8 weeks

## Context

The corpus is general aviation: cases flown under Part 91 (`GA_REGULATION = "091"`). The
regulation is recorded by investigators and may be filled in after a case first appears.
Ad-hoc over 1,061 ongoing aviation cases in the local store: 891 are `091`, 14 have the field
empty, and the rest are airline, charter, agricultural or other. Whether the field changes
after it is first recorded is unknown; no history exists. Live cases are filtered on
`completionStatus == "Ongoing"`, never on "not `Completed`" (CLAUDE.md rule 5).

## Decision

A case is watched when it is aviation, `Ongoing`, and its regulation is `091` or empty. A
case whose regulation is later recorded as anything else stops being watched that night; its
rows are kept. The regulation is one of the snapshotted fields, and the 8-week report counts
how many watched cases changed regulation after first seen.

## Why

1. **A day lost cannot be recovered.** A case watched from day one and dropped later has cost
   a few requests; a case ignored and found to be Part 91 on day 20 has lost 20 days.
2. **The empty set is small** — about 1.3% — so the extra cost is a few requests a night.
3. **Andy's condition is checkable.** He chose this over watching every aviation case on the
   condition that most cases are categorised correctly at once and do not change. The first
   half is the 1.3%; the second half is what the 8-week count measures. If changes prove
   common, widening to every aviation case is a recorded decision with a number.

## What this rules out

- **Every ongoing aviation case.** Simplest rule, and it records arrival for about 150
  airline, charter and agricultural cases that nothing in the project uses.
- **Part 91 strictly.** Loses the early days of any case whose regulation is filled in late.

## Status

Accepted, 2026-09-22.
