# Coding memory lookup test: the registration (decisions 0209, 0210)

This file fixes the lookup test's runs, its lookup rule and its stop rule **before either paid
run**, so none of them can be chosen after a result is seen. Andy reads and signs it first.
Decisions: [0209](../decisions/0209-a-lessons-finding-categories-are-alternatives-and-the-2010-lessons-are-recounted.md)
and [0210](../decisions/0210-a-lookup-test-gives-each-case-the-lessons-that-match-its-first-answer.md).
Plan: `docs/plans/2026-10-16-coding-memory-lookup.md`, Task 6. The pilot's registration,
`docs/rounds/memory-pilot.md`, still governs everything this file does not change.

**What committing this file does.** In code, it unlocks the lookup condition of the coding test:
`scripts/memory_coding_test.py` refuses `tools --lookup` until this file is committed
(`refuse_lookup_without_registration`). The refilled note uses the memory condition, which the
pilot's registration already unlocked; it is gated by this file's rule: **no paid step here runs
before Andy signs below.** Nothing here touches Ellery version 1, S4's nights or the board.

## 1. The question

When each case is shown **the lessons that match its own first answer**, rather than the same
short note for every case, do the lessons help GPT-6 Luna code better than the counts the coding
tools already give?

**Why ask it.** The pilot passed its stop rule by a thin margin (`docs/results/memory-pilot-dev.txt`):
finding recall@10 +0.7 points [−1.4, +2.7] over the counts condition. But it tested very little.
Its note was capped at 6,000 estimated tokens, so it held 15 of the 198 lessons the learner wrote,
and those 15 name only 7 finding categories. The count that chose them was also faulty (§2).

## 2. What changed since the pilot

**A counting defect was found and fixed (decision 0209).** The count required every finding
category a lesson names to be flagged in a case. Lessons list alternatives, so most well-used
lessons counted as fitting no case. Among the 106 lessons that apply to at least 10 cases, the
median fit was 0% under the old rule and 48% when one listed category is enough
(`docs/results/memory-recount-dev.txt`). The cap kept the
wrong lessons, and every lesson showed the coding model a count that made it look unreliable.

**The 2010 lessons were recounted, not relearned.** `make mem-recount` rebuilt the 2010 finish
step's final apply answers from the learner's saved replies, with no call. Every one of the 2,370
cases' request keys matched a saved reply. The new snapshot, `pilot-2010-recount`, holds the same
198 lesson texts as `pilot-2010`, with support counted by the corrected rule. Under the 6,000-token
cap it keeps 13 lessons, which name 21 finding categories against the old note's 7, and pushes out
185. `make mem-check` found 0 findings and stamped it.

**What stays from the pilot:** the sample `dev-steer-400`, GPT-6 Luna batch at reasoning `medium`,
guidance `r3-loc-stall` and `r6-aircraft-control`, the `mem` statistics, the $0.05 per-case cap,
and the pilot's own runs: tables(a), counts(a) and counts(b), which are reused, not run again.

## 3. The two new runs, and the commands

Both are post-passes over the pilot's tables(a) run,
`20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a`, like the pilot's counts and memory runs.

1. **The refilled note** (memory condition): the 13 lessons `pilot-2010-recount` keeps under the
   cap, the same for every case.
   `make mem-coding-tools SOURCE=20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a SNAPSHOT=pilot-2010-recount`
2. **The lookup** (lookup condition): for each case, up to 5 of the snapshot's 198 lessons,
   matched to that case's first answer (§4).
   `make mem-coding-lookup SOURCE=20261015T212036Z-754b6ee-dev-steer-400-mem-tables-a SNAPSHOT=pilot-2010-recount K=5`

**Why the refilled note runs too.** It separates two explanations of the pilot's thin result:
the faulty count (if the refilled note does clearly better than the pilot's note), and the
fixed-note design itself (if only the lookup does better). It does not decide anything.

## 4. The lookup rule

A script, not a model (`memory/lookup.py`):

1. **The query is the model's own first answer** in tables(a): its occurrence codes (up to three)
   and its finding categories. No NTSB code, verdict or case text is read by the lookup. In the
   coding test the model's input is the NTSB's probable-cause sentence (decision 0205), so the test
   measures coding alone; on a live case the query would be the agent's own draft.
2. **Lessons that may be chosen:** every lesson in `pilot-2010-recount`, kept or pushed out, that
   applies to **at least 10** learning cases. Fewer than 10 is too little support to rank by.
3. **A lesson matches** in up to two exact parts, each counted once however many codes the lesson
   lists: a first code it predicts is one of the answer's occurrence codes, and a finding category
   it names is one of the answer's categories. A lesson's categories are alternatives (decision
   0209), so a long list does not outrank a short one. When no first code it predicts is in the
   answer, it can still match by **event**: a first code it predicts has the same event as one of
   the answer's codes, in another phase of flight, which split lessons exist to settle.
4. **Order:** most exact parts (0, 1 or 2); then a first-code match ahead of a category match; then
   an event match; then highest fit (cases agreeing ÷ cases applied to, by the corrected rule); then
   most cases applied to; then lesson id. So the same answer always gets the same lessons.
5. **K = 5:** the first five in that order. A case that matches none reads the counts condition's
   text unchanged.
6. **Where the lessons go:** after the counts condition's system text, under the memory's heading,
   exactly as the pilot's memory condition placed its note. Nothing else in the request changes.

## 5. The noise

As in the pilot (its §7): **noise = counts(b) − counts(a)**, from the pilot's two counts runs,
which re-code the same first answers. From `docs/results/memory-pilot-dev.txt`: top-1 +0.2 points,
top-3 +0.7 points, finding recall@10 −0.3 points.

**Two properties to know before signing.** The noise is one pair of runs, and it is small. Small
noise makes the finding bar low: here a lookup gain above 0.3 points on finding recall@10 passes.
That is why §10 asks for more than a pass before more money is spent. And the counts runs ran on
2026-10-15, the lookup runs will run later: any change in the provider's model between those days
is not in the noise term. Both new runs share that gap, so lookup − note does not have it.

## 6. The stop rule, word for word

The pilot's rule (decision 0204 item 5), read on the lookup run. The registered rule is the
docstring of `lookup_rule` in `scripts/memory_lookup_result.py`, word for word:

```text
Decision 0210, as registered in docs/rounds/memory-lookup.md.

``looked`` is lookup minus counts(a); ``noise`` is counts(b) minus counts(a). Pass only if the
finding gain exceeds the noise on findings, and neither occurrence measure falls by more than
its own noise: the pilot's rule (decision 0204 item 5), read on the lookup run.
```

**The exact inequalities.** Let L = lookup − counts(a) and N = counts(b) − counts(a), each a paired
point estimate. The test **passes** only if all three hold:

- L(finding recall@10) **>** |N(finding recall@10)|, that is, above **+0.3 points**;
- L(top-1) **≥** −|N(top-1)|, that is, not below **−0.2 points**;
- L(top-3) **≥** −|N(top-3)|, that is, not below **−0.7 points**.

The rule reads point estimates. The 95% intervals are printed beside them and do not decide the
pass, but they decide what is recommended next (§10).

## 7. Failed cases count as wrong

As in the pilot (its §9, decision 0136). A case with no answer in tables(a) fails in every
post-pass alike (`source failed`).

## 8. The order of runs

1. Andy signs; this file is committed.
2. `make mem-spend EST=0.80`, then the refilled note (§3, run 1). Commit nothing but the plan tick.
3. The lookup (§3, run 2).
4. `make mem-lookup-result TA=<tables-a> CA=<counts-a> CB=<counts-b> NOTE=<note run> LOOKUP=<lookup run> PILOT=<the pilot's memory run on pilot-2010>`,
   then commit `docs/results/memory-lookup-dev.txt`.

Every step needs a clean tree. Anything unexpected goes under the plan's Deviations as it happens.

## 9. Spend and expected cost

No learner (Claude) call. Both runs are coding tests on OpenRouter: kind `coding-test`, on the $40
monthly guard and the side track's $10 line, which has $9.19 left (`make mem-spend`, 2026-10-16).

**Expected cost. An estimate:** the pilot's two memory runs cost $0.1315 and $0.1339. The refilled
note should cost about the same. A lookup run reads a mean of 2,293 estimated tokens of lessons a
case against 5,763 for the note (`docs/results/memory-lookup-reach-dev.txt`), but its per-case
text cannot share the prompt cache past the point where the lessons begin. Priced with no cache at all, it is about $0.40 at GPT-6 Luna's batch
price ($0.05 per million input tokens, $0.25 per million output). So **under $0.60 for both**.

## 10. What is published either way, and what follows

`docs/results/memory-lookup-dev.txt` is committed whatever it says, counts only: each run's
measures with intervals and failed cases; the noise; lookup − counts(a), which decides; note −
counts(a); lookup − note; the pilot's memory run − counts(a); the lookup's lessons per case and the
number of distinct lessons used; and the verdict, last line, `rule on the lookup run: PASS` or
`FAIL`, with every `not passed:` reason before it.

**What follows, fixed now:**

- **Passed, and the finding gain's 95% interval is above zero:** recommend relearning 2009 and
  2010 with the corrected rule (about $20–35 of plan credit) and a registered test of the lookup
  design on a second sample.
- **Passed, but the interval includes zero:** reported as a thin pass, as the pilot was. Recommend
  stopping the side track; going further is Andy's override, in a record.
- **Not passed:** the side track stops and is reported as it stands.

## 11. What had been seen when this was written

- **All of the pilot's results** (`docs/results/memory-pilot-dev.txt`), including tables(a),
  counts(a), counts(b) and both memory runs on `dev-steer-400`. This is the steering slice's third
  look at a memory, which raises the risk of fitting choices to this one sample; the lookup rule
  (§4) was set from the lessons and the answers, not from any score.
- **The recount's diagnostics** (§2), from the learner's saved answers on learning-part cases.
- **The lookup's reach on tables(a)'s answers, not their scores**
  (`docs/results/memory-lookup-reach-dev.txt`, read from the answers' codes only): 106 of the 198
  lessons may be chosen; 397 of 401 cases get five lessons, 3 get one to four, and 1 gets none; 93
  distinct lessons are used. Two parts of the rule were set from this reach, never from a score:
  categories count once (an independent review found long lists crowding out first-code lessons),
  and a first-code match breaks ties ahead of a category match. Of the 290 cases where a choosable
  lesson predicts the answer's first code, 9 are given none under the rule in §4, against 29
  without the tie-break. The support floor of 10 was set before either: at a floor of 5 the reach
  was almost the same.
- **Not seen:** any coding-test answer with looked-up lessons, or with the refilled note.

## 12. Prediction (optional)

None is required. Andy may write one here before signing.

## Glossary

- **Coding test:** GPT-6 Luna coding a case from the NTSB's own probable-cause sentence; it measures
  coding alone.
- **Counts:** the coding tools' output (how often the NTSB used each code), from the `mem`
  statistics.
- **Event match:** a lesson's predicted first code has the same event as one of the answer's codes,
  but a different phase of flight.
- **Exact match:** a lesson's predicted first code, or a finding category it names, is in the
  model's first answer.
- **Fit:** of the learning cases a lesson applies to, the share whose NTSB codes agree with it.
- **Lookup:** choosing, by script, the lessons that match one case's first answer.
- **Noise:** counts(b) − counts(a): how much a repeat run moves each measure.
- **Note (the refilled note):** the lessons the 6,000-token cap keeps, shown to every case alike.
- **Paired difference:** one run's score minus another's on the same cases.
- **Points:** the difference between two percentages.
- **Recount:** support counted again by the corrected rule, from answers already saved.
- **Support floor:** the fewest learning cases a lesson must apply to before it may be chosen (10).
- **Top-1 / top-3:** the NTSB's first occurrence code is the answer's first guess / any of its up to
  three guesses.

Approved by Andy, 2026-10-16
