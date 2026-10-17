# Coding memory cause-lookup test: the registration (decision 0211)

This file fixes the cause-lookup test's steps, its lookup rule and its stop rule **before either
paid step**, so none of them can be chosen after a result is seen. Andy reads and signs it first.
Decision: [0211](../decisions/0211-a-second-lookup-test-chooses-lessons-from-the-cause-sentence.md).
Plan: `docs/plans/2026-10-17-coding-memory-cause-lookup.md`, Task 5. The lookup test's registration,
`docs/rounds/memory-lookup.md`, and the pilot's, `docs/rounds/memory-pilot.md`, still govern
everything this file does not change.

**What committing this file does.** In code, it unlocks two steps: the apply step on the steering
slice (`scripts/memory_cause_apply.py`) and the cause-lookup condition of the coding test
(`tools --lookup K --applies RUN`). Both refuse to run until this file is committed. Nothing here
touches Ellery version 1, S4's nights or the board.

## 1. The question

When each case is shown **the lessons that the apply step names for its cause sentence**, rather
than the lessons whose codes match its first answer, do the lessons help GPT-6 Luna code better
than the counts the coding tools already give?

**Why ask it.** The lookup test (decision 0210) did not pass: finding recall@10 +0.0 points
[−2.2, +2.2] over counts, top-3 +4.5 [+2.0, +7.2] (`docs/results/memory-lookup-dev.txt`). Its
query was the model's own codes, so a lesson could only be chosen if it named a code or category
already in the answer. It could confirm or reorder the answer, but it could rarely bring in a
finding category the answer lacked. This test removes the codes from the choice.

## 2. What stays from the lookup test

Everything but the query: the sample `dev-steer-400`; the source run tables(a),
`20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a`; the coding tools' post-pass; GPT-6 Luna
batch at reasoning `medium`; guidance `r3-loc-stall` and `r6-aircraft-control`; the `mem`
statistics; the $0.05 per-case cap; the snapshot `pilot-2010-recount`; K = 5; the support floor of
10 learning cases; the lessons' place in the system text; and the noise, from the pilot's
counts(a) and counts(b), which are reused, not run again.

## 3. The two paid steps, and the commands

1. **The apply step** (Claude, plan credit):
   `make mem-cause-apply SNAPSHOT=pilot-2010-recount`
2. **The cause lookup** (OpenRouter), a post-pass over tables(a):
   `make mem-coding-cause-lookup SOURCE=20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a SNAPSHOT=pilot-2010-recount K=5 APPLIES=<the apply run's id>`

## 4. The lookup rule

1. **The apply step reads each case's probable-cause sentence alone**, the coding test's input
   (decision 0205); on a live case this would be the agent's own draft. It is the learner's apply
   step, unchanged: its system text (`memory.prompts.SYSTEM_APPLY`), its view of each lesson
   (id, statement and scope, never a code: `lessons.render_for_apply`), its user text
   (`prompts.apply_user`), Sonnet 5.5 at effort high in batches (the applier the agreement test
   chose, `docs/results/memory-agreement-dev.txt`), and 4,000 reply tokens. It sees all 198
   lessons of `pilot-2010-recount`, kept or pushed out, in id order. Its reply is a list of lesson
   ids; ids it invents are dropped, and a failed reply counts as naming none.
2. **No code is read in choosing the lessons**: not the model's first answer, not the NTSB's.
3. **Lessons that may be chosen:** those the apply step named for the case that apply to at least
   10 learning cases.
4. **Order:** highest fit (cases agreeing ÷ cases applied to, by the corrected rule of 0209); then
   most cases applied to; then lesson id.
5. **K = 5:** the first five in that order. A case given none reads the counts condition's text
   unchanged.
6. **Where the lessons go:** after the counts condition's system text, under the memory's heading,
   exactly as in the lookup test.

**Why the same matcher.** A lesson's fit is the share of the learning cases this same apply step
said it covers whose NTSB codes agree with it. Choosing lessons with the same step keeps fit
meaningful for the cases it is applied to.

## 5. The noise

As in the lookup test: **noise = counts(b) − counts(a)**. From `docs/results/memory-lookup-dev.txt`:
top-1 +0.2 points, top-3 +0.7 points, finding recall@10 −0.3 points. It is one pair of runs and it
is small; the counts runs ran on 2026-10-15 and this run will run later, so a change in the
provider's model between those days is not in the noise term.

## 6. The stop rule, word for word

The rule of decisions 0204 and 0210, read on the cause-lookup run. The registered rule is the
docstring of `cause_lookup_rule` in `scripts/memory_cause_lookup_result.py`, word for word:

```text
Decision 0211, as registered in docs/rounds/memory-cause-lookup.md.

``looked`` is cause lookup minus counts(a); ``noise`` is counts(b) minus counts(a). Pass only
if the finding gain exceeds the noise on findings, and neither occurrence measure falls by
more than its own noise: the rule of decisions 0204 and 0210, read on the cause-lookup run.
```

**The exact inequalities.** Let L = cause lookup − counts(a) and N = counts(b) − counts(a), each a
paired point estimate. The test **passes** only if all three hold:

- L(finding recall@10) **>** |N(finding recall@10)|, that is, above **+0.3 points**;
- L(top-1) **≥** −|N(top-1)|, that is, not below **−0.2 points**;
- L(top-3) **≥** −|N(top-3)|, that is, not below **−0.7 points**.

The rule reads point estimates. The 95% intervals are printed beside them and do not decide the
pass, but they decide what is recommended next (§10).

## 7. Failed cases count as wrong

As in the pilot (its §9, decision 0136). A case with no answer in tables(a) fails in every
post-pass alike.

## 8. The order of steps

1. Andy signs; this file is committed.
2. The apply step (§3, step 1). It writes `docs/results/memory-cause-apply-dev.txt`, counts only:
   failed replies, lessons named a case, and how many cases the lookup gives five, fewer or none.
   Commit it. It reads no score, and nothing in it may change §4.
3. `make mem-spend EST=0.40`, then the cause lookup (§3, step 2).
4. `make mem-cause-lookup-result TA=<tables-a> CA=<counts-a> CB=<counts-b> CODE=<the 0210 lookup run> CAUSE=<the cause-lookup run>`,
   then commit `docs/results/memory-cause-lookup-dev.txt`.

**Two refusals are fixed now, in code:** if more than 2% of the apply step's replies fail (more
than 8 of 401), the cause lookup is not run, and the failure is reported as it stands; and a
finished apply run is never resumed, so its failed replies are never retried. The cause lookup
also refuses an apply run made on another sample, snapshot, snapshot file or applier. Every step needs a
clean tree. Anything unexpected goes under the plan's Deviations as it happens.

## 9. Spend and expected cost

- **The apply step** is kind `learning`, on plan credit, under the learner's monthly line of $90,
  of which $33.13 was spent this month (2026-10-17). Its projection, priced with no cache and every
  reply at the full 4,000 tokens, is $23.45, so it fits under the line even at that worst case.
  **An estimate:** the 2010 learner run's batch apply calls averaged $0.0035 each, so about $1.40.
- **The cause lookup** is kind `coding-test`, on the $40 guard and the side track's $10 line, which
  has $8.86 left (`make mem-spend`, 2026-10-17). **An estimate:** the 0210 lookup run cost $0.1999;
  this one should cost about the same, so about $0.20.

## 10. What is published either way, and what follows

`docs/results/memory-cause-lookup-dev.txt` is committed whatever it says, counts only: each run's
measures with intervals and failed cases; the noise; cause lookup − counts(a), which decides; code
lookup − counts(a), as 0210 read it; cause lookup − code lookup; each lookup's lessons per case and
distinct lessons used; and the verdict, last line, `rule on the cause-lookup run: PASS` or `FAIL`,
with every `not passed:` reason before it.

**What follows, fixed now:**

- **Passed, and the finding gain's 95% interval is above zero:** recommend a registered
  confirmation on a fresh development sample, with its own counts runs, before any relearning.
- **Passed, but the interval includes zero:** reported as a thin pass. Recommend stopping the
  side track; going further is Andy's call, in a record.
- **Not passed:** the side track stops and is reported as it stands. Lessons before the first
  answer (0211, "What this rules out") are then not tested.

## 11. What had been seen when this was written

- **All results of the pilot and the lookup test**, on `dev-steer-400`
  (`docs/results/memory-pilot-dev.txt`, `docs/results/memory-lookup-dev.txt`). This is the steering
  slice's fourth look at a memory. Nothing in §4 was set from a score: the apply step, K and the
  floor are as they were before either result.
- **The learner's cost records** for 2010 (`calls.jsonl` of `20261016T102829Z-beba05b-memory-2010`),
  for the estimate in §9.
- **Not seen:** any apply-step answer for a steering case, or any coding-test answer with lessons
  chosen by cause sentence.

## 12. Prediction (optional)

None is required. Andy may write one here before signing.

## Glossary

- **Apply step:** the learner's call that reads one cause sentence and lists the lessons that
  cover it; the same call counted each lesson's support.
- **Cause lookup:** for one case, the five best fitting lessons among those the apply step named
  for its cause sentence.
- **Code lookup:** the lookup of decision 0210: lessons whose codes match the model's first answer.
- **Counts:** the coding tools' output (how often the NTSB used each code), from the `mem`
  statistics.
- **Fit:** of the learning cases a lesson applies to, the share whose NTSB codes agree with it.
- **Noise:** counts(b) − counts(a): how much a repeat run moves each measure.
- **Paired difference:** one run's score minus another's on the same cases.
- **Points:** the difference between two percentages.
- **Support floor:** the fewest learning cases a lesson must apply to before it may be chosen (10).
- **Top-1 / top-3:** the NTSB's first occurrence code is the answer's first guess / any of its up to
  three guesses.

Approved by Andy, 2026-10-17
