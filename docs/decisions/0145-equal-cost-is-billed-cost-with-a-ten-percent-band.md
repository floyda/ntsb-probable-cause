# 0145 — Equal cost is billed cost, with a ten percent band

From the S3.2 design session (2026-10-03): equal cost, option A. Fixes the meaning of "equal
cost" that [0121](0121-agency-moves-to-reading-and-coding.md) item 5 and
[0135](0135-s3-spend-counts-what-was-billed.md) item 6 left to S3.2's registration. Detail:
[the S3.2 specification](../specs/2026-10-03-s3-2-claims-design.md) §6.

## Context

0121 item 5's test and its result 2 both turn on cost: the loop is warranted only if it beats
arm B at equal cost, or matches it at lower cost. A run records two costs (0135 Context 1): the
**computed** price, every token at the list rate, and the **billed** total, which the provider
reports and which counts cached prompt tokens at a lower rate.

**What `dev-400` showed, seen before this rule was written:**

| | loop (two runs) | arm B (three parts) |
|---|---|---|
| billed | $1.84 and $1.97 (scripted, `docs/results/s3-noise-floor-dev.txt`) | $2.19: answer $1.12, tool post-pass $0.96, ordering check $0.11 (run records) |
| computed | $4.57 and $4.45 (same file) | $2.43: answer $1.21, post-pass $1.11, check $0.11 (run records) |

By the bill, the loop is about 10% to 16% cheaper. By the computed price it costs about twice
as much. The gap is prompt caching: the loop resends its growing conversation on every call, and
the provider bills what it has recently seen at a lower rate. The loop's two identical runs
differed by 7% on their bills ($1.84 against $1.97).

## Decision

1. **Each arm's cost is what was billed for its held-out run**, on the same cases, failed cases
   included (that money was spent). Arm B's is the sum of its three parts. A batch run's billed
   figure is its `reported_batch_cost_usd`. The ordering check runs synchronously, and its
   replies carry the provider's own cost, so its `cost_usd` is what was billed.
2. **The band.** The loop's cost is **lower** when more than 10% below arm B's, **greater** when
   more than 10% above, and **equal** otherwise.
3. **Printed beside, never deciding:** each arm's computed cost and its prompt and reply tokens,
   so a reader sees how much work each did.
4. **Arm B's billed figure is used without rewriting any spend record.** 0135 counted arm B at
   the computed price for spend only, so that past totals stayed as they were. The comparison
   reads the run's billed figure and changes no record.
5. **This fixes the meaning of "equal cost"** in 0121 item 5 and in 0135 item 6.

## Why

1. **Billed is the money paid,** and what the live board will pay.
2. **The 10% band is the noise.** Two identical loop runs differed by 7% on their bills, so a
   smaller gap is within chance.
3. **The billed measure is defensible although the figures were seen.** The loop's cache-friendly
   shape, the same tool definitions on every call and a conversation appended to at the end
   only, was decided in [0124](0124-native-tool-calling-and-a-cacheable-conversation.md), before
   any cost was measured. The disclosure is in the registration (spec §13).
4. **The work done stays visible.** Item 3, and the split of the saving into work and discount
   ([0149](0149-how-the-results-are-read-together.md)), show a reader how much each arm did.

## What this rules out

- **Computed price for both arms.** The strongest case: it measures work, and a fixed pipeline
  built as one cached conversation might earn the same discount. Rejected: it prices the loop at
  about twice what anyone pays. The work done is printed beside and split out in 0149.
- **"Lower" only if lower under both measures.** The most cautious reading. Rejected: with
  `dev-400`'s figures it restates computed pricing's outcome, because the loop is never lower
  by the computed price.
- **A band other than 10%.** A smaller band would sort identical runs differently by chance (the
  7% gap above). A larger one would hide real differences.

## Status

Accepted, 2026-10-03 (Andy, S3.2 design session; specification approved 2026-10-03).

## Glossary

- **Billed cost**: what the provider charged; cached prompt tokens cost less.
- **Cache discount**: the lower rate for the start of a prompt the provider has seen recently.
- **Computed cost**: every token priced at the list rate, ignoring the cache discount.
- **Equal, lower, greater**: the loop's billed cost against arm B's, with a band of 10%.
