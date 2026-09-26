# 0093 — S2.7 runs as two tracks: coding guidance on v1, transcription alongside

## Context

S2.6 closed on its development results (0090). Arm B's `dev-400` misses are mostly coding
convention rather than reading (`docs/results/s26-occurrence-misses-dev.txt`): the first guess
is in the NTSB's sequence on 35.1% of cases but is the defining event on 22.1%. Transcription
(v2) moved top-1 by +1.3% [-2.5%, +4.8%] (`docs/results/s26-armB-v2-dev.txt`) and cost $13.56
for `dev-400` (S2.6 As-built). The transcriber, Qwen3.5 122B, was chosen provisionally and post
hoc (0087), and newer vision models now list input prices of a tenth of Qwen's or less
(external, OpenRouter model list, read 2026-09-26).

Tuning guidance on Qwen's v2 would tune on evidence that a cheaper transcriber may replace.
Doing the transcriber work first would hold up guidance, the larger lever.

## Decision

1. S2.7 (specification `docs/specs/2026-09-26-s27-coding-guidance-design.md`) runs as **two
   tracks**. Track 1: Round 0, Round 1 and the guidance rounds, all on evidence version **v1**.
   Track 2: a transcriber re-test and a page-selection rule (0100).
2. The tracks meet at the end: one v1-against-v2 comparison on `dev-400` under the final
   guidance, with track 2's transcriber and page rule. Andy decides then whether v2 goes
   forward, as in 0088.
3. **Branches**: `s27-coding-guidance` from `main` holds the specification and track 1;
   `s27-transcriber` is cut from it for track 2 and merges back with a merge commit before the
   meeting point. One stage pull request, one As-built record, one release. Two plans, one per
   track, both naming the one specification.
4. **Decision numbers**: records written with the specification are 0093–0100; during the build
   track 1 takes the next free numbers up to 119, and track 2 takes 120 to 129.

## Why

1. **Nothing is tuned on evidence that may change.** v1 depends on no transcriber.
2. **Guidance is not held up** by the re-test and Andy's marking.
3. **Transcription money is spent once**, after the choice, and the sealed sample is
   transcribed only if v2 goes forward.
4. **Separate branches keep paid runs clean.** A run records its commit and whether the tree was
   dirty; two tracks in one working copy would dirty each other's runs, and git cannot check out
   one branch in two worktrees.
5. **Reserved number blocks avoid a renumbering.** Parallel branches have collided on a decision
   number before.

## What this rules out

- **Rounds on Qwen's v2.** Cheaper to start, but a transcriber switch would leave the rounds
  tuned on evidence that no longer exists.
- **Transcriber first, then rounds.** Every round would run on final evidence, at the cost of
  holding guidance for the whole re-test and a re-transcription of `dev-400`.
- **Two stages (S2.7 guidance, S2.8 transcription).** The meeting point needs both, so one stage
  would depend on the other's merge: two close-outs for one question.
- **One branch, one track at a time.** Simplest in git, but the tracks could not run in parallel.

## Status

Proposed, 2026-09-26: written with the S2.7 specification from the design session with Andy
(two tracks: "i agree with the two tracks"; branches: "i think it has to be A"). Accepted when
Andy approves the specification.
