# Agency: the hypothesis trail — design

*Drafted 2026-09-14 from a design discussion with Andy, and merged as a Draft in pull
request #1. Revised the same day after S0 closed (pull request #2, release `v0.1.0`), and
rewritten so that it is absorbed into the rest of the documentation.
Status: Approved on the merge of the pull request that carries this revision.
What was decided is in decision records 0021 to 0024. When each part is built is in
[the architecture and roadmap](2026-09-12-architecture-and-roadmap.md). This document keeps
only what those point to: the detail that the S1 and S3 specifications will take over, and
the record of how S0 changed the design. Section 1 maps every part to where it now lives.*

**How to read this.** Section 1 is the map. The rest is detail, each part citing the record
that decides it. Terms in **bold** on first use are in the glossary at the end. Every number
comes from a named script: the spike's (`../ntsb-spike/`) or S0's corpus scan
(`docs/results/s0-corpus-scan.txt`). None is new. Anything that is an illustration says so.
Tool names are placeholders: the tool interface is designed at the start of S3.

---

## 1. Where each part now lives

| part | lives in | what remains here |
|---|---|---|
| Agency is a scored hypothesis trail; the stopping rule; publishing the trail and the live statistics | decision 0021 | the step record fields (§5.4), score definitions (§6.3), live statistics (§7.2) |
| Three arms, arm B's filter, the loop's bar, the predictions P1–P6 and the four results that count against the loop | decision 0022 — the predictions are fixed there, because records are append-only | how the arms are run (§6.1) |
| Start facts, tools by source, one split for every tool, the two availability conditions | decision 0023 | the tool table and how the mask is built (§5.1, §6.2) |
| Open-split cases enter a measurement only as numbers | decision 0024 | — |
| What each stage builds | roadmap §11: the S1, S2, S2.5, S3 and S5 entries | — |
| Public pages: trajectory view and live board | roadmap §8 and S5 | the statistics and how they are labelled (§7) |
| Deferred choices: threshold, filter, slices, docket shape, weather archive, similar-case search | roadmap §13 | — |
| Risks | roadmap §15 | — |
| Not built: a separate fatal route, airfield history, date and location as evidence | roadmap §10 | — |
| What S0 changed | this document only | §4 |

**How this document ends.** The S1 specification takes over §5.4, §6 and §7.2; the S3
specification takes over §5.1 to §5.3. When both are Approved, this document is marked
Superseded, naming them. It has no As-built record of its own (0017): each stage's As-built
record says what was built.

---

## 2. The design in one paragraph

The spike showed that reading the docket changes the answer. A later spike measurement
showed that most dockets are small enough to read whole in one model call, so a tool loop
that "chooses" what to read has nothing to choose for most cases. This design puts the
agency somewhere it can be both real and measured. The agent starts from a few basic facts,
forms a **hypothesis** about the cause, and fetches one kind of evidence at a time. Each
kind comes from its real source and becomes available when a live investigation actually
has it. After every step the agent writes its hypothesis down as NTSB codes with
probabilities, says what it expects the next piece of evidence to show, and stops when it
is confident enough. That record, the **hypothesis trail**, is scored step by step against
the NTSB's verdict, and published in full. The loop is compared with a pipeline that fetches
everything and answers once. If the loop does not beat that pipeline, the result is
published as it is.

---

## 3. Why agency needs this shape

**Retrieval is measured; choice is not.** The spike's **agency figure** is 38%: the share
of cases where fetching something changes the answer (`decidability.py`,
`scripts/decidability_crosscheck.py`; 14 of 17 misses were "elsewhere in the same record").
It does not show that an agent **choosing** what to retrieve does better than a fixed step
that retrieves everything.

**Most dockets leave nothing to choose.** The spike's docket-shape addendum
(`scripts/docket_shape_probe.py`, register A13, report §10) used 160 development docket
listings, event years 2015–2019, in four strata weighted to the development population
(CA 6,126, LA non-fatal 4,608, FA 2,015, LA fatal 529), and extracted the PDFs of 32.
Tokens are estimated as characters divided by 4.

| | CA | LA non-fatal | LA fatal | FA |
|---|---|---|---|---|
| documents per docket, median | 2 | 4.5 | 7 | 11 |
| non-photo pages, median | 10 | 17.5 | 18 | 44 |
| readable text, median estimated tokens | 5,352 | 4,415 | 3,250 | 11,752 |

Across that population, 89% of dockets hold under 10,000 estimated tokens, and every CA and
non-fatal LA docket sampled was under 10,000. The large dockets are fatal cases, mostly
weather data, radio transcripts and party submissions.

**So the agency has to be somewhere else.** For about four in five development cases, a
tool loop would be a **pipeline in costume**: a fixed sequence that looks like decisions.
The agency this design measures is forming and testing a hypothesis as evidence arrives,
and it has to beat a pipeline that reads everything (0022).

---

## 4. What S0 changed

The first draft was written while S0 was open. S0's code, its corpus scan and two of its
decisions changed parts of it. Each row says what S0 found and what it changed.

| # | S0 finding | source | what it changed |
|---|---|---|---|
| 1 | **Investigation class means different things in different eras.** C-class cases are 6,126 of 13,560 development cases, 397 of 4,241 held-out cases (L-class 3,308), and 0 of the 1,840 closed open-split cases (L-class 1,729, F-class 111). | corpus scan, "by split/class" | The "four in five" figure describes the development era. No docket from 2020 or later was measured for size; of the 14 such dockets the spike probed, 5 were scan-only. Predictions are stated by fatal / non-fatal (0022), and S2 re-measures docket shape on closed open-split cases, as numbers only (0024). |
| 2 | **Event date and location are not evidence roles**, and the spike never sent them. | `fields.py`; spike `config.yaml` | Removed from the start facts. With the registration, they are handles a model could use to recall a published report (0023). |
| 3 | **Amateur-built make and model are a fixed label** (0020): 3,109 cases, 318 of them in the open split. | corpus scan | The start fact says `Amateur-built` for those cases. Similar-case search cannot match them by type. A tool that exposes more than the first aircraft applies 0020 to each (14 cases have a later amateur-built aircraft). |
| 4 | **There is one payload assembler**: `split_record(raw, exclude=…)` builds the one `Evidence` object and runs the tripwire; `Payload.from_evidence` renders it (0016). | `records/split.py`, `model/client.py` | A tool's result is the payload of the same split with every other role excluded. Arm A and the masked condition are **exclusion sets** (0023). |
| 5 | **The tripwire's minimum sentence length (20) was measured with no free-text evidence**, apart from the weather field; missed sentence breaks exist in the withheld text of 3,470 development cases. | S0 As-built, "Tripwire coverage limits" | Reading a document waits for S2 to re-measure the threshold on docket text. |
| 6 | **The preliminary narrative is empty in all 19,641 processed cases.** The processed file keeps closed cases only, and the API deletes the text at closure. | corpus scan, item (c); `data/build.py` | The tool returns nothing in every evaluation. The recorder stores the text for the live board only (0024). |
| 7 | **The model seam sends one payload and returns text** (`ModelReply`, provisional). | `model/client.py` | S1's saved OpenRouter response covers a tool call, a structured hypothesis and a two-turn exchange, so the reply type is defined once. |
| 8 | **Weather checks and provenance are tied to raw record paths** (0016, 0019). | `records/guard.py`, `fields.py` | An archive METAR has no raw path. In S3 the weather tool returns the record's fields; the archive comes later with its own provenance rule. |
| 9 | **Evidence and scoring use the first aircraft only**: 224 cases have more than one aircraft carrying codes. | corpus scan, item (b) | Per-step scores use the first aircraft's codes, as S1's scoring does. |
| 10 | **S0 took decisions 0019 and 0020.** | decisions index | This design's records are 0021 to 0024. |

---

## 5. The evidence and the loop

### 5.1 Start facts and tools

Decided in 0023. The agent starts with **start facts** and fetches the rest through tools,
each matching one real source. Every field stays within the evidence role of the split
(0013) and passes the layered guard (0016).

| tool (placeholder name) | evidence roles or content | source | when a live case has it |
|---|---|---|---|
| *(start facts, no tool)* | phase of flight, injury level, aircraft make and model (the label `Amateur-built` on amateur-built aircraft), engine type, aircraft registration (if S1's ablation keeps it) | API record | day 1 (`scripts/fresh_case_profile.py`) |
| `get_pilot_details` | pilot certificates, total hours, hours in type | API record | late: pilot hours on 0% of cases in the first two weeks |
| `get_weather` | weather condition and METAR from the record | API record | METAR in the record on 17% of cases in the first two weeks |
| `get_preliminary_narrative` | the NTSB's early account | API record | live only; about 40% of cases after some weeks; deleted at closure |
| `list_docket` | titles, types and page counts of the documents available | docket page | fills over months |
| `read_document` | the extracted text of one document | docket PDF | as each document appears; from S2 |

**How a tool returns evidence.** A tool does not read the case record. It calls
`split_record` with every evidence role outside its own excluded, and the payload is
rendered by `Payload.from_evidence`. For example, `get_pilot_details` excludes every role
except the three pilot roles. The tripwire runs on every call.

**On a live case, a tool can return "not yet available".** The agent then decides whether
to form a view without that evidence, or abstain until it arrives.

**The start-fact check in S1.** The occurrence code is read from the coded defining event,
which open cases carry from day 1 (S0 specification §2.4), and phase of flight is derived
from the same event. The spike put its contribution at no more than about 2.5 points of
top-1 (build brief §5). S1 confirms that no start fact hands over the verdict.

### 5.2 One step

1. **Choose.** Name the next tool, the reason for calling it, and what the agent expects it
   to show: which hypothesis it would strengthen or weaken.
2. **Fetch.** Call the tool.
3. **Update.** Write the new hypothesis:
   - the top three occurrence codes, with probabilities;
   - the finding codes it currently believes, with probabilities;
   - a one-sentence working cause;
   - whether the evidence confirmed, weakened or did not change what was expected.
4. **Decide.** Continue, stop and answer, or stop and abstain, by the stopping rule in 0021.

Hypotheses are written as codes because codes are scored by exact match with no judge
(0006), and the finding codes and working cause stay unknown on a live case after the
occurrence code is public.

The agent's earlier hypotheses go back into its context at each step. They are model
output, not evidence, so the conversation that S3 builds keeps them apart from payloads, and
the recording fake still sees exactly which evidence crossed to the model.

### 5.3 An illustration

*Illustrative only, not a real case. The probabilities are invented to show the shape.*

| step | tool | reason given | hypothesis after the step |
|---|---|---|---|
| 0 | *(start facts)* | — | loss of engine power 0.35 · loss of control in flight 0.30 · collision during landing 0.15 |
| 1 | `get_weather` | "If icing conditions existed, carburettor icing becomes likely." | loss of engine power 0.50 · loss of control 0.20 · … — weather consistent with carburettor icing |
| 2 | `list_docket` | "Look for an engine examination." | unchanged — an engine examination and a pilot statement are listed |
| 3 | `read_document` (engine examination) | "An intact engine with no mechanical fault supports icing over failure." | loss of engine power 0.80 — finding: carburettor icing conditions, 0.60 |
| 4 | *(stop)* | threshold reached | answer: loss of engine power; findings as above |

### 5.4 The step record

One row per step. These rows are the trajectory log, the source of the trajectory view, and
the input to every statistic in §6 and §7.

| field | purpose |
|---|---|
| case, step number | identity |
| arm, availability condition, day *N* for the masked condition | which run it belongs to |
| tool and arguments, or *stop* | what was done |
| reason given, expected effect | what the agent said it was looking for |
| evidence roles or documents returned, "not yet available" if so, and a fingerprint of the payload | what it actually received, without storing it twice |
| occurrence codes with probabilities; finding codes with probabilities; working cause | the hypothesis after the step |
| observed effect: confirmed / weakened / unchanged | what the agent said happened |
| stop reason, abstain flag | the decision |
| model, price variant, tokens, cost, cumulative cost | cost per step and per case |
| commit SHA, uncommitted-changes flag | which code produced it (0018) |

---

## 6. What is measured

### 6.1 How the arms are run

Decided in 0022: arms A (start facts only), B (call every tool, answer once) and C (the
loop), with the same model, price variant, cases and cost cap.

- **Arm A** excludes every role except the start facts.
- **Arm B** calls every available tool in a fixed order and reads every docket document its
  fixed filter admits, up to the cost cap. The filter is chosen on the development split and
  published before any held-out run; the unfiltered version is reported on development cases
  only.
- **S1's one-shot ceiling** is arm B without the docket: every structured evidence role, one
  call. Arm B with the docket runs at the end of S2, before any loop code exists.

### 6.2 Availability conditions and the mask

Decided in 0023.

| condition | what the agent can fetch |
|---|---|
| **Full** | everything in the evidence roles of the closed case, and the docket at closure (the held-out evaluation of the S0 specification §2.3) |
| **Masked** | only what a live case would have at day *N* |

- The mask is an exclusion set for day *N*, passed to `split_record`, so a masked role is
  never rendered.
- Until the recorder has data, the mask covers the structured fields, from
  `scripts/fresh_case_profile.py`, and the docket is treated as absent.
- Once the recorder (S2.5) has data, the mask uses the number of days from the event to the
  first appearance of each field and each document type. Only those numbers leave the
  recorder's store (0024).
- The preliminary narrative is absent in both conditions.

*Amended 2026-09-22 (0068): "each document type" cannot be measured — S2 found the
title-based type label unreliable (0054–0056) and the recorder records arrival per document
with no label. The docket's mask rule is presence and document count by day *N*; further
grouping is decided in S3 with the recorder's numbers. The bullet above stays as written.*

### 6.3 Scores per step

- **Accuracy by step.** Occurrence top-1 and top-3, and finding-code precision and recall,
  on the hypothesis after each step.
- **Probability on the true codes by step.** Whether the probability the agent puts on the
  NTSB's codes rises as evidence arrives.
- **Calibration by step.** When the agent says 0.8, whether it is right about 80% of the
  time.
- **Information gain per call.** The change in probability on the true codes caused by one
  tool call. A call that changes nothing is counted as wasted.
- **Hypothesis movement per call.** How far one call moved the agent's probabilities, whatever
  the truth. It needs no verdict, so it can be shown on live cases.
- **Stated versus actual.** Whether the hypothesis changed the way the agent said it
  expected. It needs no verdict either.

### 6.4 Scores per case

- Tool calls per case, and which tools, by fatal / non-fatal first and investigation class
  second (§4, item 1).
- Stop reason, and the abstain rate by condition.
- Cost per case, against the cap.
- Final accuracy for each arm and condition, with confidence intervals. The 40 like-for-like
  cases are too few for P3; it needs the larger held-out sample S1 defines.

The predictions P1 to P6 and the four results that count against the loop are fixed in 0022.

---

## 7. What is published

Decided in 0021.

### 7.1 The trajectory view

Every case on the live board opens its trajectory: the steps as in §5.3, with the reason,
expected and observed effect, what was "not yet available", the stop reason and the cost of
each step. While the case is open, the view shows what the agent did and why. Once the NTSB
publishes, each step is shown against the verdict: which hypothesis was right, and when the
agent first put its highest probability on the true codes.

The point of the view is that a reader can open any case and see the agent working, rather
than being asked to believe it.

### 7.2 Statistics on the live board

These are the numbers that drive the agent's decisions, shown across its live runs. They are
the talking points, most of all when they do not come out as expected.

| statistic | needs a verdict | what it lets a reader ask |
|---|---|---|
| steps and tool calls per case, fatal / non-fatal | no | Does the agent choose, or call everything? |
| which tools are called first, and how often | no | Do its choices differ between cases? |
| stop reasons: confident, budget or cap, nothing available | no | Does it stop because it is sure, or because it ran out? |
| abstain rate, and what was "not yet available" | no | Does it abstain when evidence is missing (P4)? |
| confidence at stop | no | What does it claim? |
| cost per case against the cap | no | Does the cap bind? |
| hypothesis movement per call; share of calls that moved nothing | no | Which calls are wasted? |
| stated versus actual agreement | no | Do its reasons carry information (P6)? |
| accuracy, calibration, information gain on the true codes | yes | Was it right, and was its confidence honest (P5)? |
| the four results that count against the loop | some | Is the loop warranted on live cases? |

**Rules for these numbers.**
- Every statistic shows the count of cases it rests on. Verdict-based scores stay empty until
  cases close, and say so. The roadmap's risk table already notes that closures are slow
  (median 140 days).
- Live statistics are never mixed with held-out results in one figure. Held-out cases have
  complete dockets and no preliminary narrative; live cases differ in both directions (S0
  specification §2.3). The board links to the Methods page for the held-out arms and the
  predictions.
- The statistics are published and never used to choose a threshold, a filter or a prompt
  (0024).
- The tone stays clinical. Nothing is ranked or presented as a contest.

### 7.3 The name

**"The hypothesis trail"**: *the agent's working hypothesis after each piece of evidence*.
Not "breaking down the thinking", which suggests the trail shows the model's actual
reasoning. A model's stated reasons are not guaranteed to be what produced its answer; the
stated-versus-actual score measures how far they can be trusted.

---

## 8. Answers recorded

Andy's answers, 2026-09-14, to the questions in the first revision.

| question | answer | recorded in |
|---|---|---|
| Aircraft details behind a tool, or start facts? | Start facts: a tool with no measured reason behind it is a pipeline in costume. | 0023 |
| Arm B with a title filter, or literally everything? | A fixed filter chosen on the development split; unfiltered reported on development cases only. | 0022 |
| On the live board, every step or a summary? | Every case opens its full trajectory, and the board shows the statistics that drive decisions (§7). | 0021 |
| May S2 measure docket shape on closed open-split cases? | Live cases stay out of measurements unless what is stored is only numbers and no raw data remains. Under that rule, yes. | 0024 |

---

## Glossary

**Abstain.** The agent declares that the evidence is not enough to name a cause.

**Agency figure (38%).** The spike's measure of the share of cases where fetching evidence
changes the answer. It justifies retrieval, not choice.

**Arm.** One way of running the same cases: A, start facts only; B, call every tool and
answer once; C, the loop.

**Calibration.** How well stated confidence matches the real hit rate. A calibrated agent
that says 0.8 is right about 80% of the time.

**Defining event.** The NTSB's coded choice of the single event that defines the accident.
The occurrence code and the phase of flight are read from it.

**Docket.** The NTSB's public folder of supporting documents for one investigation.

**Evidence role.** One named field the model may see, declared in `fields.py` with the raw
path it reads. For example, `pilot_total_hours`.

**Exclusion set.** The evidence roles removed from a split for one call. For example, arm A
excludes every role except the start facts. Excluded roles are never rendered.

**Finding codes.** The NTSB's categories for why an accident happened. On a live case they
are still unknown after the occurrence code is public.

**Full condition.** Evaluation with everything a closed case holds, withheld roles excluded.

**Hypothesis.** The agent's current view of the cause, written as occurrence codes and
finding codes with probabilities, plus one working sentence.

**Hypothesis movement.** How far one tool call moved the agent's probabilities, whatever the
truth. Zero means the call changed nothing the agent believed.

**Hypothesis trail.** The sequence of hypotheses recorded after each step, scored against
the verdict.

**Information gain (per call).** How much a tool call moved the probability on the true
codes. It needs the verdict.

**Investigation class.** The NTSB's classification of how extensive an investigation is,
read from the letter after the year in the case number (for example `C` in `CEN09CA125`).
C-class cases appear to be the most limited (S0 specification, glossary). Its use changed
over time: C-class cases are common before 2020 and absent from closed cases from 2024 on.

**Masked condition.** Evaluation where the agent can fetch only what a live case would have
at a given day, based on measured arrival.

**Occurrence code.** The NTSB's category for what happened. Often public on a live case from
day 1.

**Party submission.** A document written by a party to the investigation, such as the
manufacturer or operator. It can argue a cause.

**Payload.** The exact text sent to the model, rendered only from evidence (0016).

**Pipeline in costume.** A fixed sequence of steps presented as if the agent were making
decisions.

**Start facts.** The evidence roles the agent receives before any tool call: those a live
case has on day 1.

**Stated versus actual.** A comparison of the effect the agent said it expected from a tool
call with the change in its hypothesis that followed.

**Step.** One cycle of choose, fetch, update and decide.

**Step record.** The stored row for one step: what was done, why, what came back, the new
hypothesis, cost and commit.

**Trajectory.** The full record of one case's steps, tools, costs and decisions.

**Tripwire.** The last check of the leakage guard: it looks for withheld text or codes inside
evidence values and stops the case if it finds any (0016).
