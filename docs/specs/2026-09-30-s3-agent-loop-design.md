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
| 9 | S3's sealed sample (`dev-seal-s3-400`, seed 20260930) and the rebuilt statistics file; the guidance files stay unchanged and the overlap is disclosed (§20). | sealed choice A; guidance-files choice A |
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
- **Resolved (Andy, 2026-09-30: "Go with A and keep them unchanged") — the guidance files and
  the new sealed sample.** The two kept guidance files cite counts from S2.7's pool, which
  includes the cases the new sealed sample will be drawn from. The text was fixed before the
  sample exists, so the sample cannot have been chosen to fit it, and 400 of about 12,490
  cases carry little weight in a count. **The files stay unchanged**, so arm B stays S2.7's
  measured setup, and S3.2's registration discloses the overlap. Rewriting the counts from the
  smaller pool was rejected: it would change arm B's text away from S2.7's final setup and need
  its bar re-measured. Record 9 (§17) states this.
- **Open question for S3.3 — the preliminary narrative.** The recorder stores it for the live
  board only; evaluation never has it (0023 item 5). Whether the live loop reads it would make
  live runs differ from evaluation. S3.3's specification decides.
- **Loop runs are overnight.** A tuning round takes a night. The plan orders work so that no
  step waits idle on a run.

## As built (S3.1, 2026-10-03)

*S3.1 closed on 2026-10-03 in pull request #21. This specification stays Approved: it also holds
the design S3.2 and S3.3 share, and each of them adds a dated part like this one when it closes
(§3). This part records S3.1 only, against §18.*

S3.1 built the agent loop (arm C), arm B's fixed tool post-pass, S3's sealed sample and
statistics file, and S3's spend line, and it measured the loop's noise floor on `dev-400`. The
format gate passed on both noise-floor runs. Tuning closed with no registered round (decision
[0139](../decisions/0139-s31-tuning-closes-without-a-registered-round.md)), so the loop frozen
at commit `fd6053f` (prompt version `s3-v1+ge17fecdc66ec+p947fac1c86a4`) is S3.1's result and
the loop S3.2 starts from. No held-out case was run or scored, and `dev-seal-s3-400` is still
sealed. S3.1 also read the loop against arm B on `dev-400`. Those are development readings, not
claims (Departures, §10.5), so S2.4's held-out arm B (`docs/results/s24-bars.txt`) stays the bar.

Two cost figures appear below. The **computed** cost prices every token at the list price. The
**billed** cost is what the provider's batch reports charged; it is lower, because cached prompt
tokens cost less. S3's spend line counts the billed cost of a batch arm C run or tool post-pass
(decision [0135](../decisions/0135-s3-spend-counts-what-was-billed.md)).

### Delivered

- **The agent package**, `src/ntsb_probable_cause/agent/` (§4, §5, §8). Nothing in the library
  imports it; `apps/eval` and some scripts do.
  - `loop.py`: `CaseLoop`, one case's conversation on one trigger. It hands out its next model
    call (`next_call`) and takes the reply (`accept`), and never calls a model itself, so the
    same object runs one call at a time or in batch rounds. It holds the per-case cap, with room
    kept for the answer and its refinement, and `PASS_REASONING` (off: shape probe check 4).
  - `steps.py`: the step table. For each step: the `tool_choice` it sends, the tools a reply may
    call, the next step and the tool text that says so; and the refusals of a reply that breaks
    the protocol.
  - `schemas.py`: the seven tool definitions (`TOOL_DEFINITIONS`), in one fixed order and
    byte-identical on every call; the argument models; `parse_call`.
  - `tools.py`: the four coding tools, `describe_codes`, `occurrence_usage`, `past_findings` and
    `suggest_codes`. They are pure functions over the code tables and S3's statistics, and they
    return codes, labels and counts only.
  - `texts.py`: the system text (arm B's answer prompt and code tables, the two guidance files,
    then the loop's `PROTOCOL`), the document menus, the fixed tool texts, and the prompt
    version (`+g` for the guidance, `+p` for the text; decision
    [0133](../decisions/0133-unreadable-dockets-are-listed-and-the-text-is-fingerprinted.md)).
  - `documents.py`: every payload the agent sends, each built as
    `Payload.from_evidence(split_record(...))` (decision
    [0016](../decisions/0016-layered-leakage-guard-and-model-boundary.md)), and the case marks.
    `facts.py` holds a document's measured facts as plain values, for the menus.
  - `later.py`: a later trigger's opening (§4.3): every document read before, in full, and a
    summary of the agent's earlier choices.
  - `trail.py`: the trail. `AgentCall` is one row per model call: the tool, its parsed
    arguments, the size (never the text) of the result, the hypothesis at checkpoints, tokens,
    cost, times, batch id, commit and stop reason. Also `ReadRecord` and `LoopOutcome`.
  - `drive.py`: `drive_sync` and `drive_batch`. A batch round sends every unfinished case's next
    call as one batch. Every reply and round is written to the run folder before it is used, so
    a stopped run resumes from the folder.
  - `run.py`: `AgentRunner`, arm C in the harness. It writes the same `RunRecord` and
    `CaseResult` files as arms A and B, plus `trail.jsonl`, so `ntsb-eval report --against`
    compares arm C with any arm. Its `spec.json` also records the loop's own settings.
  - `armb.py`: arm B's fixed tool post-pass (`FixedToolsLoop`, `preflight`, `tools_run`), §7.1
    parts 2 and 3.
- **Native tool calling in the model seam** (§5). `model/client.py` and `model/openrouter.py`
  send `tools`, `tool_choice` and `parallel_tool_calls`, and read tool calls, cached-token
  counts and reasoning details. `model/tool_text.py` holds `ToolText`, the only text that is not
  evidence a tool result may carry. Two import-linter contracts hold the boundary: "Nothing in
  the library imports the agent" and "The agent's tools and texts see no case record".
- **Commands** (`apps/eval/__main__.py`).
  - `ntsb-eval run --arm C`: the loop, by default with a $0.15 per-case cap, S3's two guidance
    files and S3's statistics. `--without suggest_codes|coding` runs the ablations of §7.2.
    `--round N` is refused until `docs/rounds/s3-round-N.md` is committed.
  - `ntsb-eval tools RUN_ID`: arm B's post-pass over a finished arm B run, into a derived run
    `<run id>-tools` labelled `<source prompt version>+tools-s3+p<12 characters>`.
  - `ntsb-eval check --stats s3`: the ordering check counted in S3's statistics. On arm C it
    takes the `luna` way only (decision
    [0137](../decisions/0137-the-ordering-check-as-a-diagnostic-on-arm-c.md)).
  - `ntsb-eval report`: for arm C, an "unread" line and the cached share of prompt tokens; with
    `--against`, for an arm C check run, the count of first codes changed.
  - Make targets: `s3-smoke-sync`, `s3-smoke-batch`, `s3-noise-floor`, `s3-armb-tools`,
    `s3-check-diagnostic`.
- **S3's sealed sample and statistics** (§12, decision
  [0129](../decisions/0129-s3s-sealed-sample-and-statistics.md)). `scripts/draw_sealed.py
  --sample dev-seal-s3-400` (`make s3-draw-sealed`; seed 20260930; `dev-400` and `dev-seal-400`
  left out) wrote `tests/fixtures/eval/dev_seal_s3_400_ids.csv`. `samples.refuse_sealed`
  refuses the sample in every command until `docs/rounds/s3-registration.md` is committed.
  `scripts/coding_stats.py` (`make s3-coding-stats`) wrote
  `scoring/tables/coding_stats_s3.json` and `docs/results/s3-coding-stats.txt` from a pool
  without the three samples. `load_stats("s3")` reads it. `POOL_EXCLUDED` names the samples
  each statistics file leaves out, and `refuse_pool_holding` refuses a sample whose cases a
  file's pool holds. S2.7's file is unchanged.
- **Spend** (§14; decisions
  [0128](../decisions/0128-s3-in-three-sub-stages-with-one-spend-line.md),
  [0131](../decisions/0131-the-probe-spend-kind.md), 0135). `scoring/budget.py` gains the
  `probe` spend kind, and counts a batch arm C run or tool post-pass at its billed total
  (`counts_billed`, `spent_usd`). `scripts/relabel_probe_spend.py` relabelled the learning
  probe's three jobs from `inventory` to `probe`, and kept the original rows beside them, where
  nothing reads them. `scripts/stage_spend.py --stage s3` (`make s3-spend`) counts S3's $50
  line by commit on `s3-` branches.
- **The shape probe** (§5.5). `scripts/s3_shape_probe.py` (`make s3-shape-probe`), with its
  saved requests and replies under `tests/fixtures/openrouter/s3/`.
- **The noise floor and tuning rounds** (§10.2 to §10.4). `scripts/s3_noise_floor.py` (`make
  s3-noise-report`) prints every figure of §10.2, the format gate and the third-run rule.
  `docs/rounds/README.md` gains the S3 round template. `scripts/round_result.py` reads an arm C
  round with failed cases counted wrong and the format gate first (decision
  [0136](../decisions/0136-s3-rounds-count-failed-cases-as-wrong.md)), in the statistics file
  the run's `spec.json` names (`make s3-round`, `make s3-round-result`). No round was run (0139).
- **Task 15's scripts**, all free and offline, with no model call.
  - Live: `scripts/s3_case_groups.py` (`make s3-case-groups`) sorts `dev-400` into always right,
    always wrong and flipping (`docs/results/s3-case-groups-dev.txt`).
    `scripts/s3_trail_pages.py` (`make s3-trail-pages`) writes private trail reading pages under
    the runs folder, never committed. `scripts/miss_kinds.py` classifies how a first code misses
    the NTSB's.
  - Exploratory (decision [0059](../decisions/0059-every-script-states-its-status.md):
    they set no bar and tune nothing), under `scripts/exploratory/`, each with a `make` target
    named after it (`make s3-miss-kinds` and so on): `s3_miss_kinds`, `s3_precedent_probe`, `s3_precedent_pages` (a private
    page), `s3_coding_consistency`, `s3_finding_consistency`, `s3_finding_precedent` and
    `s3_finding_misses`. Each but the page writes a results file under `docs/results/`. Also
    `s3_probe_confidence`, the design session's reading of the learning probe, which §2 cites.
  - `scripts/check_guidance.py --agent-texts` runs S2.7's sentence check over the agent's own
    fixed texts and the coding tools' fixed result sentences.
- **A design note**, `docs/specs/2026-10-03-s3-precedent-tool-design.md` (Draft): a precedent
  tool the agent questions, placed after S4 by decision
  [0140](../decisions/0140-the-precedent-tool-after-s4-as-a-measured-v2.md).

### Done means, with evidence

1. The shape probe's six checks are answered and recorded, and any departure is decided by Andy
   — met — `docs/results/s3-shape-probe.txt` (commit `5890033`; job
   `s3-shape-probe-20261001T083255-8ff06e9`, 12 calls, $0.0049), from
   `scripts/s3_shape_probe.py`; tests `tests/test_s3_shape_probe.py`. Checks 1 to 3: yes
   (strict tools are accepted on both price variants; forced and required tool choice are
   honoured on both; a conversation of several turns works on batch). Check 4: the reasoning
   need not be passed back, so `loop.PASS_REASONING` stays off. Check 5: cost and cached tokens
   are reported on 12 of 12 calls. Check 6 prints "broken" for one batch call, which cached 0 of
   5899 prompt tokens after a switch from a forced tool to "required", while the standard call
   kept 5491 of 5898 across the same switch. The plan's switch rule was not met (the next batch
   call cached 5767 of 6033), so every step keeps its forced tool. Checks 7 and 8, added by
   the final review: arm B's fixed turn and a later trigger's opening turn are accepted on both
   price variants. No check called for a departure, so none was put to Andy. The reading is the
   plan's Task 4 entry of 2026-10-01.
2. The new sealed sample's list is committed and refused by every command; the S3 statistics
   file is committed — met — `tests/fixtures/eval/dev_seal_s3_400_ids.csv` (401 cases, commit
   `415c6dd`); its purity:
   `tests/test_contamination.py::test_the_s3_sealed_sample_is_development_and_shares_no_case_with_an_earlier_sample`.
   The refusals, each before anything is read:
   `tests/test_eval_app.py::test_run_and_transcribe_refuse_the_sealed_sample_before_anything_is_read`,
   `::test_baseline_refuses_the_sealed_sample_before_anything_is_read` and
   `::test_check_refuses_the_sealed_sample_before_any_client_is_built` (each run for both sealed
   samples), `::test_arm_c_refuses_its_sealed_sample_before_anything_is_read`,
   `::test_check_refuses_a_held_out_or_sealed_arm_c_run_before_any_reservation_or_client`, and
   `tests/test_agent_armb.py::TestCommand::test_tools_refuses_before_any_client_is_built`. The
   statistics: `src/ntsb_probable_cause/scoring/tables/coding_stats_s3.json` and
   `docs/results/s3-coding-stats.txt` (6,956 pool cases from 2009–2014 and 5,134 from
   2015–2019).
3. `ntsb-eval run --arm C` runs `dev-400` on batch to completion, resumably — met — the two
   noise-floor runs, `20261001T201506-fd6053f-dev-400-C` and
   `20261001T201648-fd6053f-dev-400-C`, each completed on batch over 401 cases
   (`docs/results/s3-noise-floor-dev.txt`). The 20-case batch smoke run
   `20261001T140150-5a63002-dev-400-C` was stopped after its second round was sent, and
   resumed. The resume waited on the batch already sent, and its 192 calls had 192 distinct
   replies from the 12 batches sent, so nothing was paid for twice (the plan's Task 14 entries).
   Tests: `tests/test_agent_drive.py::TestResume` and `tests/test_agent_run.py::TestResume`.
4. Arm B's tool post-pass runs on a finished arm B run — met — `ntsb-eval tools` over S2.7's
   final answer run `20260929T053953-674c92e-dev-400-B` wrote
   `20260929T053953-674c92e-dev-400-B-tools` (401 cases, 3 rounds;
   `docs/results/s3-armb-tools-vs-s27-armb-answer-dev.txt`), and the ordering check over it
   completed S3's arm B (`docs/results/s3-armb-full-dev.txt`). Tests:
   `tests/test_agent_armb.py::TestCommand::test_tools_then_check_gives_arm_bs_full_pipeline` and
   `tests/test_agent_armb.py::TestBatch::test_a_batch_post_pass_writes_the_same_cases_as_a_sync_one`.
5. The noise floor's results file is committed, from a script, with every figure of §10.2 —
   met — `docs/results/s3-noise-floor-dev.txt` (commit `e694635`), from
   `scripts/s3_noise_floor.py`. It holds the paired differences in occurrence top-1, top-3 and
   finding recall@10 (top-1 -2.1% [-5.9%, +1.6%] on 387 cases), the cases whose first code
   changed (162 of 387), read-or-skip agreement (2392 of 2608 documents), coding-call agreement
   (3 of 387 cases), failures by reason, cost, the cached share of prompt tokens (71.6% and
   66.7%) and the raw stated confidences. No third run was needed (-2.07 points, within 4.0).
   Test: `tests/test_s3_noise_floor.py::test_the_report_prints_every_figure_with_its_denominator`.
6. The format gate is met on the noise-floor runs — met — `docs/results/s3-noise-floor-dev.txt`:
   run a passes with 5 of 401 cases failed for format or tool reasons, and run b with 8 of 401,
   exactly at the limit of 8. Test:
   `tests/test_s3_noise_floor.py::test_the_gate_passes_eight_format_failures_and_fails_nine`.
7. Each tuning round is registered before it runs, and read by its rule — not applicable — no
   round was registered or run (decision 0139). The measurements Task 15 made instead each had
   their rule, prediction or definitions committed before their result: the precedent probe
   (`a0c6cc6`), the coding-consistency probe (`700afda`), the finding-consistency probe
   (`211c50e`), the findings-from-precedent probe (`1c44b9d`), the "where the findings go wrong"
   probe (`ef25347`), the whole-pool second readings (`bb5155b`), and the ordering diagnostic,
   whose reading rule is decision 0137 (`1ad41f0`). The case groups and the miss-kind count are
   descriptive and carry no rule.
8. `make check` passes, including the tests of §16 — met — `make check` at the merge commit
   `35f6c01`: 3681 tests passed, coverage 98.37%; and pull request #21's CI on `35f6c01`
   (lint, test, audit and image-build passed:
   https://github.com/floyda/ntsb-probable-cause/pull/21/checks). The tests of §16:
   - a reply that breaks the protocol (a wrong or unknown tool, arguments that do not parse, a
     missing or repeated decision on an offered document) is answered with a message and the
     step is issued once more:
     `tests/test_agent_loop.py::TestProtocolBreaks::test_answered_not_accepted_and_reissued_once`;
     an unknown code given to a coding tool is answered and counted:
     `tests/test_agent_loop.py::TestArgumentErrors::test_an_unknown_code_counts_and_the_case_goes_on`;
     a document number not on offer is answered and skipped (decision 0134):
     `tests/test_agent_loop.py::TestExtras::test_a_number_not_in_the_listing_is_answered_and_the_case_goes_on`;
   - no title and no document text in the trail:
     `tests/test_agent_loop.py::TestTrail::test_holds_no_tool_result_text_only_its_size`;
   - the guard: `tests/test_agent_loop.py::TestLeaks::test_a_leak_in_a_chosen_document_ends_the_case`,
     `tests/test_agent_run.py::TestLeaks::test_a_leak_in_a_chosen_document_fails_that_case_only`,
     `tests/test_boundary.py::test_an_arm_c_batch_run_sends_no_withheld_text_in_any_request` and
     `tests/test_boundary.py::test_an_arm_c_sync_run_sends_no_withheld_text_in_any_request`;
   - the new sealed sample: condition 2. The statistics script's refusals:
     `tests/test_coding_stats_script.py::test_check_pool_refuses_a_sample_case_or_a_non_development_case`
     and
     `tests/test_coding_stats_script.py::test_the_s3_pool_leaves_out_the_new_sample_and_the_guard_refuses_one_that_is_present`;
   - room for the answer and the refinement:
     `tests/test_agent_loop.py::TestCap::test_the_refinement_is_held_back_before_the_answer` and
     `tests/test_agent_loop.py::TestCap::test_coding_that_passes_the_cap_is_forced_to_answer`;
   - the cache condition:
     `tests/test_agent_loop.py::TestAppendOnly::test_system_and_tools_are_identical_on_every_call_and_across_cases`
     and `tests/test_agent_schemas.py::test_tool_definitions_serialise_identically_across_imports`;
   - later triggers:
     `tests/test_agent_triggers.py::TestTheOpening::test_holds_every_document_read_before_in_full_and_the_summary`,
     `tests/test_agent_triggers.py::TestOfferedAgain::test_a_document_skipped_before_is_offered_again`
     and
     `tests/test_agent_triggers.py::TestOfferedAgain::test_without_new_structured_evidence_no_h0_call_is_made`;
   - the `probe` spend kind:
     `tests/test_budget.py::test_a_probe_spend_row_validates_and_month_spent_counts_it` and
     `tests/test_relabel_probe_spend.py::test_month_spent_is_unchanged_by_the_relabel_and_nothing_is_counted_twice`;
   - the import contract: `lint-imports` in `make lint`, and
     `tests/test_import_boundaries.py::test_nothing_in_the_library_imports_the_agent`.
9. The As-built record is appended, the plan deleted, and the version set (0017) — met — this
   pull request's close-out commit; `uv run python -m scripts.check_docs` clean. The
   specification's status stays Approved, because S3.2 and S3.3 follow under it; the version is
   0.8.0.

### Departures from this specification

Every entry of the S3.1 plan's Deviations section is here, rewritten plainly, with the five
items the final review added. The first group changes what this specification says; the rest
follow the plan's tasks. The plan, at its last commit, is linked in the Implementation record.

#### What changes what this specification says

- **§10.3, tuning rounds: none was run** (Task 15; decision 0139). No candidate's expected gain
  cleared the noise between two identical runs (top-1 -2.1% [-5.9%, +1.6%]), and the probes,
  the ordering diagnostic and the comparisons with arm B already showed where the limits are.
  The loop frozen at `fd6053f` is S3.1's result. The candidates stay written in 0139 for a later
  stage.
- **§10.5, "does not compare arm C with arm B": S3.1 made six comparisons** (final review).
  S3.1 committed six arm C against arm B comparisons on `dev-400` (`docs/results/s3-armc-*`):
  each noise-floor run against S2.7's final arm B, against arm B with its tools step, and
  against S3's full arm B. Each is cited as a development reading, not a claim, and decision
  0139 relies on them. Against S3's full arm B, run a's paired differences are occurrence top-1
  -1.0% [-5.3%, +3.3%], top-3 -11.4% [-16.0%, -6.9%] and finding recall@10 +0.4% [-2.0%, +2.9%]
  (`docs/results/s3-armc-a-vs-s3-armb-full-dev.txt`). **S3.2's registration must state that
  this `dev-400` result was seen before its predictions were written.**
- **§19, similar-case search: probed, not built** (Task 15; decisions
  [0138](../decisions/0138-precedent-pool-whole-for-development.md), 0140). §19 puts
  similar-case search outside S3. Task 15 measured it only with free, offline probes, which
  score nothing and feed no run. The five nearest earlier cases' first codes came out "in
  between" by their rule (`docs/results/s3-precedent-probe-dev.txt`), and their findings "not
  promising" (`docs/results/s3-finding-precedent-dev.txt`). Decision 0138 sets the whole pool,
  less the judged case's own event date, for development precedent work. Decision 0140 places a
  precedent tool after S4, as a measured second version of the agent; its design note is
  `docs/specs/2026-10-03-s3-precedent-tool-design.md` (Draft).
- **§7.1 and decision 0127 item 4, the ordering check in arm B only** (Task 15; decision 0137).
  The check ran once over noise-floor run a, as a diagnostic, to test 0127's premise that the
  loop's own tool calls do its job: top-1 +1.3% [-1.5%, +4.1%] on 394 paired cases
  (`docs/results/s3-check-diagnostic-dev.txt`), so the premise is not shown to fail. The check
  stays out of arm C.
- **§4.2 and §9, a docket with nothing readable** (final review; decision 0133). The loop
  dropped such a docket and told the model "No docket documents are available for this case.",
  which was false, while arm B always sends the listing. Arm C now sends the listing, its
  not-readable lines and "None of the documents listed can be read." (decision
  [0074](../decisions/0074-words-in-images-are-read-in-the-build.md): equal evidence). The docket
  state is "none" only when nothing is listed: it describes arrival, not readability.
- **§10.3, how a round's change is labelled** (final review; decision 0133). The prompt version
  carries `+p`, a fingerprint of the source of every module that builds model-facing text, so a
  kept round's text change cannot share a label with the noise-floor runs. It is computed once,
  at a run's start. A false change is accepted: a progress-line edit to `agent/armb.py` moved
  `+p10738adc39f3` to `+p947fac1c86a4` with no text the model sees changed (Task 14).
- **§5.1, §5.2, §8.3 and §16, document numbers not on offer** (Task 14; decision
  [0134](../decisions/0134-read-choices-tolerate-documents-not-on-offer.md)). §5.2 says code
  checks that each number is on offer. In the first smoke run both read choices were refused
  once, because the instruction asks for a decision on every document listed, while only
  readable documents are on offer. A decision on a document not on offer is now answered with a
  fixed line, skipped and counted as an argument error, with no retry. A missing or repeated
  decision on an offered document still refuses the call. §8.3's trail gains
  `AgentCall.offered`, the documents on offer at each read choice.
- **§14 and §8.2, what the spend line counts** (Task 14; decision 0135). Batch replies carry no
  cost of their own, so a run's recorded cost prices every prompt token at the batch rate, but
  cached tokens are billed lower: the 20-case batch smoke run recorded $0.1458 computed against
  $0.0484 billed, with 82.7% of its prompt tokens cached. S3's spend line and the monthly guard
  count the billed total of a batch arm C run or tool post-pass. Every record keeps both
  figures, and the per-case cap still uses the computed estimate.
- **§8.4 and §10.3, failures in the do-no-harm rule** (before Task 15; decision 0136). The
  specification says failures count, but not how. In an S3 round a failed case counts as wrong,
  and a round over the format gate is dropped whatever its accuracy.
- **§5.5, the shape probe's checks** (final review). Checks 7 and 8 were added: whether arm B's
  fixed four-call turn and a later trigger's opening turn are accepted, since no earlier call
  had sent either shape. The probe's reserve and cap rose from $0.05 to $0.08.
- **§12 and decision 0129, the sample and pool sizes** (Task 5). The draw gave 401 cases, 200
  fatal and 201 non-fatal, not 400: `samples.draw` rounds each class's quota separately, as it
  did for `dev-400`. The S3 pool holds 12,090 cases (6,956 from 2009–2014, 5,134 from
  2015–2019), 401 fewer than S2.7's 12,491 (`docs/results/s3-coding-stats.txt`), against
  "about 400" in §12.
- **§1 and §9, the docket wording** (Task 1). The body says dockets arrive at closure and that
  the ongoing-docket probe agrees. But `docs/results/s25-ongoing-dockets.txt` found 2 of 100
  ongoing cases with a released docket, and the recorder report leaves out 5 dockets seen at a
  case's first sight; none of these has an arrival time. The records and the roadmap note use
  the narrower statement: no docket has been seen to arrive before closure.
- **§10.2, "153 of 399"** (Task 1; final review). §10.2 cites it to
  `docs/results/s27-round0-dev.txt`, which prints "same first guess: 246 of 399"; so 153 = 399
  − 246 is the count whose first guess changed. Task 1 had found no file holding 153 (the
  file's "123 of 399 cases change outcome" is a different measure). The body is unchanged
  (decision [0017](../decisions/0017-spec-lifecycle-as-built-and-plan-deletion.md)); `CLAUDE.md`
  cites 246 directly.
- **Decision 0137 cites a deleted plan** (final review). Its cost figure, $0.1133 for S2.7's
  Luna check over the 401-case sealed run, is from the S2.7 plan's 2026-09-29 entry. That plan
  was deleted at S2.7's close-out (pull request #19); the figure is in its last version:
  https://github.com/floyda/ntsb-probable-cause/blob/bb6a0451d6113197775d17cb3767b37a01f3c9a5/docs/plans/2026-09-26-s27-track1-coding-guidance.md
- **The plan's Task 16, and the merge** (final review). The pull request was opened before the
  close-out, because the close-stage skill needs it open. It is merged with a merge commit
  (decision [0033](../decisions/0033-stage-pull-requests-keep-their-commits.md)), not the squash the
  skill's text names. `main` was merged into the branch at `35f6c01` (S2.7's close-out and
  dependency bumps).

#### Task 1, the decision records

- Dated "Superseded in part" notes were added to 0021, 0022 and 0023, as earlier supersessions
  did; the plan named only their index rows. 0106's index row notes that 0132 closes its item
  5's S2.8 route. 0132 records that the unmerged `s28-coding-lookup` branch's draft records,
  numbered 130 to 134, were never accepted.
- The agency design says it is marked Superseded once the S1 and S3 specifications are
  Approved. Only a dated note was added: its status change is left for Andy, and it still reads
  Approved.
- The final review corrected the new records in place, before any merge: 0121's docket heading
  is narrowed and "identical runs" became "runs with identical settings"; 0123 and the note on
  0023 keep the qualifier on the 2 released dockets; 0128 names S3.1's share of the line as $20
  and says the estimates' upper ends, $52.50, pass the $50 line; 0129 states 401 cases; 0130
  says the 2% gate is set on judgement; 0131 says its $1.1954 total is the unrounded sum (the
  three costs printed to four places add to $1.1955); 0132's wording is "no content from it is
  cited".
- Andy decided 0121 item 5's open question (2026-10-01): 0022 item 4's conclusion ("retrieval
  was warranted and the loop was not") does not carry over. Each of the four results is
  published as it stands, and S3.2's registration states how they are read together. 0022's
  note and index row say so, and 0132's index row now matches its record.

#### Task 2, the probe spend kind

- The relabel writes the new rows to a side file, checks their count and total against the
  original, and only then renames. It checks all three jobs before it changes any, so a failure
  leaves every job folder as it was. It ran on the shared runs folder, dry run first, and
  printed $0.0692, $0.5542 and $0.5721; September's `month_spent` was $50.2395 before and after.
- `tests/test_s3_probe_run.py` follows the new kind, and the `s3-spend` target follows the
  Makefile's layout.

#### Task 3, the model seam

- `ToolText` has its own construction token, apart from `Payload`'s, and refuses anything but a
  string. A tool turn refuses reasoning details, which would otherwise be dropped unseen. The
  boundary test gained the tool-text surface. A lint rule moved `tool_reply`'s default usage
  into its body. No existing test needed a change for the tool-call-id rule.

#### Task 4, the shape probe's code

- Call 2b (reasoning passed back) runs on both price variants, the batch chain is its own
  conversation, and `parallel_tool_calls=False` is sent on every call, as the loop sends it.
  Each call records whether it called a tool at all. The probe goes through the real client's
  code path and has its own cap; a batch that does not finish is recorded "unfinished".
- A call has a fifth state, "error" (an outage, a timeout, an expired or cancelled batch). Its
  checks read "not measured", never "no", so an outage cannot stop the work or switch reasoning
  on. No provider text is saved. The reservation is settled on every path, and the results are
  printed before the bookkeeping.
- The boundary test now reads an assistant turn's readable reasoning. Encrypted reasoning
  cannot be screened, and a test says so.

#### Task 5, the sealed sample and statistics

- `draw_sealed.py` prints the sample by fatal and class (fatal: C 0, F 156, L 44; non-fatal: C
  113, F 3, L 85), and `--verify` re-draws it identically. `Stage` and `Draw` tables replace
  single constants, and `samples.sample_path` is new.
- `ntsb-eval check` refuses S2.7's statistics for `dev-seal-s3-400`, whose 401 cases S2.7's pool
  still holds (`refuse_pool_holding`). Task 5 noted that a check did not name its statistics
  file; the final review made a check on any file but S2.7's name it in its label
  (`+check-<way>-<stats>`).
- The tests that need the generated files were written first and committed with the files.
  `tests/test_contamination.py` gained the new list's purity test; the sealed-sample refusals
  run for both samples; `.pre-commit-config.yaml` admits `coding_stats_s3.json` (1,267 KB) past
  the large-file limit; the refusal names decisions 0095 and 0129.

#### Task 6, the tools and their definitions

- The definitions follow one fixed order, the flow's. Class docstrings are stripped from the
  argument schemas, so editing one cannot change the bytes the provider caches.
  `definitions()` returns deep copies, and a test compares the bytes across two interpreters.
  The twelve phase-group names are written out, because the type checker refuses the unpacked
  form.
- Argument errors name fields and error types only, never the model's values. Choices the brief
  left open: the line `suggest_codes` returns for a group with no cases, `describe_codes`
  keeping its check of `kind`, and a tool name that does not match its arguments raising
  `TypeError`, as a programming error.
- The package reached `records` indirectly through `model.client`. Task 10 resolved it by moving
  `ToolText`.

#### Task 7, texts and payloads

- `PROTOCOL` gained a heading and one sentence on the tools' limits, in plain ASCII. The system
  text is arm B's with its trailing whitespace trimmed, then the protocol.
- Formats the brief left open were fixed: the menu's not-readable and already-read lines, and
  the read summary. The final review changed "1 pages" to "1 page", and "Not readable (no text
  layer):" to "Not readable:", because "no text layer" is not true of a failed fetch or a file
  that is not a PDF.
- An empty payload is `{}`. `case_marks` checks that the view belongs to the record. The import
  check uses `find_shortest_chains(..., as_packages=True)`, with a positive control.
  `prior_summary` came with Task 11.

#### Task 8, the case loop

- The step table is in `agent/steps.py`. `loop.py` is longer than the brief's "about 500" lines
  (587 at Task 8, and 696 after Task 11).
- Room for the answer and its refinement is held before every call up to the answer, not only
  before coding calls (§8.2), because a large document read at a choice is the likeliest way to
  lose the answer. The estimate counts the tools each call sends.
- `LoopConfig` gains the model and the reasoning level. `texts.ANSWER_NOW` is new, for the
  coding ablation. A reply with no tool call is sent again unchanged. A coding tool that raises
  is a protocol break, not a crash. Every refusal is reduced to field names and error types.
  `LoopOutcome.answer` is set only when the case is done.
- The refinement's payload is arm B's shape, narrowed to what the agent saw: the listing and
  the documents read (`documents.answer_payload`), not the non-docket evidence alone. A leak
  keeps the call's arguments and hypothesis in the trail.

#### Task 9, the drivers

- `CaseLoop` gains `stop`, `case_id` and `call_index`. The drivers replay the folder
  themselves. A reply is written before its loop is given it, so a fault after a batch returns
  loses nothing paid for. A resume copes with an open round partly or wholly written, and
  refuses a result for a call the round never asked about.
- A dead batch (expired, failed, or completed with no result) is sent again whole and costs no
  case an attempt. A batch the provider has lost is sent again once, on resume. A cancelled
  batch stops the run, which can then be resumed. A dead round counts toward the round limit.
  `drive_sync` takes a model error as a failed call and refuses a folder with an open batch
  round. Refusals are `ConfigurationError`.

#### Task 10, arm C in the harness

- `ToolText` moved to `model/tool_text.py`, so the contract "The agent's tools and texts see no
  case record" holds as written, with no exemption.
- `spec.json` records every setting the loop depends on (`agent_prompt_version`, `stats`,
  `max_rounds`, `max_coding_calls`, `without`, `pass_reasoning`, `round`), and a resume compares
  them. `AgentRunner` also refuses `include_case_number`, a batch run with no batch client and a
  held-out run with no ledger path; `Runner.run` refuses arm C. Three of the runner's private
  pieces became shared functions.
- A case whose refinement cannot run is unscored, as in arm B. A leaked case is arm B's record,
  with the calls made before the leak in its cost. `documents_not_read` says `skipped` or
  `undecided`. The report says "unread" where arm B says "cap", and prints the cached share. The
  run record counts what a dead round cost.
- Progress is printed per round. A cancelled batch writes the records first and says how to
  resume. `--cap-usd` defaults by arm; arm C reads S3's guidance by default; `--without` is
  refused on other arms; `resolve_latest` finds a plain arm C run. The boundary test runs on
  both paths. The pairing guard now compares the docket's own key with the record's (final
  review; before, it could not fail).

#### Task 11, later triggers

- The docket state "some" is a keyword on `CaseLoop` (`docket_final`), not a field of `Prior`:
  whether more documents may come is a fact about now, which the caller knows. Nothing yet tells
  the model that more may come.
- Without new structured evidence, the opening carries what H0's result would: the listing and
  the menu (`documents.docket_payload`). `texts.ALL_READ` is new. The opening is in
  `agent/later.py`. `LoopOutcome` gains `prior`, and `ReadRecord` gains `trigger`. `prior_of`'s
  rules, the opening call's `record_hypothesis` shape and three more refusals fill what the brief
  left open. The summary adds no "prefer current evidence" instruction: that would be a prompt
  change for a round.

#### Task 12, arm B's tool post-pass

- The drivers take a `DrivenLoop` protocol, so arm B's `FixedToolsLoop` uses them unchanged.
  Five private pieces of `loop.py` and `run.py` became shared functions.
- The fixed turn carries the first answer as its content, with four calls, `fixed-1` to
  `fixed-4`. With no known phase group there is no `suggest_codes` call, since the agent itself
  could not make one. The label records the statistics file (`+tools-s3`).
- The payload is the source run's own, rebuilt and checked against its recorded fingerprint.
  Preparation comes before the reservation. The cap is the source run's, on the post-pass's own
  calls. A case the post-pass does not answer is unscored. A post-pass is not resumed: its
  folder is moved aside and the pass run again.
- More refusals than the brief named, among them a source with guidance other than S3's and
  `dev-seal-400` (final review), and an arm C source (the review of decision 0137).
  `resolve_latest` keeps its file pattern and skips derived and renamed runs by their record,
  not their name.

#### Task 13, the noise report and rounds

- The format gate counts every `failed: ` reason except `failed: leak` and `failed: rounds`, and
  fails closed on an unknown one. Running out of batch rounds is printed on its own line. A
  leak reads `leak: ...` and is not counted. The final review added how many counted failures
  had no reply.
- `spec.json` is compared key for key, apart from two keys that only size the reservation. The
  report also refuses a dirty tree, part of `dev-400`, a copied folder, a run named twice,
  missing files and a case outside development. Agreement is counted from `trail.jsonl`. The
  third-run rule is decided on whole counts. Each pair block names what (a - b) is.
- `round_result.py` reads the statistics file the run's `spec.json` names. `--round` is checked
  before anything is read. The template first left the failure rule to each registration;
  decision 0136 then set it.

#### Task 14, smoke runs and the noise floor

- Two one-case smoke runs at the standard price, `20261001T115444-5890033-dev-400-C` ($0.0057)
  and `20261001T131232-09ee533-dev-400-C` ($0.0058), both finished. In the first, from its
  second call on, 85% to 97% of prompt tokens were cached. The first led to decision 0134.
- The 20-case batch smoke run (condition 3) finished 20 of 20 cases and led to decision 0135.
  The noise-floor target reserves $0.008 a case: the run's $0.0073, rounded up. Arm B with S3's
  guidance on the same 20 cases (`20261001T160605-77b41fd-dev-400-B`, $0.0313) and its
  post-pass (20 of 20; $0.0295 computed, $0.0250 billed) finished, and the loop was frozen.
- A resume's progress line now says it waits on a round sent before it. That edit moved `+p`
  (above).

#### Task 15, tuning

- No round was run (above). Instead, outside the plan: trail reading pages from arm C's "always
  wrong" group, the miss classifier and its count, the precedent probe and its reading page, the
  coding- and finding-consistency probes (the latter's like-for-like line redefined per level
  before any figure was read), the findings-from-precedent probe (its intervals made
  independent of case order before its result was read), the "where the findings go wrong"
  probe, the whole-pool second readings, and the ordering diagnostic. Their committed results:
  - case groups: across arm C's two runs, 79 of 401 cases always right, 266 always wrong and 56
    flipping. S2.7's arm B runs carried no guidance, so the arms' groups differ partly by
    guidance (`docs/results/s3-case-groups-dev.txt`);
  - cases whose NTSB cause sentences are identical share the first occurrence code in 619 of
    1650 (37.5%), but a mean 74.1% [72.2%, 75.9%] of their flagged findings
    (`docs/results/s3-coding-consistency-dev.txt`,
    `docs/results/s3-finding-consistency-dev.txt`);
  - precedent: first codes "in between" (found in 48 of 266 "always wrong" cases, against a
    control's 19); findings "not promising" (recall@10 -3.6% [-6.8%, -0.6%] against the loop's
    own), and "not promising" again under the whole pool (-0.6% [-3.8%, +2.6%]);
  - the loop's finding misses: item choice reads as case-specific, since the NTSB's item is the
    pool's commonest in only 46 of 213 item misses (`docs/results/s3-finding-misses-dev.txt`);
  - arm B's tools step adds occurrence top-1 +6.8% [+4.0%, +9.8%] and finding recall@10 +4.7%
    [+2.5%, +7.0%] to S2.7's answer (`docs/results/s3-armb-tools-vs-s27-armb-answer-dev.txt`).
- A review found that the change for decision 0137 let arm B's post-pass accept an arm C
  source, through a shared function. No such run was made, and it is refused again.
- Two earlier attempts at the full tool post-pass lost their first batch at the provider (a
  404, no cost recorded). Their folders are kept, as `…-tools-lost-batch-1` and `-2`.

#### Across tasks

- Each task's tests were shown able to fail by one-line mutations of its code (Task 4: 14; Task
  8: 36; Task 9: 49; Task 10: 65; Task 11: 36; Task 12: 126, one of them equivalent; Task 13:
  56; decision 0134: 12; and each Task 15 script). The plan's entries record each set.
- Files outside a brief's list were changed where a task needed them: test files, `README.md`'s
  scripts table, `.pre-commit-config.yaml`. Each is named in its plan entry. The `.PHONY` line
  lost a space three times through the editing tool; `tests/test_makefile.py` now checks every
  word of it.
- The final review also made one `pass_reasoning` setting (`loop.PASS_REASONING`); added
  `agent.steps` and `agent.facts` to the tool-text contract; skipped a reasoning entry that is
  not an object, and made the boundary test fail closed on an unknown shape; made
  `stage_spend` cite S3's own decision (0128 item 2); and fixed two small texts.
- S2.7's sentence check now also covers the agent's fixed texts (final review) and the coding
  tools' fixed result sentences (before Task 14). None of them appears in any development
  case's narratives or probable cause.

### Known issues carried to S3.2

From the final review. None changes a committed result.

- A resumed round whose replies are all on disk, but whose batch the provider reports as
  cancelled, stops the run. One more resume continues it.
- In a resumed round that was partly answered, a call with no reply counts as a failed attempt
  (one of its case's two) instead of being sent again. This matters before S3.2's once-only
  held-out run.
- At a read choice, the room held for the answer does not count the documents about to be
  attached. The cap still holds, but a case may stop at the cap before it answers.
- A case forced to answer at H0, before it saw the listing, still gets the listing in its
  refinement. At a $0.15 cap this cannot happen.
- The coding step catches every exception (`except Exception`), and no test pins the
  temperature.
- Arm C's `spec.json` holds arm B's `prompt_version` beside `agent_prompt_version`; only the
  second is the loop's.
- `scripts/reply_budget.py` misreads arm C's reply tuples.
- Arm B's post-pass refuses an over-budget run only after it has read every docket. Its
  `+tools-<name>` label comes from the name passed beside the statistics, and nothing checks
  that the two match. Its refusal of a source that is not arm B's names "the ordering check".
- No `month_spent` test covers a dead round that reported a cost.
- S3's arm B answer runs count the computed price, while arm C counts what was billed. S3.2
  must define "equal cost" before its run.
- The noise pair read under decision 0136's own rule (all 401 cases, a failed case counted
  wrong) was never committed; decision 0139 uses the 387-case figure in its place.
- The precedent probes limit the pool by event date, not by the date an earlier verdict was
  published. This can only favour the search.
- `make s3-miss-kinds` with a group other than the default writes over the committed results
  file.
- `AgentCall.offered=()` cannot tell a row written before decision 0134 from a choice with
  nothing on offer.
- In `apps/eval/__main__.py`, an unreadable `spec.json` reads as "no ablation".

### Decisions taken during the stage

- [0121](../decisions/0121-agency-moves-to-reading-and-coding.md) — Agency moves to the read
  choice and the coding step; parts of 0021 to 0023 are superseded.
- [0122](../decisions/0122-h0-and-later-triggers.md) — The first hypothesis uses all non-docket
  evidence present; later triggers re-send read documents in full.
- [0123](../decisions/0123-the-staged-replay-is-paused.md) — The staged replay is paused: no
  docket has been seen to arrive before closure; re-checked at 14 nights.
- [0124](../decisions/0124-native-tool-calling-and-a-cacheable-conversation.md) — Native tool
  calling, with a stable tool set, `tool_choice` per step and an append-only conversation.
- [0125](../decisions/0125-the-suggestion-tool.md) — The suggestion tool: the pool's five
  commonest defining events for a phase group, called by choice.
- [0126](../decisions/0126-confidence-is-calibrated-in-code.md) — Confidence is calibrated in
  code; abstain is a threshold on the fitted value.
- [0127](../decisions/0127-arms-ablations-and-the-ordering-check-in-arm-b.md) — S3's arms and
  ablations; arm B calls every coding tool; the ordering check runs in arm B only.
- [0128](../decisions/0128-s3-in-three-sub-stages-with-one-spend-line.md) — S3 in three
  sub-stages, with one $50 spend line.
- [0129](../decisions/0129-s3s-sealed-sample-and-statistics.md) — S3's sealed sample and
  statistics file; the guidance files stay unchanged.
- [0130](../decisions/0130-the-loops-noise-floor-and-format-gate.md) — The loop's noise floor,
  and a 2% format gate.
- [0131](../decisions/0131-the-probe-spend-kind.md) — The `probe` spend kind, and the relabel of
  the learning probe's rows.
- [0132](../decisions/0132-s28-is-cancelled.md) — S2.8 is cancelled.
- [0133](../decisions/0133-unreadable-dockets-are-listed-and-the-text-is-fingerprinted.md) —
  Arm C sees the listing of an unreadable docket; its prompt version fingerprints the text.
- [0134](../decisions/0134-read-choices-tolerate-documents-not-on-offer.md) — A read choice
  tolerates decisions on documents not on offer, and skips them.
- [0135](../decisions/0135-s3-spend-counts-what-was-billed.md) — S3's spend counts what the
  provider billed for its batch runs.
- [0136](../decisions/0136-s3-rounds-count-failed-cases-as-wrong.md) — In an S3 tuning round, a
  failed case counts as wrong, and the format gate is a hard limit.
- [0137](../decisions/0137-the-ordering-check-as-a-diagnostic-on-arm-c.md) — The ordering check
  as a diagnostic on arm C, run once.
- [0138](../decisions/0138-precedent-pool-whole-for-development.md) — In development work,
  precedent search reads the whole pool, less the judged case's own date.
- [0139](../decisions/0139-s31-tuning-closes-without-a-registered-round.md) — S3.1's tuning
  closes without a registered round.
- [0140](../decisions/0140-the-precedent-tool-after-s4-as-a-measured-v2.md) — The precedent tool
  is built after S4, as a measured second version of the agent.

### Implementation record

- Pull request: #21 (https://github.com/floyda/ntsb-probable-cause/pull/21), merged with a
  merge commit (decision 0033).
- Plan, at its last commit:
  https://github.com/floyda/ntsb-probable-cause/blob/6d2dad099ff8fc422aab3ee2e37116651221683a/docs/plans/2026-09-30-s3-1-agent-loop.md
- The learning probe's plan, deleted with it, at its last commit:
  https://github.com/floyda/ntsb-probable-cause/blob/7ae57993ad9835ebbffb48990d42a1d74f4caadd/docs/plans/2026-09-29-s3-learning-probe.md
  - Its Deviations, in short: H0 read the structured evidence, not the start facts alone; skip
    regret was measured against the probe's own read-everything call, not an old arm B run;
    spend was first recorded as `inventory` (relabelled `probe` by decision 0131) and kept in a
    separate ledger until S2.7's sealed run had finished; a repeat run measured the probe's
    noise; and its numbers carry stated caveats (skip regret mixes reading with run-to-run noise;
    read rates follow the instructions and the menu; a call that failed in transport is counted
    as free). §2 gives its results.
- Commits: from `777c2a5` (this specification's first draft) to `35f6c01`, the merge of `main`
  into the branch and the last commit before the close-out.
- Spend: S3 has spent $5.11 of its $50 line, all on evaluation runs, counted by commit on S3's
  branches (`scripts/stage_spend.py --stage s3`, 2026-10-03; decisions 0128, 0135).
- The loop: frozen at `fd6053f`; noise-floor runs `20261001T201506-fd6053f-dev-400-C` and
  `20261001T201648-fd6053f-dev-400-C`.
- Release: v0.8.0 (tag created by Andy after the merge; a merge commit, decision 0033).

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
