# 0137 — The ordering check as a diagnostic on arm C, run once

From Andy, 2026-10-02, during S3.1 Task 15, before round 1 is registered. Detail: the S3.1 plan's
Deviations (`docs/plans/2026-09-30-s3-1-agent-loop.md`). This does not change
[0127](0127-arms-ablations-and-the-ordering-check-in-arm-b.md): the check stays out of arm C. It
measures 0127 item 4's premise once. It changes no arm, no round and no bar.

## Context

1. **The premise.** 0127 item 4 keeps S2.7's ordering check
   ([0096](0096-the-ordering-check.md)) in arm B only: "In the loop, the agent's own tool calls do
   that job." The tool meant is `occurrence_usage`. It shows the loop the statistics pool's counts:
   how often each code is present and how often it is defining, alone and in pairs. The check
   reads the same kind of counts. The premise has never been measured.
2. **What the check did for arm B.** It raised arm B's occurrence top-1 by +6.8% [+3.3%, +10.3%]
   and +9.8% [+6.0%, +13.8%] on two answer sets (`docs/results/s27-round1-dev.txt`).
3. **What the loop does with the counts.** The loop has them through `occurrence_usage`, but it
   chooses whether to call the tool, on which codes, and how to read what comes back. The check
   is given the counts for every case the loop answered without abstaining, and is asked one
   fixed question about them. The
   loop's own use of the counts is a choice; the check's is not.
4. **What the check can change.** It re-orders the answer's occurrence codes within a candidate
   list of at most eight (0096 item 3): the answer's own three, then codes the pool's counts
   suggest. So it can fix a case only when the NTSB's first code is in that list. In arm C's
   "always wrong" group (wrong in both noise-floor runs), the NTSB's first code is the loop's
   second or third code in 35 of 266 cases in run a (`docs/results/s3-miss-kinds-dev.txt`, kind
   "order"). Those are the cases that re-ordering the loop's own codes alone could fix.
5. **Run a.** Noise-floor run a is `20261001T201506-fd6053f-dev-400-C`. It scored 394 of 401
   cases; 6 of the 394 abstained (`docs/results/s3-noise-floor-dev.txt`). The check skips failed
   and abstained cases, so it asks Luna about 388 cases.
6. **What it costs.** About $0.12. S2.7's Luna check over the 401-case sealed run cost $0.1133
   (`docs/plans/2026-09-26-s27-track1-coding-guidance.md`, 2026-09-29 entry). Andy runs it.

## Decision

1. **`ntsb-eval check` accepts a finished development arm C run, with way `luna` only.** The
   ways `rule`, `jev` and `jev2` are refused for an arm C source in `checkpass.preflight`
   (`_refuse_for_arm_c`), before any budget reservation, client or folder. An arm C tool
   ablation (`--without`, recorded in `spec.json`) is refused too: the diagnostic reads the arm.
2. **On an arm C source, the check counts in the S3 statistics** (`TOOLS_STATS`,
   `coding_stats_s3.json`), the file the loop's own tools read
   ([0129](0129-s3s-sealed-sample-and-statistics.md) item 4). As for arm B's tool post-pass, the
   file is named on the command line (`--stats s3`), and any other is refused. The derived prompt
   version ends `+check-luna-s3`.
3. **It writes the usual derived folder, `<run id>-check-luna`, as a diagnostic.** The folder,
   its cost (the check's alone), the rescoring and the refusals are those of every check. The
   answer re-ordered is the case's last step. Arm C writes one step per checkpoint, and a scored
   case's last step is its final answer as scored: the refinement when it ran, else the answer.
   The check is sent that answer's codes and its own evidence narrative, exactly as for arm B
   (0096 item 2); nothing it sends changes. The derived run is never arm C's result, never a
   round's run, reference or noise run (`scripts/round_result.py` refuses it), and never in a
   bar.
4. **It is read once, on run a, by this rule, fixed before the run:**

   > Read with `ntsb-eval report <derived id> --against <run a>` on paired occurrence top-1. If
   > the interval lies above zero, the loop does not act on the counts `occurrence_usage` shows as
   > well as the check does, and round 1's target becomes how the loop reads them. If the
   > interval includes zero, the premise is not shown to fail. If it lies below zero, the check
   > would harm the loop's answers. The first codes changed, and the fixes and breaks among them,
   > are printed beside it.

   `report --against` prints that line for an arm C check run only
   (`report.first_code_changes`); arm B's reports are unchanged. The report pairs the cases scored
   in both runs. The check passes run a's 7 failed cases through unchanged, so they fail in both
   runs. Counting them wrong, as an S3 round does
   ([0136](0136-s3-rounds-count-failed-cases-as-wrong.md)), would add 7 zero differences and
   change no fix or break.
5. **Held-out, open and sealed runs stay refused.** Held-out and open runs are refused by the
   development rule (the sample, the run id and every case's split). For an arm C source, a
   sealed sample is refused even once its registration is committed.

Example: the loop answers aerodynamic stall/spin first and loss of control in flight second, and
the NTSB coded loss of control first. If the check puts loss of control first, the case is a fix.
Had the NTSB coded stall/spin first, the same move would be a break.

## Why

1. **A premise that shapes the design should be measured, not assumed.** 0127 item 4 rests on
   Andy's judgement that the extra checker is "only ever a way to replicate a tool call" (0127,
   Why 1). If the check still raises the loop's top-1, the loop has the counts but does not use
   them as well as one fixed question does. That would point round 1 at how the loop reads the
   counts.
2. **Luna only.** It is the way S2.7 kept by 0096 item 5's rule. It beat the plain rule by +4.8%
   [+1.0%, +8.5%] and +8.0% [+4.0%, +12.3%] on the two answer sets
   (`docs/results/s27-round1-dev.txt`). Jev was not kept, and `jev2` did not replace Luna
   ([0103](0103-a-registered-second-jev-check.md); `docs/results/s27-round1-jev2-dev.txt`: "luna
   stays"). The diagnostic needs the best check measured, not a new comparison of ways.
3. **The S3 statistics.** The question is whether the loop uses the counts its tool shows. The
   check must see the same counts, or a difference could come from the file, not the loop.
4. **A diagnostic, not part of an arm.** 0127 item 4 stands. If the check entered a round or a
   bar, the loop's result would include a fixed step after its answer, which 0127 rejected.
5. **Once, by a rule written first.** A reading rule fixed before the run cannot be argued around
   afterwards (0136, Why 2). Run a is the first noise-floor run, already paid for.

## What this rules out

- **The check in arm C.** 0127's rejection stands: after the answer it would redo the coding
  tools' job and blur what the loop's own choices add.
- **Using the diagnostic in a round, a round's reference or a bar.** It measures a premise. It
  is not the loop's result.
- **Jev on arm C** (`jev`, `jev2`). Jev was admitted as one of S2.7's ways of the check
  ([0097](0097-jev-as-an-ordering-check-model-on-development-cases.md), 0103), and neither way was
  kept.
- **The plain rule on arm C.** It is free, and it would show what the counts alone do to the
  loop's answers. Not chosen: Luna beat it on both of S2.7's answer sets, and a second way would
  be a second reading of one premise.
- **A check over run b, or a later run, without a new record.** Two answer sets, as 0096 read
  S2.7's check, would guard against a lucky result on one run, for about $0.12 more. Not chosen
  (Andy: once, on run a). A second look taken after the first result is known needs its own
  record, written before it runs.

## Status

Accepted, 2026-10-02 (Andy: 'lets do both of those', approving the diagnostic).

## Glossary

- **Candidate list**: the codes the check may put first: the answer's own three, then codes the
  pool's counts suggest; at most eight (0096 item 3).
- **Derived run**: a run folder written by a post-pass over a finished run, named after it.
- **Diagnostic**: a measurement that tests a premise. It is not an arm's result, a round or a bar.
- **Fix / break**: a case the check makes right on occurrence top-1 / makes wrong.
- **Noise-floor run a**: the first of the two identical arm C runs on `dev-400` (0130).
- **Ordering check**: a GPT-6 Luna call after the answer that re-orders its occurrence codes,
  given the counts and the answer's own evidence narrative (0096).
