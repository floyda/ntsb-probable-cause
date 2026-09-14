# Agency: the hypothesis trail — design

*Drafted 2026-09-14 from a design discussion with Andy. Status: Draft (awaiting Andy's
sign-off). This is a cross-stage design, not a stage specification. It proposes how the
agent's agency is built and, above all, how it is measured. Once approved, it amends the
roadmap entries for S1, S2, S2.5, S3 and S5 in
[the architecture and roadmap](2026-09-12-architecture-and-roadmap.md). It was written
while S0 is open, so it deliberately changes nothing S0 touches: no decision records, no
roadmap edits, no `CLAUDE.md` edits. Section 9 says how it becomes official after S0
merges.*

**How to read this.** Each section says what is proposed, then why. Terms in **bold** on
first use are in the glossary at the end. Every number comes from a named script in the
spike (`../ntsb-spike/`); none is new. Anything that is a prediction, a judgement or an
illustration says so. The tool names used here are placeholders: the roadmap keeps the
tool interface for the start of S3, and this document does not change that.

---

## 1. The whole design in one paragraph

The spike showed that reading the docket changes the answer. A later spike measurement
showed that most dockets are small enough to read whole in one model call, so a tool loop
that "chooses" what to read has nothing to choose for most cases. This design puts the
agency somewhere it can be both real and measured. The agent starts from a few basic facts,
forms a **hypothesis** about the cause, and fetches one kind of evidence at a time. Each
kind comes from its real source and becomes available when a live investigation actually
has it. After every step the agent writes its hypothesis down as NTSB codes with
probabilities, says what it expects the next piece of evidence to show, and stops when it
is confident enough. That record, the **hypothesis trail**, is scored step by step against
the NTSB's verdict. The loop is then compared with a pipeline that fetches everything and
answers once. If the loop does not beat that pipeline, the result is published as it is.

---

## 2. The problem this solves

### 2.1 What the spike measured, and what it did not

The spike's **agency figure** is 38%: the share of cases where fetching something changes
the answer (`decidability.py`, `scripts/decidability_crosscheck.py`; 14 of 17 misses were
"elsewhere in the same record"). That justifies **retrieval**. It does not show that an
agent **choosing** what to retrieve does better than a fixed step that retrieves
everything.

### 2.2 What the docket-shape measurement found

Andy reopened the spike for one measurement (`scripts/docket_shape_probe.py`, register
A13, spike report §10). It used 160 docket listings from the development split, event years
2015–2019, in four strata by investigation class and fatality, weighted to the population.
It extracted the PDFs of 32 of those dockets. Tokens are estimated as characters divided by
4.

| | CA | LA non-fatal | LA fatal | FA |
|---|---|---|---|---|
| documents per docket, median | 2 | 4.5 | 7 | 11 |
| non-photo pages, median | 10 | 17.5 | 18 | 44 |
| readable text, median estimated tokens | 5,352 | 4,415 | 3,250 | 11,752 |

- Across the population, 89% of dockets hold under 10,000 estimated tokens of readable
  text, and 97% fit inside the input that the whole £0.05 per-case line would buy.
- Every CA and non-fatal LA docket sampled was under 10,000.
- The large dockets are fatal cases. Their size is mostly weather data, radio transcripts
  and party submissions.

### 2.3 What follows

For about four in five closed cases, "read the whole docket, answer once" is cheap and
complete. A tool loop run on those cases would be a **pipeline in costume**: a fixed
sequence that looks like decisions. The roadmap's S3 entry already asks this question.
The measurement answers it for document selection. This design therefore looks for agency
somewhere else: in forming and testing a hypothesis as evidence arrives.

---

## 3. The design

### 3.1 Evidence is split by real source and real arrival

The agent does not receive the whole evidence payload at once. It starts with a small set
of **start facts** and fetches the rest through tools. Each tool matches one real source
of evidence. Every field stays within the evidence role of the evidence / synthesis /
verdict split (0013), and every payload still passes the layered leakage guard (0016).
Nothing withheld becomes fetchable.

| tool (placeholder name) | what it returns | source | when a live case has it |
|---|---|---|---|
| *(start facts, no tool)* | date, location, aircraft make and model, injury level, phase of flight | API record | day 1 (`scripts/fresh_case_profile.py`) |
| `get_aircraft_details` | engine type, other aircraft fields in the evidence role | API record | day 1 |
| `get_pilot_details` | certificate, flight hours | API record | late: pilot hours on 0% of cases in the first two weeks |
| `get_weather` | weather condition and METAR from the record; if absent, the METAR from the Iowa Mesonet archive | API record, external archive | METAR in the record on 17% of cases in the first two weeks; the archive recovers it byte-identical (A10) |
| `get_preliminary_narrative` | the NTSB's early account | API record | live only; about 40% of cases after some weeks, and deleted at closure |
| `list_docket` | titles, types and page counts of the documents available | docket page | fills over months |
| `read_document` | the extracted text of one document | docket PDF | as each document appears |

**Which splits come from the data, and which are a design choice.**
- **Measured to arrive late:** pilot details, the METAR, the preliminary narrative and
  the docket. Putting them behind tools is how a live investigation actually looks.
- **A design choice only:** aircraft details are present from day 1. Putting them behind a
  tool gives the agent a decision to make, not a gap to fill.

The call-every-tool arm (section 4.1) exists to test whether a split like this matters at
all.

**On a live case, a tool can return "not yet available".** The agent has to decide whether
to form a view without that evidence, or abstain until it arrives.

**The start facts need one check in S1.** The occurrence code is read from the coded
defining event, which open cases carry from day 1 (S0 specification §2.4). Phase of flight
is derived from the same event. The spike's ablation put its contribution at no more than
about 2.5 points of top-1 (build brief §5). Before the start facts are fixed, S1 confirms
that none of them hands over the verdict.

### 3.2 The loop

One **step** is:

1. **Choose.** Name the next tool, the reason for calling it, and what the agent expects it
   to show: which hypothesis it would strengthen or weaken.
2. **Fetch.** Call the tool.
3. **Update.** Write the new hypothesis:
   - the top three occurrence codes, with probabilities;
   - the finding codes it currently believes, with probabilities;
   - a one-sentence working cause;
   - whether the evidence confirmed, weakened or did not change what was expected.
4. **Decide.** Continue, stop and answer, or stop and abstain.

The **stopping rule** has three parts:
- Stop and answer when the top hypothesis reaches a confidence threshold.
- Stop and abstain when the step budget or the per-case cost cap is reached below that
  threshold.
- Also stop and abstain when nothing more is available.

The threshold is chosen on the development split, never on held-out cases.

Hypotheses are written as **codes**, not only prose, for two reasons. Codes can be scored
by exact match with no judge (0006). And the occurrence code alone is a weak live target,
because it is often public from day 1 (S0 specification §2.4). Recording finding codes and
the working cause at every step keeps the trail scoreable on the parts that are still
genuinely unknown on a live case.

### 3.3 An illustration

*Illustrative only, not a real case. The probabilities are invented to show the shape.*

| step | tool | reason given | hypothesis after the step |
|---|---|---|---|
| 0 | *(start facts)* | — | loss of engine power 0.35 · loss of control in flight 0.30 · collision during landing 0.15 |
| 1 | `get_weather` | "If icing conditions existed, carburettor icing becomes likely." | loss of engine power 0.50 · loss of control 0.20 · … — weather consistent with carburettor icing |
| 2 | `list_docket` | "Look for an engine examination." | unchanged — an engine examination and a pilot statement are listed |
| 3 | `read_document` (engine examination) | "An intact engine with no mechanical fault supports icing over failure." | loss of engine power 0.80 — finding: carburettor icing conditions, 0.60 |
| 4 | *(stop)* | threshold reached | answer: loss of engine power; findings as above |

A reader sees the agent's working view change as evidence arrives. Every row is scored
against the verdict later.

### 3.4 The step record

Every step is stored as one row. These rows are the trajectory log that the roadmap
already requires in S3.

| field | purpose |
|---|---|
| case, step number | identity |
| tool and arguments, or *stop* | what was done |
| reason given, expected effect | what the agent said it was looking for |
| fingerprint of the returned evidence | what it actually received, without storing it twice |
| occurrence codes with probabilities; finding codes with probabilities; working cause | the hypothesis after the step |
| observed effect: confirmed / weakened / unchanged | what the agent said happened |
| stop reason, abstain flag | the decision |
| tokens, cost, cumulative cost | cost per step and per case |
| commit SHA, uncommitted-changes flag | which code produced it, as for every S1 run record (0018) |

---

## 4. What is measured

This is the substance of the design. Each measurement becomes a number on the Methods page
or a view on the case page, produced by a script.

### 4.1 Three arms

Same model, same cases, same per-case cost cap.

| arm | what it does | what it isolates |
|---|---|---|
| **A — start facts only** | one call, no tools | how far the basic facts alone get |
| **B — call every tool** | every available tool in a fixed order, then one call | retrieval without choice: the pipeline the loop has to beat |
| **C — the loop** | section 3.2 | choice, hypothesis testing and stopping |

Arm B is the comparison the spike's measurements make necessary. The planned ablation of
the docket tool only compares C with A. It shows that the docket matters, not that the loop
does.

### 4.2 Two availability conditions

| condition | what the agent can fetch | why |
|---|---|---|
| **Full** | everything in the evidence role of the closed case, and the docket as it is at closure | the ceiling; matches the held-out evaluation described in the S0 specification §2.3 |
| **Masked** | only what a live case would have at day *N* | the live situation, where "not yet available" is a real answer |

**How the mask is built.**
- **Until the recorder has data,** the mask covers the structured fields, using the arrival
  profile from `scripts/fresh_case_profile.py`, and the docket is treated as absent.
- **Once the recorder (S2.5) has timestamps,** the mask also uses real docket arrival
  times. This is the time-sliced evaluation the S0 specification anticipates ("only
  documents that existed by day 30").

The mask is measured, never chosen to make the agent look busy.

### 4.3 Scores per step

- **Accuracy by step.** Occurrence top-1 and top-3, and finding-code precision and
  recall, computed on the hypothesis after each step.
- **Probability on the true codes by step.** Does the probability the agent puts on the
  NTSB's codes rise as evidence arrives?
- **Calibration by step.** When the agent says 0.8, is it right about 80% of the time?
- **Information gain per call.** The change in probability on the true codes caused by
  each tool call. A call that changes nothing is a wasted call, and is counted.
- **Stated versus actual.** Did the evidence change the hypothesis the way the agent said
  it expected? This checks the reasons in the trail against what happened, rather than
  taking them on trust.

### 4.4 Scores per case

- Tool calls per case, and which tools, by investigation class and by fatal / non-fatal.
- Stop reason, and the abstain rate by condition.
- Cost per case, against the cap.
- Final accuracy for each arm and condition, with confidence intervals.

### 4.5 Predictions, written before any measurement

These are predictions to be tested, not targets. Each is published whichever way it comes
out.

| # | prediction | why it is expected |
|---|---|---|
| P1 | Fatal and FA cases take more steps than CA and non-fatal LA cases | their dockets are larger and more varied (section 2.2) |
| P2 | In the full condition, arm C matches arm B's accuracy at lower cost on non-fatal cases | small dockets leave little to gain from reading everything |
| P3 | Any accuracy advantage of C over B is concentrated in fatal cases | that is where there is enough evidence for choice to matter |
| P4 | In the masked condition, C abstains more often than in the full condition, and asks for the missing evidence | the evidence genuinely is not there |
| P5 | On average, the probability on the true codes rises with each step | evidence should help |
| P6 | Stated and actual effects agree more often than chance | the reasons in the trail carry information |

### 4.6 What would show that the loop is not warranted

- Arm C calls every tool on most cases.
- Arm C matches arm B only at the same or greater cost.
- The intermediate hypotheses are not calibrated.
- Stated and actual effects do not agree.

If any of these holds, the published result is that retrieval was warranted and the loop
was not.

---

## 5. Where each part lands

These are proposals for each stage's own specification. None is decided here.

| stage | proposed addition |
|---|---|
| **S1** | The step-record schema. Per-step scoring: accuracy, probability on the true codes, calibration, information gain, stated versus actual. Arms A and B as harness modes. The stopping threshold chosen on the development split. The headline live metric, already an S1 decision, weighs finding codes and the cause, not only the occurrence code. The start-fact check in section 3.1. |
| **S2** | The docket tool exposes the listing (titles, types, pages) so that reading a document is a choice. The evidence / synthesis filter decides the role of party submissions (in 62% of FA dockets sampled). It handles older pilot forms that carry a scanned text layer (18 of 27 extracted as text in the sample). It reports scanned documents it cannot read as unavailable rather than skipping them silently. |
| **S2.5** | The recorder's first-seen timestamps become the masked condition's arrival profile. Proposed addition: snapshot the structured fields on each poll too, so their arrival is measured rather than taken from the spike's profile. |
| **S3** | The loop, stopping rule, step budget and cost cap, with the step record as the trajectory log. The tool interface is still designed at the start of S3. |
| **S5** | The trajectory view presents the hypothesis trail. The Methods page shows the per-step scores and the three arms. |

---

## 6. How it is presented

**Name: "the hypothesis trail"**, described as *the agent's working hypothesis after each
piece of evidence*.

**Not "breaking down the thinking".** That phrase suggests the trail shows the model's
actual reasoning process. A model's stated reasons are not guaranteed to be what produced
its answer, and a reader who knows this would rightly object. The trail is what the agent
recorded at each step, scored against the published verdict. The stated-versus-actual
score in section 4.3 measures how far the reasons can be trusted, rather than asserting it.

The tone is unchanged: clinical, no victim names, nothing that reads as a game.

---

## 7. Not in this design

- **A separate route for fatal cases.** It is not needed if the stopping rule works: class
  differences should emerge as step counts (P1). It stays a fallback if the loop costs too
  much on small cases.
- **Similar-case search** (same aircraft type, same airframe). This is allowed only as a
  declared experiment: an ablation stated before it runs, retrieval limited to accidents
  dated before the case, and the retrieval-contamination test the roadmap already requires.
  The spike's labels showed no demand for it on complete records. It may matter on thin
  early evidence, and that is what the experiment would measure.
- **Airfield accident history.** Possibly useful context for a lay reader. It is not a
  verdict input, because a location's history does not establish a cause.
- **Hiding evidence without a measured reason.** Every masked tool in the masked condition
  rests on a measured arrival profile.

---

## 8. Risks and open questions

| item | why it matters | handling |
|---|---|---|
| **Cost per case rises.** Every step is a model call with a growing context. | The per-case cap could bind before the loop is useful. | Cost per step is recorded; prompt caching; the cap is re-measured in S1 and S3, as the roadmap already says. |
| **Stated reasons are unfaithful.** | The trail could read well and mean nothing. | Stated versus actual is scored (section 4.3); the published description claims only what was recorded. |
| **The threshold is tuned on held-out cases.** | Scores become meaningless. | Chosen on the development split only. |
| **Memorisation.** | The model may know a held-out case's outcome. | As in the S0 specification: identifiers kept out, registration ablated in S1, live cases as the control. |
| **The masked condition is unrealistic before the recorder has data.** | Its scores would describe an invented situation. | Until then it masks structured fields only, from the measured profile, and says so. |
| **The docket-shape numbers are from 2015–2019 only.** | Held-out and live dockets may differ; the spike's 2020+ CA dockets had scan-only pilot forms. | The held-out years were not touched for this. Treat the numbers as indicative; S2 observes real dockets. |

**Questions for Andy.**
1. Should aircraft details sit behind a tool (a design choice, section 3.1), or be given
   as start facts?
2. Should arm B apply a title filter (for example, dropping weather attachments), or
   fetch literally everything?
3. On the live board, should the trail show every step, or a summary with the full trail
   one click away?

---

## 9. How this becomes official

1. **Now:** this Draft, on its own branch, as an unmerged draft pull request. S0 is
   untouched.
2. **After S0 squash-merges and is tagged:** rebase onto `main`. This is a single new file,
   so there is no conflict, and `scripts/check_docs.py` can resolve every decision it cites.
3. **On Andy's approval:**
   - Status becomes Approved.
   - Decision records are written with the next free numbers, confirmed against S0's
     close-out. Proposed records: agency is measured as a scored hypothesis trail; the loop
     must beat a call-every-tool arm at equal cost; evidence is split by source, with
     availability masked from measured arrival.
   - The roadmap entries for S1, S2, S2.5, S3 and S5, its risk table and its table of
     deferred decisions are amended, and so is the eval section of `CLAUDE.md`.
4. **Merged before the S1 specification is written,** because S1's scoring design has to
   include per-step scoring from the start.

---

## Glossary

**Abstain.** The agent declares that the evidence is not enough to name a cause.

**Agency figure (38%).** The spike's measure of the share of cases where fetching evidence
changes the answer. It justifies retrieval, not choice.

**Arm.** One way of running the same cases, compared with the others: start facts only,
call every tool, or the loop.

**Calibration.** How well stated confidence matches the real hit rate. A calibrated agent
that says 0.8 is right about 80% of the time.

**Call-every-tool arm (arm B).** A fixed pipeline that fetches all available evidence and
answers once. The loop has to beat it to show agency.

**Confidence threshold.** The probability the top hypothesis must reach before the agent
stops and answers.

**Defining event.** The NTSB's coded choice of the single event that defines the
accident. The occurrence code and the phase of flight are read from it.

**Docket.** The NTSB's public folder of supporting documents for one investigation.

**Finding codes.** The NTSB's categories for why an accident happened. On a live case
they are still unknown after the occurrence code is public.

**Full condition.** Evaluation with everything a closed case holds, withheld roles
excluded.

**Hypothesis.** The agent's current view of the cause, written as occurrence codes and
finding codes with probabilities, plus one working sentence.

**Hypothesis trail.** The sequence of hypotheses recorded after each step, scored against
the verdict.

**Information gain (per call).** How much a tool call moved the probability on the true
codes. Zero means the call changed nothing.

**Masked condition.** Evaluation where the agent can fetch only what a live case would
have at a given day, based on measured arrival.

**Occurrence code.** The NTSB's category for what happened. Often public on a live case
from day 1.

**Party submission.** A document written by a party to the investigation, such as the
manufacturer or operator. It can argue a cause.

**Pipeline in costume.** A fixed sequence of steps presented as if the agent were making
decisions.

**Start facts.** The few evidence fields the agent receives before any tool call.

**Step.** One cycle of choose, fetch, update and decide.

**Step record.** The stored row for one step: what was done, why, what came back, the new
hypothesis, cost and commit.

**Stopping rule.** The conditions under which the agent stops: threshold reached, budget
or cap reached, or nothing more available.

**Stated versus actual.** A comparison of the effect the agent said it expected from a
tool call with the change in its hypothesis that followed.

**Trajectory.** The full record of one case's steps, tools, costs and decisions.
