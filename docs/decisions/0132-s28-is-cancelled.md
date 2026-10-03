# 0132 — S2.8 is cancelled

From Andy, 2026-09-30, at the end of the S3 design session. Detail:
[the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §10.1 and §17 (record 12).

## Context

After S2.7, Andy was designing a stage S2.8: a fixed coding lookup, with finding codes as its
main target ([0106](0106-round-6-kept-by-override.md) item 5). Its draft design is on the branch
`s28-coding-lookup`, cut from S2.7's track 1 branch
([0107](0107-s27-spend-counts-its-own-branches-only.md)). In the same period, the S3 design put
coding checks inside the loop, as tools the agent calls with codes as arguments
([0121](0121-agency-moves-to-reading-and-coding.md),
[0125](0125-the-suggestion-tool.md)).

While S2.8 was open, its branch shared the runs folder with S3's work, and so held back a change
to the spend reader ([0131](0131-the-probe-spend-kind.md); spec §10.1 item 2).

## Decision

1. **S2.8 is cancelled.** Andy (2026-09-30): "I think S2.8 is a dead end and I've decided to can
   it".
2. **The branch `s28-coding-lookup` is left in place, unmerged.** No content from it is cited by
   any record, specification or result. Its draft decision records, numbered 130 to 134 on that
   branch, were never accepted. On `main` those numbers belong to other records, from S3's own
   0130 onwards.
3. **0106 item 5's route is closed.** It named S2.8's lookup as the next place to pursue finding
   codes. Finding codes stay a target in S3: the loop's coding step includes `past_findings` and
   the finding refinement (spec §4.2, §5.1), and finding recall@10 is reported on every run
   (spec §10.2). 0106's other items stand.

## Why

1. **Andy's judgement**, in his words above. This record states it as judgement; no measurement
   is cited for it.
2. **A cancelled stage is recorded**, so that no reader looks for its results, and so that
   0106 item 5's plan is closed openly rather than left to lapse.

## What this rules out

- **Keeping S2.8 open for later.** It keeps the option. Rejected, on judgement: an open branch
  that shares the runs folder holds back changes to shared code, as it held back the spend kind.
- **Merging the draft into `main` for reference.** It would keep the design beside the rest.
  Rejected: it would put an unaccepted design, and decision numbers that clash with S3's, into
  `main`.
- **Deleting the branch.** A cleaner branch list. Rejected, on judgement: the branch is left in
  place as history.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
