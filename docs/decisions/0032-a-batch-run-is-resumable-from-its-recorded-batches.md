# 0032 — A batch run is resumable from the batches it already paid for

## Context

An evaluation run over `dev-400` submits its 401 cases to the provider's batch service and
then waits. The waiting is the whole run: from submission to a terminal status took between
30 and 100 minutes on the runs measured in S1. During that window the local process does
almost nothing, but it is the only thing holding the run together — the batch id lives in
its memory, and the results are collected only when `wait` returns.

That made the run as fragile as the process. Three separate dev-400 runs died mid-wait and
each one left a paid batch stranded at the provider with nothing to show for it:

| batch | requests | cost | how the run died |
|---|---|---|---|
| `batch-1789521169-LFofWWoQzHwuChB7kK27` | 401 | $0.2553 | a poll immediately after submit returned 404 (fixed, `cf8fd2e`) |
| `batch-1789525382-ddUvtcxz8IxMxerkhNp3` | 249 | $0.1825 | the run was abandoned deliberately; the batch could not be cancelled |
| `batch-1789528868-uJRGBbMh4Hxp07qRRB9m` | 401 | $0.2604 | the operating system killed the process for low memory |

The third is the one that forced this record. Nothing was wrong with the code, the request
or the provider: the machine was short of memory and killed a process that happened to be
sitting in a sleep loop. 398 of that batch's 401 replies parse cleanly. The work was bought
and paid for, and the only thing standing between it and a finished run was that the
process holding the batch id no longer existed.

A batch is also not cancellable once submitted (`POST …/cancel` returns 404, `DELETE`
returns 409 while in progress), so a dead waiter cannot even stop the spending it started.

The runner already wrote `batches.jsonl` — every batch id, with its stage, appended before
the wait begins — precisely so a dead run's spending would be visible afterwards. It was
written for forensics. This record makes it load-bearing.

## Decision

1. **A run folder records the spec that produced it.** `Runner.run` writes `spec.json` into
   the run folder before any call is made: sample, arm, exclusions, includes, model, price
   variant, caps, prompt version, and the commit sha. A run folder is now self-describing.
2. **`ntsb-eval run --resume <run-id>` continues that run instead of starting one.** It
   adopts the recorded run id and folder rather than minting new ones, so the resumed run
   is the same run, writing to the same place, and not a second run that happens to
   duplicate it.
3. **A recorded batch is reused, never resubmitted.** `_submit_and_wait` is the single point
   where a batch is submitted and waited on. On a resume it first looks for an unconsumed
   batch id recorded for that stage in `batches.jsonl`; finding one, it skips the submit and
   waits on that id, which returns at once when the batch has already completed. Stages with
   no recorded id are submitted normally, so a run that died after stage 1 pays only for
   stage 2.
4. **A resume must be the same run or it is refused.** The spec reconstructed from the
   command line must equal `spec.json` in every recorded field, and the commit sha must
   match. Any difference refuses the resume and names the field. Reusing replies bought by
   a different prompt, model, exclusion set or code version would silently mix two
   configurations inside one set of results.
5. **A run folder written before this change cannot be resumed** — it has no `spec.json`.
   Writing one by hand is a deliberate, recorded act of recovery, not something the code
   does on a guess.

## Why

The money is the smallest reason. It matters — $0.70 of a $25 monthly budget was lost to
this in one night — but the real cost is that a run which cannot survive its own machine
cannot be trusted to produce a measurement at all. `heldout-400` is touched rarely and on
purpose (0026); a harness that needs a 100-minute uninterrupted process to touch it makes
each attempt a gamble, and the temptation after a failure is to re-run rather than to
resume, which quietly spends the held-out budget twice for one number.

Reuse at `_submit_and_wait` rather than at a higher level is what keeps this small. The
stages already flow through that one function, and the request set at each stage is
determined by the spec, the records and the previous stage's results — all of which the
replay reproduces exactly, given the same commit and the same spec. So resume is not a
parallel code path with its own bugs; it is the same path, with the submit step short-
circuited. That is why point 4 is strict: the guarantee that the replayed requests match
the recorded ones rests entirely on the spec and the code being identical, so anything less
than equality has to refuse.

Making the run folder self-describing is worth more than the resume feature itself. Until
now a run's identity lived in the command line that started it, which is nowhere after the
shell closes. `spec.json` means a folder found later can be read, checked, and reasoned
about without reconstructing what someone typed.

Refusing to resume pre-change folders keeps the code honest about what it can verify. The
alternative — resume anyway, validating only what the run id encodes (time, sha, sample,
arm) and trusting the operator for model and exclusions — puts a permanently unverifiable
branch into the harness to serve a problem that exists exactly once.

## What this rules out

- **Resuming by re-submitting.** Simple, and wrong: it pays twice for work already bought,
  which is the problem this record exists to solve.
- **A checkpoint after every case.** The sync path would need it too, and it would mean
  writing partial `cases.jsonl` files that later runs must learn to distinguish from
  complete ones. The batch path's unit of work is already the batch; recording the batch is
  the cheaper and more honest checkpoint.
- **A daemon or job queue that owns long runs.** The right answer if runs were frequent and
  unattended. They are neither: an evaluation run is a deliberate act a few times a stage,
  and a background process with its own lifecycle is a great deal of machinery, and a new
  place for spending to hide, for a problem a recorded batch id solves.
- **Making the waiter harder to kill** (lower priority, smaller footprint, a pure-shell
  poller). None of these make the run survivable — they only make it less likely to be
  chosen by the killer. The run still cannot be continued once it dies.
- **Trusting the operator to re-supply the original flags.** See point 4: it makes results
  that look complete but silently mix configurations, which is worse than no result.

## Status

Accepted.
