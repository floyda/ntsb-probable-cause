# 0122 — The first hypothesis uses all non-docket evidence present; later triggers re-send read documents in full

Applies [0121](0121-agency-moves-to-reading-and-coding.md)'s supersession of 0023 items 1 and 2.
From the S3 design session (2026-09-29 to 2026-09-30): H0 choice B, and later-trigger choice B.
Detail: [the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §4.1 to §4.3.

## Context

- 0023 started the agent from **start facts**, the evidence a live case has on day 1, and put
  the rest behind tools.
- The learning probe formed its first hypothesis (H0) from all the structured evidence of a
  closed case, not from start facts alone. That departed from the flow agreed before the probe,
  and was logged in the probe plan's Deviations for Andy to confirm
  (`docs/plans/2026-09-29-s3-learning-probe.md`, 2026-09-29).
- A live case changes over time. It holds start facts only in its first days, and everything by
  closure, when the docket arrives ([0123](0123-the-staged-replay-is-paused.md)). The live loop
  must run each time something new arrives, with the docket in any state.
- The probe sent its own earlier replies back to the model as the conversation grew. It had to
  add a note telling the model to prefer the current evidence over those replies (probe plan
  Deviations, Task 4, fix round 2).

## Decision

1. **Triggers.** The loop runs once each time something new arrives for a case: its first
   sight, a new structured field, or new docket documents. Its input always has the same shape:
   - the evidence present now, from `split_record` (0016);
   - the docket in one of three **docket states**: none, some or all;
   - the case's earlier trail, if there is one.
2. **H0 uses all non-docket evidence the case holds at that moment**, plus any documents read
   on earlier triggers.
3. **The steps on one trigger** (spec §4.2): H0; a read choice on every offered document not yet
   read; H1, skipped when nothing was chosen; a second look over what is left, with H2 only if
   something was read; coding, "code first, then check", at most 6 tool calls; the finding
   refinement that arm B's answer uses; confidence and abstain, set in code
   ([0126](0126-confidence-is-calibrated-in-code.md)).
4. **The offered documents** are exactly the set arm B may attach: every document whose text
   extraction found text (`docket/filter.py`, `arm_b_documents`; 0052, 0056). Scan-only
   documents are listed as not readable. Documents classified as synthesis never appear. S3.1
   and S3.2 add no transcription tool (spec §11; 0120 says the loop *may* have one).
5. **A later trigger on the same case** (spec §4.3):
   - receives every document read so far, in full, word for word, as evidence;
   - receives a short summary of the agent's own earlier replies: its last hypothesis, and which
     documents it read or skipped, with its reasons;
   - gets a fresh read-or-skip choice on every unread document, including ones skipped before;
   - forms H0 again only when new structured evidence arrived. When only documents arrived, its
     last answer already is its best hypothesis on everything it had, so that call is skipped.
6. **Evaluation uses one trigger per closed case**, with everything present: the **full
   condition**, which is the state of a live case at closure. The same code runs live, in
   evaluation, and in the staged replay if it is reopened. Later triggers are built and tested
   in S3.1, on development cases replayed in two steps as the probe did. S3.3 is the first
   stage that uses them on live cases.

*Example (invented).* On a first trigger the agent reads the pilot's report and skips a
two-page weather printout ("weather was visual; no change expected"). A week later an engine
examination arrives, with no new structured field. The second trigger re-sends the pilot's
report in full, summarises the last hypothesis and the read and skip reasons, skips H0, and
offers the engine examination and the weather printout.

## Why

1. **One rule for every state.** A read choice made against start facts alone tests a state no
   live case is in when its docket arrives, and makes every document look more valuable than it
   is. In the full condition, H0 is the same task as S1's one-shot ceiling, so it can be
   compared with a measured arm.
2. **The agent always sees the source text.** A document skipped on the first night can matter
   once a later one arrives. A document read earlier can be read differently in the light of a
   later one.
3. **Its own replies are summarised, not replayed.** The whole conversation grows without
   limit, and stale replies mislead: the probe needed the note above.
4. **H0 is not repeated without a reason.** When only documents arrive, nothing H0 reads has
   changed.

## What this rules out

- **H0 from start facts alone** (the flow agreed before the probe, and 0023's start). It would
  separate what documents add from what the other structured fields add. Rejected by Why 1.
- **The agent's own notes standing in for documents it already read.** It saves the most
  tokens. Rejected: a note can drop the detail that a later document makes decisive.
- **Replaying the whole earlier conversation on a later trigger.** It keeps every word.
  Rejected by Why 3.
- **Never re-offering a skipped document.** Fewer decisions. Rejected by Why 2.
- **A separate input shape for evaluation and for live runs.** Rejected: the evaluated loop and
  the live loop would then differ.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).
