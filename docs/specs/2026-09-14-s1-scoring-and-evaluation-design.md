# S1 — Scoring and the evaluation harness: design

*Drafted 2026-09-14 and 2026-09-15 from a design session with Andy, after the merge of the
agency design (pull request #3).
Status: Implemented (2026-09-17, pull request #5).
This is the specification for build stage S1 in
`docs/specs/2026-09-12-architecture-and-roadmap.md` §11. It records what S1 builds, why,
the decisions S1 was asked to take, and the condition for moving on. It takes over §5.4,
§6 and §7.2 of the agency design (`2026-09-14-agency-hypothesis-trail-design.md`), as that
document says it will. The implementation plan is written from it separately.*

**How to read this.** Each section says what is built, then why, with an example where one
helps. Terms in **bold** on first use are in the glossary at the end. Every number is
labelled **M1–M10** and comes from `scripts/exploratory/s1_design_measurements.py`; its full
output is saved beside this document as `2026-09-14-s1-design-measurements.txt`. That
script reads the frozen spike's local data, because this repository's data is not in git.
It reads no withheld text: only codes, code labels, counts and whether a field is present.
Numbers from the spike cite the spike's script. Nothing here is a result: S1 produces the
results.

Decision records written with this specification: 0025 to 0031 (section 15).

---

## 1. What S1 is for

S0 built the road from a case record to the model: it takes a record, removes the answer,
and produces a safe payload. S1 builds the other half. It decides what the model must
answer, how the answer is marked, and it runs the first paid experiments. Its job is to set
the **bar**: the number the agent must beat later. The bar is set before the agent exists,
so nobody can say the agent was tuned against its own test.

Three things come out of S1.

1. **A known number, reproduced.** The spike's structured baseline — guess the most common
   cause for this phase of flight and this weather — scored 16.2% top-1
   (`../ntsb-spike/src/ntsb_spike/baseline.py`). S1 computes it again through new code. If
   the new code gets 16.2%, it can be trusted. If it gets 23%, it has a bug.
2. **The ceiling, re-measured.** One model call with every structured fact the record
   holds, no docket, no tools, and the model must pick codes from lists. This is the most a
   single call can do, and it is **arm B without the docket** (0022). The spike's 57% was
   free text, marked by a human, with the narrative included, and is history (0006, 0013).
   The spike's cases with no narrative scored 12%; the new ceiling may land near that.
3. **Arm A and per-step scoring.** Arm A is the model with only the day-one facts. It shows
   what the start facts alone are worth. Per-step scoring is the maths that will mark each
   step of the agent's trail in S3; S1 proves it on a scripted trail now, so that S3 does
   not write its own marking scheme after seeing its own results.

An analogy. Before a student sits the exam, the mark scheme is written, checked on a past
paper with a known score, and the score of a student who has only read the front page is
recorded. Only then does the student sit.

S1 also takes the decisions the roadmap deferred to it (§9): the bars and the slices, the
headline metric for live cases, how the prose outputs are graded, the stopping threshold,
whether the registration is a start fact, how memorisation is measured, and, added in the
design session, which model is the default.

**What S1 is not.** It does not fetch a docket (S2), take a step (S3), or store anything
for the live board (S2.5). It spends money on model calls for the first time, under a cap
and a budget written in code.

---

## 2. The measurement, in one page

Every run in S1 is one **answering pass** per case: a model turn that produces the
hypothesis, and a second short turn that refines the finding codes (§3.2). No tools. The
harness varies three things.

| axis | values in S1 | why |
|---|---|---|
| **arm** | A: start facts only. Ceiling: every structured evidence role. | 0022. Arm B with the docket is S2; arm C is S3. |
| **exclusions** | none; registration removed; phase of flight removed; case number added (development split only) | the ablations of §6.2 |
| **sample** | `heldout-40`, `heldout-400`, `dev-400` (§5) | continuity with the spike, statistical weight, and somewhere to tune |

Every run records the commit SHA and whether the tree was dirty (0018), the model and price
variant, the tokens and cost of every call, and the exclusion set. Every score comes with a
count and a 95% interval. Nothing is tuned on `heldout-*`: prompts, schema and the threshold
are settled on `dev-400`, and every held-out run is listed in a committed ledger (§5.4).

The order is fixed by the argument: the baseline first, because it is known; the ceiling
second, because it is the bar; arm A third, because it shows what the start facts alone
give; the ablations last, because they interpret the ceiling.

---

## 3. The verdict vocabulary and the output schema

### 3.1 The code tables come from the NTSB's own dictionary

The NTSB publishes its whole aviation database as a download, `avall.zip`, from its
accident data page (`https://www.ntsb.gov/safety/data/Pages/Data_Stats.aspx`). Inside is a
table, the **data dictionary**, listing every code the NTSB may use, with its meaning and a
definition sentence. The spike holds a copy at `data/raw/avall.zip`. It gives (M10):

| list | rows | example |
|---|---|---|
| finding items, eight digits | 1,019, in 130 six-digit categories | `01022214` "Aircraft — aircraft systems — auto flight system — autopilot trim indicator" |
| finding modifiers, the last two digits | 73 | `01` "Failure", `44` "Pilot" |
| occurrence events, the last three digits | 94 | `092` "Hard landing" |

The dictionary has no separate list of phase prefixes for the post-2008 scheme. Every
occurrence row in the public dataset carries its phase label, so the phase table is read
from those labels: 43 prefixes, each with exactly one label (M9). Labels only; no case
data.

Building the tables from a public reference document rather than from our own cases has
three effects. The model can choose any code the NTSB could choose: 99.8% of held-out
finding codes and 99.5% of held-out occurrence codes compose from the official lists,
against 96.2% and 97.4% from the development years alone (M1, M2, M10). No held-out case is
read to build a table, so there is nothing to argue about. And each item comes with a
definition sentence the model can be shown when choosing between neighbours.

The tables are built once by `scripts/build_code_tables.py` from the dictionary, committed
as package data under `src/ntsb_probable_cause/scoring/tables/` (labels only; the model
needs them at run time), and summarised with the dataset's date in
`docs/results/s1-code-tables.txt`. `scoring/codes.py` loads them, composes and validates
codes, and the build script checks the tables against the development corpus and reports
any code in use that the dictionary lacks (M10 found one eight-digit item of 678, and 3
event suffixes of 81).

### 3.2 Occurrence codes

An **occurrence code** is six digits: a three-digit **phase prefix** and a three-digit
**event suffix**. `552230` is "loss of control on the ground during the landing roll", the
most common code in the held-out years at 8.0% of cases (M1). The development years hold
829 distinct primary codes (M1). The spike's "58 occurrence codes" (0006) counted event
categories, not codes.

Listing 829 codes with labels costs about 10,600 tokens per call (M6). Listing the two
parts costs about 900 (M9, M10). So the model is given the phase table and the event table,
picks one of each for its top-1 and for each entry of its top-3, and the harness composes
the six-digit code.

```
model:   phase 552 (landing roll)   event 230 (loss of control on ground)
harness: 552230   compared with the NTSB's code for the defining event
```

**Scoring.** The **primary occurrence code** is the code of the NTSB's defining event,
first in `Verdict.occurrence_codes` (S0 `fields.py`). Top-1 is exact match of the six
digits. Top-3 is the primary code anywhere in the model's three. A second column, **event
match**, scores the suffix alone; it is reported, never the headline, because it is closest
to what the spike's human marked and it separates "what happened" from "when". A pair the
NTSB never uses (829 of 3,483 possible pairs occur, M9) counts as a miss and is counted in
its own column, "pair unseen"; the tables are not restricted to seen pairs because 0.2% of
held-out codes are unseen pairs too.

### 3.3 Finding codes: two stages

A **finding code** is ten digits in five pairs, and each pair narrows the meaning:

```
02 06 30 40 44
│  │  │  │  └─ modifier: who or what — 44 = the pilot
│  │  │  └─── item: 40 = aircraft control
│  │  └────── section: 30 = use of equipment or information
│  └───────── subcategory: 06 = task performance
└──────────── category: 02 = personnel issues
```

The pairs are not independent choices. A pair's meaning depends on the pairs before it: the
tier-2 pair `02` means "aircraft systems" after one category and "psychological" after
another, and 44 of the 52 tier-4 values change meaning with their path
(`2026-09-14-s1-design-measurements.txt`, and the session's pair check). Two parts are
independent: tier 1, and the **modifier**, whose 73 values mean the same thing everywhere.
So the code is a walk down a tree to eight digits, plus a modifier chosen on its own.

The full ten-digit vocabulary is 2,928 codes in the development years, 1,241 seen once, and
the list would cost about 75,700 tokens (M2, M6). The official eight-digit item list is
about 22,000 tokens (M10). Neither fits a call at the cap. The six-digit category list is
130 rows, about 2,000 tokens, and a category has a median of 6 items (M10). So:

- **Stage 1, the category pass.** In the answering turn, the model picks six-digit
  categories from the 130-row table, and a modifier for each from the 73-row table.
- **Stage 2, the refinement pass.** A second, short turn shows the official items under each
  chosen category — about 18 rows for three categories at the median (M10) — with their
  definitions, and the model picks the item. The harness composes item plus modifier into
  the ten-digit code.

```
stage 1:  category 020630 (personnel — task performance — use of equipment/info), modifier 44 (pilot)
stage 2:  items under 020630: 02063040 aircraft control, 02063020 checklist, ...  → 02063040
compose:  02063040 + 44 = 0206304044
```

The second turn is not a tool call, so the ceiling stays "no tools, no docket". Its
definition in 0022, "one call", becomes "one answering pass of two turns" (0025). During a
trail (S3), each step's hypothesis stays at stage 1, because it is a working belief and it
is cheap; the refinement pass runs once, when the agent stops. The rule is the same for
every arm, so the comparison stays fair.

**Which findings are the target.** The NTSB flags each finding as in the probable cause or
not: 84.6% of findings are flagged, 99.0% of cases have at least one, and in 67.1% of cases
every finding is flagged (M3). The target set is the **flagged findings**, because those
are the NTSB's own answer to "why". `Verdict` gains `finding_codes_in_cause` beside the
existing `finding_codes`; both are read by the splitter only (0016), and the tripwire's
whole-token check covers both. The public dataset also marks each finding as a cause or a
contributing factor; that split is reported as a slice in the results and is not a target
in S1.

**Scoring.** Precision and recall of the model's set against the flagged set, at three
granularities, each as its own column.

| digits | what it tests | example of a near miss |
|---|---|---|
| 10 | the exact NTSB code; the headline | pilot `44` against pilot of other aircraft `45` |
| 8 | the item, ignoring who or what | same item, wrong modifier |
| 6 | the category | right area, wrong item |

Precision is the share of the model's codes that were right; recall is the share of the
NTSB's flagged codes the model found. Example: flagged `0206304044` and `0102256099`; model
`0206304044`, `0301301099`, `0500000000`; precision one of three, recall one of two. The same
numbers against all findings are reported beside them, because the spike's finding baseline
was scored against all findings and the reproduction in §6.3 needs it. The baseline is
computed at all three granularities so every column has a floor.

### 3.4 The Hypothesis schema

The model's answer is one object, the **Hypothesis**. It is the same object for a one-shot
answer and for the hypothesis after each step of the trail (0021), so that S3 does not
define a second one. Fields, in the order the model writes them:

| field | type | why it is there |
|---|---|---|
| `evidence_narrative` | text | the model's own account of what the evidence shows, written before the verdict (0013); compared with the withheld factual narrative (§8) |
| `occurrence` | list of up to 3 entries: `{phase, event, probability}` | ranked; the first is top-1; probabilities sum to at most 1; the remainder is "something else" |
| `findings` | list of `{category6, modifier, probability}`; after stage 2, each gains `item8` | the findings it believes are in the cause |
| `probable_cause` | one or two sentences | the verdict in the NTSB's form |
| `lay_explanation` | text | what a reader with no domain knowledge needs (demo criteria); graded in §8 |
| `confidence` | 0 to 1 | the model's belief that its top-1 occurrence code is right; checked in §4 |
| `abstain` | boolean | the evidence is too thin to name a cause |
| `evidence_used` | list of evidence roles or document names | which inputs it rests on |

Codes are validated on parse against the tables: an unknown phase, event, category,
modifier or item is a schema error, and the turn is retried once with the error text. A
second failure is recorded as a failed case with its own reason, never silently dropped.

The three step-only fields of the trail — reason for the call, expected effect, observed
effect (0021) — are not in the Hypothesis. They belong to the **step record** (§6.4) that
wraps it.

### 3.5 The prompt

One system prompt, one user message. The user message is the `Payload` of S0, unchanged,
followed by the phase, event, category and modifier tables. The system prompt says what the
task is, that the narrative comes first, and that abstaining is allowed and expected when
the evidence is thin. It never names the case, the date or the location (0023). It is a
typed constant in `scoring/prompt.py`, versioned by a short name that the run record
carries. The tables are identical in every call, so they are placed first and marked for
the provider's prompt cache where the probe (§7.1) shows it is honoured. Prompt wording is
settled on `dev-400` and frozen before any `heldout-*` run.

---

## 4. Scoring

### 4.1 Per case

| score | definition |
|---|---|
| occurrence top-1 | composed six-digit top-1 equals the primary occurrence code |
| occurrence top-3 | primary code is among the three composed codes |
| event match | the suffix of top-1 equals the suffix of the primary code |
| pair unseen | top-1 is a phase–event pair not seen in the development years |
| finding precision, recall | at 10, 8 and 6 digits, against the flagged findings; and against all findings |
| abstained | the abstain flag; an abstained case scores 0 on every accuracy column and is counted separately |
| confidence | as stated; used for calibration and the threshold |
| cost | prompt tokens, completion tokens, USD, from the provider's usage (§7) |
| failed | schema failure after retry, provider error after retries, or over the cap: the reason is recorded and the case counts as neither right nor abstained |

**Abstention is a claim, not a free pass.** An abstained case is scored as wrong in the
headline, and the abstain rate is reported beside it. A third column, accuracy on answered
cases, shows what the model gets when it commits. Example: 100 cases, 20 abstained, 40 of
the other 80 right; headline 40%, abstain rate 20%, accuracy when answering 50%. All three
are needed to see whether abstention is selective or lazy.

**Confidence is checked, not trusted.** Cases are binned by stated confidence in ten equal
bins. If the cases where the model said 0.8 are right about 80% of the time, it is
calibrated; if 40%, it is overconfident, and that is published.

### 4.2 Per step

The definitions the agency design gave in words (§6.3 there), made exact. A **trail** is
the ordered list of hypotheses for one case; a one-shot run is a trail of length one. Let
*p_k(c)* be the probability the hypothesis after step *k* puts on code *c*, and *c\** the
primary occurrence code.

| score | definition |
|---|---|
| accuracy by step | the per-case scores of §4.1, computed on the hypothesis after step *k*, at stage-1 granularity for findings |
| probability on the true code | *p_k(c\*)*, zero if *c\** is not listed |
| information gain of step *k* | *p_k(c\*) − p_{k−1}(c\*)*; a step with gain 0 "moved nothing on the truth" |
| hypothesis movement of step *k* | total variation distance between the occurrence distributions before and after the step, with the unlisted remainder as one bucket; needs no verdict |
| calibration | per confidence bin, mean stated confidence against observed top-1 accuracy; the expected calibration error is the count-weighted mean gap |
| stated versus actual | the step record's observed effect (confirmed / weakened / unchanged) against the sign of information gain (positive / negative / zero); agreement is the share of steps where they match, with chance agreement beside it |

These functions take a trail and a verdict and return numbers. They know nothing about
tools or the loop. S1 proves them on a scripted trail replayed through the recording fake
(S0 `model/client.py`): a test builds a three-step trail with known probabilities and
checks every number by hand.

### 4.3 Intervals and comparisons

A result on a sample is a best guess, not the true accuracy: 23 right of 40 says "57%", but
a different 40 cases might have given 20 or 26. The **confidence interval** is the range of
true accuracies the result is consistent with; for 23 of 40 it is roughly 42% to 72%, for
the same rate on 400 cases roughly 52% to 62%. The spike reported no intervals
(`../ntsb-spike/docs/demo-criteria.md` asks for them); with 40 cases a 50% model and a 65%
model cannot be told apart, which is why §5 adds a larger sample.

- Every proportion carries a **Wilson 95% interval** and its count. A figure with no count
  is a bug.
- A difference between two runs on the same cases — arm A against the ceiling, with the
  registration against without, agent against ceiling in S3 — is a **paired difference**:
  per case, +1 if the first run is right and the second wrong, −1 the reverse, 0 otherwise;
  the mean, with a bootstrap 95% interval over cases (2,000 resamples, seeded). "The agent
  beats the ceiling" means this interval lies entirely above zero. Two separate intervals do
  not answer whether a difference is real; the paired one does, and it is more sensitive
  because it removes the effect of which cases happened to be easy.
- Precision and recall are averaged over cases, with the same bootstrap.

### 4.4 Slices

Every table is reported for all cases and then by **fatal / non-fatal** first and
**investigation class** second (0026), which closes the proposal in the agency design. The
held-out split holds 727 fatal and 3,514 non-fatal cases; by class, 397 C, 531 F and 3,308
L, and 5 in other classes (M4). C-class cases are 45% of development cases, 9% of held-out
cases and 0 of the closed open-split cases (M4, `docs/results/s0-corpus-scan.txt`), so a
prediction about them would be about cases the live board never sees, while injury level
means the same in every era. The five cases in classes I, M and T are excluded from
samples and said so.

The spike's slice, narrative present or absent, is gone: the narrative is withheld in every
case (0013). What replaces it as a description of the corpus is **report flavour**: 2,248
of 4,241 held-out cases are "Basic (no factual)", 1,851 of them L-class and 397 C-class; a
factual narrative is present on 2,200 (M5). This answers the S0 open question about recent
no-narrative cases: they are the basic-flavour reports, mostly L-class, a reporting style
rather than a C-class habit. Flavour is reported as a slice for context only.

---

## 5. Samples and the held-out ledger

The rule that matters: **nothing is tuned on held-out cases.** Every look at them teaches
something that the next prompt change could be shaped by. So the harness runs there as few
times as possible, and writes down every time it does.

### 5.1 `heldout-40`

The 40 case IDs of the spike's decidability sheet, already in
`tests/fixtures/eval/decidability_ids.csv`: 11 fatal and 29 non-fatal; 5 C, 9 F, 26 L
(M7). The ceiling runs here first, for continuity, so the spike's 57% and the new number
sit side by side with the warning that 40 is too few.

### 5.2 `heldout-400`

400 held-out cases: 200 fatal and 200 non-fatal, each half stratified by class in
proportion, drawn once with seed 20260914 from `cases.parquet` and committed as
`tests/fixtures/eval/heldout_400_ids.csv` (IDs and event dates only). Held-out cases are
17% fatal, so a proportional 400 would hold 69 fatal cases; fatal cases are oversampled
because the agency predictions concentrate there (0022, P1 and P3). The all-cases headline
is therefore **weighted** by the held-out fatal share, 727 of 4,241, and the unweighted
number is shown beside it. 200 per slice gives an interval of about ±7 points on a
proportion near 50%.

### 5.3 `dev-400`

The same construction on the development split, seed 20260914, committed as
`tests/fixtures/eval/dev_400_ids.csv`. Prompt wording, schema changes, the judge (§8), the
threshold (§9), the case-number probe (§6.2) and the model comparison (§9) happen here and
nowhere else. Nothing measured here is a result.

### 5.4 The ledger

`docs/results/heldout-ledger.md` lists every run that touched a `heldout-*` sample: date,
sample, arm, exclusions, model, commit, cost, and the results file. The harness appends the
row itself; a held-out run from a dirty tree is refused. Anyone can count how many times
the held-out split was looked at.

The full labelling sheets of the spike are copied into `tests/fixtures/eval/` as regression
fixtures, as `CLAUDE.md` says, with the spike commit recorded. The columns that hold the
NTSB's codes and cause are withheld data and are kept out of any payload by the same guard
as everything else.

---

## 6. The harness

### 6.1 Arms and conditions as exclusion sets

An arm in S1 is an **exclusion set** passed to `split_record`, nothing more (0023). Arm A
excludes every role except the start facts: phase of flight, injury level, aircraft make
and model, engine type, and the registration until §9 decides. The ceiling excludes nothing
S0's evidence roles hold; the preliminary narrative is empty on every closed case anyway
(0023). The docket is absent from both because S2 has not built it.

The **full** availability condition is the only one S1 runs. The **masked** condition is
built as a function — day *N* to an exclusion set, from the spike's fresh-case profile
(`../ntsb-spike/scripts/fresh_case_profile.py`) until the recorder has data (0023) — and
tested, but in one call there is nothing to mask that the ablations do not already cover.

### 6.2 Ablations

An **ablation** is a run with one input removed, on the same cases, so the paired difference
shows what that input was worth.

| flag | what it removes or adds | what it answers |
|---|---|---|
| `--exclude registration` | the registration role | §9: is the registration a start fact, and how much of the ceiling is memory. The tail number is a name the model may have seen in a published report; make, model and engine type already carry what it could honestly add |
| `--exclude phase_of_flight` | the phase role | repeats the spike's ablation under the new schema, where the phase is the first three digits of the answer; the spike found at most 2.5 points (`../ntsb-spike/scripts/ablation_phase.py`). No value of phase, injury level or engine type maps to one occurrence code more than 40% of the time (M8), so no single start fact gives the answer away |
| `--include case_number` | adds the NTSB case number to the payload; **development split only**, refused on any other sample | the case-number probe: if a model told the case number scores higher, it has seen the report. The difference is the memorisation ceiling for that model |

The case-number probe is the one place a bookkeeping field is rendered. It is a separate
code path that the guard's key check rejects unless the sample is development, and the run
record says so.

Example of the output, made up:

| run | top-1 | paired difference against the ceiling |
|---|---|---|
| ceiling | 30% | |
| without registration | 29% | −1, interval −3 to +1: no effect |
| without phase | 27% | −3, interval −5 to −1: the phase is worth 3 points |
| with case number, development only | 38% | +8, interval +5 to +11: the model remembers some reports |

### 6.3 Reproducing the baseline

The spike's phase-and-weather modal baseline: for each case, predict the most common
primary occurrence code among cases with the same phase of flight and weather condition,
top-3 the three most common (`../ntsb-spike/src/ntsb_spike/baseline.py`). The spike fitted
and scored it on one 1,000-case stratified draw of the held-out split, seed 7, and got 16.2%
top-1, 32.2% top-3, and finding precision 17.0% and recall 19.0% against all findings at ten
digits (`../ntsb-spike/docs/spike-report.md` §4).

S1 ports the method, not the code, and reports two numbers.

1. **The reproduction:** the same draw rule, seed and in-sample fit. Done means it lands
   within one point of 16.2% and 32.2%, or the results file explains the difference, as S0
   explained its split counts.
2. **The honest baseline:** fitted on the development split, scored on all 4,241 held-out
   cases and on each sample. This is the floor every table shows.

The finding baseline is computed at ten, eight and six digits against the flagged set and
against all findings, so the model's finding columns each have a floor on the same target.

### 6.4 Records

Three record types, all pydantic, frozen, `extra="forbid"`, in `scoring/records.py`.

**Run record**, one per run: run id (timestamp and short SHA), sample, arm, exclusion set,
prompt version, model, price variant, cost cap, budget, commit SHA, dirty flag, start and
end times, totals.

**Case result**, one per case: case id, split, slices (fatal, class, flavour), the verdict
codes at every scored granularity, the trail (a list of step records), the §4.1 scores,
cost, and the failure reason if any.

**Step record**, one per step, the agency design §5.4 made into fields: case, step number,
arm, condition, day *N* or null, tool and arguments or `stop`, reason given, expected
effect, evidence roles or documents returned, "not yet available" flags, a fingerprint of
the payload (SHA-256 of the rendered text; the text is not stored twice), the Hypothesis,
observed effect, stop reason, model, price variant, tokens, cost, cumulative cost, commit
SHA, dirty flag. A one-shot run writes one step: tool `none`, reason and effects empty,
stop reason `answered` or `abstained`.

Runs are written under `data/runs/<run id>/` as JSON lines, one file per record type, never
in git. The summary — every table of §4 with counts and intervals — is one text file the
`report` command prints, and the ones that set a bar or record a decision are committed
under `docs/results/`. The case result holds the model's text outputs, so results files
stay out of git: the committed summaries are numbers.

### 6.5 The command

`apps/eval`, a thin wrapper (roadmap §3), installed as `ntsb-eval`:

```
uv run python -m scripts.openrouter_probe              (§7.1; a script, because it runs
                                                        before the types it produces exist)
ntsb-eval baseline  [--sample heldout-400]
ntsb-eval run       --arm ceiling|A --sample heldout-40|heldout-400|dev-400
                    [--exclude ROLE ...] [--include case_number]
                    [--model ID] [--price-variant batch|standard]
                    [--cap-usd 0.05] [--budget-usd 25]
ntsb-eval report    <run id> [--against <run id>]
ntsb-eval judge     <run id>                           (§8; dev-400 until validated)
ntsb-eval threshold <run id>                           (§9)
make bars
```

`make bars` is the done-means command: baseline, ceiling on `heldout-40` and
`heldout-400`, arm A on `heldout-400`, each reported with intervals and cost, and the
ceiling written to `docs/results/s1-bars.txt`. The ablations are separate runs because they
are interpretation, not bars. A run refuses to start if its projected cost — cases times the
measured cost per case from the probe, or the cap if there is no measurement — would take
the month's ledger total past the budget flag (0030).

---

## 7. The model client

### 7.1 The probe, first

S0 left `ModelReply` provisional because the response shape must come from a real response,
not a guess (0016). S1's first task is `scripts/openrouter_probe.py`, which makes three calls to
OpenRouter with one committed fixture record and saves the raw responses under
`tests/fixtures/openrouter/`, with any request id or key material removed:

1. a structured answer under a JSON schema — the Hypothesis;
2. the same with one tool declared, prompted so the model calls it — the reply type must
   carry a tool call for S3;
3. a two-turn exchange: the tool result returned, then the structured answer.

The probe also records what the usage block contains — whether the provider reports cost
directly or only tokens, and whether the prompt cache is honoured — submits one small batch
of the same ten cases to the batch service and saves its response shape as a fourth
fixture, and runs the answering pass on ten `dev-400` cases with each of the two Luna
variants (0031), printing the cost per case from tokens and the batch total side by side. Every later type is written from the
saved files, the tests parse them, and every later run is projected from that cost.

### 7.2 The client

`model/openrouter.py`, an `httpx` client in the pattern of S0's `data/api.py`: bearer key
from `Settings.openrouter_api_key` (added, as `.env.example` already lists), retries on
429 and 5xx with backoff, a per-call timeout, a rate limit. `ModelSettings` gains
`price_variant`, `max_output_tokens`, `temperature` (fixed at 0 for every S1 run) and the
schema to enforce. `ModelReply` becomes what the probe saw: content, tool calls, finish
reason, usage (prompt tokens, completion tokens, reported cost if any), provider model id,
response id. Cost is computed from `sources.py` prices when the provider does not report
it, and the record says which.

Structured output is requested the way the probe shows works. If the provider cannot
enforce a schema, the harness validates on parse and retries once (§3.4); the probe decides
which path is real.

**Batch.** OpenRouter's batch service (`https://openrouter.ai/docs/batch-quickstart`,
read 2026-09-15) is asynchronous: a run submits an array of requests, each with a
`custom_id`, receives a batch id, polls until the status is `completed`, and reads the
results inline, within a 24-hour window, at half the token price. A JSON schema on the
reply is supported. Cost is reported per batch, not per request, so **per-case cost is
computed from each response's token counts and the price table, and the batch total is the
check** the run record stores beside it. The two-stage answering pass is therefore two
batches per run: every case's answering turn in one batch, then every case's refinement
turn in a second. The runner is written as submit, poll, collect: the run record keeps the
batch ids, so an interrupted run resumes by polling rather than re-submitting, and a
`--sync` flag runs the same cases one call at a time for the probe and for small checks.
OpenRouter keeps batch inputs and results for 30 days; the inputs are evidence payloads
that hold no withheld text, and the judge's batch holds NTSB narrative that is public. A
trail (S3) cannot be batched within a case, because each step depends on the last, but one
step across many cases can; that is S3's design question, noted here so the runner's
submit-poll-collect shape is kept general.

Tests never reach the network (`pytest-socket`); they replay the saved responses through
`respx`, as the NTSB client's tests do. The `RecordingFakeClient` stays for scoring tests
and gains the ability to replay a scripted Hypothesis.

### 7.3 One client, two roles, and the default model

The judge of §8 uses the same client with a different model. There is no second transport.

**Another provider.** The OpenRouter client is one implementation of the `ModelClient`
protocol S0 defined; the recording fake is another. The saved probe responses are the
contract the rest of the code is written to. A client for another provider — the OpenAI
API directly, say — would slot in at the same seam, and scoring, records and the harness
would not know. It would need its own probe and saved responses, its own price entries and
cost path (OpenRouter can report cost per call; most providers report tokens only), a
decision reversing 0009, and a re-measured bar, because a bar measured through one
provider is not the bar for another. An agent framework is not used: the trail needs a
structured record after every step, tools that are exclusion sets over one payload builder,
and cost per step, which a framework tends to hide. The question is asked properly when the
tool interface is designed at the start of S3 (roadmap §13).

The default model is `openai/gpt-5.6-luna`, batch variant, at $0.10 per million input
tokens and $0.60 per million output tokens on OpenRouter's public list (checked 2026-09-15,
`https://openrouter.ai/api/v1/models`; 0031). It advertises a JSON schema on the reply and
tool calls, the two things the harness needs. Sonnet 5 at $1.00 and $5.00 batch would cost
ten times as much. The model stays a harness parameter, and the roadmap's model axis is
placed after S3 (§9).

---

## 8. Grading the prose

Three text outputs need a quality measure and none can have a deterministic one: the
evidence narrative, the probable-cause sentence and the lay explanation. The spike's one
judge was wrong in one direction — it rejected 14 of 23 answers a human had accepted
(`../ntsb-spike/scripts/ablation_phase.py`) — which is why the headline needs no judge
(0006). S1 measures the judge before using it.

- **The judge** is a model from a different family than the answerer, Haiku 4.5 (batch,
  $0.50 and $2.50 per million), so the grader does not share the answerer's blind spots. It
  is given a rubric and returns labels only, never a score it invents.
- **Evidence narrative** against the withheld factual narrative: `consistent`,
  `contradicts`, or `adds unsupported facts`. The withheld text reaches the judge call
  through a separate payload builder in `scoring/judge.py`, which is inside the import
  allow-list for verdict and synthesis (0025) and on which the tripwire is not run — it is
  supposed to contain the narrative. It is the only such path, the boundary test names it,
  and the test asserts its payload never reaches the answering client.
- **Probable-cause sentence** against the NTSB's: `same cause`, `related`, `different`.
  Example: NTSB "loss of engine power due to fuel exhaustion, the result of the pilot's
  inadequate fuel planning"; model "engine failure from fuel starvation after the pilot
  misjudged the fuel needed"; label `same cause`.
- **Lay explanation** against the model's own chosen codes: `explains the chosen codes in
  plain language` or not, so that the page never shows an explanation that disagrees with
  the codes beside it.

**Validation, on `dev-400` only.** The judge's `same cause` label is compared with the
code layer: agreement with occurrence top-1 and finding recall is reported as a confusion
table. Andy hand-checks 30 disagreements, chosen at random with a seed — about an hour —
and the sheet is committed with the case IDs and the verdict text removed. The judge is
used on held-out runs only if agreement with the code layer is at least the spike's 62.5%
*and* the hand-check shows no one-sided error like the spike's; otherwise the prose is
still produced and published, labelled "unchecked by a validated judge". Either way the
labels are reported and never a bar (0028).

---

## 9. Decisions S1 takes

Each is decided by a rule written here before the run, so that the answer is read off, not
chosen.

| decision | rule | recorded in |
|---|---|---|
| **The bars.** | The ceiling's weighted top-1 and ten-digit finding recall on `heldout-400`, with intervals, are the bars in `docs/results/s1-bars.txt`. The agent (S3) must beat the top-1 bar by a paired difference whose interval excludes zero on the same cases and the same model. Cost bar: S3's mean cost per case at or under the cap S3 sets, which starts from the ceiling's measured mean and p95 cost. | As-built, and the roadmap's S3 done-means |
| **The slices.** | Fatal / non-fatal first, class second, flavour for context. | 0026 |
| **Live headline metric.** | The occurrence code is read from the coded defining event, which open cases often carry from day 1 (roadmap §13), so on a live case "predicted the occurrence" could mean "read something public". The live board's headline is the **finding score** at closure, ten-digit precision and recall against the flagged set; occurrence top-1 is shown beside it, labelled "often public early". Held-out tables show both, so the two are comparable. | 0029 |
| **The stopping threshold.** | On `dev-400`, from the ceiling run: score +1 for a right top-1, −1 for a wrong one, 0 for an abstention. For each candidate *t* from 0.05 to 0.95 in steps of 0.05, treat every case below *t* as abstained and compute the mean score; the *t* with the best mean is the threshold. Recorded with its curve. S3 re-selects with the same rule on its own development trails, because one-call confidence may not transfer to a loop; it never selects on held-out cases (0021). | As-built; §12 |
| **Registration.** | Paired difference of ceiling top-1 with and without the registration, on `dev-400` then `heldout-400`. Interval includes zero: the registration stays a start fact, a day-1 fact that costs nothing. Interval favours having it: the registration is removed from every evidence payload and the difference is published as the memorisation estimate. There is no branch that keeps something that only helps by memory. | 0027 |
| **Memorisation.** | Two numbers: the registration difference above, and the case-number probe on `dev-400`. Live cases, which no training set holds, are the control once the board runs (S3, S5). | 0027 |
| **The default model, and the model axis.** | `openai/gpt-5.6-luna` is the default; the probe picks between `luna` and `luna-pro` on ten cases and the plan records why. One comparison in S1, Sonnet 5 against Luna, ceiling only, on `dev-400`, as a sanity check that the cheap model is not far behind on this task; it is reported and does not change the plan unless the gap is large, in which case Andy decides before any held-out run. The bar is measured on one model and the agent is compared on the same model; a cross-model table is separate and labelled by model, never mixed into the bar. The full model axis — which model gains most from reading the docket — needs arms B and C and is placed after S3 in the roadmap. | 0031 |

---

## 10. Repository changes

```
src/ntsb_probable_cause/
  scoring/
    __init__.py
    codes.py        the code tables from the NTSB data dictionary; composition and validation
    hypothesis.py   the Hypothesis model and its JSON schema, both stages
    prompt.py       system prompt constants, versioned by name
    metrics.py      §4.1 per case, §4.2 per step, §4.3 intervals; pure functions
    baseline.py     §6.3
    samples.py      the three samples and their draw; the mask function of §6.1
    records.py      run, case and step records
    runner.py       one run: cases → payloads → two turns → results; the caps and the budget
    judge.py        §8; the only module that builds a payload holding withheld text
    ledger.py       §5.4
  model/
    openrouter.py   §7.2
apps/eval/__main__.py          the command of §6.5
scripts/exploratory/s1_design_measurements.py
tests/fixtures/openrouter/     three saved responses
tests/fixtures/eval/           the sample ID files and the full labelling sheets
docs/results/s1-code-tables.txt, s1-bars.txt, heldout-ledger.md
```

- `Verdict` gains `finding_codes_in_cause` (§3.3). `fields.py` gains its extractor under
  the withheld subtree; the path check already covers `aircrafts[].findings[]`.
- The import-linter contract and `tests/test_import_boundaries.py` add
  `ntsb_probable_cause.scoring.metrics`, `scoring.runner` and `scoring.judge` to the
  allow-list for verdict, and `scoring.judge` alone for synthesis (0025). `scoring.codes`,
  `hypothesis`, `prompt`, `samples` and `records` stay outside it. The model package still
  cannot see any of them.
- `Settings` gains `openrouter_api_key`, `openrouter_base_url`, `runs_dir`,
  `monthly_budget_usd`. `sources.py` gains the prices of Luna and Haiku 4.5 and the
  OpenRouter endpoint of 0009, each with its provenance comment.
- `errors.py` gains `ModelError` (transport), `SchemaError` (parse), `BudgetError` (cap or
  budget).
- `Makefile` gains `bars`, `probe`. `README.md` and `CLAUDE.md` gain the commands, and the
  "Eval bars to beat" table in `CLAUDE.md` is replaced at close-out by a pointer to
  `docs/results/s1-bars.txt`.

---

## 11. Tests and continuous integration

- **Metrics by hand.** Every §4 function is tested on tiny inputs with answers worked by
  hand in the test, including the paired bootstrap on a fixed seed and the Wilson interval
  against a published table value.
- **The scripted trail.** A three-step trail through the recording fake, with known
  probabilities, checked on every per-step score. This is a done-means condition.
- **Composition and validation.** Every phase and event composes; every category, item and
  modifier composes; an out-of-table choice raises `SchemaError`; a Hypothesis parses from
  each saved response; the tables match `docs/results/s1-code-tables.txt`.
- **The boundary, extended.** S0's boundary test runs on the payload of every arm and
  ablation and on the stage-2 turn, and asserts the case-number path is rejected on any
  sample but development. The judge payload is asserted to be the only payload that carries
  withheld text, and never to reach the answering client.
- **Caps and budget.** A run whose projected cost exceeds the budget does not make a call; a
  call whose prompt estimate exceeds the cap is recorded as failed with reason `cap`.
- **The ledger.** A held-out run on a dirty tree is refused; a clean one appends exactly one
  row.
- **Contamination.** `dev_400_ids.csv` holds only development event dates;
  `heldout_400_ids.csv` only held-out; no ID appears in both or in a fixture record.
- **Baseline.** The modal method on the nine fixture records gives the hand-computed answer.
- Coverage stays at the S0 gate; CI is unchanged in shape (lint, test, audit) and never
  needs a key: the probe is a command Andy runs, not a test.

---

## 12. Build order within S1

1. The probe, and the saved responses; the Luna variant chosen; the cost per case measured.
   Nothing else is written until the response shape is real.
2. `ModelReply`, `ModelSettings`, the OpenRouter client, replay tests.
3. Code tables from the dictionary, Hypothesis for both stages, prompt,
   `Verdict.finding_codes_in_cause`.
4. Metrics with hand-worked tests; the scripted trail.
5. Records, samples, the ledger, the runner, the command, the caps and budget.
6. Baseline: reproduction and honest version.
7. Ceiling and arm A on `dev-400`: settle the prompt; freeze it; write the threshold; the
   Sonnet 5 comparison.
8. Ablations on `dev-400`; the judge and its validation; Andy's hand-check.
9. `make bars`: `heldout-40`, `heldout-400`, arm A; the registration ablation on
   `heldout-400`; the ledger.
10. Close-out: `s1-bars.txt`, the outcome of 0027 recorded, `CLAUDE.md` table replaced,
    As-built, plan deleted.

---

## 13. Done means

1. `tests/fixtures/openrouter/` holds the three saved responses and the saved batch
   response, and every model type is parsed from them in tests; the probe's cost per case
   is recorded.
2. `ntsb-eval baseline` reproduces 16.2% and 32.2% on the spike's draw rule within one
   point, or the results file explains the difference; and reports the honest baseline on
   the full held-out split.
3. `make bars` produces the ceiling on `heldout-40` and `heldout-400`, and arm A on
   `heldout-400`, each with counts, intervals and cost, and writes `docs/results/s1-bars.txt`.
4. The per-step scoring test passes on the scripted trail from the recording fake.
5. The registration decision is read off the rule in §9 and recorded; the phase ablation,
   the case-number probe and the Sonnet 5 comparison are reported on `dev-400`.
6. The threshold is recorded with its curve, from `dev-400`.
7. The judge validation table and Andy's 30-case hand-check are committed, and the prose
   labels are reported on `heldout-400` under the outcome of §8.
8. `docs/results/heldout-ledger.md` lists every held-out run made, and nothing else touched
   the held-out split.
9. No run exceeded its budget flag, and the total S1 spend is stated in the As-built record.
10. Continuous integration is green; the documentation check passes; this specification is
    closed out under 0017.

---

## 14. Cost of S1

Bounds set in advance, in US dollars because that is what the provider bills (0030). At
Luna's batch price and roughly 8,500 input and 700 output tokens per case across both
turns, a case costs about a tenth of a cent, so a 400-case run costs about fifty cents;
the probe replaces this estimate with a measurement before any run. Andy's limit is $25 a
month on OpenRouter, which the `--budget-usd` flag defaults to.

| runs | cases | estimate |
|---|---|---|
| probe and cost check | 20 | under $1 |
| `dev-400`: ceiling, arm A, two ablations, case-number probe, and re-runs while the prompt is settled | up to 4,000 | about $5 |
| Sonnet 5 comparison on `dev-400`, batch | 400 | about $5 |
| `heldout-40`, `heldout-400` ceiling and arm A, registration ablation | 1,240 | about $2 |
| judge on both 400-case samples, Haiku 4.5 batch | 800 | about $1 |

The whole of S1 fits in one month's budget with room for re-runs. The As-built record
states the actual spend.

---

## 15. Documents written with this specification

| record | decision |
|---|---|
| 0025 | Scoring targets from the NTSB's code tables: composed occurrence codes, finding codes in two stages against the flagged findings; the scoring modules may read the verdict. Amends 0006 and the ceiling's wording in 0022 |
| 0026 | Slices are fatal / non-fatal first and class second; the fixed samples and the held-out ledger |
| 0027 | The registration rule and the case-number probe measure memorisation |
| 0028 | Prose outputs are graded by a validated judge and are never a bar |
| 0029 | The live board's headline is the finding score; the occurrence code is shown beside it |
| 0030 | Cost is recorded in US dollars from the provider; the per-case cap and the monthly budget are enforced in code |
| 0031 | The default model is GPT-5.6 Luna; the model axis is measured after S3 |

The roadmap's S3 entry gains one line for the model axis, in the same commit. Its S1 entry
is unchanged until close-out. The agency design's §5.4, §6 and §7.2 are taken over here;
that document is marked Superseded when S3's specification is Approved, as it says.

---

## 16. Not in S1

| item | where | why |
|---|---|---|
| docket client, document classification, arm B with the docket | S2 | the docket is S2's whole subject |
| the loop, tools, arm C, the stopping rule in action | S3 | nothing in S1 takes a step |
| the masked condition on real arrival data | S2.5 onward | the recorder has no data yet |
| the model axis: which model gains most from the docket | after S3 | needs arms B and C |
| cause versus contributing factor as a target | later | reported as a slice in S1 |
| live headline in use | S5 | decided here, applied there |
| any store beyond JSON lines under `data/runs/` | S2.5 | the recorder is the first writer of the store |

---

## 17. Risks and open questions

| item | why it matters | handling |
|---|---|---|
| **The probe shows a response shape the design did not expect** (no schema enforcement, no cost in usage, no prompt cache). | Types and cost accounting rest on it. | The probe runs first (§12) and the plan adapts before any type is written; cost falls back to `sources.py` prices and says so. |
| **A batch takes hours or expires.** The window is 24 hours and a batch can end `failed` or `expired`. | A run is not a single sitting. | Submit, poll, collect with the batch ids in the run record; an expired batch is re-submitted for its missing cases only; `--sync` for anything small. |
| **The cheap model cannot follow the two-stage task.** | The bar would be set on a model that fails the format, not the task. | The probe's ten cases show the failure rate; the Sonnet 5 comparison on `dev-400` shows the accuracy gap; Andy decides before any held-out run. |
| **Composed codes that never occur.** | A valid-looking miss. | The "pair unseen" column; the tables are not restricted to seen pairs. |
| **Ten-digit finding scores are low.** | The modifier alone can turn a right item into a miss. | The eight- and six-digit columns explain the misses, and the baseline has a floor at each. |
| **Oversampled fatal cases.** | An unweighted headline would overstate difficulty. | Weighted and unweighted both shown; the weight is a corpus count. |
| **Judge validation fails.** | The prose goes out unchecked. | That outcome is a stated branch of §8; the page labels it. |
| **Held-out looks accumulate.** | Every run is a small tune. | The ledger, and the rule that nothing is settled outside `dev-400`. |
| **Memorisation is not measurable by these two probes.** | A model can recall without the case number or registration. | Stated as a limit; live cases are the real control (S3, S5). |
| **The dictionary lags the data.** | One development item and three event suffixes in use are not in the dictionary (M10). | `scoring/codes.py` reports them; they count as misses; the dataset date is recorded with the tables. |

---

## As built

*Closed 2026-09-17 in pull request #5.*

### Delivered

- **`ntsb-eval`**, the evaluation command (`apps/eval/__main__.py`), with five subcommands:
  `baseline`, `run`, `report`, `judge`, `threshold`. `run` takes `--arm`, `--sample`,
  `--exclude ROLE`, `--include case_number`, `--limit`, `--sync`, `--price-variant`,
  `--cap-usd`, `--budget-usd`, `--resume RUN_ID` and `--out`.
- **The scoring library** under `src/ntsb_probable_cause/scoring/`: `hypothesis.py` (the
  two-stage answer and its strict JSON schemas), `prompt.py` (frozen at `s1-v5`), `codes.py`
  (the NTSB code tables), `metrics.py` (Wilson intervals, paired bootstrap differences,
  top-1/top-3, finding precision and recall at 6, 8 and 10), `samples.py` (the three fixed
  samples, streamed from the parquet store), `runner.py` (the run loop, the batch service,
  resume), `report.py` (slice tables, comparisons, the threshold curve), `judge.py` (the
  prose judge), `ledger.py` (the held-out ledger and the commit state every run records).
- **The batch path** (`model/batch.py`): submit, poll, collect, at half price. Submission is
  never retried, because a duplicate batch is billed and OpenRouter has no cancel endpoint.
- **Resume** (0032): a run that died is continued from the batches it already paid for,
  refusing where a replay would not be faithful.
- **The held-out ledger**, `docs/results/heldout-ledger.md`: one row per run that touched the
  held-out split, with its commit, cost and results file.
- **The results**, all under `docs/results/`, all written by a command: `s1-baseline.txt`,
  `s1-ceiling-dev.txt`, `s1-armA-dev.txt`, `s1-ablations-dev.txt`, `s1-threshold.txt`,
  `s1-model-comparison-dev.txt`, `s1-judge-validation.txt`, `s1-judge-handcheck.csv`,
  `s1-bars.txt`, `s1-heldout-40.txt`, `s1-armA-heldout.txt`, `s1-registration-heldout.txt`,
  `s1-judge-heldout.txt`, `heldout-ledger.md`.

**The bars, on `heldout-400` (399 scored of 400), at commit `c717ab5` (`f037b67` after the
history rewrite, [0036](../decisions/0036-heldout-text-purged-from-history-shas-map-forward.md)):**

| | top-1 | top-3 |
|---|---|---|
| honest baseline, no model | 17.7% [16.6, 18.9] | 35.7% [34.2, 37.1] |
| one-shot ceiling | 10.8% [8.1, 14.2] | 20.3% [16.6, 24.5] |

**The one-shot ceiling is below the no-model baseline, and is published as measured.** It
fixes what "the agent wins" must mean: the bar is the baseline's 17.7%, not the ceiling's
10.8%. Arm A (start facts only) is 8.0 points [4.8, 11.3] below the ceiling on paired cases,
an interval excluding zero, so the investigators' findings do carry information the model
uses — the first measured case for reading the docket at all.

**Total S1 spend: $7.17**, from `month_spent` over every run record — the same accounting the
budget guard reads, so the published figure cannot disagree with what was enforced. Against
$25 a month and the specification's §14 estimate of about $14. Under, because the planned
Sonnet 5 comparison (about $5) was replaced by Gemini 3.1 Flash Lite (about $1) under
[0034](../decisions/0034-cross-model-check-uses-gemini-flash.md). Measured cost per case at
the batch price: **$0.0011**.

### Done means, with evidence

1. **Saved responses parsed in tests; probe cost recorded** — met —
   `tests/fixtures/openrouter/{structured,tool_call,two_turn,batch}.json`, parsed by
   `tests/test_openrouter.py::test_parse_structured_reply_from_saved_response`,
   `::test_parse_tool_call_reply_from_saved_response`,
   `::test_parse_two_turn_reply_from_saved_response` and
   `tests/test_batch.py::test_wait_polls_until_terminal_and_parses_results`. Probe cost per
   case **$0.0011**, recorded above and in `tests/fixtures/openrouter/README.md`.
2. **Baseline reproduces the spike within one point, and reports the honest baseline** — met
   — `docs/results/s1-baseline.txt`: reproduction top-1 16.4% [14.2, 18.8] and top-3 32.4%
   [29.6, 35.4] against the spike's 16.2% and 32.2%; honest baseline over all 4,241 held-out
   cases, top-1 17.7%, top-3 35.7%. Written by `ntsb-eval baseline --out`.
3. **`make bars` produces the three runs with counts, intervals and cost** — met —
   `docs/results/s1-bars.txt` (heldout-400 ceiling, and the paired difference against arm A),
   `docs/results/s1-heldout-40.txt` (heldout-40 ceiling), `docs/results/s1-armA-heldout.txt`
   (arm A's own table). Each carries its run id, commit, per-slice counts, Wilson intervals
   and cost. The three tables are in three files rather than one; see Departures.
4. **Per-step scoring on the scripted trail** — met —
   `tests/test_scripted_trail.py::test_three_step_trail_is_scored_step_by_step`, with
   `tests/test_metrics.py::test_trail_scores_by_hand`.
5. **Registration decided by the §9 rule; phase ablation, case-number probe and the model
   comparison reported on `dev-400`** — met — `docs/results/s1-ablations-dev.txt` (phase
   withheld, case number supplied) and `docs/results/s1-model-comparison-dev.txt`.
   **The registration stays a start fact.** The rule in §9 and
   [0027](../decisions/0027-registration-rule-and-case-number-probe.md) is "interval includes
   zero: it stays"; withholding it moved top-1 by −2.0% [−5.2, +1.0] on `dev-400`
   (`s1-ablations-dev.txt`) and +0.3% [−2.8, +3.0] on `heldout-400`
   (`docs/results/s1-registration-heldout.txt`), every interval including zero. That is the
   held-out confirmation 0027 required, and the decision is recorded here because the plan
   that first carried it is deleted at close-out.
6. **The threshold recorded with its curve, from `dev-400`** — met —
   `docs/results/s1-threshold.txt`, which names its run and sample in a provenance header,
   gives the full 0.05 to 0.95 curve with the number of cases answered at each point, and
   states that the chosen threshold is **not a usable operating point**: no case is answered
   at 0.95, so the policy answers nothing and scores what always abstaining scores. Below 50%
   accuracy no threshold can be worth answering at.
7. **Judge validation and the hand-check committed; prose reported on `heldout-400`** — met —
   `docs/results/s1-judge-validation.txt` (agreement 346/401 = 86.3% against the 62.5%
   threshold, and a 30-case hand-check whose marks put the judge's errors on both sides:
   **validated**), `docs/results/s1-judge-handcheck.csv` (30 rows, case ids and verdict text
   removed), `docs/results/s1-judge-heldout.txt` (399 cases, agreement 83.0%, 37 generous and
   31 harsh). The judge is a secondary measure only ([0028](../decisions/0028-prose-graded-by-validated-judge-never-a-bar.md)).
8. **The ledger lists every held-out run, and nothing else touched the split** — met —
   `docs/results/heldout-ledger.md`, five rows. Enforced by
   `scoring/ledger.py::refuse_if_heldout_and_dirty`, tested by
   `tests/test_ledger.py::test_heldout_refused_when_dirty` and
   `tests/test_eval_app.py::test_judge_on_a_heldout_run_from_a_dirty_tree_is_refused`; sample
   purity by `tests/test_contamination.py::test_s1_samples_are_split_pure_and_disjoint` and
   `::test_evaluation_cases_are_held_out_by_event_date`; the case-number probe's double guard
   (sample *and* the record's own event date) by
   `tests/test_runner.py::test_case_number_probe_included_on_a_development_sample_and_case`.
9. **No run exceeded its budget flag; the total spend is stated** — met — total **$7.17**,
   stated above. Refusals tested by `tests/test_runner.py::test_budget_refusal_before_any_call`,
   `::test_over_cap_case_is_failed_without_a_call`,
   `tests/test_judge.py::test_judge_run_refuses_over_budget_before_any_call`. **Read with the
   departure below**: the guard is per-process and does not hold across concurrent runs.
10. **CI green, documentation check passes, closed out under 0017** — met — this pull
    request's close-out commit; `uv run python -m scripts.check_docs` clean.

### Departures from this specification

- **The prompt was frozen at `s1-v5`, not `s1-v1`.** The first ceiling attempt failed its
  schema check on 249 of 401 cases. The stage-1 schema offered `item8`, the finding's item
  code, which stage 1 is never shown the list for and could not answer. `_stage1_schema()`
  now prunes it. Re-measured: 0 schema failures in 401. The prompt *text* is unchanged from
  v4; the version moved because the schema is part of what elicits an answer.
- **The cross-model comparison used Gemini 3.1 Flash Lite, not Sonnet 5**, on cost
  ([0034](../decisions/0034-cross-model-check-uses-gemini-flash.md)). Result: Gemini top-1
  12.5%, top-3 **22.9%**, against Luna's 8.7% and **22.9%** — top-3 identical to the decimal,
  no format failures on either. The task is hard, not the model weak, which is what the check
  exists to establish. The top-1 gap is abstention, not judgement: Gemini abstains on 1.5% of
  cases against Luna's 22.9%, and on the cases each chose to answer they are 11.3% and 12.7%.
- **Two candidate models could not run at all**, and are recorded because the check's value
  depends on what it rejected. `google/gemini-3.5-flash-lite` refused every request, because
  our stage 2 ends on a model turn. `z-ai/glm-5.3-flash` could not answer inside the
  2,000-token output cap: 376 of 401 stage-1 replies unusable, 287 of them empty at exactly
  the cap. "Flash" in a model name does not mean non-reasoning.
- **A smoke test drawn from the head of a sorted sample is not representative.** `--limit N`
  takes the *first* N cases; the first ten `dev-400` cases are short enough to pass, so the
  GLM check reported 10 of 10 while the true failure rate was 94%. Any future model
  comparison must probe `finish_reason` on a random sample before committing spend.
- **The three held-out runs were launched in parallel**, not sequentially as `make bars`
  runs them. At the queue times seen the day before, sequential would have taken most of the
  day. `heldout-ledger.md` was created and committed with its header first, because
  `append_row` writes the header only when the file is absent and two runs finishing together
  could otherwise race and lose a row.
- **Reports were generated from explicit run ids, never `--latest`.** `resolve_latest`
  matched only on sample and arm, so it returned the registration ablation for
  `--latest ceiling heldout-400`; `make bars` would have published the ablation as the bar.
  Fixed to read each candidate's own record, and to refuse rather than guess when candidates
  span several models. The published bars were never affected.
- **The three bars tables are in three files**, not one: `s1-bars.txt` carries the
  heldout-400 ceiling and the paired difference against arm A, with `s1-heldout-40.txt` and
  `s1-armA-heldout.txt` beside it. A paired difference carries no counts, intervals or cost,
  so arm A needed its own table to satisfy §13.
- **The judge's narrative dimension gained a fourth label**, `less_detailed`
  ([0035](../decisions/0035-judge-narrative-gains-a-less-detailed-label.md)), after the first
  pass put 159 of 178 cases in `contradicts`. A separate defect was fixed at the same time and
  was a bug, not a decision: the judge was never shown the model's occurrence codes, so its
  `lay` dimension measured our own rendering on 158 of 178 cases. The first pass was discarded.
- **Withheld held-out text had been committed and is purged from history**
  ([0036](../decisions/0036-heldout-text-purged-from-history-shas-map-forward.md)). Two fixture
  sheets held the NTSB's cause and finding codes for 40 held-out cases and the investigator's
  factual account for 30 — and the 40 are `heldout-40` itself. The purge rewrote every commit
  after `2e647c0`, so 0036 carries the old-to-new SHA mapping and is the provenance record
  where a recorded `commit_sha` no longer resolves.
- **Stage pull requests are merged, not squashed**
  ([0033](../decisions/0033-stage-pull-requests-keep-their-commits.md)), superseding
  [0018](../decisions/0018-squash-merges-and-tag-only-releases.md) on that point and
  the plan's own closing step. A squash would leave every recorded commit SHA unresolvable.
- **Known defects, found by the close-out review and knowingly not fixed** (Andy's ruling:
  fix five, log the rest). The monthly budget guard is per-process: `month_spent` is read once
  at startup and a run records its cost only when it finishes, so runs launched together each
  see zero spent — four launched seconds apart on 2026-09-17 each projected $20 against a $25
  budget, though actual spend was about $1.30. The per-case cap estimates prompt size only and
  ignores output tokens entirely. A re-judge that dies mid-pass truncates the previous paid
  pass. An expired recorded batch makes a run permanently unresumable. Precision and recall
  are averaged over different denominators (394 and 381) than the row's printed `n` (399), and
  an answered case with no usable finding code is dropped from precision while an honest
  abstention scores 0.0. Failures are excluded from every accuracy denominator. `--against` on
  two runs with no shared cases prints `+0.0% [+0.0%, +0.0%] on n=0`. `baseline --sample
  dev-400` prints a table of `0.0%` figures over zero cases. The boundary test that proves
  withheld text never reaches a system prompt covers only the sync path, though the batch path
  is the default — that one should be closed first in S2.

### Decisions taken during the stage

- [0032](../decisions/0032-a-batch-run-is-resumable-from-its-recorded-batches.md) — A batch run
  is resumable from the batches it already paid for.
- [0033](../decisions/0033-stage-pull-requests-keep-their-commits.md) — Stage pull requests are
  merged, not squashed, so a recorded commit resolves.
- [0034](../decisions/0034-cross-model-check-uses-gemini-flash.md) — The cross-model sanity
  check uses Gemini 3.1 Flash Lite, not Sonnet 5.
- [0035](../decisions/0035-judge-narrative-gains-a-less-detailed-label.md) — The judge's
  narrative dimension gains a fourth label, "less detailed".
- [0036](../decisions/0036-heldout-text-purged-from-history-shas-map-forward.md) — Withheld
  held-out text is purged from git history; the runs' recorded SHAs map forward.

### Implementation record

- Pull request: #5 (https://github.com/floyda/ntsb-probable-cause/pull/5)
- Plan, at its last commit:
  https://github.com/floyda/ntsb-probable-cause/blob/dfd7127/docs/plans/2026-09-15-s1-scoring-and-evaluation.md
- Commits: `ccbfe31`..`dfd7127`, plus this close-out commit
- Release: v0.2.0 (tag created by Andy after the merge; 0018 as amended by 0033)

---

## Glossary

- **Ablation.** A run with one input removed, on the same cases, to measure what it was
  worth.
- **Answering pass.** The model turns that produce one Hypothesis: the answer, then the
  finding refinement. No tools.
- **Arm.** One way of giving evidence to the model: A, start facts only; B, every tool once;
  C, the loop (0022). In S1 an arm is an exclusion set.
- **Bar.** A number, set before the agent exists, that the agent must beat.
- **Calibration.** Whether stated confidence matches observed accuracy.
- **Case-number probe.** A development-split run with the case number in the payload, to
  measure recall of published reports.
- **Ceiling (one-shot).** The best a single answering pass with every structured evidence
  role can do; arm B without the docket.
- **Confidence interval.** The range of true values a sample result is consistent with;
  95% here.
- **Data dictionary.** The NTSB's table of every code and its meaning, inside the public
  `avall.zip` download.
- **Event suffix.** The last three digits of an occurrence code: what happened.
- **Exclusion set.** The evidence roles removed before the payload is built.
- **Finding code.** Ten digits in five pairs, the NTSB's coding of why: an eight-digit item
  and a two-digit modifier.
- **Flagged findings.** The findings the NTSB marked as in the probable cause.
- **Hypothesis.** The model's structured answer: codes with probabilities, cause, narrative,
  explanation, confidence and abstain flag.
- **Ledger.** The committed list of every run that touched the held-out split.
- **Modifier.** The last two digits of a finding code: who or what, with the same meaning
  everywhere.
- **Occurrence code.** Six digits, phase prefix plus event suffix, the NTSB's coding of what
  happened. The primary one belongs to the defining event.
- **Paired difference.** The mean per-case difference between two runs on the same cases,
  with a bootstrap interval.
- **Phase prefix.** The first three digits of an occurrence code: when in the flight.
- **Report flavour.** The NTSB's label for the form of the final report: basic, standard or
  detailed.
- **Start facts.** The evidence a live case has on day 1 (0023).
- **Step record.** One row per step of a trail, wrapping a Hypothesis with what was done and
  what it cost.
- **Trail.** The ordered hypotheses for one case; length one for a one-shot run.
- **Wilson interval.** A confidence interval for a proportion that behaves at small counts.
