# 0127 — S3's arms and ablations; arm B calls every coding tool; the ordering check runs in arm B only

Keeps [0022](0022-loop-must-beat-call-every-tool-arm.md) item 1's three arms and applies them to
the loop of [0121](0121-agency-moves-to-reading-and-coding.md). From the S3 design session
(2026-09-29 to 2026-09-30): ordering choice B, and the arms and ablations of spec §7. Detail:
[the S3 specification](../specs/2026-09-30-s3-agent-loop-design.md) §7 and §8.1.

## Context

0022 item 1 fixes three arms with the same model, cases, price variant and per-case cap: A
(start facts, one call), B (every available tool in a fixed order, then one call) and C (the
loop). The loop's tools now include coding tools ([0124](0124-native-tool-calling-and-a-cacheable-conversation.md),
[0125](0125-the-suggestion-tool.md)).

S2.7's final setup is arm B's answer with the two kept guidance files, then the ordering check
(`luna`). It scored occurrence top-1 25.1% [21.1%, 29.5%] on `dev-400` and 27.5% [23.3%, 32.0%]
on `dev-seal-400` (`docs/results/s27-sealed-dev.txt`). The ordering check (0096) is a second call
after the answer that re-orders its occurrence codes. It raised top-1 by +6.8% [+3.3%, +10.3%]
and +9.8% [+6.0%, +13.8%] on two answer sets (`docs/results/s27-round1-dev.txt`).

## Decision

1. **Arm A**: start facts only, one call, as in S1. It is re-run at S3.2's commit, so that all
   arms share one commit (estimate: about $0.20 on `dev-400`).
2. **Arm B, the fixed pipeline and the bar**, in four fixed parts:
   1. **The answer**: S2.7's final setup. Evidence v1, the fixed document filter, one answer
      with the two guidance files.
   2. **Every coding tool on its own top three**, in this order: `describe_codes`;
      `occurrence_usage` on the three codes and their pairs; `past_findings` for its first code;
      `suggest_codes` for that code's phase group.
   3. **One more answer**, with the tool results.
   4. **S2.7's ordering check** (`luna`), as a post-pass.

   Parts 2 and 3 run as a post-pass over a finished arm B run, through the same tool code, and
   write a derived run folder, as the ordering check does (0096). Part 1 then stays byte-for-byte
   S2.7's answer. Arm B without the ordering check is reported second.
3. **Arm C**: the loop (0121, [0122](0122-h0-and-later-triggers.md), 0124).
4. **The ordering check is in arm B only.** In the loop, the agent's own tool calls do that job.
5. **Three ablations of arm C**, each about $3.30 on `dev-400` at the batch price (estimate,
   spec §14):

   | ablation | what it shows | where it runs |
   |---|---|---|
   | no docket (docket state none) | what reading adds inside the loop | `dev-400` and `heldout-400` |
   | no `suggest_codes` | what the suggestion tool adds | `dev-400` |
   | no coding tools (the answer is the latest hypothesis, then the refinement) | what the coding step adds, where the agency is meant to sit | `dev-400` |

6. Arms B and C are compared on the cases both scored, with each arm's failure count beside the
   result (spec §8.4). Both read S3's statistics file
   ([0129](0129-s3s-sealed-sample-and-statistics.md)).

## Why

1. **Andy's choice** (2026-09-29): the extra checker is "only ever a way to replicate a tool
   call". In the loop, a checker after the answer would do what the coding tools are for.
2. **Arm B is the pipeline a sceptic would build**: every tool and the best known fixed check,
   with no choosing. It is S2.7's measured best plus the tools the loop has. If the loop's
   choices add nothing, this arm shows it (0022, Why 1).
3. **A post-pass keeps S2.7's answer exact**, so arm B's first part is the setup whose results
   are already published.
4. **The ablations test the parts the design rests on.** The no-docket ablation is the one the
   project's goal 2 requires on held-out. The other two isolate the suggestion tool and the
   coding step.

## What this rules out

- **The ordering check in both arms.** The loop would also get S2.7's best fixed check.
  Rejected: after the answer it would redo the coding tools' job, and blur what the loop's own
  choices add.
- **The ordering check in neither arm.** A plainer like-for-like comparison. Rejected: arm B
  would fall below S2.7's measured best, and the bar would be weaker than a pipeline already
  known.
- **Arm B as S2.7's answer only.** Rejected: 0022 item 1 requires arm B to call every available
  tool, and the coding tools are tools.
- **Arm B's tool calls inside its first run.** One run folder instead of two. Rejected: part 1
  would no longer be byte-for-byte S2.7's answer.

## Status

Accepted, 2026-09-30 (Andy, S3 design session; specification approved 2026-09-30).

**Amended 2026-10-03 by [0141](0141-s32-five-runs-and-the-sealed-sample-kept-for-v2.md)
(appended; nothing above is edited).** The no-docket ablation runs on held-out only, and the
`suggest_codes` ablation is not run in S3.2. Item 1's re-run of arm A on `dev-400` is not made
either: arm A runs on held-out only.
