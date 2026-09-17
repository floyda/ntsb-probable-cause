# 0036 — TypeSafe's Jev enters as a declared experiment on a second transport

Amends [0009](0009-model-access-via-openrouter.md) (one transport) for one named model
class only. Every other part of 0009 stands. Adds a row to the model axis of
[0031](0031-default-model-gpt-luna-model-axis-after-s3.md); never touches the bar.

## Context

TypeSafe AI opened early access to Jev on 2026-09-15. Jev is a "System One" model: it
generates no text. A request carries one `state` (text or JSON) and a map of typed
questions; the reply carries a typed answer per question with probabilities. Three question
shapes exist: **Choice** (one label from up to 255, with a probability per label and a
confidence), **Score** (a position on an ordered rubric, with a probability per level and a
confidence), and **Noul** (a yes/no claim, returning the probability it is true). The
vendor's training claim is calibration: a stated 70% should be right about 70% of the time.
Its published prices are $0.042 per million input tokens and nothing for output; its
published accuracy figures are agreement with labels made by averaging two frontier
models, on the vendor's own tasks, and say nothing about a task with a real verdict.

The request shape is not chat completions, so Jev is not on OpenRouter and cannot be. The
wire schema below is read from the vendor's Python SDK (`typesafe-sdk` 0.6.0 on PyPI),
whose models are generated from `https://api.typesafe.ai/openapi.json`; the SDK itself is
not a dependency of this project. Andy holds an early-access key.

```
POST https://api.typesafe.ai/v1/systemone      Authorization: Bearer <TYPESAFE_API_KEY>
{"state": <text|object|array>, "model": "jev-latest", "questions": {<name>: <question>}}
  question: {"type": "choice", "instructions": ..., "criteria": {<label>: <description|null>}}
            {"type": "score",  "instructions": ..., "criteria": [<level 0>, <level 1>, ...]}
            {"type": "noul",   "instructions": ..., "criteria"?: {"true": ..., "false": ...}}
reply:    {"model": <resolved version>, "usage": {"input_tokens", "output_tokens"}, "answers": {<name>:
            {"type": "choice", "choice", "confidence", "probabilities": {<label>: p}}
            {"type": "score",  "score": <expected level>, "confidence",
                               "legend": {"0": <level 0>, ...}, "probabilities": {"0": p, ...}}
            {"type": "noul",   "noul": p}}}
GET  https://api.typesafe.ai/v1/models        {"models": [{"name", "description", "release_date"}]}
```

Why this project should care, in the order that matters:

1. **The answer format of 0025 is already a set of picks from short tables**, and every
   table fits one Choice: 47 phases, 93 events, 130 finding categories, 73 modifiers
   (`docs/results/s1-code-tables.txt`), against a limit of 255. The eight-digit item is
   chosen among a category's children (median 6, max 41), which is a second, serial Choice.
   The variable-sized set of findings, which Choice cannot return, is a Noul per category.
2. **0021 scores the trail on probability on the true code, calibration, and a confidence
   threshold.** Today those numbers are what an LLM writes into a JSON field. Jev returns
   a probability vector over the 93 events on every call, and confidence is what it claims
   to be trained for. The fourth result that counts against the loop in 0022 is "the
   intermediate hypotheses are not calibrated". Jev is a direct test of whether calibration
   can be bought from the model class rather than prompted for.
3. **The bar is 17.7%, and both LLMs measured in S1 lost to it** (`docs/results/s1-bars.txt`,
   `s1-model-comparison-dev.txt`). A model trained to output distributions may behave more
   like a classifier than a writer here. That is the unknown worth a cheap measurement.
4. **Two smaller fits.** Score on ordered levels is the judge of 0028, and the repo already
   holds Andy's 30-case hand-check to validate it against. A Choice over document titles is
   the evidence-versus-synthesis classifier S2 needs.

What does not fit: Jev writes no evidence narrative, probable cause or lay explanation, and
cannot state a reason for a tool call or an expected effect, all of which are step-record
fields (0021 §5.4). It can pick a next tool as a Choice; it cannot say why.

## Decision

1. **Jev is a declared experiment, stated here before any measurement.** It is run as the
   ceiling arm only (0022, as read by 0025 point 4), on `dev-400`, and reported as one row
   of the model-axis table of 0031 point 2. The bar stays Luna's. No held-out case is sent
   to Jev unless the development row earns it, and then only with a ledger entry (0026).
2. **A second transport is admitted for this model class only.** `TYPESAFE_API_KEY` and a
   base URL join `Settings`; the endpoint paths and the vendor's published price join
   `sources.py`, dated and marked self-reported until a real usage block replaces the
   estimate (0030). The OpenRouter rule of 0009 is unchanged for every chat model.
3. **The first artefact is a saved real response, not code** (0009's own rule, and rule 2).
   `scripts/typesafe_probe.py` sends the payload of one redacted development fixture, built
   by `split_record` and `Payload.from_evidence` as every payload is (0016), with the phase,
   event and modifier tables as Choices, one Noul per finding category, and one Score. It
   saves the redacted request and reply under `tests/fixtures/typesafe/`. A client is
   written only against those fixtures.
4. **How the row is judged**, fixed now:
   - the same evidence payload text is the `state`; no prompt, no schema;
   - phase and event are two Choices and the harness composes the code, as 0025 does;
     top-1 is the composed code with the highest joint probability, top-3 the next two;
   - categories are 130 Nouls; a finding is "believed" above a threshold chosen on
     `dev-400`, and precision and recall are read off that threshold;
   - Jev never abstains, so abstention is a confidence threshold chosen on `dev-400`, and
     `answered top-1` is the like-for-like column against the LLM rows;
   - the calibration table of the S1 specification (expected calibration error per
     confidence bin) is reported for Jev's event distribution beside Luna's and Gemini's
     self-reported probabilities. This column, not top-1, is the one the experiment exists for.
5. **The judge test runs first.** Score against the 30-case hand-check of 0028, on the
   development split, before any answering run. It costs cents and needs no new case.
6. **The prose columns are reported as absent** for the Jev row. No LLM is chained behind
   Jev to write them inside this experiment; a hybrid arm, if the row earns one, is a
   later decision.

## Why

1. **It is the cheapest test of the project's most exposed claim.** The loop is warranted
   only if its intermediate hypotheses are calibrated (0022). If calibration is a property
   of a model class rather than of prompting, the loop should be built on that class, and
   the project should know before S3 writes it. A `dev-400` ceiling row at the published
   price is about a cent.
2. **The shape removes two failure modes S1 paid for.** No JSON to parse, no stage 2 that
   ends on the model's turn. Two comparison models were lost to those in 0034.
3. **A declared experiment is how this project admits anything unplanned** (roadmap §13
   on similar-case search). Stating the arm, the sample, the columns and the threshold
   rule before the run keeps the row from being tuned against its own result.
4. **A second transport is a real cost to 0009's argument**, which was that the evaluated
   agent and the deployed agent share one transport. Confining it to a declared experiment
   on the development split keeps that argument intact for the product. If Jev ever enters
   the product, that is a new record superseding 0009, not an extension of this one.

## What this rules out

- **Jev as the agent.** It cannot write the narrative, the cause, the lay explanation or a
  reason for a call. A Jev-only trail would lose the columns 0021 uses to test whether
  stated reasons can be trusted.
- **Mixing the Jev row into the bar.** 0031 point 2 forbids it; the bar is one model, and
  the agent is compared on the same model.
- **A held-out run on the strength of the vendor's numbers.** Their accuracy is agreement
  with two other models on their tasks, and their price is, in their own words, not shown
  to be unsubsidised.
- **Depending on `typesafe-sdk`.** It brings `httpx2`, `msgspec` and `tenacity` for one
  POST with a five-key body. The wire shape is in this record and in the saved fixtures;
  `httpx`, already a dependency, sends it. If the SDK's shape and the saved reply ever
  disagree, the saved reply wins and this record is amended.
- **Chaining an LLM behind Jev inside this experiment.** It would measure two models and
  attribute the result to one.

## Probe result (2026-09-17)

`scripts/typesafe_probe.py` ran once against `jev-latest` and saved its replies under
`tests/fixtures/typesafe/`. The saved replies agree with the SDK's shape, and the wire block
above now records five details the SDK does not state. Where they differ, the saved reply
is the authority.

1. **The reply names a resolved version** (`jev-1.13.0` for a request naming `jev-latest`).
   Every run records the reply's `model`, not the requested name, for the same reason 0018
   records the commit SHA. The model list also offers `jev-preview`.
2. **Probabilities are rounded to two decimals.** A vector sums to 0.99 or 1.00, and most
   labels are exactly 0. A log score or any probability on the true code therefore needs a
   stated floor, and calibration bins finer than 0.01 are meaningless.
3. **`confidence` is its own number, not the top probability** (0.84 against 0.85, 0.47
   against 0.48, 0.30 against 0.32 in the probe). The calibration table bins on
   `confidence` and reports the top probability beside it; neither is assumed to be the other.
4. **A Score's `score` is not an integer.** The probe returned 1.29 with level
   probabilities 0.06, 0.58 and 0.36, which is their expectation to rounding. The judge test
   takes the level with the highest probability as the grade, and reports `score` beside it.
   `legend` and `probabilities` are keyed by the level index as a string.
5. **A Noul needs no `criteria`.** The probe sent none, and all 130 came back, each as a
   bare float. Nothing was refused or truncated at 130 questions and about 7,000 input
   tokens. In the probe no category was above 0.5 (the highest was 0.20), so the
   believed-finding threshold of point 4 cannot be assumed to sit near 0.5. It is chosen
   on `dev-400` as stated.

The usage blocks are real: 4,344 and 7,154 input tokens. Output tokens are counted (1,911
and 2,994) but, per the vendor, not priced. The price itself is still self-reported.

**dev-400 row (2026-09-17).** Run `20260917T182646-adda233-dev-400-jev`, 401 of 401 answered,
$0.0517 at the published price. Composed top-1 9.7% [7.2, 13.0], against the 17.7% baseline:
**not above the baseline**, and level with Luna (+1.0% [-2.7, +4.7]) and Gemini (-2.7%
[-6.2, +0.7]) case by case on paired plain top-1, which counts an abstention as wrong; on
`answered top-1`, the like-for-like column point 4 fixed, Jev (9.7%) is below both Luna
(11.3%) and Gemini (12.7%). Expected calibration error on the event confidence 0.318 against
a threshold of 0.10: **not calibrated**, overconfident in every bin. On the comparable figure
— the composed top-1 product, table (c) of the report — Jev's error is 0.359, worse than
Luna's own self-reported 0.279. Point 4 named the confidence column as the one this
experiment exists for, and the specification fixed "not calibrated" as grounds for declining,
so this record is put to Andy as **decline**. Details: `docs/results/typesafe-jev-dev400.md`;
the printed tables are `docs/results/typesafe-jev-dev400.txt`. The judge test of point 5 has
not run.

## Status

Proposed: written 2026-09-17 for Andy's acceptance. Becomes Accepted when the probe's
fixtures are committed and the judge test of point 5 has run.

The dev-400 row above records a **decline** on the calibration reading the decision was
proposed for; Andy's acceptance of the record is separate from the accept/decline call on the
row itself.
