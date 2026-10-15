# Coding memory pilot: the registration (decisions 0200 to 0207)

This file fixes the pilot's samples, conditions, models, checks, runs and stop rule **before any
paid pilot run**, so that none of them can be chosen after a result is seen (decision 0204 item
6). Andy reads and signs it first. Design: `docs/specs/2026-10-08-coding-memory-design.md`
(approved 2026-10-14). Plan: `docs/plans/2026-10-14-coding-memory-pilot.md`, Task 16.

**What committing this file does.** In code, it unlocks one thing: the memory condition of the
coding test. `scripts/memory_coding_test.py` refuses `tools --snapshot` until this file is
committed (`refuse_memory_without_registration`). The tables and counts conditions, the learner
and the shape probe are not gated in code. They are gated by this file's rule: **no paid pilot
step runs before Andy signs below.** Nothing here touches Ellery version 1, S4's nights or the
board.

## 1. The question

Does a short file of written coding lessons, learned from how the NTSB coded earlier development
cases, help GPT-6 Luna code a case **better than the counts the agent's coding tools already
give**?

Why this comparison: S3's fixed coding-tools step already adds occurrence top-1 +6.8% and finding
recall@10 +4.7% to S2.7's answer on `dev-400`
(`docs/results/s3-armb-tools-vs-s27-armb-answer-dev.txt`). A memory is worth having only if it
beats those counts, not merely if it beats nothing (decision 0204, Why 2).

The pilot learns two periods, the event years 2009 and then 2010, and measures after each. It
answers one thing first: does the score move at all?

## 2. The samples

| sample | size | who reads it | why |
|---|---|---|---|
| learning part, event year 2009 | 1,201 cases | the learner only | the first period the learner studies |
| learning part, event year 2010 | 1,169 cases | the learner only | the second period |
| `dev-steer-400` (the steering slice) | 401 cases | the coding test only | measures each snapshot; never learned from |

- **The learning part** is S3's statistics pool less the steering slice: the development split,
  classes C, F and L, less `dev-400`, `dev-seal-400`, `dev-seal-s3-400` and `dev-steer-400`. It
  holds 11,689 cases (6,710 in 2009 to 2014, 4,979 in 2015 to 2019;
  `docs/results/mem-coding-stats.txt`). The pilot reads only its 2009 and 2010 cases. The two
  sizes above were counted by `memory.pool.learning_part` on 2026-10-15; the propose step prints
  its chunk count for each period (cases in groups of up to 30), which will confirm them.
- **What the learner reads** of each case: its probable-cause sentence, its occurrence codes in
  order and its finding codes, with their labels. Never evidence, synthesis or a docket (decision
  0200 item 1).
- **The steering slice `dev-steer-400`** was drawn once, on 2026-10-14, by `make mem-draw-steer`
  (`samples.draw`, seed 20261014, stratified by fatal and non-fatal and by class). It holds 401
  cases, not 400: the quota rounding the other 400-case samples share. The redacted record
  fixtures were left out of this draw only, because the seed's draw held one (plan Deviations,
  Task 1). Its event years run from 2009 to 2019. Its case list is
  `tests/fixtures/eval/dev_steer_400_ids.csv` (case id and event date only).
- **Why the slice is kept apart.** The memory is revised again and again. Anything it is scored
  against often, it slowly learns. So the learner never sees the slice, and the `mem` statistics
  file (`scoring/tables/coding_stats_mem.json`) is built without it: a case must not be scored
  with counts that include its own verdict (decision 0203). The guard refuses the slice with S3's
  statistics, which do include it (decision 0206).
- **Never read by the pilot:** `dev-400`, `dev-seal-400`, `dev-seal-s3-400`, any held-out case,
  any open-split case and any live case (decision 0200 item 3). The learner's client refuses a
  call that names any case outside the learning part, before it is sent.

## 3. The three conditions, and the commands that run each

The **coding test** gives GPT-6 Luna the NTSB's own probable-cause sentence for one steering-slice
case and asks for the answer in the agent's format: up to three occurrence guesses, then findings
in the two stages of decision 0025 (decision 0204 item 1). The payload is
`{"ntsb_probable_cause": <the sentence>}` and nothing else, built by `Payload.for_coding_test`,
the declared exception to the request boundary (decision 0205). Why: the reading of the evidence
is taken out, so a change in score is the coding's.

| condition | what the model is given | command | run id ends in |
|---|---|---|---|
| **tables** | the code tables, arm B's answer text and the two guidance files; stage 1, then the refinement of the finding items | `make mem-coding-answer REPEAT=a`, then `REPEAT=b` | `-dev-steer-400-mem-tables-a` / `-b` |
| **counts** | arm B's fixed coding-tools post-pass (`agent.armb.FixedToolsLoop`, unchanged) over tables run a's answers, with the tools counting in the `mem` statistics | `make mem-coding-tools SOURCE=<tables a> REPEAT=a`, then `REPEAT=b` | `-counts-a` / `-counts-b` |
| **memory** | the same post-pass over the same answers, with one checked snapshot added to the system text under the heading "Coding memory (lessons learned from earlier NTSB cases)" | `make mem-coding-tools SOURCE=<tables a> SNAPSHOT=pilot-2009`, then `SNAPSHOT=pilot-2010` | `-memory-pilot-2009` / `-memory-pilot-2010` |

- **Every condition** uses the guidance files `r3-loc-stall` and `r6-aircraft-control`, the
  `mem` statistics, a reply budget of 8,000 tokens and a per-case cap of $0.05.
- **`suggest_codes` is never called** in the counts or memory conditions. The coding test has no
  phase-of-flight evidence, so the post-pass is given no group. Both conditions omit it, so the
  comparison stays fair (`spec.json` records `"suggest_codes": "omitted: no phase-of-flight
  evidence"`).
- **Why counts and memory both start from tables run a.** The two counts runs and both memory
  runs re-code the same first answers. So a memory run differs from counts run a in one thing
  only: the snapshot.
- **Where the memory is read.** The snapshot is in the system text of the post-pass's calls,
  which choose the occurrence codes and the finding categories. The last step, which refines the
  finding items and modifiers, does not see it, in the counts or the memory condition alike, as in
  arm B. Lessons predict first occurrence codes and finding categories only, so this matches what
  they say; it may understate any effect on finding items.
- **The memory condition runs once per snapshot**, not twice. The two counts runs give the noise
  (§7); the memory run is read against it.
- An interrupted run is continued with `RESUME=<run id>` and the same arguments, from the same
  commit (so nothing is committed between a run that stopped and its resume). The script checks
  the folder's `spec.json` against them and never sends an answered call again.

## 4. The models, efforts and prices

| job | model id | effort | how sent | max output tokens |
|---|---|---|---|---|
| propose lessons (one call per group of up to 30 cases) | `claude-sonnet-5-5` | `high` | one at a time, standard price | 16,000 |
| revise a lesson | `claude-sonnet-5-5` | `high` | one at a time, standard price | 16,000 |
| agreement reference | `claude-sonnet-5-5` | `high` | batch | 4,000 |
| apply lessons to cases (the applier) | `claude-haiku-5-5` | `low`; `medium` on the one retry; else Sonnet at `high` (§5) | batch | 2,048 (Haiku); 4,000 (Sonnet) |
| the coding test | `openai/gpt-6-luna` through OpenRouter | reasoning `medium` | batch | 8,000 |

- **Every learner call states its effort**, never relying on a model's default, and every spend
  row records it. Thinking stays at the model's default. Output is structured by a JSON schema
  (`output_config.format`). The system text is marked for prompt caching, because the memory
  repeats from call to call (decisions 0202 item 2, 0207).
- **No refusal fallback.** A learner call sends none. A refused call is a failed call, recorded
  with its `stop_details` category, so every lesson keeps the model that wrote it. A refusal or a
  reply cut off at its token limit is a failed reply, never raised (decision 0207 item 4).
- **Opus 5.5 is not used** in the pilot (decision 0202 item 2).
- **Prices per million tokens** (`sources.py`; Anthropic's pricing page read 2026-10-08, and
  OpenRouter's models API read 2026-09-22):

  | model | standard input / output | batch input / output | cache write / read, standard |
  |---|---|---|---|
  | `claude-sonnet-5-5` | $2.00 / $10.00 | $1.00 / $5.00 | $2.50 / $0.10 |
  | `claude-haiku-5-5` (prompts up to 100,000 tokens) | $0.10 / $0.50 | $0.05 / $0.25 | $0.125 / $0.01 |
  | `openai/gpt-6-luna` | $0.10 / $0.50 | $0.05 / $0.25 | — |

  The Batch API halves every Claude rate, cache rates included. The client refuses a Haiku prompt
  over 100,000 estimated tokens, where Haiku's price rises. One source differs: the claude-api
  skill's model summary (read 2026-10-15) gives Sonnet 5.5 cache reads as $0.20, not $0.10. The
  pricing page's figure is used, as the primary source; it touches only cached-prompt reads
  (plan Deviations, Task 4).
- **Why two transports.** Learning calls are small and are paid from Andy's monthly plan credit,
  which cannot be spent through OpenRouter. The coding test stays on the product's model and
  transport, so the memory is measured on the model that would use it (decisions 0202, 0009).
- **Keys.** Every paid `mem-` target runs through `scripts/with_pass_keys.sh`, which reads
  `ANTHROPIC_API_KEY` from `pass` at `api/anthropic` and `OPENROUTER_API_KEY` at `api/openrouter`
  (the development key), and prints neither. S4's live key is never used (decision 0202 item 3).

## 5. The agreement check

**Why it exists.** The apply step runs once per case and dominates the learner's call count, but
it asks the simplest question: which lessons cover this case? Haiku is far cheaper than Sonnet.
Its answers enter every support count, so it must first be shown to agree with Sonnet (decision
0204 item 3).

- **When:** once, on the 2009 draft (after `propose`, before `finish`), by `make mem-agreement
  RUN=<the 2009 learner run id>`.
- **The sample:** 100 learning-part cases of 2009, drawn by `random.Random(20261014).sample`.
- **What runs:** Sonnet at `high` (the reference), then Haiku at `low`, on the same cases and
  the same draft. Each decides which lessons apply from the cause sentence alone, never from the
  case's codes. A failed or unreadable reply counts as "no lesson applies", and is counted.
- **The measure:** agreement = case-and-lesson pairs both models mark ÷ pairs either model marks.
- **The bar: at least 90%.** If Haiku at `low` reaches it, Haiku at `low` is the applier. If not,
  Haiku at `medium` is checked once on the same cases by the same bar. If it misses again, Sonnet
  at `high` applies.
- **The cost of Sonnet applying.** A Sonnet apply reply is limited to 4,000 tokens (an apply
  answer is a short list of lesson ids; the limit leaves room for its thinking). A reply cut off
  there counts as "no lesson applies" and is counted. If `finish` projects a cost past the $90
  learning line with Sonnet as the applier, it refuses before any call, the pilot stops there, and
  Andy decides by record whether to raise the line or stop.
- **Why only the marked pairs.** Most answers are "does not apply". Counting them would make
  almost any model look in agreement. The 90% itself is judgement, not a measurement (decision
  0204, Why 4).
- **If neither model marks any pair**, no lesson covered any case. The check writes that and stops,
  and the pilot cannot proceed.
- **The result** is `docs/results/memory-agreement-dev.txt`: counts only, ending in the line
  `chosen applier: <name>`. It is committed before `finish`, which refuses to run otherwise. The
  same applier serves both periods.

## 6. The snapshots

A **snapshot** is the memory file at the end of a period, saved by `make mem-learn-finish`:

- **`pilot-2009`**: learned from 2009, starting from an empty memory.
- **`pilot-2010`**: learned from 2010, starting from `pilot-2009`. Its `finish` step applies and
  counts over every period so far (2009 and 2010 together, 2,370 cases).

`finish` first drops any lesson that would fail the copying or withheld-text check below (it
prints the lesson's id and which check, never its words), so a snapshot that reaches `make
mem-check` can pass it. It then applies the lessons, counts each one's support (the cases it
applies to, and how many agree), sends back to Sonnet each lesson that disagrees with more cases
than it agrees with, retires lessons that apply to no case, and fills the memory in order of
support up to **6,000 estimated tokens** (characters ÷ 4). The fill stops at the first lesson that
does not fit: that lesson and every weaker one are pushed out, so a lesson enters a full memory
only by beating the weakest. The snapshot records the lessons pushed out and their support
(decision 0201 item 5). Every number in a lesson comes from the counting step, never from the
model (rule 3).

**The three checks**, run by `make mem-check SNAPSHOT=<name>` before any use (decision 0201 item 2):

1. **Identifier check:** no digit, and no capitalised word that is not on
   `memory/allowed_words.txt`. So no case number, date, place, registration, name or operator.
2. **Withheld-text check:** no lesson sentence of 30 characters or more appears in any
   development case's factual narrative, analysis narrative or probable cause.
3. **Copying check:** no run of 8 or more words is shared with any development case's
   probable-cause sentence. Eight words allows common phrases ("the pilot's failure to
   maintain") and catches a quoted cause.

**The stamp.** When all three pass, the check writes `<name>.stamp.json` beside the snapshot: the
snapshot's name and SHA-256, how many texts each check compared against, the date and the
commit. The snapshot and its stamp are committed together. Continuous integration re-runs the
identifier check and refuses a snapshot whose stamp does not match it. At run time, the coding
test and the next period's `propose` refuse a snapshot without a matching stamp. So a snapshot
edited after its check cannot be used.

**The reading uses the last snapshot, `pilot-2010`.** The memory run on `pilot-2009` is a point on
the curve and is reported, but it does not decide.

## 7. The noise

**noise = counts(b) − counts(a), on each measure**: occurrence top-1, occurrence top-3 and finding
recall@10, as paired point estimates over the same cases.

**Why it matters.** Two identical runs of a model do not give identical answers. Two identical arm
B answer runs once differed by top-1 +4.0% [+0.5%, +7.5%] (`docs/results/s27-round0-dev.txt`). A
memory must move the score by more than a repeat run moves it, or the move could be chance. The
coding test's own noise is measured here, not assumed (design note §6).

The two counts runs re-code the same first answers (tables run a), as the memory runs do, so the
noise is the variation of exactly the step the memory changes. The tables pair's difference,
tables(b) − tables(a), is printed but does not decide.

**A property of the rule to know before signing.** The noise is one pair of runs, so it is itself
an estimate. A small noise lowers the finding bar, which makes the rule easier to pass on findings,
and narrows the allowed fall on top-1 and top-3, which makes it easier to fail there. A noise of
zero on top-1 means any fall at all on top-1 fails.

## 8. The stop rule, word for word

Decision 0204 item 5, as Andy decided it on 2026-10-14: *the pilot passes only if the memory
condition beats the counts condition on finding recall@10 by more than the noise, and is not worse
beyond the noise on occurrence top-1 or top-3. Otherwise it stops and is reported as it stands.
Top-1 and top-3 are reported either way; a gain there without a finding gain is "not passed", and
any override is Andy's, in a record.*

The registered rule is the docstring of `stop_rule` in `scripts/memory_pilot_result.py`, word for
word:

```text
Decision 0204 item 5, as registered in docs/rounds/memory-pilot.md.

``memory`` is memory minus counts(a); ``noise`` is counts(b) minus counts(a). Pass only if the
finding gain exceeds the noise on findings, and neither occurrence measure falls by more than
its own noise.
```

**The exact inequalities.** Let M = memory(`pilot-2010`) − counts(a) and N = counts(b) −
counts(a), each a paired point estimate as a fraction. The pilot **passes** only if all three hold:

- M(finding recall@10) **>** |N(finding recall@10)| (strictly greater: equal is not beyond);
- M(top-1) **≥** −|N(top-1)|;
- M(top-3) **≥** −|N(top-3)|.

In the code, the pilot fails on findings when `not memory.recall10 > abs(noise.recall10)`, and on
top-1 or top-3 when `memory.top1 < -abs(noise.top1)` or `memory.top3 < -abs(noise.top3)`. Only
the size of the noise counts, not its sign. The rule reads point estimates; the 95% intervals are
printed beside them and do not decide. Every reason for failing is printed, one `not passed:` line
each, before the verdict.

**Why findings decide.** The NTSB codes findings most consistently: identical cause sentences agree
on flagged findings at recall@10 74.1%, against 37.5% on the first occurrence code
(`docs/results/s3-finding-consistency-dev.txt`, `s3-coding-consistency-dev.txt`). So findings are
the most learnable, and they are the live board's headline (decision 0029). One named measure is
harder to pass by luck than any one of three (decision 0204, Why 3).

**A worked example. The numbers are invented**, in percentage points. Say the noise is N: top-1
−1.2, top-3 +0.8, finding recall@10 +1.5. The bars are then: findings above +1.5; top-1 not below
−1.2; top-3 not below −0.8.

| memory − counts(a) | findings > 1.5? | top-1 ≥ −1.2? | top-3 ≥ −0.8? | verdict |
|---|---|---|---|---|
| findings +2.4, top-1 −0.9, top-3 +0.3 | yes | yes | yes | **passed** |
| findings +2.4, top-1 −1.5, top-3 +0.3 | yes | no | yes | **not passed**: top-1 falls beyond its noise |
| findings +1.5, top-1 +4.0, top-3 +5.0 | no (equal) | yes | yes | **not passed**: no finding gain beyond the noise, whatever top-1 does |

## 9. Failed cases count as wrong

A case that fails in a run scores 0 there, as in S3's rounds (decision 0136): occurrence top-1 and
top-3 are wrong, and finding recall@10 is 0.0 where the NTSB's verdict flags findings in the cause
(left out of recall where it flags none). This holds for every run: tables, counts and memory.

The ways a coding-test case can fail: the case has no probable-cause sentence (`no cause`); tables
run a gave no answer, so the post-pass has nothing to start from (`source failed`, in every counts
and memory run alike); a call's estimate passes the $0.05 cap (`cap`); or a reply fails its schema
twice. **Why:** leaving failures out would let a condition that fails more often look better than
it is.

The reading refuses runs that cover different sets of cases, a run on another sample, a run of
another condition than expected, and a memory run with no snapshot named.

## 10. The order of runs

Every step needs a clean tree; the scripts refuse a dirty one, so every run names a clean commit.
Commit between steps. Anything unexpected is logged under the plan's Deviations as it happens. The
steps are plan Task 16.

0. **First:** everything under "Before signing" (§15) is done, Andy signs, and this file is
   committed. Before the first OpenRouter run, the S4 session is told that the side track will
   spend about $2–3 of the shared $40 development line, and any objection is waited for.
1. **The two tables runs.** `make mem-spend EST=0.80`; then `make mem-coding-answer REPEAT=a` and
   `make mem-coding-answer REPEAT=b`.
2. **The two counts runs**, over tables run a. `make mem-spend EST=0.80`; then
   `make mem-coding-tools SOURCE=<tables a> REPEAT=a` and `REPEAT=b`.
3. **Learn 2009.** `make mem-learn-propose PERIOD=2009 FROM=empty TO=pilot-2009`; then
   `make mem-agreement RUN=<run id>`; commit `docs/results/memory-agreement-dev.txt`; then
   `make mem-learn-finish RUN=<run id> TO=pilot-2009`; `make mem-check SNAPSHOT=pilot-2009`;
   `uv run pytest tests/test_memory_snapshots.py` passes; commit the snapshot and its stamp.
4. **The memory condition after 2009.** `make mem-spend EST=0.40`;
   `make mem-coding-tools SOURCE=<tables a> SNAPSHOT=pilot-2009`.
5. **Learn 2010.** `make mem-learn-propose PERIOD=2010 FROM=pilot-2009 TO=pilot-2010`;
   `make mem-learn-finish RUN=<run id> TO=pilot-2010` (the applier already chosen);
   `make mem-check SNAPSHOT=pilot-2010`; commit the snapshot and its stamp.
6. **The memory condition after 2010.** `make mem-spend EST=0.40`;
   `make mem-coding-tools SOURCE=<tables a> SNAPSHOT=pilot-2010`.
7. **The reading**, free: `make mem-pilot-result TA=<tables a> TB=<tables b> CA=<counts a>
   CB=<counts b> MEM="<memory 2009 run> <memory 2010 run>" LEARN="<2009 learner run> <2010
   learner run>"`; commit `docs/results/memory-pilot-dev.txt`.
8. **The boundaries held.** `make check` and `make s33-continuity` pass (`+t` unchanged);
   `uv run python -m scripts.stage_spend --stage mem` and the learning line's month total go in the
   results commit message.

**Every paid step checks its line first:**

- **Learner steps** check the month's learning line (`budget.check_learning_budget`) before each
  phase: propose, each apply batch and revise. Each phase prints its projection first: every
  planned call priced at its estimated input and its full output limit, so the projection is high
  on purpose.
- **Coding-test steps:** the `make` recipe first runs `scripts.stage_spend --stage mem --estimate
  4.01` (401 cases × $0.01), which refuses the run if the side track's spend plus $4.01 would pass
  its $10 line. So a coding test is refused once more than $5.99 has been spent on that line. The
  script then reserves the same $4.01 under the $40 monthly guard before any call. The plan's
  `make mem-spend EST=…` before each step prints the line's state with that step's estimate.

## 11. Spend lines and expected costs

| spend | paid from | rows of kind | line | hard stop |
|---|---|---|---|---|
| learner calls (Claude) | Andy's monthly plan credit ($100) | `learning` | `NTSB_LEARNING_MONTHLY_BUDGET_USD`, default **$90** a month; never counted by the $40 guard | the Claude Console workspace's spend limit |
| coding tests (OpenRouter) | the project's development key | `coding-test` | the **$40** monthly development guard (shared with any S4 development run), and the side track's **$10** line, `scripts.stage_spend --stage mem` (commits on `coding-memory*` branches holding `938bd83`) | the guard's refusal |

**Why two lines.** Credit spend is not the project's money; counting it against the $40 line would
crowd out S4 development runs. The $10 line bounds the coding tests alone, as S3.3's line bounded
the live runs (decision 0207). Credit spend is recorded at its real price, never as zero.

**Expected costs. These are estimates**, from the published prices and the token sizes in the
design note (plan Task 16). The results file and the commit message report what was spent.

- **Learner:** about **$10–20 of plan credit** for the two periods. Propose dominates: one Sonnet
  call per group of up to 30 cases, so 41 calls for 2009 and 39 for 2010, at the standard price. The agreement check and the apply batches are
  smaller, at batch prices.
- **Coding tests:** about **$2–3 on OpenRouter** for the six runs (two tables, two counts, two
  memory). The plan's per-step estimates are $0.80 for each pair of runs and $0.40 for each memory
  run.
- **Shape probe:** run on 2026-10-15; $0.0029 of plan credit (`docs/results/memory-shape-probe.txt`).

## 12. What is published either way

`docs/results/memory-pilot-dev.txt` is committed whatever it says. It holds counts only: no case
number, no cause sentence, no lesson text.

- **The verdict**, last line: `stop rule on the last memory run (memory-2): PASS` or `FAIL`,
  published as **passed** or **not passed**, with every `not passed:` reason before it.
- **Per run:** occurrence top-1 and top-3 (Wilson intervals), finding recall@10 (bootstrap
  interval), each with its `n`, and the failed cases.
- **Paired differences:** tables(b) − tables(a), the noise, and each memory run − counts(a), on all
  three measures with intervals. **Top-1 and top-3 are reported either way**, pass or not.
- **The curve:** tables(a), counts(a), then the memory run after each period, on all three
  measures.
- **Each snapshot's lessons kept and pushed out**, and the agreement file's last line (the chosen
  applier).
- **The learner's refusals by category** (failed replies whose stop reason is `refusal`, by
  `stop_details` category), so a refusal is counted, not hidden.

Also committed: the agreement result, the shape probe's result, and both snapshots with their
stamps. Then the result is written into the design note and `CLAUDE.md` in plain words (plan Task
17).

**After the result.** If the pilot passes, the full pass (to 2019), the coding test on `dev-400`
and the transfer check each get their own registration first (decision 0204 item 6). If it does
not pass, it stops and is reported as it stands; Andy then decides whether the code stays as the
record of how the result was produced, or a record removes it. A gain on top-1 or top-3 without a
finding gain is "not passed"; any override is Andy's, made openly in a decision record.

## 13. What had been seen when this was written

- **No pilot run had been made.** No learner call and no coding-test call. No lesson exists, and
  no coding-test score on the steering slice exists. The shape probe ran on 2026-10-15 on invented
  text only; it read no case.
- **Seen:** the steering slice's case list (case ids and event dates); the `mem` statistics file
  and its counts (`docs/results/mem-coding-stats.txt`); the learning part's sizes for 2009 and
  2010.
- **The measurements behind the design**, all on development cases: the finding and coding
  consistency figures (§8), the coding-tools step's gain (§1), and every earlier `dev-400` reading
  in S2.7 and S3.
- **Chosen by judgement, not measured:** the 90% agreement bar (decision 0204, Why 4), the
  6,000-token cap (decision 0201 item 5), one event year per period, and the stop rule itself
  (Andy, 2026-10-14).
- **What the pilot cannot rule out.** GPT-6 Luna and the learner's models were very likely trained
  on public NTSB reports. The pilot can show a memory improves on the same model without one. It
  cannot show the memory works from nothing (design note §5).

## 14. Prediction (optional)

None is required. Andy may write a prediction here before signing, or delete this section. If one
is written, the close-out (plan Task 17) states whether it was met, from the numbers in the
results file.

None written (Andy, 2026-10-15).

## 15. Before signing

**Done on 2026-10-15:**

- **The shape probe ran and every check passed** (`docs/results/memory-shape-probe.txt`, commit
  0a36711, made at 249aacb). Both model ids, `claude-sonnet-5-5` and `claude-haiku-5-5`, can be
  retrieved. One Sonnet call's reply parses as the learner's propose reply; both replies of a
  two-request Haiku batch parse as the apply reply. Every reply stopped at `end_turn`, and none
  reached its token limit. So the Claude wire shapes the learner uses (the effort and schema in
  `output_config`, the usage counts) are confirmed against the real API, not only the SDK's
  source (rule 2). No reply was refused, so the refusal category in `stop_details` was not seen;
  it stays confirmed by the SDK's source only. The batch took 425 seconds. Cost: $0.0029 of plan
  credit.
- **The Anthropic key is in `pass`** at `api/anthropic`.
- **The tree is clean.** `.claude/launch.json` was removed (Andy, 2026-10-15).
- **The Claude Console spend limit is set** on the workspace that holds the key (Andy,
  2026-10-15). Decisions 0202 item 6 and 0207 item 2 make that limit the hard stop for credit
  spend.

**Outstanding:**

1. **The S4 session is told before the first OpenRouter run** that the side track will spend about
   $2–3 of the shared $40 development line, and any objection is waited for.

## Glossary

- **Agreement check:** Haiku and Sonnet decide which lessons apply on the same 100 cases; Haiku is
  used only if it agrees on at least 90% of the pairs either model marks.
- **Applier:** the model and effort chosen by the agreement check to decide which lessons apply to
  each case.
- **Batch:** requests sent together and answered later, at half the standard price.
- **Coding memory:** a short file of written lessons about how the NTSB codes accidents.
- **Coding test:** GPT-6 Luna coding a case from the NTSB's own probable-cause sentence; it
  measures coding alone, with the reading of the evidence taken out.
- **Condition:** what the coding test gives the model: tables, counts, or memory.
- **Counts:** the coding tools' output (how often the NTSB used each code), from the `mem`
  statistics.
- **Curve:** the coding test's scores after each period learned, beside the counts condition.
- **Effort:** the setting that controls how much a Claude model thinks before it answers.
- **Failed case:** a case with no usable answer in a run; it counts as wrong.
- **Finding recall@10:** the share of the NTSB's flagged findings found among the answer's first
  ten finding codes.
- **Flagged finding:** a finding the NTSB names in its probable cause.
- **Identifier check, withheld-text check, copying check:** the three checks a snapshot passes
  before use (§6).
- **Learner:** the Claude models, and the scripts around them, that write, test and revise the
  lessons. It never answers a case.
- **Learning part:** the pool cases the learner may read: S3's statistics pool less the steering
  slice.
- **Lesson:** one statement in the memory, with its kind, its scope, what it predicts and its
  counted support.
- **Noise:** counts(b) − counts(a): how much a repeat run moves each measure.
- **Paired difference:** one run's score minus another's on the same cases.
- **Period:** one event year of learning-part cases, learned together.
- **Plan credit:** the monthly Claude API credit included with Andy's Claude plan; it expires at the
  end of each billing cycle.
- **Point estimate:** the measured difference itself, without its interval.
- **Points (percentage points):** the difference between two percentages, for example 27.0% −
  25.5% = +1.5 points.
- **Post-pass:** arm B's fixed step after the first answer: the coding tools in a fixed order,
  then one more answer.
- **Refusal:** a reply in which the model declines to answer; recorded as a failed reply with its
  category.
- **Shape probe:** one small paid call of each kind, to record the real request and reply shapes
  before any real run.
- **Snapshot:** the memory file at the end of a period (`pilot-2009`, `pilot-2010`).
- **Spend line:** a limit in code on what a kind of spend may total; a step that would pass it is
  refused.
- **Stamp:** the record the local checks write beside a snapshot, holding its hash; a snapshot
  that no longer matches its stamp cannot be used.
- **Steering slice (`dev-steer-400`):** 401 development cases kept back to measure the memory; the
  learner never reads them.
- **Stop rule:** the registered rule that decides whether the pilot passed (§8).
- **Top-1 / top-3:** the NTSB's first occurrence code is the answer's first guess / any of its up
  to three guesses.

Approved by Andy, 2026-10-15
