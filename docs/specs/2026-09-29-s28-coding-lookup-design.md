# S2.8 — Coding lookup: design

*Drafted 2026-09-28/29 from a design session with Andy, while S2.7 was finishing its guidance
rounds. Status: Draft (awaiting Andy's review).
This is the specification for build stage S2.8, a stage added between S2.7 and S3 of
`docs/specs/2026-09-12-architecture-and-roadmap.md` §11. It records what S2.8 builds and
measures, why, the decisions it takes, and the condition for moving on. The implementation
plan is written from it separately, in `docs/plans/`.*

**How to read this.** Each section says what is done, then why, with an example where one
helps. Terms in **bold** on first use are in the glossary at the end. Numbers are of three kinds,
and each is labelled:

- **scripted** numbers cite the committed script and results file that produced them;
- **ad-hoc** numbers were counted during the design session by the throwaway scripts kept in
  `scripts/exploratory/s28_*.py`. They are not citable. S2.8's committed scripts re-derive
  every one of them before it is relied on (§3.3, §9);
- **estimates** are arithmetic, and are replaced by measured figures in the As-built record.

Nothing here is a result: S2.8 produces the results.

Decision records written with this specification: 0130 to 0134 (§12). S2.7 holds the block
from 0093 to the number before 0130 (its track 1 may still write records below 0120, and track 2
holds 0120 and the nine after it), so S2.8 starts at 0130.

**Depends on S2.7.** S2.8 works on top of whatever S2.7 ends with: its kept guidance, its
ordering check (Luna, decision 0096, confirmed by 0103), the table fix of decision 0105, and
S2.7's final `dev-400` runs. It changes none of them. Nothing in S2.8 opens `dev-seal-400`,
which belongs to S2.7's final check (decision 0095).

---

## 1. What S2.8 is for

Findings are arm B's weakest score. On `dev-400` the model finds about one in nine of the
findings the NTSB flagged as part of the probable cause (finding recall@10 10.4% on B-v1,
scripted, `docs/results/s26-armB-v2-dev.txt`). The no-model baseline, which gives the same three
codes to every case with the same phase and weather, finds about one in five on held-out cases
(recall 23.2%, scripted, `docs/results/s1-bars.txt`).

A design-session look at the recorded answers (ad-hoc, `scripts/exploratory/s28_design_lookup_keys.py`,
on the repeat run after the Luna check, `20260927T111202-fbab38a-dev-400-B-check-luna`) shows
why. The model found 122 of 1,110 flagged findings. The NTSB's commonest finding, "Aircraft
control / Pilot" (0206304044), is flagged in 138 of 397 cases; the model gives it once. The model
gives "Incorrect action performance / Pilot" (0204101544) 167 times; the NTSB flags it 22 times.
The NTSB flags findings with modifier 20 ("Not attained/maintained") 202 times; the model uses
it once. The model gives 1.7 findings a case; the NTSB flags 2.8.

**The table is stronger than the model.** The same look asked how many of the NTSB's flagged
findings a plain table would find, with no model call: the three findings the NTSB flagged most
often in past cases like this one (ad-hoc, the same script; three `dev-400` runs gave the same
picture):

- the model's own findings: recall 10–12%;
- the pool's top three for the case's phase group (evidence only): 30.0%;
- the pool's top three for the **model's own first occurrence code**, falling back to its event
  and then to the phase group below 20 pool cases: **about 34.5%**, with precision 28% against
  the model's 17%;
- the same keyed on the NTSB's true defining code (a cheat, an upper limit only): 39.7%.

So a lookup is not a small hint to the model. It is a strong opponent, and the question S2.8
answers is whether the model, reading the evidence, can do better than the table does alone.
That is decision 0096's rule for the ordering check — a model must beat the plain rule —
applied to findings.

**What else was tried** (ad-hoc, `scripts/exploratory/s28_design_examples_and_retrieval.py`
and `s28_design_memory.py`, Round 3's checked run, three findings a case):

- adding the weather condition or engine type to the key: 35.5% and 34.6%;
- **retrieval (RAG)**: the 25 or 100 past cases whose factual narrative shares the most
  distinctive words with the model's own evidence narrative, their flagged findings counted:
  36.6%; using past probable-cause sentences instead: 33.7–36.4%;
- **a memory of the model's own answers** ("when the model said X, the NTSB flagged Y"),
  learned from four fifths of `dev-400` and scored on the rest: 33.5%. Size-matched, it is level
  with the table: on the cases the memory could answer, 32.4% against 31.7% for a table built
  from the same number (320) of pool cases, and 32.2% against 32.5% on a second run.

Every data-only method lands between 34% and 37%, and even the cheat reaches only about 40%.
Beyond that, a gain must come from the model choosing among the table's lines with the evidence
in view.

**Why before S3.** Decision 0022 says arm B is every tool the loop has, in a fixed order, and
the loop must beat it at equal cost. If S3's loop is to have a coding lookup, arm B needs its
fixed version first, measured before any loop code exists. S2.8 builds that fixed version, and
its result decides whether S3 has the tool at all (§8).

**What S2.8 is not.** No agent loop. No held-out case is read, scored or fetched. No open-split
case is used. No change to how the occurrence is answered: that is S2.7's ordering check. No
worked examples or case text reach the model (the rule of 0098 item 2). No similar-case
retrieval (RAG): it is written down as a candidate declared experiment for S3 (§11).

---

## 2. The stage in one page

- **The table** (§3): for each occurrence code, the findings the NTSB flagged in past pool
  cases with that defining code, with counts. Built once from the statistics pool of 0094,
  committed as a table of codes and counts.
- **The memory** (§4): arm B's answers on a drawn development sample of 401 cases, outside
  both samples, and what the NTSB flagged in those cases: "when the model's first occurrence
  was X, the NTSB flagged Y in K of N". Batch 1 of three is drawn and its dockets are fetched.
- **The step** (§5): a third turn in arm B's own conversation, run as a pass over a finished,
  checked arm B run. The model sees everything it saw before, its own answer, and the table
  (and, in the second way, the memory lines), and gives its final findings: one to five, from
  a closed list.
- **The test** (§6): on two existing checked `dev-400` runs, the model with the table must beat
  the plain table at the same count, case by case; memory must then beat the model with the
  table. Registered before the first paid pass, with predictions.
- **After** (§8): the result fills two slots in S3: whether the loop has a coding-lookup tool,
  and what arm B's fixed call is.
- **Cost** (§9): at most about $3.70 at uncached prices with one memory batch ($6.30 with
  three), spent in order, so a failed first step stops the spend at about $1.20.

---

## 3. The table

### 3.1 What it holds

`scripts/finding_stats.py` builds, once, from the statistics pool (decision 0094: every
development case in classes C, F and L outside `dev-400` and `dev-seal-400`, about 12,460 cases
with codes and flagged findings, ad-hoc):

- for each **defining occurrence code** (six digits), the number of pool cases with that
  defining code, and the twenty flagged findings (ten digits) most often in their probable
  cause, with counts;
- the same for each **event suffix** (three digits), summed over phases;
- the same for each **phase group** (the `cicttPhaseSOEGroup` the model already has as
  evidence);
- each split into 2009–2014 and 2015–2019, so a habit that changed is visible, as in
  `s27-coding-stats.txt`.

It writes `src/ntsb_probable_cause/scoring/tables/finding_stats.json` (codes and counts only)
and `docs/results/s28-finding-stats.txt`, a readable print of the commonest keys with their
labels. It reuses `scripts/coding_stats.py`'s pool and its refusal (`check_pool`), and its
exclusion list: it never widens or narrows the pool. S2.7's `coding_stats.json` is not changed.

### 3.2 The key, and what one case's table is

For one case:

1. The key is the model's **first occurrence code after the ordering check**: the code that
   will be scored as its top-1.
2. If fewer than **20** pool cases have that defining code, the key falls back to its event
   suffix; below 20 again, to the case's phase group; below 20 again, to the whole pool.
3. The case's table is the key's **eight** most often flagged findings, each with its full
   ten-digit code, its label (category, item and modifier, in words) and its count, "flagged in
   K of N past cases".
4. Wording follows decision 0101: a line holding at least 60% of at least 20 cases is stated
   as a habit ("the NTSB usually flagged…"); every other line is a count only, and the text
   says the evidence decides.

**Why the model's code, not the evidence alone.** The key is something the model says
itself, so S2.7's Round 4 trap does not apply: that trap was counts that rested on what the
NTSB would code, which the model cannot know. This table says "if you are right that it is X,
the NTSB usually flagged Y". The price is that a wrong occurrence looks up the wrong findings:
about 5 points (34.5% against the cheat's 39.7%, ad-hoc). The phase group alone costs about 4.5
points more (30.0%).

**Why eight lines.** The most a perfect chooser could reach from the table plus its own
findings is 49% with five lines, 55% with eight and 58% with ten (ad-hoc,
`s28_design_grounding.py`). Eight keeps most of that without asking the model to read a long
list; each line is about 40 tokens.

**Why twenty cases.** The same line 0094 and 0101 use for a count worth acting on.

**Example** (ad-hoc pool counts; labels shortened). The model's first code is "Landing roll /
loss of control on ground"; 985 pool cases have it as the defining code:

- Directional control, not attained/maintained: flagged in 773 of 985 (78%, a habit);
- Aircraft control / Pilot: 698 of 985 (71%, a habit);
- Aircraft control / Student pilot: 83 of 985;
- Decision making/judgment / Pilot: 49 of 985;
- Incorrect action performance / Pilot: 36 of 985;
- and three more.

### 3.3 Re-deriving the design figures

`scripts/finding_stats.py --design-check` recomputes, from the committed table and the named
`dev-400` runs, the figures §1 and §3.2 quote (model recall, table recall at 3, 5 and 8 lines,
the fallback shares). Its output goes into `docs/results/s28-finding-stats.txt`. Where it
differs from an ad-hoc figure in this specification, the scripted figure is the one cited from
then on.

---

## 4. The memory

### 4.1 The memory sample

Three **batches** of development cases, each drawn by `samples.draw` exactly as `dev-400` was
(200 fatal and 200 non-fatal, each split by class C, F, L in proportion, which gives 401):

- batch 1 with seed 20260928, excluding `dev-400` and `dev-seal-400`;
- batch 2 with seed 20260929, excluding those and batch 1;
- batch 3 with seed 20260930, excluding those and batches 1 and 2.

`scripts/draw_memory.py` draws them and commits each list as
`tests/fixtures/eval/dev_memory_<n>_ids.csv`; a `--verify` mode re-draws from the processed file
and compares (as `draw_sealed.py` does). The samples are named `dev-memory-1`, `-2` and `-3`.

**Batch 1's dockets are already fetched** (2026-09-28/29, `scripts/exploratory/s28_memory_fetch.py`,
free): 401 of 401 cases, no failures, 5.2 GB in the docket cache (a mean of 13 MB a case, a
median of 4 MB, the largest 0.8 GB). The draw script must reproduce that list; if it does not,
the build stops and says so.

**Batches 2 and 3 wait for disk space.** After batch 1 the disk had 23.2 GB free. Batches 2
and 3 need about 10.4 GB together at batch 1's rate (estimate), which would leave about 12.8 GB,
under the fetch's own 15 GB guard. Andy decides whether space is freed or another disk is used
(the cache location is `NTSB_DOCKET_DIR`). The memory is built from the batches fetched when
the registration (§6.4) is committed, and the registration names them.

### 4.2 The memory's answers

Arm B runs on each fetched batch with **S2.7's final setup** (model, reasoning level, prompt
version, kept guidance, reply budget), then the kept ordering check runs over it, exactly as on
`dev-400`. Estimate: about $1.20 a batch for arm B and $0.12 for the check (Round 3's costs).

### 4.3 What the memory holds and shows

For each **first occurrence code the model gave after the check** in the memory sample: the
number of memory cases where it did, and the findings the NTSB flagged in those cases, with
counts. A code with fewer than **5** such answers has no memory lines.

The key matches the table's, so the two sit side by side. The design session also tried a
memory keyed on the model's own findings ("when the model gave finding Y…"): 29.8% against 33.5%
(ad-hoc), so it is not built.

A case's memory lines are the memory's five commonest findings for its key, shown beneath the
table:

    In 23 past answers where this model's first occurrence was Landing roll / Loss of control
    on ground, the NTSB flagged:
      Directional control, not attained/maintained -- in 17
      Aircraft control / Pilot -- in 15
      ...

(An invented example of the form; the numbers are not measured.)

**Why a memory at all.** The table assumes the model's occurrence is right. The memory learns
the model's habits: if the model often says "stall" where the NTSB coded "loss of control",
the memory returns loss-of-control findings for "stall". The room it could close is the gap
between the table and the cheat key, about 5 points. At 320 answers it was level with a
size-matched table (§1), so whether it helps at 401 or 1,203 answers is exactly what S2.8 tests.

### 4.4 The memory goes stale

A memory describes one model with one setup. It records its source runs and their setup. The
step **refuses** a memory built on another model or reasoning level. It **prints** any difference
in prompt version, guidance or check between the memory's runs and the answer set it is applied
to, and the result carries that line. On the live board a memory would be rebuilt from resolved
predictions of the setup that is running (§11); that is not built here.

---

## 5. The step: a third turn

### 5.1 Where it sits

Arm B answers each case in two turns (decision 0025): turn 1 the answer, turn 2 the finding
items. Both send the full evidence and docket (a median of about 27,000 prompt tokens for the
two turns, $0.0030 a case at batch prices, ad-hoc from Round 3's run). The ordering check then
runs over the finished run as a pass (decision 0096).

The lookup is **turn 3**, run as a pass over a finished, checked run, like the check: a derived
run folder `<checked run id>-lookup-<way>`. It never changes turns 1 and 2 or the check.

**Why a third turn (Andy's choice, A2), not a short separate call or a change to turn 2.** The
step exists to choose between table lines using the evidence ("the flare was misjudged" against
"the flare was not reached"; "pilot" against "student pilot"), and only a turn that sees the
evidence can do that. It is also the shape of the S3 tool: in the loop, the table would arrive as
a tool result in a conversation that already holds the evidence. A separate short call like the
check (about $0.20 a `dev-400` pass) would choose blind wherever the model's narrative left the
deciding fact out. Folding the table into turn 2 would key it on the unchecked occurrence and
need a new arm B run for every test, with run-to-run variation that hides the effect (checked
top-1 ranged 26.6%–31.3% across `dev-400` runs, S2.7).

### 5.2 What turn 3 sends

For each case:

1. **The evidence**, rebuilt through `split_record` and the docket attachment exactly as the
   answering run built it, from the docket cache. Its fingerprint must equal the
   `payload_fingerprint` the run recorded; if it does not, the case is **refused**, counted and
   reported, never answered on different evidence.
2. **The model's earlier answer**, as an assistant turn. The run keeps the parsed final answer
   (narrative, codes, items), not the raw text of turns 1 and 2, so the answer is rendered as
   JSON from the stored hypothesis. Its content is the model's; the wording of the rendering is
   ours. Every derived run records this. (The batch ids are recorded, but S2.8 does not assume
   the provider still holds those replies: rule 2.)
3. **The checked first occurrence code**, stated, because the table is keyed on it.
4. **The table** (§3.2) and, in the memory way, the memory lines (§4.3).
5. **The instruction**, committed as its own file,
   `src/ntsb_probable_cause/scoring/lookup/turn3.md`: the lines are how the NTSB coded past
   cases, not facts about this case; choose the findings the evidence supports; give one to
   five; choose only from the list.

Never the verdict, the factual or analysis narrative, or any case's text but this one's
evidence. The table and memory hold codes, labels and counts only.

### 5.3 What the model may answer

- **Findings only.** The occurrence codes stay as the check left them. The narrative, probable
  cause, lay explanation and confidence are unchanged.
- **A closed list**: the table's eight lines, the memory lines, and the model's own findings
  from turns 1 and 2. Every one is a full ten-digit code, so no item turn is needed. Inventing
  other codes would make the step a second analysis, not a lookup.
- **One to five findings** (Andy's choice). The count is not forced: whether seeing the table
  stops the model under-giving (1.7 a case today against the NTSB's 2.8) is measured (§6.3).
- A strict JSON schema: a list of one to five entries, each a code from the list and a
  probability. A reply that breaks it is retried once with the reason; if it fails again the
  case keeps its earlier findings, and the step's note says so (as the check does).

### 5.4 How it is recorded and run

- One `StepRecord` per case, tool `coding_lookup`, with the key used and its level (code,
  event, group, pool), the lines shown, the memory lines shown, the findings chosen, the
  evidence fingerprint and the cost. The earlier findings stay on the earlier step.
- Finding scores are recomputed (a `rescore_findings` beside `rescore_occurrence`);
  occurrence scores are copied and must come out identical, which the report checks.
- **Batch price** (no latency need), the agent's model and reasoning level, the 8,000-token
  reply budget (0084). The client records **cached tokens** on every call; the budget estimate
  assumes none (§9).
- Refusals before any spend, as `checkpass.preflight` does: not a development arm B run; not
  checked; a `dev-seal-400`, held-out or open case; a folder that exists; a memory from another
  model or reasoning level. The budget reservation is made only after every refusal has passed,
  and settled when the pass ends or stops.
- `ntsb-eval lookup RUN_ID --way table-model|table-memory-model [--memory SAMPLE...]`.

---

## 6. The test

### 6.1 The four ways

All on the same answers of one checked `dev-400` run:

1. **No lookup**: the checked run as it is.
2. **The plain table**: for each case, the table's top *N* lines as the findings, where *N* is
   the number the model gave in way 3 on that case. No model call. Computed by the report.
3. **The model with the table** (`table-model`).
4. **The model with the table and memory** (`table-memory-model`).

**Why count-matched.** Recall rises with every finding given, and precision falls. Giving the
plain table the model's count on each case means neither can win by giving more; at equal
counts, more hits is better on recall and precision alike.

### 6.2 The two answer sets

Each way runs on **two existing checked runs**, so no new `dev-400` arm B run is needed:

- **set 1**: the checked run of S2.7's final setup (Round 3's,
  `20260928T144353-031e97e-dev-400-B-check-luna`, unless a later round is kept, in which case
  that round's checked run);
- **set 2**: the checked run before it in the kept line (for example the repeat,
  `20260927T111202-fbab38a-dev-400-B-check-luna`).

Each set is paired within itself, so the two need not share a setup. The registration names
both.

**Why two.** S2.7 found that one pair of identical runs understates how much results move
(Round 4's note). A lucky gain on one set is what the second set catches.

### 6.3 The reading rule (decision 0133)

- **Decides:** flagged finding recall, exact to ten digits, paired, with its interval.
- **The model step is kept** if way 3's gain over way 2 has a lower interval bound above zero
  on **both** sets. Otherwise, if way 2 beats way 1 on both sets, **the plain table** goes
  forward. Otherwise nothing is kept.
- **Memory is kept** if way 4's gain over way 3 has a lower interval bound above zero on both
  sets.
- **In order.** Way 3 runs first, on both sets. Memory's arm B runs (§4.2) and way 4 run only if
  the model step is kept. So a failed first step stops the spend.
- **Printed beside, never deciding:** precision; the count given (mean and spread, against the
  NTSB's); recall at eight and six digits; fatal and non-fatal separately; the fallback level
  used; the refused cases; cached tokens; occurrence top-1, which must be identical to the
  checked run's.

**Power.** Two identical runs differ in finding recall by −0.9% [−2.6%, +0.8%], with a per-case
spread of 17 points; comparisons involving the table spread 19–25 points (ad-hoc,
`s28_design_grounding.py`). At about 397 cases a gain of about **3 points** is the smallest this
sample can reliably show (80% power). A smaller real gain will read as "not kept", and the result
says so.

### 6.4 The registration and the predictions

Before the first paid pass, `docs/rounds/s28-lookup.md` is committed, naming: the two answer
sets; the table's commit; the instruction file's hash; the memory batches and their runs; the
reading rule; the cost estimate; and the predictions below. `ntsb-eval lookup` refuses to run
from a tree where it is missing or uncommitted (the same check S2.7's rounds use). Results are
appended below it by `scripts/lookup_result.py`.

The predictions (decision 0133), published whichever way they come out:

- **P1.** With the table in view, the model gives between 2.5 and 3.5 findings a case on
  average, against 1.7 today.
- **P2.** The model with the table beats no lookup by at least 15 points of finding recall on
  both sets.
- **P3.** The model with the table beats the count-matched plain table by less than 3 points on
  each set, so it may not be kept.
- **P4.** Memory adds less than 2 points over the model with the table.

---

## 7. Tests and continuous integration

- **The table is clean**: `finding_stats.py` refuses, and a test proves it refuses, any case
  from `dev-400`, `dev-seal-400`, held-out or open (it reuses 0094's `check_pool`).
- **The memory is clean**: a memory built from any case in the sample it is applied to, or from
  `dev-seal-400`, held-out or open cases, is refused, and a test proves it. The memory samples
  share no case with `dev-400` or `dev-seal-400` (checked on the committed lists in CI).
- **The draw is reproducible**: `draw_memory.py --verify`, run locally, as for the sealed sample.
- **No case text in the table, the memory or the instruction**: a test fails on any
  case-number pattern; the instruction passes `scripts/check_guidance.py`.
- **Turn 3's boundary**: a test captures the body actually sent and checks it holds only this
  case's evidence (by fingerprint), the rendered earlier answer, codes, labels and counts (0016,
  layer 5); a mutation test proves the check can fail.
- **The fingerprint refusal**: a case whose rebuilt evidence differs is refused, not answered.
- **The closed list**: a reply naming a code outside the list is rejected.
- **The count-matched plain table** is computed as §6.1 says (tested on a small hand example).
- **Refusals**: the lookup refuses held-out, open, sealed and unchecked runs, and a missing or
  uncommitted registration.
- `scripts/check_docs.py` and `make check` pass.

---

## 8. After S2.8: the slots it fills in S3 (decision 0134)

S3's design can start before S2.8's result. Two slots in it are filled by that result:

1. **Whether the loop has a coding-lookup tool.**
   - If **the model step is kept**: `coding_lookup` is a tool the loop may call once it holds a
     hypothesis. Its result is the table (and the memory lines, if memory was kept) for the
     loop's current first occurrence code, in the form of §3.2.
   - If **only the plain table** is kept: no tool. The table's top lines become a fixed step
     after the answer for every arm alike, because there is nothing to choose.
   - If **nothing** is kept: no tool and no step.
2. **Arm B's fixed call** (decision 0022: every tool the loop has, in a fixed order). With the
   tool, arm B is: answer (turns 1 and 2), the ordering check, then the lookup turn, exactly as
   S2.8 ran it. Its cost per case, and the bar S3 must beat, are measured with that turn in
   place.

**The lookup's result is not evidence about the case.** Decision 0023 says every tool result
goes through `split_record`. This tool returns other cases' coding habits as counts, not this
case's record, so it is kept apart from evidence payloads, as the conversation already keeps the
agent's own output apart. S3's tool design records that as an explicit exception, and the
provenance check must not count it as evidence.

---

## 9. Cost and budget

Estimates at uncached prices, from Round 3's costs:

| step | estimate |
|---|---|
| the table, the draw, the design check | free |
| way 3 (the model with the table) on two sets | about $1.20 |
| memory's arm B and check, per fetched batch (only if way 3 is kept) | about $1.30 |
| way 4 on two sets (only if way 3 is kept) | about $1.20 |

The most it can cost is about $3.70 with one memory batch, and about $6.30 with all three. If
the model step is not kept, it stops at about $1.20. Any caching the provider applies comes off
these figures; the first pass shows how much.

**A $10 stage line**, counted by commit from S2.8's first commit, as S2.7 counts its own
(`scripts/stage_spend.py` gains the stage's first commit as a parameter). The monthly budget of
0083 applies separately: September 2026 had about $4.50 left of its $50 (0104) when this was
written, so the paid passes are expected in October.

---

## 10. Branches, plan and build order

- **`s28-coding-lookup`**, cut from `s27-guidance` at `c590e44` (S2.7 Round 5 registered), holds
  this specification, its decision records and the build. It merges `main` (merge commit) once
  S2.7's stage pull request has merged, before its own pull request.
- **One plan** in `docs/plans/`, naming this specification on its `**Spec:**` line; deleted at
  close (0017).
- **One stage pull request**, `S2.8: coding lookup`, merged with a merge commit (0033); one
  As-built record; one release.
- **Paid passes** start only from a clean, committed tree, with `NTSB_DATA_DIR` pointed at the
  main checkout's `data/` (0057), and only on Andy's go-ahead.

Build order:

1. This specification and decisions 0130–0134.
2. `finding_stats.py`, its table and its tests; the design check (free).
3. `draw_memory.py`, the three lists, `--verify` against batch 1's fetched cases (free).
4. The turn-3 step: the rebuilt evidence and its fingerprint refusal, the rendered answer, the
   table and memory lines, the closed-list schema, the derived folder, the preflight and budget,
   `rescore_findings`, `ntsb-eval lookup`, and the tests of §7.
5. `lookup_result.py`: the four ways, count-matched, both sets, the reading rule of §6.3.
6. The registration `docs/rounds/s28-lookup.md`; Andy's go-ahead; way 3 on both sets.
7. Only if way 3 is kept: memory's arm B and check runs, the memory, way 4 on both sets.
8. Close-out (`close-stage` skill).

---

## 11. Not in S2.8, and written down for later

- **Similar-case retrieval (RAG)** gained about 2 points over the table (ad-hoc, §1), within
  what `dev-400` can show. It needs other cases' narratives as its search index, which the
  roadmap allows only as a declared experiment with its own contamination test (§10 of the
  roadmap). It is a candidate declared experiment for S3, as a second variant of the same tool.
- **A live memory**: on the board, resolved predictions (S4) build the memory from the setup
  that is running, at no cost. That needs its own decision in S4.
- **The live table's pool**: on the board, only cases closed before the prediction was made.
  Whether held-out years or closed open-split cases may join it (open-split cases only as
  numbers, 0024) needs its own decision before the board uses the tool.
- Held-out runs, any change to the occurrence answer, and `dev-seal-400`.

---

## 12. Decisions S2.8 takes

Written with this specification:

- [0130](../decisions/0130-a-finding-lookup-keyed-on-the-models-occurrence.md) — the lookup
  holds the NTSB's past flagged findings as pool counts, keyed on the model's checked first
  occurrence code; findings only; retrieval deferred.
- [0131](../decisions/0131-the-lookup-is-a-third-turn-over-finished-runs.md) — the lookup is a
  third turn in arm B's conversation, run as a pass over finished checked runs, with a closed list
  of one to five findings.
- [0132](../decisions/0132-a-memory-of-the-models-own-answers.md) — a memory of the model's own
  answers, from drawn development batches, keyed like the table, refused when stale.
- [0133](../decisions/0133-the-model-must-beat-the-count-matched-table.md) — the reading rule,
  the order of spend, the $10 line and the predictions.
- [0134](../decisions/0134-how-the-lookup-reaches-s3.md) — how S2.8's result fills S3's
  coding-lookup tool and arm B's fixed call.

---

## 13. Done means

1. `docs/results/s28-finding-stats.txt` exists, built from the pool, with the contamination
   test green and the design figures re-derived.
2. The memory lists are committed and reproducible; batch 1's list matches the fetched cases.
3. The turn-3 step, its refusals and its tests are in, and `make check` is green.
4. `docs/rounds/s28-lookup.md` is registered before the first paid pass, and its result is
   appended: the four ways (or the first three, if the order stopped), on both sets, the
   outcome of §6.3, and each prediction scored.
5. S3's two slots (§8) are stated as filled, in the As-built record.
6. `scripts/check_docs.py` passes; the As-built record is appended and the plan deleted.

---

## 14. Risks and open questions

- **The memory may be too small to show anything.** At 320 answers it was level with a
  size-matched table. With one batch it has 401; the result may be "not kept" for that reason
  alone, and it says so. Batches 2 and 3 need disk space (§4.1).
- **The rendered earlier answer is not the model's own wording.** The content is the same; if
  the model treats a rendered answer differently from its own reply, turn 3 measures that too.
  If the provider's batch replies can still be fetched (checked from the saved batch shape, not
  assumed), the raw text can replace the rendering; that would be a recorded departure.
- **Caching may save nothing.** Turn 3 runs hours after turns 1 and 2, and a cache matches only
  an identical opening of the prompt. The estimates assume no caching.
- **S2.7 may still change turns 1 and 2** through finding rounds. S2.8 applies to whatever runs
  S2.7 ends with, and the registration names them.
- **Coding habits may drift** between the pool's decade and held-out years; the table prints
  both halves, as S2.7's statistics do.
- **The disk.** 23.2 GB free after batch 1. The fetch stops itself below 15 GB.

---

## Glossary

- **Flagged finding**: a finding the NTSB marks as part of the probable cause; finding recall is
  scored against these.
- **Finding recall**: the share of the NTSB's flagged findings the answer contains, exact to all
  ten digits. **Precision**: the share of the answer's findings the NTSB flagged.
- **Statistics pool**: development cases outside both samples, used only for counting (0094).
- **Table**: for one case, the eight findings the NTSB flagged most often in past pool cases
  with the same key, with counts.
- **Key**: what the table is looked up by: the model's checked first occurrence code, else its
  event, else the phase group.
- **Fall back**: use a coarser key when fewer than 20 pool cases match the finer one.
- **Clear habit**: at least 60% of at least 20 pool cases (0101).
- **Memory**: a table built from the model's own earlier answers and the NTSB's findings for
  those cases: "when the model said X, the NTSB flagged Y".
- **Memory sample, batch**: development cases drawn for the memory, 401 at a time, outside both
  samples.
- **Stale**: built from a model setup that has since changed.
- **RAG (retrieval)**: finding stored past cases similar to this one and using their content;
  here it would use only their codes.
- **Turn**: one model call; a conversation re-sends what came before.
- **Pass**: running one step over every case of a finished run.
- **Answer set**: one finished, checked `dev-400` run the step is applied to.
- **Closed list**: the only codes the model may choose from in turn 3.
- **Count-matched**: the plain table gets as many findings as the model gave on each case.
- **Plain table**: the table's top lines used as the answer, with no model call.
- **Fingerprint**: a short code computed from the exact evidence text; one changed character
  changes it.
- **Rendered answer**: the model's earlier answer rewritten from the stored record, not its
  original wording.
- **Under-giving**: giving fewer findings than the NTSB usually flags.
- **Power**: how small a real gain a sample can reliably show; here about 3 points.
- **Slot**: a part of S3's design left open, with the rule that fills it written down.
- **Registration**: the committed note that fixes the test before any paid pass.
