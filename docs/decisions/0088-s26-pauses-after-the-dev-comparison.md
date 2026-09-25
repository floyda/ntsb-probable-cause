# 0088 — S2.6 pauses after the dev-400 comparison; the held-out step is decided then

Applies [0083](0083-the-monthly-budget-is-forty-dollars-in-development.md) item 2's pause point
to S2.6's re-estimate, and corrects [0087](0087-the-transcriber-is-qwen-provisionally.md) item
2, which said v2 reaches `heldout-400` "only as that task's rule allows": the plan and spec hold
no such rule. Spec §9.3 (both B-v1 and B-v2 on held-out once each) is unchanged as the expected
path.

## Context

The stage re-estimate at S2.6 Task 13 Step 12 (`scripts/transcriber_test.py estimate`, model
`qwen/qwen3.5-122b-a10b`, 2026-09-25):

- spent on S2.6 so far: $3.68;
- the rest of the stage: $49.78, of which transcription of both samples is $38.28 (12,458 image
  pages per sample at the measured $0.00154 per page), arm B runs $6.79 (a floor) and the v3
  probe $4.72;
- stage total $53.47, past the $40 stage line; this month's headroom $22.38.

About half the rest is transcribing `heldout-400`, which is only useful if v2 is carried to
held-out.

## Decision

1. **Dev first.** The resolution comparison on the chosen transcriber, then transcription of
   `dev-400` and the dev B-v1 and B-v2 runs (spec §9.1), each paid step confirmed by Andy.
2. **A stop after the dev comparison.** When `docs/results/s26-armB-v2-dev.txt` is published,
   work stops and Andy decides, with those results in view, whether to transcribe `heldout-400`
   and run B-v1 and B-v2 there (spec §9.3), expected to be in the next month's budget.
3. **No automatic rule.** The decision is Andy's at the stop; what the dev comparison shows is
   published whichever way it comes out (spec §9.1), and the held-out decision is recorded with
   its reasons.

## Why

1. **Money.** About $19 of held-out transcription is not spent before the dev comparison is
   seen, and the stage stays within each month's budget.
2. **Andy's position.** The held-out runs are the expected path ("we will probably run against
   the held-out anyway"), but the position is re-evaluated on the dev results rather than fixed
   by a threshold chosen now.

## What this rules out

- **Transcribing `heldout-400` before the dev comparison.**
- **A pre-set go/no-go threshold for held-out.** Considered (v2 helping on occurrence top-1 or
  finding recall@10, hurting neither) and not adopted: Andy prefers to decide at the stop.
- **Reading 0087 item 2 as a rule.** It is superseded by item 2 above.

## Status

Accepted, 2026-09-25 (Andy: "we will probably run against the held-out anyway but we should gate
after the dev-400 runs to re-evaluate our position").
