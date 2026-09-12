# Architecture and build roadmap

*Drafted 2026-09-12. Status: awaiting Andy's sign-off. This document records
architecture decisions and the order work will be done in. It does not design any
individual component; each numbered stage below gets its own specification before it
is built.*

**How to read this.** Each decision says what was chosen, then why, then what the
alternative would have cost. Terms in **bold** on first use are in the glossary at the
end. Every number quoted from the spike names the script or sheet it came from.
Numbers that are estimates rather than measurements say so explicitly — this document
introduces four of them, all about hosting cost, and all are marked.

---

## 1. What is being built

An agent that reads the evidence investigators gathered about a US general-aviation
accident and determines the **probable cause**, scored against the verdict the NTSB
later publishes. The spike (`../ntsb-spike/`) established that this is worth building:
a single model call with no tools scores 57% top-1 on the **occurrence code** against a
16.2% **conditional modal baseline** (`oneshot.py`, `baseline.py`), so the model is
reading the evidence rather than guessing. But that 57% splits into 88% when the case
has a written **factual narrative** and 12% when it does not, and only about 52% of
2020–23 cases have one. In 13 of the 14 no-narrative failures the missing information
was sitting in the case's **docket**. The agent exists to go and read the docket.
Nothing beyond that is justified by measurement yet.

This document covers how that agent is packaged, tested, deployed and published.

---

## 2. Repository topology

**Decision: two repositories, no more.**

- `ntsb-spike` — frozen. It is the citable record: an assumptions register, a report,
  labelling sheets, and a script behind every number. No new work goes here. One piece
  of housekeeping is owed (section 11, stage S-0).
- `ntsb-probable-cause` — the build. One repository containing a library, several thin
  entrypoints, infrastructure code, and the static site generator.

**Why one build repository rather than several.** The project makes one central claim:
*here are numbers measured on a held-out set, and here is the same agent running live
on open cases.* If the agent that gets deployed lives in a different repository from
the agent that was evaluated, the two can drift apart, and a sceptical reader has no
way to check. They must take the claim on trust, which is precisely what this project
is built to avoid.

With one repository, every prediction row records the commit identifier of the code
that produced it. A reader can check out that commit and re-run the case. The property
is enforced by structure, not by discipline.

**What was rejected.** Splitting the agent into a published package consumed by a
separate deployment repository is cleaner on paper and is how a team with several
consumers would do it. Here it introduces version skew between the measured artefact
and the deployed one, which is the exact failure the demo cannot afford. Folding the
spike into the build repository was also rejected: it would mix one-off measurement
scripts with product code and weaken the claim that the spike's record is frozen.

---

## 3. Internal structure

The repository is split by **responsibility**, not by where code runs.

```
src/ntsb_pc/          the library. no command-line entrypoints, no AWS, no printing
  data/               ingestion, record loading, evidence/answer split + assertion
  codes/              NTSB code tables, code-constrained output schema
  tools/              docket client, PDF classification and extraction  (weather later)
  agent/              loop, router, step budget, cost cap, trajectory log
  scoring/            scoring layers, per-slice reporting, confidence intervals
  store/              SQLite schema and repository functions
apps/
  eval/               local command: fixed case list, ablation flags, cost report
  recorder/           phase 1: poll open cases, diff docket listings, timestamp
  poller/             phase 2: run the agent on cases whose evidence changed
  watcher/            phase 3: detect closure, score the standing prediction
  site/               static generator: store -> HTML and JSON -> dist/
infra/                AWS CDK (Python)
tests/  fixtures/
```

The three scheduled modules are **phases of one job, not three schedules**. A single run
executes recorder, then poller, then watcher, in that order, and exits. This is what keeps
the single-writer guarantee in section 6 true: three independently scheduled tasks could
overlap, and the store design assumes they cannot. Each phase is runnable on its own
locally for development.

**The rule that keeps this honest:** every `apps/*` module contains argument parsing
and wiring only. If logic appears in an app, it belongs in the library, where a test
can reach it. The reason is that the library is the part that runs identically in all
three execution contexts; anything that lives only in an app is, by definition,
untested in two of the three.

---

## 4. The three execution contexts, and the one seam between them

The same library runs in three places:

| Context | Where | What it needs |
|---|---|---|
| Evaluation harness | Andy's machine, interactive, large local data | agent, docket tool, scoring, splits |
| Recorder, poller, watcher | AWS, scheduled, unattended | agent, docket tool, store |
| Site build | Continuous integration | store reader, scoring, templates |

These are three entrypoints over one library, not three systems.

**The model-client seam.** All model calls go through a single interface with one
implementation: OpenRouter (`https://openrouter.ai/api/v1/chat/completions`, bearer token
from the environment). Evaluation runs and scheduled live calls use the same transport.

Why one transport rather than the subscription locally and an API in the cloud: two
implementations of the same interface can behave differently, and the two places they
would have differed are precisely the two the project claims are equivalent. One transport
makes "the evaluated agent is the deployed agent" true at the transport layer as well as
the code layer.

The agent's model starts at `anthropic/claude-sonnet-5`, for continuity with the spike.
Model choice is a parameter of the harness rather than a constant, which makes accuracy
against cost across models an evaluation axis the project can report rather than assume.

Evaluation runs use the `:batch` variant at half price — they are offline and have no
latency requirement. The live path does not.

Checked before adopting this (2026-09-12, from `https://openrouter.ai/api/v1/models`):
`anthropic/claude-sonnet-5` advertises `reasoning_effort`, `response_format` and
`structured_outputs`, and does **not** advertise `temperature`, `top_p` or `top_k` —
matching the constraints the spike recorded for that model, where `anthropic/claude-haiku-4.5`
advertises the sampling parameters and no `reasoning_effort`. The metadata tracks each
model's real surface rather than flattening it. One live probe is still owed in S1 before
any measurement is trusted: metadata is not a response, and rule 2 is satisfied by a saved
real response.

Because the calls are metered, the £0.05-per-case cap is enforced in code rather than
watched. Cost per call is read from the response `usage`.

Full reasoning: `docs/decisions/0009-model-access-via-openrouter.md`.

---

## 5. Data flow

Data moves in one direction only.

```
NTSB Enterprise API
        |
        v
   ingestion  ------>  local processed file (large, never in git)
                              |
                              +--> evaluation harness --> results artefacts
                              |                           (small, committed)
                              |                                   |
AWS scheduled jobs --> predictions store (SQLite in S3) --> ledger |
                                                              |    |
                                                              v    v
                                                    site build (CI) --> S3 + CloudFront
```

**The property this buys: the public site is a pure function of the store.** Nothing is
computed when a visitor arrives. There is no server, no request-time database, no API.
The site is a folder of files.

Two consequences worth stating plainly:

1. Hosting cost does not move when someone links to the page. The demo criteria require
   cost to be bounded and instrumented; here it is bounded by architecture rather than
   by an assertion in a README.
2. The site build can be run locally and produce the same files continuous integration
   publishes. If the page is wrong, it is reproducible.

**The ledger and why continuous integration writes it.** Each prediction is appended to
a file in the repository with a hash, so the git history becomes a public, tamper-evident
record of what was predicted and when. The design notes suggested this. The scheduled
job does *not* write to the repository: it writes to durable storage, and continuous
integration pulls, verifies the hashes and commits. This keeps repository write
credentials out of the cloud job, which is both safer and easier to explain.

---

## 6. Deployment shape

**The project runs in its own AWS account.** Andy's existing account hosts `floyda.dev`
on S3 behind CloudFront with Route 53. That account becomes the management account of an
AWS Organization, and this project gets a member account of its own. An account is AWS's
real isolation unit: no mistake in this project's code, and no command an agent runs, can
reach the profile site, because the credentials do not extend there. Consolidated billing
then reports this project's spend as its own figure. DNS crosses the boundary once —
`ntsb.floyda.dev` is delegated to a hosted zone in the project account by a single NS
record in the parent zone, after which the project's own stack manages its records.
Reasoning: `docs/decisions/0010-separate-aws-account.md`.

**Decision: one scheduled AWS Fargate task, triggered by EventBridge Scheduler.
Infrastructure defined in AWS CDK (Python). Site on S3 behind CloudFront. State in a
SQLite file in S3 with object versioning.**

Three reasons, in order of weight:

1. **The compute choice determines the store.** A single scheduled container running the
   three phases in sequence (section 3) is a single writer, which lets SQLite remain SQLite: download the file, change it, upload
   it. The build brief already judged SQLite sufficient at 1,000–1,400 cases a year.
   Lambda with fan-out would mean concurrent writers, which means DynamoDB, which means
   two store implementations and a weaker local development story.
2. **Identical execution locally and in the cloud.** One container image, one
   entrypoint. What Andy runs on his machine is what runs at 03:00. This makes the
   "evaluated agent is the deployed agent" claim concrete.
3. **No fifteen-minute limit.** Polling a few hundred open dockets at a self-imposed 30
   requests per minute takes about ten minutes before the agent does any work at all.
   Lambda would need a queue and fan-out to work around a ceiling we do not have to
   accept.

**The counter-argument, stated fairly.** Lambda with SQS and EventBridge reads as more
conventional production infrastructure, and some readers treat serverless fan-out as a
signal of competence. The judgement taken here is that choosing the simpler shape and
being able to say exactly why — batch workload, single writer, one store
implementation, identical local run — is the better signal, and consistent with the
restraint the spike itself demonstrates. This is a judgement, not a measurement.

**Estimated monthly cost.** These four figures are estimates, not measurements, and
must be replaced with billed figures once the stack runs:

| item | estimate |
|---|---|
| Fargate, roughly 20 minutes a day at 0.25 vCPU | under £1 |
| S3 and CloudFront for a small static site | under £1 |
| Container registry and scheduling | pennies |
| Model calls, a handful of agent runs a day at £0.034 each | roughly £5 |

Model calls dominate. The total is expected to sit well inside £20 a month. A budget
alarm is set separately from the per-case cap in code, because the two fail differently:
the cap stops one runaway case, the alarm catches a pattern.

---

## 7. The output schema

The agent's answer carries seven fields:

| field | purpose |
|---|---|
| occurrence code | the NTSB category for *what happened*, chosen from a supplied list |
| finding codes | the NTSB categories for *why*, chosen from a supplied list |
| probable cause | one or two sentences, in the style the NTSB writes |
| lay explanation | plain English a non-expert can follow without leaving the page |
| confidence | a number from 0 to 1 |
| abstain flag | "I do not have enough evidence to say" |
| evidence used | which pieces of evidence the answer rests on |

**Why the codes come from a supplied list.** The spike scored free-text answers by hand.
When a small model was used as a stand-in judge, it agreed with Andy only 62.5% of the
time, and its errors were one-sided: it rejected 14 of the 23 answers he had marked
correct (build brief §5). A judge that unreliable cannot gate anything. If the model
picks from a list of codes, the headline score is exact match, and needs no judge and
no human at all.

**Why the lay explanation is included even though it costs a grading layer.** The demo
criteria require a reader with no domain knowledge to understand the output without
leaving the page. That requirement propagates backwards into the schema: if the page
must explain, the model must produce the explanation. It is graded rather than
published unchecked, because free text going public without a quality measure is the
kind of shortcut this project exists to avoid.

**A consequence to plan for.** The 57% ceiling was measured on free text scored by a
human. A model choosing from 58 occurrence codes is doing a measurably different task.
The 57% is therefore *not* a like-for-like bar for the new agent, and the comparison
must be re-measured: a one-shot run under the code-constrained schema, on the same 40
cases, before the agent is allowed to claim it beat anything. Cost: about £1.34 through
the API (`scripts/oneshot_summary.py` rate) or nothing on the subscription. This is
scheduled into stage S1 rather than discovered later.

---

## 8. The public surface

Five pages. This list is also the complete set of questions the store must be able to
answer, which is why it is settled before the store is designed.

1. **Home** — what the system does, the headline numbers, and the caveats stated
   *before* the results rather than after them.
2. **Live board** — open investigations, the agent's standing prediction, its
   confidence, and when it last changed.
3. **Case view** — the evidence-arrival timeline, every prediction ever made with its
   timestamp, and the NTSB's verdict beside them once it publishes.
4. **Trajectory view** — one case's steps, tool calls and costs. The demo criteria call
   this the single most compelling artefact available.
5. **Methods** — held-out numbers, the baseline, the ablations, each naming the script
   that produced it.

**Tone.** These are fatalities. The writing is clinical, no victim names appear
anywhere, and nothing on the page may read as a game or a scoreboard contest.

---

## 9. Testing and what continuous integration enforces

Four checks, each guarding a failure that cannot be caught by reading output:

- **The leakage assertion, as a test.** One function assembles everything a model sees,
  and asserts that no answer field is present. Analysis narrative, probable cause,
  occurrence codes and finding codes are answer fields. There is never a second payload
  assembler. This is the single rule the project's credibility rests on.
- **Held-out contamination.** A test that cases from the held-out years never appear in
  development fixtures. Tuning on the cases you report on makes the numbers meaningless,
  and the mistake is invisible once made.
- **Docket parser fixtures.** Saved real responses, so the parser is tested without the
  network and a change in the NTSB's page structure fails loudly rather than silently
  returning nothing.
- **Retrieval contamination**, only if similar-case search is ever added. It is not in
  scope now.

Continuous integration runs formatting, type checking and the test suite on every push
from the first commit. The reason for doing this at the start rather than later is that
a test which exists but is not enforced is indistinguishable from no test.

---

## 10. What is deliberately not being built

Each of these was considered and rejected on evidence, not on effort:

- **Similar-case search, regulation lookup, airframe history.** Andy labelled what would
  have fixed each of the 17 one-shot misses. None of them needed these. Building a
  retrieval tool nothing asked for would weaken the argument that agency was added only
  where it was measured to be warranted.
- **Reconstructing historical preliminary reports.** The API deletes preliminary text
  when a case closes. The timeline of an investigation exists only if captured live.
- **OCR of handwritten pilot forms.** Leaving it out cuts the reachable **agency**
  figure from 38% to about 25%, which is still above the 20% threshold the spike set, so
  the build decision does not depend on it. It is a phase-2 item and, when it comes,
  it is a *probe* with a written result rather than a build stage.
- **Any request-serving tier.** See section 5.

---

## 11. Build order

Each stage gets its own specification before it is built. "Done means" is the condition
for moving on.

### S-0. Spike housekeeping *(short, in the spike repository)*

The spike's `.gitignore` excludes `labelling/*.filled.csv`. Confirmed by `git ls-files`:
`decidability.filled.csv` and `leakage.filled.csv` are not in version control. Those two
sheets hold Andy's labels, and the 57% one-shot figure, the 20% leakage figure and the
A:0 / B:14 / C:1 miss breakdown all rest on them. The citable record currently has a
hole where its evidence should be.

Fix it as a small, clearly-described commit in the spike repository — completing the
record, not extending it. Decide separately whether `config.yaml` should be tracked; the
subscription key must stay out of version control either way.

*Done means:* the sheets are tracked, and every number in the spike report can be traced
to a file a stranger can open.

### S0. Foundation

Repository skeleton and tooling. Configuration and split definitions carried over from
the spike. Ingestion producing a processed file, with raw data kept out of version
control. The evidence/answer split function and its leakage test. The held-out
contamination test. Continuous integration. The model-client seam.

*Deliberately excluded, with where each went:* code lookup tables (S1 — nothing in S0
reads them); the SQLite schema (S2.5 — nothing in S0 writes to it, and designing a
schema before the access patterns are known is the mistake, not the precaution);
incremental ingestion (S2.5 — incrementality is a live-board requirement); trajectory
logging and cost accounting (S3 — nothing in S0 takes a step or spends money).

*Done means:* ingestion runs; the test suite is green in continuous integration; the
leakage test fails if an answer field is smuggled into the evidence payload.

### S1. Scoring and the evaluation harness

Code lookup tables, seeded from the spike's `decidability_form.build_code_lookups()`.
The code-constrained output schema, including the lay explanation. Exact-match scoring
for occurrence and finding codes. Per-slice reporting (narrative present / absent),
confidence intervals, cost per run, ablation flags.

Then two measurements: reproduce the 16.2% baseline through the new harness, and
establish the real code-constrained one-shot ceiling on the same 40 cases.

*Why reproduce a known number:* it is a correctness check on new code, not a
re-opening of the spike's finding. If the harness cannot reproduce a number that is
already known, it cannot be trusted to judge a number that is not.

*Done means:* one command produces the baseline and the ceiling, with intervals and
cost, and the ceiling figure is the bar recorded for the agent.

### S2. The docket tool

Docket client, HTML table parser, document downloader, classification by characters of
text per page, born-digital text extraction, caching, and offline fixtures built from
the 14 dockets already probed in the spike.

*Done means:* given a case identifier, the module returns extracted text and a manifest
of what it could and could not read; the tests run without network access.

### S2.5. The recorder

Poll open investigations, diff each docket's document listing against the last
observation, and stamp the time when a document first appears. The first tables in the
store. Incremental ingestion. No agent is involved.

*Why this is pulled forward, out of order.* The spike established that the timing of
evidence arrival cannot be reconstructed afterwards: the API deletes preliminary text at
closure, docket listings carry no per-document dates, and the web server's
`Last-Modified` header reflects caching rather than authorship. This is the only part of
the project with a hard clock on it. Every week it is not running is a week of timeline
that can never be recovered. It depends on the docket client and a table, not on the
agent, so it does not have to wait for one.

*Done means:* running on a schedule and accumulating first-seen timestamps.

### S3. The agent loop

Deterministic router — factual narrative present sends the case down a cheap
single-call path, absent sends it down the tool path. Tool interface, step budget,
abstain path, hard cost cap enforced in code, trajectory log.

*The tool interface is designed at the start of this stage, not now.* Designing it from
14 probed dockets would be guessing at shapes we are about to be able to observe
directly, once S2 and S2.5 have seen real ones.

*One honest question to carry into this stage.* The median docket holds 3 documents. If
most are that small, letting the model choose which to read is barely a decision, and
the loop risks being a pipeline in costume. The agency the spike actually measured is
the 38% figure: the share of cases where *going and fetching* changes the answer. So
the metric to publish is tool steps per case — and if it turns out the agent almost
never takes more than one, that belongs on the Methods page rather than in a drawer.

*Done means:* the five conditions from build brief §6, each produced by a script — at
least 50% top-1 on no-narrative cases, overall top-1 above the S1 ceiling, an ablation
showing the docket tool's contribution concentrated in no-narrative cases, sensible
abstention, and average cost under £0.05 per case.

### S4. Predictions and resolution

Predictions store with case, evidence fingerprint, timestamp, answer, cost and commit
identifier. The resolution watcher that notices a case has closed and scores the
standing prediction. The hashed ledger and the continuous-integration job that commits
it.

*Done means:* a case closing causes its standing prediction to be scored without anyone
intervening.

### S5. Deployment and the public site

CDK stack, scheduled Fargate task, S3 and CloudFront, the static site generator, and the
five pages.

*Done means:* a public URL, rebuilt from the store, with hosting cost that does not move
with traffic.

---

## 12. How decisions are recorded

Every decision in this document, and every significant one taken from here, is written to
`docs/decisions/` as a numbered record: context, decision, reasoning, and what it rules
out. Records are append-only — a decision that changes gets a new record naming the one it
replaces. The reasoning is the substance of this project, and a reader who disagrees with
a choice should be able to find the argument for it and say where it fails rather than
guess at what was weighed. Rule 8 in `CLAUDE.md`; format in `docs/decisions/README.md`.

## 13. Decisions deferred, and when they get made

| decision | deferred to | why |
|---|---|---|
| Tool interface and loop mechanics | S3 | needs real docket shapes, not the 14 probed |
| Store schema | S2.5 | the recorder is the first writer and should shape it |
| Grading method for the lay explanation | S1 | belongs with the rest of the scoring design |
| OCR for handwritten forms | phase 2 | a probe with a written result, not a build stage |
| Weather tool | after S3 | one of 17 misses; parameters already verified in the spike |

---

## 14. Inputs still needed from Andy

None of these block S0.

Answered 2026-09-12: an AWS account exists and hosts `floyda.dev` on S3, CloudFront and
Route 53 — so the domain question is settled (`ntsb.floyda.dev`) and the isolation question
is decided in 0010. Model access is decided in 0009; no Anthropic key is needed. The AWS
CLI (2.36.44) and CDK (2.1141.0) are installed locally.

Still open:

- Preferred AWS region.
- A monthly spend ceiling for the budget alarm, and the address alarms should reach.
- Whether `config.yaml` should be tracked in the spike repository (S-0).

---

## 15. Risks

| risk | why it matters | how it is handled |
|---|---|---|
| The 57% bar is not comparable | The headline claim is "beats the one-shot ceiling"; if the ceiling was measured on a different task, the claim is empty | Re-measure under the code-constrained schema in S1, before the agent exists |
| The loop turns out to be a pipeline | The whole project rests on agency being warranted | Publish tool steps per case, including if it embarrasses the design (S3) |
| Docket page structure changes | Silent wrong answers rather than a visible outage | Parser fixtures in continuous integration; failures are loud |
| The live board has too few resolutions to mean anything | Median time to close is 140 days; the first six months will yield a handful | Say so on the page first. The held-out numbers carry the weight; the board is the narrative device |
| Cost runs away on a pathological case | Real money once scheduled jobs use the API | Hard per-case cap in code, plus a separate account budget alarm |

---

## Glossary

**Ablation.** Re-running an evaluation with one input or tool removed, to measure what
it was contributing. If the score does not drop, that input was not earning its place.

**Agency (the 38% figure).** The share of all cases where going and fetching something
changes the answer. The spike's rule was that 20% or more justifies building an agent.

**Born-digital PDF.** A PDF created on a computer, so its text can be read directly.
A scan is a picture of paper and needs optical character recognition.

**Code-constrained output.** Requiring the model to answer with a code from a fixed list
rather than free text, so answers can be scored by exact match with no judge.

**Conditional modal baseline.** "Guess the commonest answer, given something known in
advance." Here, the commonest occurrence code for this phase of flight and weather.
Scores 16.2%.

**Docket.** The NTSB's public folder of supporting documents for one investigation.

**Evidence half / answer half.** The split of each record. Evidence is what the agent
may see. Answer is what it must not. Enforced in one function with an assertion.

**Factual narrative.** The written account of the facts in the final report. Present on
about 82% of cases overall, but only about 52% of those from 2020 to 2023.

**Finding codes.** The NTSB's categories for why an accident happened.

**Held-out set.** Cases never used while building. Scored only at the end.

**Infrastructure as code.** Defining cloud resources in a programming language so they
are version-controlled and reproducible rather than clicked into existence.

**Ledger.** The append-only, hashed record of predictions committed to version control,
so a reader can verify what was predicted and when.

**Occurrence code.** The NTSB's category for what happened: six digits, a phase prefix
plus an event suffix.

**One-shot.** Sending the evidence to the model in a single message with no tools. Its
score is the ceiling for what you get without an agent.

**Probable cause.** The NTSB's determination of why an accident happened, published for
every closed investigation. The project's ground truth.

**Top-1 / top-3.** Top-1: the first answer is exactly right. Top-3: the right answer
appears in the first three.

**Trajectory.** The sequence of steps the agent took on one case: tools called, what
came back, what it decided, what it cost.
