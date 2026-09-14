# Agency: the hypothesis trail — design

*Drafted 2026-09-14 from a design discussion with Andy, and merged as a Draft in pull
request #1. Revised 2026-09-14 after S0 closed (pull request #2, release `v0.1.0`):
section 2.4 lists what S0 changed and where each change lands.
Status: Approved on the merge of the pull request that carries this revision; until then,
awaiting Andy's sign-off.
This is a cross-stage design, not a stage specification. It says how the agent's agency is
built and, above all, how it is measured. Decision records 0021, 0022 and 0023 are written
with it, and it amends the S1, S2, S2.5, S3 and S5 entries of
[the architecture and roadmap](2026-09-12-architecture-and-roadmap.md). Section 9 says how
it relates to the stage specifications.*

**How to read this.** Each section says what is proposed, then why. Terms in **bold** on
first use are in the glossary at the end. Every number comes from a named script: the
spike's (`../ntsb-spike/`) or S0's corpus scan (`docs/results/s0-corpus-scan.txt`). None is
new. Anything that is a prediction, a judgement or an illustration says so. The tool names
are placeholders: the roadmap keeps the tool interface for the start of S3, and this
document does not change that.

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
- The population weights are development-split counts: CA 6,126, LA non-fatal 4,608,
  FA 2,015, LA fatal 529 (spike session log, addendum of 2026-09-13). Section 2.4, item 1,
  shows why these weights do not describe held-out or live cases.

### 2.3 What follows

For about four in five development cases, "read the whole docket, answer once" is cheap
and complete. A tool loop run on those cases would be a **pipeline in costume**: a fixed
sequence that looks like decisions. The roadmap's S3 entry already asks this question.
The measurement answers it for document selection. This design therefore looks for agency
somewhere else: in forming and testing a hypothesis as evidence arrives.

### 2.4 What S0 changed

The first draft was written while S0 was open. S0 has now closed, and its code, its corpus
scan and two of its decisions change parts of the draft. Each row says what S0 found, what
it changes here, and where the change is made.

| # | S0 finding | source | what it changes | where |
|---|---|---|---|---|
| 1 | **Investigation class means different things in different eras.** C-class cases are 6,126 of 13,560 development cases, 397 of 4,241 held-out cases (L-class 3,308), and 0 of the 1,840 closed open-split cases (L-class 1,729, F-class 111). | corpus scan, "by split/class" | The "four in five" figure is weighted to the development era. Held-out and live cases are mostly L-class, and no docket from 2020 or later was measured for size; of the 14 such dockets the spike probed, 5 were scan-only. Class is not a stable slice, so the predictions use fatal and non-fatal (injury level, which means the same thing in every era). | §4.4, §4.5; S1 slices; S2 re-measures docket shape (question 4) |
| 2 | **Event date and location are not evidence roles.** S0's roles are: preliminary narrative, aircraft make, model and registration, engine type, pilot certificates, total hours and hours in type, weather condition and METAR, phase of flight, injury level. The spike never sent date or location either. | `fields.py` | The draft's start facts named date and location. Both are removed. With the aircraft registration, they are handles a model could use to recall a published report (S0 specification §8). | §3.1; decision 0023 |
| 3 | **Amateur-built make and model are a fixed label** (0020): 3,109 cases, 318 of them in the open split. | corpus scan; 0020 | The start fact says `Amateur-built` for those cases. Similar-case search by aircraft type cannot work on them. If any tool exposes more than the first aircraft, it applies 0020 to every aircraft (14 cases have a later amateur-built aircraft behind a factory-built first one). | §3.1, §7; S3 |
| 4 | **There is one payload assembler.** `split_record(raw, exclude=…)` builds the one `Evidence` object and runs the tripwire; `Payload.from_evidence` renders it (0016). | `records/split.py`, `model/client.py` | A tool never reads the raw record. Its result is the payload of the same split with every other evidence role excluded. Arm A and the masked condition are **exclusion sets**, not separate code paths, so the guard runs on every call in every arm. | §3.1, §4.1, §4.2; decision 0023 |
| 5 | **The tripwire's minimum sentence length (20) was measured with no free-text evidence**, apart from the weather field. Missed sentence breaks exist in the withheld text of 3,470 development cases. | S0 As-built, "Tripwire coverage limits" | `read_document` cannot run until S2 re-measures the threshold on docket text and closes the sentence-break gaps. | §5 (S2) |
| 6 | **The preliminary narrative is empty in all 19,641 processed cases.** The processed file keeps closed cases only, and the API deletes the text at closure. No ongoing case reaches S0's processed file. | corpus scan, item (c); `data/build.py` | `get_preliminary_narrative` returns nothing in every offline evaluation, in both conditions. It can be scored only after the recorder has captured the text live. The structured-field arrival profile is still the spike's, not re-measured. | §3.1, §4.2; S2.5 captures the text on each poll |
| 7 | **The model seam sends one payload and returns text.** `ModelClient.complete(payload, settings)` returns a provisional `ModelReply(text)`; the response shape waits for a saved OpenRouter response (S1's first task). | `model/client.py` | The loop needs several turns, tool calls, a structured hypothesis at every step, and usage per call. If S1's saved response covers only one plain call, S3 has to redefine the reply type. | §5 (S1, S3) |
| 8 | **The weather checks are keyed to the record field** `weatherConditions[0].metar` (0019), and provenance is checked against a raw path (0016, checks 2 and 3). | 0016, 0019 | A METAR from the Iowa Mesonet archive has no raw path, so the guard cannot vouch for it. In S3, `get_weather` returns the record's weather fields only; the archive stays after S3, as the roadmap already defers it, and needs its own provenance rule. | §3.1, §7 |
| 9 | **Evidence and scoring use the first aircraft only.** 224 cases have more than one aircraft carrying codes (162 development, 39 held-out, 23 open). | corpus scan, item (b) | Per-step scores use the first aircraft's codes, as S1's scoring does. | §8 |
| 10 | **S0 took decisions 0019 and 0020.** | decisions index | This design's records are 0021 to 0023. | §9 |

---

## 3. The design

### 3.1 Evidence is split by real source and real arrival

The agent does not receive the whole evidence payload at once. It starts with a small set
of **start facts** and fetches the rest through tools. Each tool matches one real source
of evidence. Every field stays within the evidence role of the evidence / synthesis /
verdict split (0013), and every payload still passes the layered leakage guard (0016).
Nothing withheld becomes fetchable.

| tool (placeholder name) | evidence roles or content | source | when a live case has it |
|---|---|---|---|
| *(start facts, no tool)* | phase of flight, injury level, aircraft make and model (the label `Amateur-built` on amateur-built aircraft, 0020), engine type, aircraft registration (if S1's ablation keeps it) | API record | day 1 (`scripts/fresh_case_profile.py`) |
| `get_pilot_details` | pilot certificates, total hours, hours in type | API record | late: pilot hours on 0% of cases in the first two weeks |
| `get_weather` | weather condition and METAR from the record | API record | METAR in the record on 17% of cases in the first two weeks; the archive that recovers it (A10) comes after S3 (§2.4, item 8) |
| `get_preliminary_narrative` | the NTSB's early account | API record | live only; about 40% of cases after some weeks, and deleted at closure; never present offline (§2.4, item 6) |
| `list_docket` | titles, types and page counts of the documents available | docket page | fills over months |
| `read_document` | the extracted text of one document | docket PDF | as each document appears; from S2, behind the same boundary |

**Every tool rests on a measurement.** Pilot details, weather and the preliminary narrative
are measured to arrive late. The docket both arrives late and is large enough, on fatal
cases, for choosing what to read to be a real decision. Fields a live case has on day 1
are start facts, not tools. The draft put aircraft details behind a tool as a design choice
only; that is removed (question 1), because a tool with no measured reason behind it is the
pipeline in costume this design exists to avoid.

**How a tool returns evidence.** A tool does not read the case record. It calls the same
`split_record` with every evidence role outside its own excluded, and the payload is
rendered by `Payload.from_evidence` as for any model call. The tripwire therefore runs on
every tool call, and there is still one payload assembler (0016). Docket documents are not
evidence roles yet; S2 adds them behind the same boundary.

**On a live case, a tool can return "not yet available".** The agent has to decide whether
to form a view without that evidence, or abstain until it arrives.

**Date and location are not start facts** (§2.4, item 2). The weather archive, when it
comes after S3, needs them to find the right observation. They are then bookkeeping, like
the case number: used by code, never rendered to the model.

**The start facts need one check in S1.** The occurrence code is read from the coded
defining event, which open cases carry from day 1 (S0 specification §2.4). Phase of flight
is derived from the same event. The spike's ablation put its contribution at no more than
about 2.5 points of top-1 (build brief §5). Before the start facts are fixed, S1 confirms
that none of them hands over the verdict, and its registration ablation decides whether
the registration stays.

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

The agent's own earlier hypotheses go back into its context at each step. They are model
output, not evidence, so the conversation that S3 builds keeps them apart from payloads:
the recording fake still sees exactly which evidence crossed to the model.

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
| arm, availability condition, day *N* for the masked condition | which run it belongs to |
| tool and arguments, or *stop* | what was done |
| reason given, expected effect | what the agent said it was looking for |
| evidence roles or documents returned, and a fingerprint of the payload | what it actually received, without storing it twice |
| occurrence codes with probabilities; finding codes with probabilities; working cause | the hypothesis after the step |
| observed effect: confirmed / weakened / unchanged | what the agent said happened |
| stop reason, abstain flag | the decision |
| model, price variant, tokens, cost, cumulative cost | cost per step and per case |
| commit SHA, uncommitted-changes flag | which code produced it, as for every S1 run record (0018) |

---

## 4. What is measured

This is the substance of the design. Each measurement becomes a number on the Methods page
or a view on the case page, produced by a script.

### 4.1 Three arms

Same model, same price variant, same cases, same per-case cost cap.

| arm | what it does | exclusion set | what it isolates |
|---|---|---|---|
| **A — start facts only** | one call, no tools | every role except the start facts | how far the basic facts alone get |
| **B — call every tool** | every available tool in a fixed order, then one call | none, within the condition | retrieval without choice: the pipeline the loop has to beat |
| **C — the loop** | section 3.2 | none, within the condition | choice, hypothesis testing and stopping |

Arm B is the comparison the spike's measurements make necessary. The planned ablation of
the docket tool only compares C with A. It shows that the docket matters, not that the loop
does.

**Arm B's document filter.** Arm B reads every docket document that a fixed filter admits,
up to the cost cap. The filter is a list of document types and titles, chosen on the
development split and published before any held-out run. The spike found that the excess in
large dockets is weather data, radio transcripts and party submissions, which a title filter
could also drop (A13), so an unfiltered arm B would be a weak opponent. The unfiltered
version is reported on the development split only, to show what the filter removes
(question 2).

**How the arms meet S1's bar.** S1's re-measured one-shot ceiling is arm B without the
docket: every structured evidence role, one call. Arm B with the docket runs once S2 has
built the docket module, before any loop code is written, so the loop's bar exists before
the loop does.

### 4.2 Two availability conditions

| condition | what the agent can fetch | why |
|---|---|---|
| **Full** | everything in the evidence role of the closed case, and the docket as it is at closure | the ceiling; matches the held-out evaluation described in the S0 specification §2.3 |
| **Masked** | only what a live case would have at day *N* | the live situation, where "not yet available" is a real answer |

**How the mask is built.**
- **The mask is an exclusion set for day *N*,** passed to `split_record`, so a masked role
  is never rendered at all.
- **Until the recorder has data,** the mask covers the structured fields, using the arrival
  profile from `scripts/fresh_case_profile.py`, and the docket is treated as absent.
- **Once the recorder (S2.5) has timestamps,** the mask also uses real docket arrival
  times. This is the time-sliced evaluation the S0 specification anticipates ("only
  documents that existed by day 30").
- **The preliminary narrative is absent in both conditions offline,** because closed cases
  no longer hold it (§2.4, item 6). The masked condition can include it only for cases the
  recorder captured live.

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

- Tool calls per case, and which tools, by fatal / non-fatal first and by investigation
  class second. Class is reported but not relied on, because its meaning changed between
  eras (§2.4, item 1).
- Stop reason, and the abstain rate by condition.
- Cost per case, against the cap.
- Final accuracy for each arm and condition, with confidence intervals. The 40
  like-for-like cases are too few to test a difference that appears only on fatal cases;
  prediction P3 needs the larger held-out sample S1 defines.

### 4.5 Predictions, written before any measurement

These are predictions to be tested, not targets. Each is published whichever way it comes
out.

| # | prediction | why it is expected |
|---|---|---|
| P1 | Fatal cases take more steps than non-fatal cases | fatal dockets are larger and more varied in every class sampled (section 2.2) |
| P2 | In the full condition, arm C matches arm B's accuracy at lower cost on non-fatal cases | small dockets leave little to gain from reading everything; this rests on development-era docket sizes (§2.4, item 1) |
| P3 | Any accuracy advantage of C over B is concentrated in fatal cases | that is where there is enough evidence for choice to matter |
| P4 | In the masked condition, C abstains more often than in the full condition, and asks for the missing evidence | the evidence genuinely is not there |
| P5 | On average, the probability on the true codes rises with each step | evidence should help |
| P6 | Stated and actual effects agree more often than chance | the reasons in the trail carry information |

The draft stated P1 as "fatal and FA cases take more steps than CA and non-fatal LA cases".
It is restated on fatality alone, before any measurement, because CA cases are almost
absent from held-out and live cases (§2.4, item 1).

### 4.6 What would show that the loop is not warranted

- Arm C calls every tool on most cases.
- Arm C matches arm B only at the same or greater cost.
- The intermediate hypotheses are not calibrated.
- Stated and actual effects do not agree.

If any of these holds, the published result is that retrieval was warranted and the loop
was not.

---

## 5. Where each part lands

Each stage's own specification designs its part. This table is what the roadmap entries
now carry.

| stage | addition |
|---|---|
| **S1** | The saved OpenRouter response, S1's first task, covers a tool call, a structured hypothesis in the step schema, and a two-turn exchange, so that the reply type is defined once (§2.4, item 7). The step-record schema. Per-step scoring: accuracy, probability on the true codes, calibration, information gain, stated versus actual. Arm A and the no-docket arm B (the one-shot ceiling) as harness modes, with availability as exclusion sets. The stopping threshold chosen on the development split. The headline live metric, already an S1 decision, weighs finding codes and the cause, not only the occurrence code. The start-fact check in section 3.1, and the registration ablation. Slices by fatal / non-fatal first, class second, proposed for S1's slicing decision. |
| **S2** | Docket documents enter as evidence behind the one split and payload (0016). The tripwire's minimum sentence length is re-measured on docket text and the sentence-break gaps are closed before any document reaches a model (§2.4, item 5). The docket tool exposes the listing (titles, types, pages) so that reading a document is a choice. The evidence / synthesis filter decides the role of party submissions (in 62% of FA dockets sampled). It handles older pilot forms that carry a scanned text layer (18 of 27 extracted as text in the sample). It reports scanned documents it cannot read as unavailable rather than skipping them silently. Arm B's document filter is chosen. Docket shape is re-measured on dockets from 2020 or later without touching the held-out years (question 4). Arm B with the docket runs at the end of the stage. |
| **S2.5** | The recorder's first-seen timestamps become the masked condition's arrival profile. The recorder ingests ongoing cases, snapshots their structured fields on each poll so that their arrival is measured rather than taken from the spike's profile, and stores the preliminary narrative each time it is seen, because the API deletes it at closure. |
| **S3** | The loop, stopping rule, step budget and cost cap, with the step record as the trajectory log. The conversation keeps model output apart from evidence payloads. The tool interface is still designed at the start of S3, from the tool groups in section 3.1. If more than the first aircraft becomes evidence, 0020 applies to each. Arm C against arm B at equal cost, published whichever way it comes out. |
| **S5** | The trajectory view presents the hypothesis trail. The Methods page shows the per-step scores, the three arms and the two conditions. |

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
  early evidence, and that is what the experiment would measure. It cannot match by type on
  amateur-built aircraft, whose make and model are a label (0020).
- **The weather archive.** A METAR from the Iowa Mesonet archive needs its own provenance
  rule (§2.4, item 8). It stays after S3, as the roadmap defers it.
- **Event date and location as evidence.** Adding either is a separate decision, with an
  ablation like the registration's, because both are handles for recall (§2.4, item 2).
- **Airfield accident history.** Possibly useful context for a lay reader. It is not a
  verdict input, because a location's history does not establish a cause.
- **Hiding evidence without a measured reason.** Every tool, and every masked role in the
  masked condition, rests on a measured arrival profile or a measured docket size.

---

## 8. Risks and open questions

| item | why it matters | handling |
|---|---|---|
| **Cost per case rises.** Every step is a model call with a growing context. | The per-case cap could bind before the loop is useful. | Cost per step is recorded; prompt caching; the cap is re-measured in S1 and S3, as the roadmap already says. |
| **Stated reasons are unfaithful.** | The trail could read well and mean nothing. | Stated versus actual is scored (section 4.3); the published description claims only what was recorded. |
| **The threshold is tuned on held-out cases.** | Scores become meaningless. | Chosen on the development split only. |
| **Memorisation.** | The model may know a held-out case's outcome. | As in the S0 specification: identifiers kept out, registration ablated in S1, date and location not evidence, live cases as the control. |
| **The masked condition is unrealistic before the recorder has data.** | Its scores would describe an invented situation. | Until then it masks structured fields only, from the measured profile, and says so. The preliminary narrative and the archive weather are absent, and the Methods page says so. |
| **Docket shape and class mix differ by era.** | P2 and the "four in five" figure rest on development dockets from 2015–2019, a C-heavy era; held-out and live cases are mostly L-class, and the spike's 2020+ CA dockets had scan-only pilot forms. | The held-out years were not touched for this. S2 re-measures docket shape on dockets from 2020 or later (question 4); predictions use fatality, not class. |
| **Only the first aircraft is scored.** | On a mid-air collision the second aircraft's codes are ignored. | The same convention as S1's scoring and S0's evidence; the count is reported (§2.4, item 9). |

**Questions for Andy.** Questions 1 and 2 have a proposed answer written into decisions
0022 and 0023; changing either before the merge means editing that record.

1. **Should aircraft details sit behind a tool, or be given as start facts?** *Proposed:*
   start facts. They are present from day 1, so a tool would give the agent a decision with
   no measured reason behind it (section 3.1).
2. **Should arm B apply a title filter, or fetch literally everything?** *Proposed:* a fixed
   filter chosen on the development split and published before held-out runs, with the
   unfiltered version reported on development cases (section 4.1). This is the stronger
   opponent the spike's A13 names.
3. **On the live board, should the trail show every step, or a summary with the full trail
   one click away?** Open; decided in S5.
4. **May S2 measure docket shape on closed cases from the open split** (event year 2024 or
   later, 1,840 closed cases)? *Proposed:* yes, reading docket listings and documents only,
   never verdict or synthesis fields. They are the only closed cases from the held-out and
   live era that are not held-out. Rule 5 in `CLAUDE.md` says open cases feed the live board
   only; this would be a written exception for docket shape, recorded in S2.

---

## 9. How this becomes official

1. **Done:** the Draft was merged in pull request #1, before S0 merged. It was a single new
   file, so nothing conflicted.
2. **This revision** carries decisions 0021, 0022 and 0023 and the roadmap, decisions index
   and `CLAUDE.md` amendments in one pull request. Andy's squash merge is the sign-off; the
   records and the status line say so.
3. **Merged before the S1 specification is written,** because S1's scoring design has to
   include per-step scoring from the start.
4. **Its lifecycle under 0017.** This document has no As-built record of its own. It stays
   Approved while stages take their parts: each stage specification cites the rows of
   section 5 it builds, and its own As-built record says what was built. A later change of
   mind is a new decision record, and this document is then marked Superseded, naming it.
5. **Outside this repository.** The spike's branch `docket-shape-probe`, which holds report
   §10 and register A13, is not yet merged into the spike's `main`. The top-level
   `../CLAUDE.md` still says no build decision on agency is recorded here.

---

## Glossary

**Abstain.** The agent declares that the evidence is not enough to name a cause.

**Agency figure (38%).** The spike's measure of the share of cases where fetching evidence
changes the answer. It justifies retrieval, not choice.

**Arm.** One way of running the same cases, compared with the others: start facts only,
call every tool, or the loop.

**Calibration.** How well stated confidence matches the real hit rate. A calibrated agent
that says 0.8 is right about 80% of the time.

**Call-every-tool arm (arm B).** A fixed pipeline that fetches all available evidence,
through a fixed document filter, and answers once. The loop has to beat it to show agency.

**Confidence threshold.** The probability the top hypothesis must reach before the agent
stops and answers.

**Defining event.** The NTSB's coded choice of the single event that defines the
accident. The occurrence code and the phase of flight are read from it.

**Docket.** The NTSB's public folder of supporting documents for one investigation.

**Evidence role.** One named field the model may see, declared in `fields.py` with the raw
path it reads. For example, `pilot_total_hours`.

**Exclusion set.** The evidence roles removed from a split for one call. For example, arm A
excludes every role except the start facts. Excluded roles are never rendered.

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

**Investigation class.** The NTSB's classification of how extensive an investigation is,
read from the letter after the year in the case number (for example `C` in `CEN09CA125`).
C-class cases appear to be the most limited (S0 specification, glossary). Its use changed
over time: C-class cases are common before 2020 and absent from closed cases from 2024 on.

**Masked condition.** Evaluation where the agent can fetch only what a live case would
have at a given day, based on measured arrival.

**Occurrence code.** The NTSB's category for what happened. Often public on a live case
from day 1.

**Party submission.** A document written by a party to the investigation, such as the
manufacturer or operator. It can argue a cause.

**Payload.** The exact text sent to the model, rendered only from evidence (0016).

**Pipeline in costume.** A fixed sequence of steps presented as if the agent were making
decisions.

**Start facts.** The evidence roles the agent receives before any tool call: those a live
case has on day 1.

**Step.** One cycle of choose, fetch, update and decide.

**Step record.** The stored row for one step: what was done, why, what came back, the new
hypothesis, cost and commit.

**Stopping rule.** The conditions under which the agent stops: threshold reached, budget
or cap reached, or nothing more available.

**Stated versus actual.** A comparison of the effect the agent said it expected from a
tool call with the change in its hypothesis that followed.

**Trajectory.** The full record of one case's steps, tools, costs and decisions.

**Tripwire.** The last check of the leakage guard: it looks for withheld text or codes
inside evidence values and stops the case if it finds any (0016).
