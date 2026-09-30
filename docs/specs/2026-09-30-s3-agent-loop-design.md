# S3 — The agent loop: design

*Drafted 2026-09-30 from a design session with Andy (2026-09-29 to 2026-09-30), after S2.7
closed and the S3 learning probe merged (pull request #18). Status: Approved (2026-09-30, Andy: "Spec looks good").
This is the specification for build stage S3 of
`docs/specs/2026-09-12-architecture-and-roadmap.md` (§S3). S3 is split into three sub-stages
(§3). This document holds the design all three share, and S3.1 in full. S3.2 and S3.3 each get
their own specification when they start (§11). The implementation plan for S3.1 is written
from this document separately, in `docs/plans/`.*

**How to read this.** Each section says what is done, then why, with an example where one
helps. Terms in **bold** on first use are in the glossary at the end. Numbers in this document
are of five kinds, and each is labelled:

- **scripted** numbers cite the committed script and results file that produced them;
- **exploratory** numbers come from a committed script under `scripts/exploratory/`, run over
  the probe's trails or the local run records. They are signals, not results, and set no bar;
- **ad-hoc** numbers were counted during the design session by a throwaway command. They are
  not citable, and S3.1 re-derives any it relies on with a committed script;
- **external** numbers come from a saved copy of a published list, cited by file and date;
- **estimates** are arithmetic, and are replaced by measured figures in the As-built record.

Nothing here is a result. The probe that informs it ran on 20 cases, and every accuracy figure
it produced moved between two identical runs (§2).

**Decision records.** The records this design needs are written in S3.1's first task (§10.1),
not with this document. They are numbered from 121 on; numbers 108 to 119 were never used and
stay unused. §17 lists them.

**Depends on S2.7.** Every run in S3 uses the agent's model as S2.4 left it (GPT-6 Luna at
`medium`, decision 0073), the reply budget of 8,000 tokens (0084), S2.6's case marks (0077,
0078), S2.7's two kept guidance files (`r3-loc-stall`, `r6-aircraft-control`; 0098, 0106), and
evidence version **v1** (text layers only; transcription is off by default, 0120).

---

## 1. What S3 is for

The project must answer "why does this need an agent at all?" with a measurement. Decision
0022 fixed the test: the loop (arm C) must beat a fixed pipeline that calls every tool and
answers once (arm B), at equal cost.

The design of 0021–0023 put the loop's choices in **gathering evidence**: tools grouped by
source, a hypothesis after every tool call, and a masked condition in which evidence arrives
late. Three measurements since then moved where the choices are worth making:

- **Reading more barely helps.** Arm B with transcriptions against arm B without, on
  `dev-400`, paired on 399 cases: occurrence top-1 +1.3% [-2.5%, +4.8%] (scripted,
  `docs/results/s26-armB-v2-dev.txt`).
- **Coding moves the score.** S2.7's ordering check raised arm B's top-1 by +6.8%
  [+3.3%, +10.3%] and +9.8% [+6.0%, +13.8%] on two answer sets (scripted,
  `docs/results/s27-round1-dev.txt`). Andy's hand-read of 40 misses put 34 down to coding
  (19 convention, 15 wrong phase) and 4 to a misread or missing fact.
- **Dockets arrive at closure.** The recorder has seen 7 dockets appear, all in the same
  nightly run as their case's closure, none before (scripted,
  `docs/results/s3-recorder-report-2026-09-29.txt`; §9).

So S3's loop has two real choices on every case:

1. **Which documents to read.** Every document gets a read-or-skip decision, with the effect
   the agent expects from it.
2. **How to code.** The agent drafts its codes first, then checks them with tools that take
   codes as arguments ("code first, then check").

Arm B gets the same tools in a fixed order. If the loop's choices add nothing, arm B shows it.

## 2. What the learning probe showed

The probe ran the flow on 20 `dev-400` cases (5 per cell of fatal × has-scan), twice, with
identical settings. Standard price, GPT-6 Luna at `medium`, the two guidance files. Plan and
deviations: `docs/plans/2026-09-29-s3-learning-probe.md`. Reports (scripted):
`docs/results/s3-probe-dev.txt` (run 1) and `docs/results/s3-probe-dev-run2.txt` (run 2).

**Stable across the two runs** — these shape the design:

| signal | run 1 | run 2 | kind |
|---|---|---|---|
| documents read, of 136 offered | 104 | 111 | scripted |
| same read-or-skip decision on a document in both runs | 123 of 136 | | exploratory (`s3_probe_noise.py`) |
| mean cost per case (standard price) | $0.0277 | $0.0286 | scripted |
| median calls per case | 12 | 11 | scripted |
| prompt growth, first call to last coding call (mean ratio) | 4.78 | 4.83 | scripted |
| coding step's share of cost | 36% | 38% | exploratory (`s3_probe_confidence.py`) |
| skip-regret call's share of cost | 12% | 12% | exploratory |
| mean stated confidence before reading (H0) | 0.25 | 0.24 | exploratory |
| mean stated confidence after reading (H2) | 0.69 | 0.72 | exploratory |

**Moved between identical runs** — these are noise at n=20 and carry no claim:

| signal | run 1 | run 2 |
|---|---|---|
| H2 occurrence top-1 | 5 of 20 | 9 of 20 |
| skip regret, "read everything was right and H2 wrong" | 3 of 5 | 0 of 6 |
| coding step changed the first code | 4 of 17 | 1 of 20 |
| cases that failed | 3 (coding) | 0 |

**Four lessons the design takes:**

1. **The agent only checks codes it already holds.** The true primary occurrence code was among
   the codes the agent passed to a tool on 9 of 20 and 11 of 20 cases (scripted). Adding the
   statistics pool's five commonest defining codes for the case's phase-of-flight group would
   have put it in reach on 13 and 14 of 20 (exploratory, `s3_probe_candidates.py`). Reach is an
   upper bound, not accuracy. → a suggestion tool (§5.1).
2. **Stated confidence tracks how much was read, not how often the agent is right.** After
   reading, cases at stated confidence 0.6 or above were right on 5 of 16 and 8 of 18
   (exploratory, `s3_probe_confidence.py`). The abstain flag never fired after reading. →
   calibration in code (§6).
3. **Read decisions are a stable habit.** The agent read every mid-size document (2,000 to
   10,000 tokens: 23 of 23 in both runs, scripted) and skipped short ones more often.
4. **Accuracy at n=20 is noise.** The loop needs its own noise floor before any tuning (§10.2).

## 3. The stage in one page

| sub-stage | what it does | cases | claims | specification |
|---|---|---|---|---|
| **S3.1 — the loop** | builds the loop, its tools and native tool calling; the shape probe; the noise floor; tuning rounds; the format gate | `dev-400` only | none | this document |
| **S3.2 — the claims** | arm C against arm B at equal cost; the ablations; the calibration fit; the new sealed sample once; held-out once | `dev-400`, the new sealed sample, `heldout-400` | yes, registered before the first run | its own, written when S3.1 closes |
| **S3.3 — live shadow** | the recorder triggers nightly runs of the loop on open cases; everything logged, nothing locked or published | open cases (0024) | mechanics and cost only | its own, written when S3.3 starts |

**Why three.** Building the loop and making claims about it are kept in separate merges, so a
claim is never made on code that was still changing. S3.2 needs two inputs S3.1 produces (the
noise floor and a frozen loop) and one the recorder produces (the 14-night re-check, §9).
S3.3 exercises the loop on real arrivals for weeks before S4 needs it, but cannot measure
accuracy: open cases enter a measurement only as numbers (0024), and their verdicts are not
published yet.

Each sub-stage closes with an As-built record and a tag, as every stage does (0017, 0018).

## 4. The loop for one case

### 4.1 Triggers and input

The loop runs once each time something new arrives for a case. That is its **trigger**: the
case's first sight, a new structured field, or new docket documents. Its input always has the
same shape:

- the evidence present now, from `split_record` (0016);
- the docket in one of three **docket states**: none, some, or all;
- the case's earlier trail, if there is one (§4.3).

In evaluation, each closed case has one trigger with everything present: the **full
condition**, which is the state a live case is in at closure (§9). The same code runs live, in
evaluation, and in the replay if it is reopened.

### 4.2 The steps on one trigger

1. **Hypothesis before reading (H0).** Formed from all non-docket evidence the case holds at
   that moment, plus any documents read on earlier triggers.
   *Why all of it:* a live case holds start facts only in its first days, and everything by
   closure, when the docket arrives. A read choice made against start facts alone would test a
   state no live case is in, and make every document look more valuable than it is. In the
   full condition, H0 is the same task as S1's one-shot ceiling, so it can be compared with a
   measured arm.
2. **Read choice.** Every offered document not yet read gets read or skip, each with the effect
   the agent expects. The chosen documents come in through the same attach step, split and
   guard as arm B (§8.4).
3. **Hypothesis after reading (H1).** Skipped when nothing was chosen.
4. **Second look.** One more read choice over what is left, with a new hypothesis (H2) only if
   something was read. The probe used it on 17 of 20 and 15 of 20 cases, and read 11 and 10
   more documents that way (scripted).
5. **Coding: code first, then check.** The latest hypothesis is the draft. The agent calls the
   coding tools with codes as arguments (§5.1), at most 6 calls, then submits its answer.
6. **Finding refinement.** The same second pass on finding codes that arm B's answer uses.
7. **Confidence and abstain.** Code maps the stated confidence to a probability and sets the
   abstain flag (§6).

**Which documents are offered.** Exactly the set arm B may attach: every document whose text
extraction found text (`docket/filter.py`, `arm_b_documents`; decisions 0052, 0056). Scan-only
documents are listed as not readable. Documents classified as synthesis never appear.

**Example.** A non-fatal landing accident. H0 from the structured fields: "loss of control on
ground", confidence 0.35. The docket lists four documents; the agent reads the pilot's report
and the airframe notes, and skips a two-page weather printout ("weather was visual; no change
expected"). H1 moves to "abnormal runway contact", confidence 0.6. The second look skips the
weather printout again. The agent calls `occurrence_usage` with its first two codes and
`suggest_codes` for the landing group, then submits. Code maps the stated 0.6 to a calibrated
probability; below the threshold, the case would abstain.

### 4.3 Later triggers

A later trigger on the same case:

- receives **every document read so far, in full**, as evidence, word for word;
- receives a **short summary of the agent's own earlier replies**: its last hypothesis, and
  which documents it read or skipped, with its reasons;
- gets a **fresh read-or-skip choice on every unread document**, including ones skipped before;
- forms H0 again **only when new structured evidence arrived**. When only documents arrived,
  its last answer already is its best hypothesis on everything it had, so that call is skipped.

*Why:* a document skipped on the first night can matter once a later one arrives, and a
document read earlier can be reinterpreted by a later one, so the agent always sees the source
text. Its own earlier replies are summarised, not replayed, because the whole conversation
grows without limit and its stale replies mislead: the probe had to add a note telling the
model to prefer current evidence over its earlier replies (plan Deviations, fix round 2).

**Ruled out:** the agent's own notes standing in for documents it already read. It saves the
most tokens, but a note can drop the detail a later document makes decisive.

**Where this matters.** In evaluation each case has one trigger, so S3.1 and S3.2 do not use
§4.3. S3.3 and a reopened replay do. It is built and tested in S3.1, on development cases
replayed in two steps as the probe did.

### 4.4 Stops

The loop stops at the end of its steps, at the per-case cost cap (§8.2), or when a call fails
after one retry. Each stop reason is recorded.

### 4.5 What the probe had and the loop drops

- **The skip-regret call** (`h_all`, one call with every document). It was 12% of the probe's
  cost. Skip regret is measured instead against arm B, which reads every offered document, on
  the same cases.
- **Structured evidence behind tools** (0023's pilot-details and weather tools). By §4.2 step
  1, non-docket evidence the case holds is in H0.

## 5. Tools and native tool calling

The loop uses the provider's **native tool calling** (Andy: "expected within the industry for
production systems"). The probe used one structured reply per step with a tool field; that is
not carried forward.

### 5.1 The tool set

Every tool is defined once, as a name, a fixed one-line description and a strict JSON schema.

**Reading**

- `choose_documents(decisions, reason)`: one entry per offered document — its number, read or
  skip, and the expected effect.
  *Why one tool, not a `read_document` call per document:* with free per-document calls, a skip
  is a call never made, so nothing is logged and no expected effect is stated. The design
  needs a decision on every document.

**Hypothesis**

- `record_hypothesis`: the top three occurrence codes with probabilities, finding codes with
  probabilities, a one-sentence working cause, a stated confidence and an abstain flag. Called
  at each checkpoint of §4.2.
- `submit_answer`: the same fields. It ends the coding step.

**Coding** (codes as arguments; the S3 statistics file, §12)

- `describe_codes(kind, codes)`: labels for occurrence codes, finding categories or items.
- `occurrence_usage(codes, pairs)`: how often each code appears in the pool and how often it
  is the defining event, alone and in pairs, by phase.
- `past_findings(occurrence)`: the flagged findings most often recorded under that event.
- `suggest_codes(phase_group)`: new. The pool's five commonest defining events for a
  phase-of-flight group, with counts.

Coding tools return codes, labels and counts only, never case text. An invalid code or
document number comes back to the agent as a message, with one retry; it is not a failure.
The probe saw argument errors on 0 of 50 and 2 of 56 tool calls (scripted).

**The suggestion tool is a separate tool the agent chooses to call**, not a list added to
every check. The agent decides whether and when to use it; each call is logged; and removing
it is a clean ablation (§7.2). If the agent never calls it, that is a finding.

**Guidance.** The two kept S2.7 guidance files are in the system text, as in the probe.

### 5.2 How the agent knows what it may read

The list of documents is **in the message**, not in the tool description. Each read step ends
with a numbered list of the documents on offer and their measured facts:

```
Documents you have not read. Choose read or skip for each:
[3] Pilot/operator accident report: 6 pages, text layer, about 2,100 tokens
[4] Airframe examination notes: 2 pages, text layer, about 900 tokens
Not readable (no text layer): [5] Photographs, 14 pages
```

Titles pass through the same guard as the rest of the evidence. Document numbers in the tool's
schema are plain integers. Code checks that each is on offer and that every offered document
has a decision.

### 5.3 Keeping the prompt cacheable

**Prompt caching** discounts a prompt that starts the same way as a recent one. The match runs
from the start: tool definitions, then system text, then messages. Everything after the first
difference is paid at full price. So:

1. **The same tool definitions on every call, for every case in a run.** No per-case list of
   allowed document numbers in the schema: that would make each case's prompt differ from the
   first byte of the tools.
2. **The step's tool is chosen with `tool_choice`, not by changing the tool set.** A step
   either forces one named tool (a read step forces `choose_documents`; a checkpoint forces
   `record_hypothesis`) or requires any tool (the coding step). After the sixth coding call,
   `submit_answer` is forced.
3. **The system text is identical for every case.** It holds the code tables and the two
   guidance files, the largest fixed block, so it can be cached across a whole run.
4. **The conversation is append-only.** Case evidence follows the system text. Each document
   read arrives as a tool result at the end; no earlier message is rebuilt. The probe rebuilt
   its evidence block after each read, so nothing past the system text could be reused.

**What is given up:** the schema no longer makes a wrong document number impossible. Code
catches it instead (§5.1).

### 5.4 Packaging

The tools are **in-process Python functions**, each with its native definition beside it. The
loop runs them between calls. A later MCP server would be a thin wrapper over the same
functions.

**Ruled out:**

- a local MCP server from the start: a second process and a serialisation boundary, and tool
  results lose `mypy --strict`'s checks, for no new capability;
- provider-hosted MCP, where the provider calls the tools during a request: the loop would
  lose its step-by-step control — the cost cap, the step limit, and logging each tool result
  as it passes the guard.

A public, read-only MCP server of the coding tools (codes and counts only) may be a good S4
artefact. That is a separate decision.

### 5.5 The shape probe

Before any loop code, one development case runs through a minimal native-tool conversation:
standard price first, then batch. It checks:

1. strict tool schemas are accepted;
2. a forced tool call and a required tool call are honoured;
3. a multi-turn conversation with tool results works on batch;
4. whether the model's reasoning must be passed back between turns;
5. the reported cost, and the cached-token count on each response;
6. whether changing `tool_choice` between calls keeps the cache, standard and batch.

The saved OpenRouter model list claims `tools` and `tool_choice` for both
`openai/gpt-6-luna` and `openai/gpt-6-luna:batch` (external,
`data/s27/openrouter-models-2026-09-27.json`, not committed). A claim is not a test.

**If batch refuses tools, work stops and Andy chooses** between standard calls at about twice
the cost and a batch-only fallback, documented as a departure. If forcing a tool breaks the
cache, the fallback is "require any tool", with the step named in the message.

## 6. Confidence and abstain

The model still states a confidence at every checkpoint and in its answer. **Code, not the
model, turns it into the reported confidence**:

- a curve from stated confidence to the chance of being right, fitted on the loop's own
  `dev-400` runs and frozen before any held-out run;
- the **abstain** flag is a threshold on the fitted value, chosen on `dev-400` only (0021
  item 4);
- the raw stated confidence is recorded and reported beside the fitted one, so the fit can be
  audited.

*Why:* in the probe, stated confidence rose from about 0.25 to about 0.7 with reading, while
answers at 0.6 or above were right about a third to under half of the time (§2, lesson 2). A
board that shows 70% beside answers right a third of the time misleads the reader.

S3.1 records the raw values. The noise-floor runs (§10.2) give 802 answers to fit on. The fit
itself, its method and its check on the sealed sample belong to S3.2.

## 7. The arms and ablations

### 7.1 The three arms

Decision 0022's structure is kept: three arms, the same model, cases, price variant and
per-case cap.

- **Arm A — start facts only, one call.** As in S1. Re-run at S3.2's commit so all arms share
  one commit (estimate about $0.20 on `dev-400`).
- **Arm B — the fixed pipeline, and the bar.** It is built in four fixed parts:
  1. **The answer.** S2.7's final setup: v1, the fixed document filter, one answer with the two
     guidance files. On `dev-400` that setup, with the ordering check, scored top-1 25.1%
     [21.1%, 29.5%], and 27.5% [23.3%, 32.0%] on `dev-seal-400` (scripted,
     `docs/results/s27-sealed-dev.txt`).
  2. **Every coding tool on its own top three**, in this order: `describe_codes`,
     `occurrence_usage` on the three codes and their pairs, `past_findings` for its first
     code, and `suggest_codes` for that code's phase group.
  3. **One more answer**, with the tool results.
  4. **S2.7's ordering check** (`luna`), as a post-pass.

  Arm B without the ordering check is reported second.
- **Arm C — the loop** (§4, §5).

**The ordering check is in arm B only.** In the loop, the agent's own tool calls do that job
(Andy: the extra checker is "only ever a way to replicate a tool call"). Arm B is then the
pipeline a sceptic would build: every tool and the best known fixed check, with no choosing.

**Implementation (proposal for the plan).** Arm B's parts 2 and 3 run as a post-pass over a
finished arm B run, writing a derived run folder, as S2.7's check does (0096). Part 1 then
stays byte-for-byte S2.7's answer.

### 7.2 Ablations of arm C

| ablation | what it shows | where it runs |
|---|---|---|
| no docket (docket state none) | what reading adds inside the loop | `dev-400` and `heldout-400` (CLAUDE.md goal 2) |
| no `suggest_codes` | what the suggestion tool adds | `dev-400` |
| no coding tools (answer = latest hypothesis, then refinement) | what the coding step adds, where the agency is meant to sit | `dev-400` |

Each costs about $3.30 on `dev-400` at the batch price (estimate, §14).

## 8. Running it

### 8.1 Two ways to run

- **Standard** (`--sync`): the shape probe and one-case smoke tests.
- **Batch rounds**: every evaluation run. Each round sends every unfinished case's next call
  as one batch. When it returns, the tools run locally, the conversations are extended, and
  the next round goes out. Cases at different steps share a round. State is saved after every
  round, and `--resume` continues a run that stopped.

A loop run is about 10 to 15 rounds. Past single-call batch runs on `dev-400` took 0.53 to
2.20 hours from start to finish, median 0.71 (exploratory, `s3_probe_confidence.py`, 10 runs).
So a loop run is an overnight job: about 6 to 11 hours (estimate).

The command is `ntsb-eval run --arm C`. Arm B's tool post-pass runs through the same tool
code with a fixed script in place of the agent's choices, so both arms write the same records.

### 8.2 Limits enforced in code

- **Per-case cost cap.** S3.1 starts at the probe's $0.15. The noise-floor runs measure the
  real spread; S3.2 fixes the cap before any comparison run. Before each coding call, code
  checks there is room left for the answer and the refinement; if not, the coding step stops
  and the case answers.
- **Steps.** At most 2 read choices and 6 coding calls per trigger, with one retry for a
  missing or invalid tool call.
- **Budgets.** The run budget and the monthly guard (0083) apply as now, and S3's spend line
  through the stage-spend script (§14).

### 8.3 The trail

One row per model call and per tool result (0021 item 2). Each row holds:

- run, case, trigger, docket state, and the step kind;
- the tool name and its arguments; the size of the tool's result, never its text;
- the hypothesis, at checkpoints;
- prompt, cached and reply tokens; cost; sent and returned times; batch identifier;
- commit SHA and the uncommitted-changes flag (0018); the stop reason.

Trails are JSONL in the run folder, like runs now. The probe's test that a trail holds no
docket title or document text carries over. The predictions tables stay in S4. Where S3.3's
shadow trails are stored is S3.3's decision.

### 8.4 Guard, marks and failures

- Every chosen document goes through the same attach step as arm B, so S2.6's marks apply
  (0077, 0078). Reports print every result for all cases, then for unmarked cases.
- A guard refusal on a chosen document ends the case as a failure, as in arm B.
- A failed case is excluded from `n` and listed with its reason. Failures count in the
  do-no-harm rule (§10.3).
- B and C are compared on cases both scored, with each arm's failure count beside the result.

### 8.5 Code layout (proposal)

A new package, `src/ntsb_probable_cause/agent/`, holds the loop, the tools, the trail, the
prompts and the batch-round driver. An import-linter contract lets `agent` import the records,
docket and scoring code, never the reverse. Tools reach case text only through `split_record`.
The probe's `scripts/s3_probe/` is not reused as it stands; its tools and tests are the
starting point.

## 9. Arrivals: docket states and the paused replay

**What the recorder has seen** (scripted, `docs/results/s3-recorder-report-2026-09-29.txt`,
8 runs on 7 distinct nights, 23 to 29 September 2026):

- docket arrival before closure: 0 cases; in the same run as closure: 7; after: 0;
- documents that appeared at closure: 94; after closure: 0; new documents in runs 3 to 8
  (24 to 29 September): 0;
- on cases seen without a field and then with it, before closure: make, model, phase and
  registration first appear at a median of 3 days after the event (n=8); injury level at 4
  (n=9); the weather condition at 17 (n=15) and the METAR at 18 (n=16). Engine type, pilot
  hours and pilot certificates appeared only in the same run as closure (6 or 7 cases each).
  These are small counts.

The earlier ongoing-docket probe agrees: 98 of 100 sampled ongoing cases had no released
docket (scripted, `docs/results/s25-ongoing-dockets.txt`).

If this holds, a live case's docket goes from none to all at closure, together with the
verdict. That contradicts 0023's context ("docket documents arrive over months").

**What S3 does with it:**

1. **The loop handles all three docket states** — none, some and all — with the same code
   (§4.1). If documents turn up only at closure, the live page shows exactly that.
2. **The staged replay is paused.** Andy proposed mimicking real arrival patterns in the
   evaluation: closed development cases released in steps timed by the recorder's measured
   distributions. With no measured docket arrivals before closure, any schedule for documents
   would be invented, and 0023 requires the mask to be measured, not chosen.
3. **Re-check at 14 distinct nights** (about 6 October 2026), with the same script, before
   S3.2's specification is fixed. If dockets still arrive only at closure, S3.2 measures the
   full condition only and says so. If they arrive earlier, the replay design is reopened as
   a decision.

The masked condition of 0023 (only what a live case would have at day N) is paused with the
replay. Arm A still reports the start-facts-only score for every case.

## 10. S3.1 in full

### 10.1 Build order

1. **Records.** The decision records of §17, including the supersession record and the record
   cancelling S2.8.
2. **The `probe` spend kind.** Add `probe` to `SpendRecord.kind`. Relabel the three probe jobs'
   rows from `inventory` to `probe`, keeping the original rows beside the new ones; the record
   lists the job IDs, the old and new kind, and the unchanged costs. `s28-coding-lookup` no
   longer constrains this: S2.8 is cancelled.
3. **The native-tool shape probe** (§5.5).
4. **The new sealed sample and the S3 statistics file** (§12).
5. **The `agent` package and arm B's tool post-pass** (§4, §5, §7.1, §8), with the tests of §16.
6. **Smoke runs.** One case on standard, then 20 cases on batch.
7. **The noise floor** (§10.2).
8. **Tuning rounds** (§10.3).
9. **The format gate** (§10.4).
10. **Close.** The loop is frozen, the As-built record written, and the tag set. S3.2 starts
    from that exact commit.

### 10.2 The noise floor

**Why.** Two identical arm B runs in S2.7 differed by top-1 +4.0% [+0.5%, +7.5%] and changed
the first code on 153 of 399 cases (scripted, `docs/results/s27-round0-dev.txt`). The loop has
more sources of chance: read choices, tool arguments and multi-turn state. A tuning round is
only readable against the loop's own noise.

**What runs.** Arm C on `dev-400`, twice, identical, at v1, on batch, on one frozen commit.
**A third run** is added if the paired top-1 difference between the first two is larger than
4.0 points, S2.7's figure. A third run only improves the estimate of the spread, so it is
worth it only when the first gap is wide.

**What is reported** (counts and paired differences with intervals): occurrence top-1 and
top-3; finding recall@10; cases whose first code changed; read-or-skip agreement per document;
tool-argument agreement; failures by reason; cost; the cached share of prompt tokens. Raw
stated confidences are kept for S3.2's calibration fit.

**Estimate:** about $7 for two runs; about $10.50 with a third.

### 10.3 Tuning rounds

Tuning rounds follow S2.7's pattern (0098):

- **Registration.** Each round is registered in `docs/rounds/` before it runs.
- **Reading.** A round must beat the noise floor. Failures count in the do-no-harm rule.
- **What may change:** prompts, tool descriptions and step limits. Calibration waits for S3.2.
- **Cases read to design a round** are chosen by a stated reason. A script sorts `dev-400`
  into always right, always wrong and flipping, across the noise-floor runs and existing arm B
  runs. Cases are never picked from arm B's misses.
- **Guidance text** gets the case-text leak check (`make s27-check-guidance`).
- **Stop:** two dropped rounds in a row, or S3.1's share of the spend line spent (§14).

### 10.4 The format gate

At most 2% of cases (8 of 401) may fail for format or tool reasons on each noise-floor run.
S2.4's gate was 0 of 401 for a single call; a loop makes about ten calls per case. If the
gate fails, the fix comes before S3.2.

### 10.5 What S3.1 does not do

It does not compare arm C with arm B, fit calibration, open the new sealed sample, touch
held-out, or make any claim.

## 11. S3.2 and S3.3 in outline

**S3.2 — the claims** (its own specification):

- It starts from S3.1's frozen commit, after the 14-night recorder re-check (§9).
- **A registration file** comes before its first run. It fixes the new predictions (§13), the
  definition of equal cost, and the bound for the calibration result. It discloses the probe
  and the noise-floor runs, which saw development accuracy.
- On `dev-400`: arms A, B (with and without the ordering check), C, and the three ablations.
  The calibration curve and the abstain threshold are fitted on C's `dev-400` outputs and
  frozen.
- Then once each: the new sealed sample (C and B) and `heldout-400` (A, B, C, and C without
  the docket), with ledger rows committed in order, as in S2.4.

**S3.3 — live shadow** (its own specification):

- The recorder store triggers nightly batch runs on cases that changed, under an entry rule
  and a monthly cap that its specification sets. About 940 cases are watched (scripted,
  recorder report), so a first pass over all of them would cost about $7.50 on batch
  (estimate).
- Nothing is locked or published. Predictions tables and tamper-evident rows are S4.
- **Proposal:** shadow trails hold model text derived from open-case evidence, so they are
  open-split data under 0024. They are never committed and never used in development or
  evaluation.

**Transcription as a loop tool.** 0120 says the S3 loop *may* choose transcription as a tool.
S3.1 and S3.2 do not add it: scan-only documents are listed as not readable. Transcribing a
sample cost about ten times answering it (0120), and v2 against v1 was +1.3% [-2.5%, +4.8%]
on top-1 (§1). It is revisited only if trails show the agent repeatedly wanting scan-only
documents. This uses 0120's "may"; it does not overturn it.

## 12. The sealed sample

`dev-seal-400` was opened once, on 2026-09-29, for S2.7 (0095); a second look would make it a
working sample. S3 needs its own.

1. **A new sample**, drawn by `samples.draw` exactly as `dev-seal-400` was (200 fatal and 200
   non-fatal, each split by class C, F and L in proportion; 0026), with a new seed fixed in its
   record, excluding every `dev-400` and `dev-seal-400` case. Its list is committed as a test
   fixture.
2. **Refused until registered.** Nothing about it is scored, read, fetched or transcribed until
   S3.2's registration file is committed. The runner, the docket fetch and every other command
   refuse it before then, and tests prove they refuse.
3. **Used once**, in S3.2: arm C and arm B, reported beside the same setups' `dev-400` results.
4. **The statistics pool is rebuilt without it.** It comes from the statistics pool (0094), so
   the coding tools' counts would otherwise include its own verdicts. The same script builds a
   new counts-only file, `docs/results/s3-coding-stats.txt`, from the smaller pool, and refuses
   the new sample. **Both arms in S3 read this file**: the loop's tools and arm B's tool
   post-pass and ordering check. S2.7's file stays as it is, so S2.7's numbers stay citable.
   The pool shrinks from about 12,490 cases (0094, ad-hoc there) by about 400.

## 13. Predictions

**P1 to P6 of 0022 are withdrawn**, now, before any measurement of the loop. They were written
for the design of 0021–0023: hypotheses after every tool call, a masked condition with
late-arriving documents, and fatal dockets needing more steps. The six stay published as
written; the supersession record gives the reason for each. The learning probe (n=20, no
claim) is disclosed there.

**Nothing about the loop is predicted in S3.1.** New predictions are registered at the start
of S3.2, in its registration file, before its first run. They come after the noise floor, so
effect sizes are set knowing how much identical runs differ. S2.7's prediction (top-1 between
30% and 36% on `dev-400`) was fixed before S2.7 measured its own noise floor, and was not met.

**The four results that count against the loop (0022 item 4), reworded for this design
(proposal; the supersession record fixes the wording):**

1. arm C reads every offered document on most cases, **or** calls the coding tools in arm B's
   fixed order on most cases;
2. arm C matches arm B only at the same or greater cost;
3. arm C's code-fitted confidence is not calibrated on held-out, by the bound S3.2 registers;
4. the effect the agent states for a document it reads does not agree with the change observed
   after reading it more often than chance.

As in 0022, if any one holds, it is published whichever way the others go.

## 14. Cost and the spend line

**Where spending stands.** September's shared spend is $50.24 against the $50 set for
September only (ad-hoc, `month_spent` on 2026-09-29; 0104). No paid S3 work starts before
1 October. From October the monthly guard is $40 again (0083).

**Estimates** (arithmetic from the probe, at the batch price, which halves the standard
price):

- The probe's cases without transcribed pages cost $0.0180 and $0.0177 per case at standard
  price (exploratory, `s3_probe_confidence.py`). At v1 without the skip-regret call, about
  $0.016; on batch, about $0.008; so about $3.20 to $3.50 per `dev-400` loop run.
- Past arm B runs on `dev-400` cost $1.10 to $1.33 each (exploratory).
- **S3.1:** under $1 for the probe and smoke runs; about $7 for the noise floor ($10.50 with a
  third run); about $3.50 per tuning round. About $15 to $20 in all.
- **S3.2:** arms A and B, the three ablations and C on `dev-400`; the sealed sample; held-out
  once. About $20 to $25.
- **S3.3:** about $7.50 for a first pass over the watched cases, less if cases with no docket
  are cheaper, which is likely but not measured.

Prompt caching (§5.3) may lower these. The noise floor measures by how much.

**The spend line: $50 for all of S3**, counted by commit on S3's branches from S3's first
commit, by the stage-spend script (0098, 0107, applied to S3's branch prefix). The probe's
$1.20 was spent before that commit and sits outside the line. The line spans October and
November under the monthly guard. If a re-estimate passes the line, work stops and Andy
decides (0083 item 2).

## 15. Branches, plans and decision numbers

- S3.1's branch is named with the prefix `s3-`, so the stage-spend script counts it. Each
  sub-stage has one plan in `docs/plans/`, deleted at its close (0017).
- Decision records during S3 take numbers from 121 on, in order.
- A stage-closing pull request is titled `S3.1: the agent loop` (and so on for S3.2 and S3.3)
  and merged with a merge commit (0033).

## 16. Tests and continuous integration

S3.1 adds tests that:

- a wrong document number and an invalid code come back to the agent as a message, with one
  retry;
- every offered document gets a decision, or the step retries;
- a trail holds no docket title and no document text;
- a chosen document passes the guard, and a guard refusal ends the case as a failure;
- the new sealed sample is refused by every command before S3.2's registration;
- the S3 statistics script refuses the new sealed sample, `dev-400`, `dev-seal-400`, held-out
  and open cases;
- the cost cap holds back room for the answer and the refinement;
- the tool definitions and system text are byte-identical across the cases of a run (the cache
  condition of §5.3);
- a later trigger re-sends every read document in full, re-offers skipped documents, and skips
  H0 when only documents arrived (§4.3);
- the `probe` spend kind is read by `month_spent`, and relabelled rows are not counted twice.

The import-linter contract of §8.5 runs in CI.

## 17. Decisions S3 takes

Written in S3.1's first task, numbered from 121 on in this order:

| # | record | from the session |
|---|---|---|
| 1 | Agency moves to the read choice and the coding step. Supersedes the named parts of 0021 (hypothesis after every tool call; stopping at a confidence threshold), 0022 (P1–P6 withdrawn; item 4 reworded, §13) and 0023 (tools grouped by source for structured fields; the masked condition as the second headline). | the direction agreed before the probe; supersession choice C |
| 2 | H0 from whatever non-docket evidence is present; later triggers re-send read documents in full and re-offer skipped ones; docket states none, some and all. | H0 choice B; later-trigger choice B |
| 3 | The staged replay is paused until the recorder shows arrivals; re-check at 14 nights. | replay paused |
| 4 | Native tool calling, a stable tool set, `tool_choice` per step, an append-only conversation; in-process tools, ready for an MCP wrapper. | native tools; packaging choice A |
| 5 | The suggestion tool. | candidates choice C |
| 6 | Confidence calibrated in code; abstain as a threshold. | calibration choice B |
| 7 | The arms and ablations; the ordering check in arm B only. | ordering choice B; §7 |
| 8 | S3 in three sub-stages, with one $50 spend line. | sub-stages choice A; spend choice B |
| 9 | S3's sealed sample and the rebuilt statistics file. | sealed choice A |
| 10 | The loop's noise floor and the format gate. | noise floor choice A; §10.4 |
| 11 | The `probe` spend kind and the relabel. | spend kind choice B |
| 12 | S2.8 is cancelled. | Andy, 2026-09-30 |

The roadmap's §S3 is amended by record 1 when it is written, with a dated note in place, as
earlier amendments were.

## 18. Done means (S3.1)

1. The shape probe's six checks are answered and recorded, and any departure is decided by Andy.
2. The new sealed sample's list is committed and refused by every command; the S3 statistics
   file is committed.
3. `ntsb-eval run --arm C` runs `dev-400` on batch to completion, resumably.
4. Arm B's tool post-pass runs on a finished arm B run.
5. The noise floor's results file is committed, from a script, with every figure of §10.2.
6. The format gate is met on the noise-floor runs.
7. Each tuning round is registered before it runs, and read by its rule.
8. `make check` passes, including the tests of §16.
9. The As-built record is appended, the plan deleted, and the version set (0017).

## 19. Not in S3

- Transcription as a loop tool (§11).
- The weather archive (0023 item 6).
- Similar-case search.
- The predictions store, prediction locking and the resolution watcher (S4).
- The public site (S5).
- A memory of which document kinds were decisive. It is built from read-everything
  development trails and frozen before held-out, when it is taken up; not in S3.1.
- The model axis and reasoning levels (after S3, 0031, 0073).

## 20. Risks and open questions

- **Batch may not accept tools.** The shape probe finds out first (§5.5).
- **Caching may not reach batch requests**, or may break when `tool_choice` changes. The cost
  estimates do not rely on it.
- **The loop may be a pipeline in costume.** It reads every document and calls tools in a
  fixed order. §13's first result catches that, and it is published.
- **Dockets may start arriving before closure** as the recorder watches longer. The 14-night
  re-check (§9) reopens the replay if so.
- **Open question for Andy — the guidance files and the new sealed sample.** The two kept
  guidance files cite counts from S2.7's pool, which includes the cases the new sealed sample
  will be drawn from. The text was fixed before the sample exists, so the sample cannot have
  been chosen to fit it, and 400 of about 12,490 cases carry little weight in a count.
  **Proposal:** keep the files as they are and disclose this in S3.2's registration.
  The alternative, rewriting the counts from the smaller pool, changes arm B's text away from
  S2.7's final setup.
- **Open question for S3.3 — the preliminary narrative.** The recorder stores it for the live
  board only; evaluation never has it (0023 item 5). Whether the live loop reads it would make
  live runs differ from evaluation. S3.3's specification decides.
- **Loop runs are overnight.** A tuning round takes a night. The plan orders work so that no
  step waits idle on a run.

## Glossary

- **Abstain**: the agent declines to answer because the evidence is thin. In S3, a threshold
  on the code-fitted confidence.
- **Ablation**: the loop with one part removed, to measure what that part adds.
- **Arm**: one way of answering, compared on the same cases. A is start facts only; B is the
  fixed pipeline; C is the loop.
- **Batch round**: one submission covering every unfinished case's next call.
- **Calibration**: when the system says 70%, it is right about 70% of the time.
- **Docket state**: none, some or all of a case's docket documents released.
- **Full condition**: everything a closed case holds in evidence roles, with its whole docket;
  the state of a live case at closure.
- **H0, H1, H2**: the loop's hypotheses before reading, after the first read choice, and after
  the second look.
- **Native tool calling**: the provider's own mechanism, where the model returns tool calls as
  a separate field of its reply.
- **Noise floor**: how much two identical runs differ by chance alone.
- **Prompt caching**: a discount on a prompt that begins the same way as a recent one.
- **Reach**: the true code is among the codes the agent looked at. An upper bound, not
  accuracy.
- **Sealed sample**: cases set aside, unread and unscored, until one final check.
- **Statistics pool**: development cases whose verdicts feed the coding tools' counts, kept
  apart from every scored sample (0094).
- **`tool_choice`**: a request setting that says whether the model must call a named tool, any
  tool, or none.
- **Trail**: the record of every step on a case: hypotheses, tool calls, costs and times.
- **Trigger**: an arrival of new evidence that starts one pass of the loop.
