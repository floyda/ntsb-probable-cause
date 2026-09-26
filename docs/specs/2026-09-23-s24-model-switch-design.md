# S2.4 — The model switch: design

*Drafted 2026-09-23 from a design session with Andy, alongside the S2.6 design. Status: Implemented
(2026-09-25, pull request #11). This is the specification for build stage S2.4, a small stage added to
`docs/specs/2026-09-12-architecture-and-roadmap.md` §11. It records what S2.4 builds, why, the
decision it takes, and the condition for moving on. The implementation plan is written from it
separately, in `docs/plans/`.*

**How to read this.** Each section says what is done, then why. Terms in **bold** on first use
are in the glossary at the end. Numbers are labelled: **scripted** numbers cite the committed
results file that holds them; **ad-hoc** numbers were counted during the design session from a
run record and are re-derived by a script in this stage before they appear anywhere else;
**external** numbers come from OpenRouter's public model list, dated; **estimates** are
arithmetic, replaced by measured figures in the As-built record.

Decision record written with this specification: 0073 (section 9).

---

## 1. What S2.4 is for

The agent's model is `openai/gpt-5.6-luna` (decision 0031). On 2026-09-22 OpenRouter listed
`openai/gpt-6-luna`, the next model in the same line, at about half the price (external,
2026-09-22, per million tokens):

| model | batch in / out | standard in / out |
|---|---|---|
| GPT-5.6 Luna (current) | $0.10 / $0.60 | $0.20 / $1.20 |
| GPT-6 Luna | $0.05 / $0.25 | $0.10 / $0.50 |

Both list structured outputs, tool calls and a batch variant, and a context of about 1,050,000
tokens.

S2.4 switches the default model to GPT-6 Luna, if it passes a gate, and re-establishes the bars
on held-out with it.

**Why a stage of its own.** Decision 0031 says the bar and the agent are always compared on one
model. Every bar today is on GPT-5.6 Luna. Switching the model therefore means re-measuring the
bars, which touches held-out and needs a record. Kept apart from S2.6, which changes the
evidence, each stage changes one thing, so each held-out comparison isolates one change.

**Why now.** S2.6 is about to measure a new bar, and S3's loop makes several calls per case, so
most of the project's model spending is still ahead. Switching after S2.6 would mean
re-measuring its bar a second time.

**What S2.4 is not.** No change to the evidence, the guard, the prompts or the scoring. The
guard refuses exactly what it refuses today.

---

## 2. The stage in one page

1. **Shape probe**: one development case, both stages of the exchange, sync and batch (§3.1).
2. **Gate**: the ceiling on `dev-400` with GPT-6 Luna, at most 1% format failures (§3.2).
3. **Switch**: one default-model constant, the new prices, decision 0073 (§4).
4. **Held-out bars**: the ceiling and arm B on `heldout-400` with GPT-6 Luna, once each (§5).
5. **Failures by reason**: the report lists why each failed case failed (§6).
6. **Cost**: about $1.35 of model calls (§8).

If the gate fails, the default stays GPT-5.6 Luna, the result is recorded, and held-out is not
touched.

---

## 3. The gate

### 3.1 The shape probe

Both the ceiling and arm B send a two-stage exchange: stage 1 asks for a hypothesis, and stage 2
sends the model's own stage-1 reply back and asks it to refine (`scoring/runner.py`). Stage 2 is
a request that ends on the model's own turn. In S1, Gemini 3.5 and newer rejected that shape
(`sources.py`; decision 0034). A new model can fail the same way, or spend its whole output
budget reasoning and return empty content, as the reasoning tiers of other families did.

So the first calls are one development case, through both stages, once with the standard model
id and once through the batch service. The probe passes if both stages return a reply that
parses as the reply schema. Temperature stays 0 and the reasoning level is `medium` (§4.1). If
GPT-6 Luna needs a different reasoning level to return content, that is a change to the
comparison and goes to Andy before the gate runs.

### 3.2 The gate run

The ceiling on `dev-400` with GPT-6 Luna, batch, paired against the GPT-5.6 Luna ceiling run
`20260916T032106-179520f-dev-400-ceiling` (scripted, `docs/results/s1-ceiling-dev.txt`: top-1
8.7% [6.3%, 11.9%], 0 of 401 failed).

**It passes if at most 1% of cases (4 of 401) fail the reply format**, each failure listed with
its reason.

**Why 1% rather than "no worse than 5.6".** GPT-5.6 Luna failed 0 of 401 on this run, so "no
worse" would mean zero, and one stray reply would decide the stage. On held-out arm B it failed
2 of 400 on format (ad-hoc, from the S2 run record; §6 publishes it). 1% is strict enough to catch
a model that does not follow the format and loose enough that one odd reply does not.

**The score is recorded, not gated.** Decision 0031 argued the project's claim does not depend
on the model being strong: the agent is compared with a single call of the same model. One
exception: if the paired top-1 difference against GPT-5.6 Luna has its whole interval below
zero, the stage stops and Andy decides before held-out is touched.

### 3.3 If the gate fails

The default stays GPT-5.6 Luna. Decision 0073 records the result and why; the development result
is published; held-out is not touched; the stage closes with that negative result. S2.6 then
proceeds on GPT-5.6 Luna and nothing in its specification changes except the model's name.

---

## 4. The switch

1. One constant names the agent's default model, in `sources.py`, beside its price. Today the
   name is written in two places (`scoring/runner.py` `RunSpec.model` and `model/client.py`);
   both read the constant.
2. `sources.py` gains `openai/gpt-6-luna` and `openai/gpt-6-luna:batch` with their prices and the
   date they were read, as every other model has.
3. GPT-5.6 Luna's prices stay, so its runs still price and its results still report.
4. **The reasoning level is set, not left to the provider** (§4.1).
5. Decision 0073 replaces item 1 of 0031. Items 2 to 4 of 0031 — one model per comparison, the
   cross-model table kept separate, the model axis after S3 — stand.

### 4.1 The reasoning level

Both Luna models reason by default. OpenRouter's model list gives them the levels `none`, `low`,
`medium`, `high`, `xhigh` and `max`, with `medium` the default (external, 2026-09-23). Reasoning
tokens are billed as output and count against the reply's token limit; one recorded GPT-5.6 reply
spent 161 of its 188 output tokens reasoning (`tests/fixtures/openrouter/structured.json`).

Until now the code sent no reasoning setting (`model/openrouter.py`), so every S1 and S2 run used
the provider's default, and no run records it. A changed default would shift results with
nothing in the record to say why.

1. Every request states `reasoning: {"effort": "medium"}`, from one constant beside the default
   model, and every run's spec file records the level beside the model.
2. `medium` is kept for the switch, so the stage changes the model alone. **Limit, stated:** the
   GPT-5.6 runs used the default, listed as `medium` on 2026-09-23; what it was on the days they
   ran cannot be proved.
3. **The level is examined when the model is** (Andy, 2026-09-23). More reasoning may help a task
   that weighs evidence, or may hurt, as the transcription benchmark found for Gemini. A
   comparison — for example the ceiling at `low`, `medium` and `high` on `dev-400` — belongs with
   the model axis after S3 (0031), and the bar and the agent always share one level, as they
   share one model.

---

## 5. The bars on held-out

After the gate passes, and before anything else changes, two runs on `heldout-400`, once each,
with GPT-6 Luna, batch, at one commit, with today's guard:

- **the ceiling** (every tool except the docket, one answer);
- **arm B** (every tool including the docket, one answer), evidence as S2 read it.

Both are appended to the held-out ledger. The output is `docs/results/s24-bars.txt`, which
prints four comparisons, each paired on the cases both runs scored:

| comparison | question | kind |
|---|---|---|
| ceiling, GPT-6 against GPT-5.6 | Is the new model better or worse at one call? | model comparison, labelled as such (0031 item 2) |
| arm B, GPT-6 against GPT-5.6 | Is it better or worse at reading the docket? | model comparison, labelled |
| arm B against the ceiling, both GPT-6 | Does reading the docket still help on the new model? | the S2 question, re-asked |
| arm B, GPT-6, against the no-model baseline | Does it still clear 17.7% top-1? | the S1 floor (`docs/results/s1-bars.txt`) |

**Limit, stated beside the model comparisons.** The GPT-5.6 runs are on older commits (`c717ab5`
for the ceiling, `3bc3a51` for arm B), so a small part of any difference could come from code
changes. No evidence, guard or prompt change separates them, which is the point of this stage.

**What becomes of the old numbers.** S1's ceiling (10.8%) and S2's arm B (22.3%) stay in the
record as GPT-5.6 Luna results. They are history, not bars. The no-model baseline carries over
unchanged. Arm B on GPT-6 Luna is the bar until S2.6 replaces it.

---

## 6. Failures by reason

`ntsb-eval report` today prints failures as one count ("42 of 400"). It will also print them by
reason: leak (with the withheld source), reply schema, cap, and model or transport error.

**Why.** Counted by hand from the S2 run record (ad-hoc), 40 of arm B's 42 held-out failures were
refusals for analysis-narrative sentences in docket documents, and 2 were reply-format failures.
That is 10% of held-out cases refused, against 4.2% on development
(`docs/results/s2-docket-leak.txt`). The gate in §3 needs the format count, and S2.6, which
changes how such cases are handled, needs the refusal count, from a script rather than a person
reading a log. The breakdown prints counts by reason and never case numbers.

---

## 7. Tests and continuous integration

- The default model is read from the one constant; a test fails if either former hard-coded
  site names a model directly.
- Every model the harness can run has a price; a run on a model id with no price refuses to
  start (as today).
- The report's failure breakdown: fixed failed cases in, counts by reason out, no case number in
  the text.
- The shape probe's recorded replies become fixtures, as S1's probe replies did, so the tests run
  offline.

---

## 8. Cost

Estimates from the real GPT-5.6 costs in the held-out ledger and `s1-ceiling-dev.txt`, scaled
by the price ratio (input half, output about four tenths):

| run | GPT-5.6 cost (scripted) | GPT-6 estimate |
|---|---|---|
| shape probe | — | under $0.01 |
| ceiling, `dev-400` | $0.44 | about $0.20 |
| ceiling, `heldout-400` | $0.49 | about $0.22 |
| arm B, `heldout-400` | $2.00 | about $0.90 |
| **total** | | **about $1.35** |

Within the monthly budget (decision 0030).

---

## 9. The decision S2.4 takes

| # | decision |
|---|---|
| 0073 | The agent's default model is GPT-6 Luna, behind a shape probe and a 1% format gate on development, at a reasoning level set to `medium` and recorded; the ceiling and arm B are re-measured on held-out with it; replaces 0031 item 1 |

---

## 10. Build order

1. The single default-model constant, the reasoning-level constant and its record in the run
   spec, and the new prices (no model call).
2. Failures by reason in the report, with its test (no model call).
3. The shape probe (§3.1). *Stop point:* the shape is rejected, or content comes back empty.
4. The gate run on `dev-400` (§3.2). *Stop point:* over 1% format failures, or a clearly worse
   score for Andy's decision.
5. The switch (§4).
6. The ceiling and arm B on `heldout-400`, once each, at one commit (§5).
7. `CLAUDE.md`'s model and bars sections appended; the As-built record; the plan deleted.

---

## 11. Done means

1. The shape probe's result and the gate run are published in `docs/results/s24-gate-dev.txt`,
   with failures by reason.
2. Either: the default is GPT-6 Luna, `docs/results/s24-bars.txt` holds the four comparisons,
   and the ledger holds both held-out rows; or: the gate failed, 0073 records why, and held-out
   was not touched.
3. `CLAUDE.md` names the default model and shows the bars on both models, GPT-5.6 Luna's marked
   as history.
4. Tests and CI green; `scripts/check_docs.py` passes; the As-built record is appended and the
   plan deleted (0017).

---

## 12. Not in S2.4

- Any change to the evidence, the guard, the prompts or the scoring.
- The model axis proper — which model gains most from the docket — after S3 (0031).
- A different reasoning level, unless §3.1 forces one, and then only with Andy's decision. The
  comparison of levels goes with the model axis after S3 (§4.1).
- The arm A ablation on GPT-6 Luna: it shows what start facts alone give, which is not what S2.6
  or S3 is compared against.

---

## 13. Risks and open questions

| risk | how it is handled |
|---|---|
| GPT-6 Luna rejects the stage-2 shape or returns empty content | The shape probe runs first and costs under a cent |
| Its format failure rate is higher on held-out than on development | Failures by reason are published on every run; a format failure is never counted as a wrong answer |
| It scores clearly worse | Recorded; Andy decides before held-out |
| The provider changes the model behind the same id, or its price | The model id and the price's read date are recorded with every run |
| The model is a day old when chosen | The gate is on our task, not on reputation; the old model stays priced and runnable |

---

## As built

*Closed 2026-09-25 in pull request #11.*

### Delivered

- **One named default.** `sources.DEFAULT_MODEL` is `openai/gpt-6-luna` and
  `sources.DEFAULT_REASONING_EFFORT` is `medium`. `ModelSettings` and `RunSpec` read them; no other
  module names a Luna model (`tests/test_sources_settings.py::test_no_module_but_sources_names_a_luna_model`).
  GPT-6 Luna's standard and batch prices are in `sources.py`; GPT-5.6 Luna's stay, so its runs
  still price.
- **The reasoning level is stated and recorded.** `ModelSettings.reasoning_effort` is sent as
  `reasoning: {"effort": ...}` only when set, so the judge's requests are unchanged. Every agent
  call states `medium`; `spec.json`, `RunRecord.reasoning_effort` and the report header record it.
  A run from before S2.4 reads as "provider default".
- **The report.** `ntsb-eval report` prints `failures by reason:` (counts only, never a case
  number) and labels a comparison across models or reasoning levels with both commits
  (`report.failure_summary`, `report.comparison_heading`).
- **Recovery from a lost batch.** `BatchClient.wait` raises `BatchNotFoundError` once its 404
  grace ends. On a resume, a re-used batch the provider no longer has is marked `lost` in
  `batches.jsonl`; every batch recorded after it is marked `superseded`, because its requests were
  built from the lost batch's replies; both are resubmitted fresh. A batch submitted fresh in the
  same run still stops the run. `recorded_batches` skips lost and superseded ids.
- **Make targets.** `s24-probe`, `s24-gate`, `s24-bars-ceiling`, `s24-bars-b` (one held-out run
  per target).
- **Results.** `docs/results/s24-gate-dev.txt`, `docs/results/s24-bars.txt`,
  `docs/results/s24-armB-gpt56-failures.txt`.

### Done means, with evidence

1. The shape probe's result and the gate run are published with failures by reason — met —
   `docs/results/s24-gate-dev.txt`: both probe runs `failed 0 of 1`, `failures by reason: none`;
   the gate run 0 of 401 format failures, top-1 +0.7% [−2.0%, +3.7%] against GPT-5.6 Luna.
2. The default is GPT-6 Luna, `s24-bars.txt` holds the four comparisons, and the ledger holds both
   held-out rows — met — `sources.DEFAULT_MODEL`; `docs/results/s24-bars.txt` (arm B against the
   ceiling, arm B and the ceiling each against GPT-5.6 Luna, and the baseline floor line);
   `docs/results/heldout-ledger.md` holds the ceiling row, the arm B row, and a hand-written row for
   the aborted arm B run (Departures below).
3. `CLAUDE.md` names the default model and shows the bars on both models, GPT-5.6 Luna's marked as
   history — met — `CLAUDE.md` sections "Model access" and "Eval bars to beat (held-out split)".
4. Tests and CI green; `scripts/check_docs.py` passes; the As-built record appended and the plan
   deleted — met — CI on pull request #11 green (audit, lint, test); `make check` 747 tests,
   coverage 97.9%; this pull request's close-out commit; `uv run python -m scripts.check_docs`
   clean.

### Departures from this specification

- **The shape probe runs through `ntsb-eval run --limit 1`**, not a separate script, so it tests
  the exact code the gate and the bars use. As a result no new reply fixtures were recorded
  (spec §7): the probe showed no reply shape the existing fixtures do not cover.
- **Spec §5's four comparisons are three `report` invocations**; the fourth, against the no-model
  baseline, is the `Baseline floor` line every `heldout-400` report prints.
- **Paid steps from a worktree need `NTSB_DATA_DIR`** pointed at the main checkout's `data/`. The
  first probe attempt stopped before any model call because the worktree's `data/` is empty. This
  is now in `CLAUDE.md`.
- **The gate passed its rule, but finding recall@10 on `dev-400` was −1.1% [−2.2%, −0.2%]**
  against GPT-5.6 Luna, outside the gate. Andy chose to switch and read findings on held-out arm B,
  which showed +1.4% [−0.8%, +3.6%] (recorded in 0073).
- **Thirteen tests were pinned to GPT-5.6 Luna after the switch**: 10 encoded its price and 3 its
  model id as a literal. All keep testing what they were written to test; no expected number was
  changed.
- **Two held-out runs cannot share one `make` recipe.** The first run's ledger row leaves the tree
  dirty and the held-out guard refused the second before any model call. `s24-bars` was split into
  `s24-bars-ceiling` and `s24-bars-b`. The two runs sit on commits that differ only by that ledger
  row.
- **A held-out arm B run aborted and was run again.** Run `20260924T075506-36bcd22-heldout-400-B`
  completed stage 1, but its stage-1 retry batch (`batch-1790239332-REtOQmoQUfUloC44CBt5`) queued at
  OpenRouter for over 10 hours and then returned 404, while OpenRouter's dashboard still showed it
  as processing. Nothing was scored. Andy chose a fresh run over a salvage. The aborted run cost
  $0.58, is entered in the held-out ledger by hand from its run record, and makes the fresh run
  the second held-out touch for arm B in this stage. The resume recovery in "Delivered" was built
  so that this no longer needs a fresh run. If the lost batch later completes, OpenRouter may bill
  it; that amount is not in any run record.
- **Held-out arm B on GPT-6 Luna failed 24 cases on the reply format**, against 2 for GPT-5.6
  Luna (`docs/results/s24-armB-gpt56-failures.txt`). By an ad-hoc tally, 19 are truncated or empty
  replies and 5 give probabilities summing above 1. The likely cause of the truncation is that
  reasoning tokens count against the 2,000-token reply limit when a docket fills the prompt. The
  gate could not see this: it runs the ceiling, which has no docket. The bar is therefore measured
  on 336 scored cases. Andy's decision: S2.4 closes as it stands, and S2.6 confirms the cause on
  `dev-400` and sets the reply budget as a decision before its held-out runs.

### Decisions taken during the stage

- [0073](../decisions/0073-the-default-model-is-gpt-6-luna-behind-a-gate.md) — the default model is
  GPT-6 Luna behind a shape probe and a format gate, at a reasoning level set and recorded;
  replaces 0031 item 1. Its appended notes record the gate result and the held-out outcome.

**Known limits carried forward** (from the final review; none changes a published number):

- The cost of a lost or superseded batch is not added to the resumed run's record, so the monthly
  total can understate money spent.
- A recorded batch that ended `failed` or `expired` still cannot be resumed; S2.6 fixes this
  before its held-out runs.
- `max_output_tokens` is not recorded in `spec.json`; S2.6 records it if it changes the reply
  budget.

### Implementation record

- Pull request: #11 (https://github.com/floyda/ntsb-probable-cause/pull/11)
- Plan, at its last commit: https://github.com/floyda/ntsb-probable-cause/blob/377a634bc99fdaf5bee12ea26d845b5bb43f8473/docs/plans/2026-09-23-s24-model-switch.md
- Commits: 83c330e..23bdeb0
- Model spend, from the six S2.4 run records: $2.16 (probe $0.0018, gate $0.22, held-out ceiling
  $0.24, aborted arm B $0.58, arm B $1.13), against the spec's estimate of $1.35.
- Release: v0.4.0 (tag created by Andy after the merge; decision 0018)

---

## Glossary

- **Default model**: the model every run uses unless told otherwise.
- **Gate**: a check that must pass before the next step is allowed to run.
- **Reasoning level**: how much a model thinks before answering; billed as output.
- **Shape probe**: a one-case test that the model accepts the exact form of our requests.
- **Stage 1 / stage 2**: the two turns of each case: a hypothesis, then a refinement that sends
  the model's own first reply back to it.
- **Format failure**: a reply that does not parse as the reply schema, after one retry.
- **Ceiling**: every tool except the docket, one answer.
- **Arm B**: every tool including the docket, one answer.
- **Bar**: the held-out score the next stage must beat.
- **Paired comparison**: two runs compared on the same cases, with an interval.
- **Held-out ledger**: the committed list of every run that touched a held-out sample.
- **Baseline**: the no-model score, 17.7% top-1, from counting past cases.
