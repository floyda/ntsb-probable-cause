# TypeSafe's Jev on dev-400: design

*Drafted 2026-09-17 from a design session with Andy.
Status: Approved (Andy, 2026-09-17, in the design session).
This is the specification for one run of the declared experiment of decision 0060. It is not
a build stage: it adds no stage to the roadmap and changes nothing in the product. The
implementation plan is written from it separately, in `docs/plans/`.*

**How to read this.** Each section says what is done, then why. Terms in **bold** on first
use are in the glossary at the end. Every number here is quoted from a committed results file
or from the probe's saved replies, and the file is named beside it.

## 1. The question

Jev is a new kind of model. It writes no text. It picks one label from a list and returns a
probability for every label. The vendor says those probabilities are **calibrated**. This
run answers two questions on data this project already scored:

1. **How does Jev behave on our main task?** Pick the occurrence code for a case, from the
   same evidence Luna and Gemini were given.
2. **Can its probabilities be trusted?** If Jev says 70%, is it right about 70% of the time?

The second question matters more. S3 fixes the shape of a hypothesis. If a model class can
give calibrated distributions, S3 should store distributions and use the model's confidence
to decide when to stop. If it cannot, S3 should not be built around that claim.

**Why dev-400.** S1 already ran Luna and Gemini on the same 401 development cases, with the
same payload and the same scoring (`docs/results/s1-ceiling-dev.txt`,
`docs/results/s1-model-comparison-dev.txt`). A Jev run on those cases can be compared case by
case, and no new case is drawn. The held-out split is not touched.

## 2. What runs

`scripts/exploratory/jev_dev400.py` makes one request per case for the 401 cases of
`dev-400`.

- **Payload.** Built by `scoring/runner.py:case_payload` with the ceiling arm, so it passes
  through `split_record` and the layered leakage guard as every payload does (decisions 0013,
  0016). The payload text is the request's `state`. Nothing else is sent as text.
- **Questions.** Two **Choice** questions per request: phase (47 labels) and event (93
  labels), with the probe's wording and the code tables' labels as label descriptions
  (`scripts/typesafe_probe.py`). No findings, no modifier, no Score.
- **Saved replies.** Each raw reply is appended to
  `data/runs/<timestamp>-<sha>-dev-400-jev/replies.jsonl`, which is outside git. A row holds
  the case ID, the model version the reply names, the usage block, the time the request took
  and the HTTP status. A second start skips cases already saved.
- **Pace.** Four requests at a time. The run records failures and retries so the report can
  state the rate limits and latency seen at 400 cases.
- **Cost.** The probe's phase-event-modifier request used 4,344 input tokens
  (`tests/fixtures/typesafe/README.md`). At the vendor's published $0.042 per million input
  tokens, 401 requests of that size cost about $0.07. The script stops before a request that
  would take the total above **$0.50** at the published price. The published price is
  self-reported (`sources.py:JEV`). Jev is in preview, so its price is reported for
  comparison with the LLM rows only; no reading in §5 depends on it (Andy, 2026-09-17). The
  cap stays, because every metered call has one in code.

**Why no prompt.** Jev has no prompt. The only instructions are the question text and the
label descriptions. The system prompt the LLMs were given is therefore not sent. This is the
reason the wording is kept the same as the probe's: changing it is a separate question
(spike question 4), which this run does not answer.

## 3. A small client in the library

`src/ntsb_probable_cause/model/typesafe.py` sends one request and parses the reply into
typed objects: a Choice answer (choice, confidence, probability per label) and the usage
block. It uses `httpx`, which is already a dependency. Its tests read the committed probe
replies in `tests/fixtures/typesafe/`.

**Why in the library.** Decision 0060 point 3 says the client is written against the saved
replies. The parser is the part most likely to be wrong, and a strict-typed module with
tests catches that. Everything else about this run stays in the exploratory script.

## 4. Scoring

S1's scoring code is reused, not copied.

- **Composed code.** Every (phase, event) pair gets the product of its two probabilities.
  The highest product is top-1; the next two complete top-3 (0060 point 4). Pairs the NTSB
  has never used are not removed. S1's **pair unseen** column shows how often Jev's top-1 is
  such a pair.
- **Accuracy.** The composed answer is wrapped in a `Hypothesis` with empty text fields, no
  findings, `abstain` false and `confidence` equal to the top-1 product. `metrics.score_case`
  then gives top-1, top-3, event match and pair unseen exactly as it did for Luna. The
  finding columns are reported as absent. Jev never abstains, so every case counts.
- **Calibration.** `metrics.calibration` (10 bins, **expected calibration error**) gives
  three tables:
  - (a) Jev's event `confidence` against whether the event is right. This is the vendor's
    claim.
  - (b) Jev's highest event probability against whether the event is right. The probe
    showed that `confidence` is a different number (0060, probe result point 3).
  - (c) The top-1 product against whether top-1 is right, beside Luna's and Gemini's
    probability on their own first guess against whether that guess is right. The LLM
    values are read from their saved runs (`20260916T032106-179520f-dev-400-ceiling` and
    `20260917T060746-c366a04-dev-400-ceiling`), whether or not the model abstained.
- **Comparison.** Paired top-1 differences, Jev minus Luna and Jev minus Gemini, on the
  cases all three scored, with `metrics.paired_difference`.
- **Probability on the true event.** The median, and the share of cases where it is exactly
  0. The probe showed that most labels get exactly 0, so this says how often Jev rules out
  the right answer entirely.
- **Examples.** Five cases, chosen by a fixed seed, each with Jev's five most probable events
  and the true event. Codes and code labels only; no evidence text.

## 5. Readings fixed before the run

These are written before any reply is seen, so the result cannot move them.

**Calibration**, on table (a):

| result | reading |
|---|---|
| expected calibration error ≤ 0.05, and no bin with 20 or more cases off by more than 0.10 | Calibrated on our data. S3 should consider storing distributions and a confidence-based stopping rule. |
| expected calibration error > 0.10 | Not calibrated. The vendor's central claim fails on our data; decision 0060 is declined. |
| anything between | Inconclusive. In a bin of 50 cases, chance alone moves accuracy by about ±0.07. |

**Accuracy**, on composed top-1, against the honest baseline of 17.7%
(`docs/results/s1-baseline.txt`):

| result | reading |
|---|---|
| the lower bound of the 95% interval is above 17.7% | The first model to beat the baseline without the docket. A held-out run is worth discussing; this run does not do it. |
| otherwise | Jev joins Luna (8.7%) and Gemini (12.5%) on this sample (`docs/results/s1-model-comparison-dev.txt`); the task is confirmed hard. |

The baseline was measured on held-out cases, not on these 401. It is the bar S1 set, so it
is the line this row is read against.

## 6. Output

- `docs/results/typesafe-jev-dev400.txt`: the script's printed tables, saved as run.
- `docs/results/typesafe-jev-dev400.md`: a short report in simplified technical English
  with a glossary. It states the two readings of §5 and what they mean for S3.
- One dated line added to decision 0060 recording the row. 0060 stays Proposed, because its
  own condition (the judge test of point 5) has not run.

## 7. Out of scope

Held-out cases; findings and the 130 Nouls; abstention thresholds; other wordings of the
questions; a batch path; the judge test; any change to the product or to decision 0009.

## Glossary

- **Calibrated.** A model is calibrated when its stated probabilities match how often it is
  right. Of all answers given at 70%, about 70% are correct.
- **Choice.** A Jev question type. The model picks one label from a list of up to 255 and
  returns a probability for each label and a confidence.
- **Composed code.** The six-digit occurrence code: a three-digit phase and a three-digit
  event joined (decision 0025).
- **dev-400.** The fixed sample of 401 development-split cases S1 uses for development runs
  (`tests/fixtures/eval/dev_400_ids.csv`).
- **Expected calibration error.** Answers are grouped into ten bins by stated probability.
  For each bin, take the gap between the mean stated probability and the share correct, and
  weight it by the bin's size. The sum is the error: 0 is perfect.
- **Pair unseen.** The share of cases where top-1 is a code that is never the defining
  occurrence of any development-split case (`samples.seen_pairs`).
- **State.** The single text a Jev request carries: here, the evidence payload.
- **Top-1, top-3.** The composed code ranked first is right (top-1), or the right code is
  among the first three (top-3).
