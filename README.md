# NTSB probable-cause agent

An agent that determines the **probable cause** of a US general-aviation accident from the
evidence investigators gathered, scored against the verdict the National Transportation
Safety Board later publishes.

> **TL;DR** — The NTSB publishes a determined cause for every aviation accident it
> investigates, coded into a fixed taxonomy. That gives a hard judgement task with free,
> authoritative ground truth: **nobody here labels anything**, so the evaluation cannot
> become an argument with itself.
>
> The agent reads the evidence for a case and returns a cause, chosen from the NTSB's own
> codes so scoring is exact match with no judge in the loop. Where the case file is thin it
> goes and fetches the investigation's public document folder — which is the one place a
> measurement showed an agent earns its keep, rather than the one place it looked
> impressive.
>
> It will run on **open** investigations, publishing timestamped predictions that the NTSB
> scores months later by publishing its own verdict. Predictions are append-only and hashed,
> so "it predicted this on day 3" is checkable by a stranger rather than something they have
> to take on trust.
>
> **Status: not built yet.** This repository holds the architecture, the build order, and
> the decisions behind both. The measurement work that justifies building it is complete and
> frozen at [floyda/ntsb-spike](https://github.com/floyda/ntsb-spike).

---

## What the NTSB publishes

The NTSB investigates every US civil aviation accident. A closed investigation leaves a
public record containing both prose and a coded layer:

| | |
|---|---|
| **Factual narrative** | What investigators found: the flight, the wreckage, the weather, the pilot's records |
| **Analysis** | The investigator's reasoning from those facts toward a conclusion |
| **Probable cause** | The determination, one or two sentences |
| **Occurrence code** | The category for *what happened*, from a taxonomy of about 58 |
| **Finding codes** | The categories for *why* — the contributing factors |
| **Docket** | A public folder of supporting documents: wreckage examinations, records of conversation, the pilot's own accident form, photographs |

All of it is a work of the US federal government and therefore public domain — no licence
friction, and the docket needs no login.

- [NTSB Enterprise API developer portal](https://developer.ntsb.gov/) — `https://api.ntsb.gov/public`, the interface this project is built against
- [CAROL](https://data.ntsb.gov/carol-main-public/basic-search) — the public search tool
- [Bulk downloads](https://data.ntsb.gov/avdata) — **retiring 5 April 2027**, which is why this is built on the API rather than the file
- [An example docket](https://data.ntsb.gov/Docket?ProjectID=104739) — one investigation's documents

**What the agent does, and does not, do.** An investigation has two halves: field
investigators gather evidence — wreckage examinations, witness statements, maintenance
records, weather — and then an analyst reads that evidence and writes the verdict. **The
agent only does the second half.** It never sees the wreckage; it sees what the
investigators wrote down. That keeps the claim honest and matches what the data can
actually support.

**The split that makes the evaluation honest.** The factual narrative and the docket are
*evidence* the agent may read. The analysis, the probable cause and the codes are the
*answer*, and are never passed to a model except to score it. That boundary is enforced in
one function with an assertion and a test — not by convention, because convention is what
fails silently.

## Why this dataset, for a demonstration

The usual problem with a portfolio project is that it cannot be checked: the system is
asserted to work and the reader takes your word. This dataset removes that.

- **A federal agency wrote the labels.** No self-labelling, so no risk that the evaluation
  measures agreement with its own author.
- **Part of the scoring needs no judge.** The answer is a code from a fixed list, so it is
  exact match — no model, no rubric. That matters because model judges are unreliable in
  ways the spike measured directly: one agreed with a human on only 62.5% of the same
  answers, and its errors were one-sided.
- **Every result traces to a public URL.** A reader who doubts an output can open the same
  record and disagree specifically.
- **It supports live prediction with an external oracle.** Investigations run for months —
  a median of 140 days — so the agent can commit to an answer long before anyone knows if
  it is right.
- **The volume is right**: roughly 1,000–1,400 closed general-aviation cases a year. Enough
  to sample properly, cheap enough to process exhaustively.

The honest caveat, measured rather than glossed: these accidents are repetitive, so a
trivial "guess the commonest cause" strategy does better than you would like. That baseline
is reported next to every result.

## Why an agent, and not a single model call

That question has a measured answer rather than an opinion, which was the point of running
a spike before building anything.

| | |
|---|---|
| Conditional modal baseline | **16.2%** top-1 on the occurrence code |
| One model call, no tools | **57%** top-1 |
| ...on cases *with* a written factual narrative | **88%** |
| ...on cases *without* one | **12%** |
| Share of 2020–23 cases with no narrative | about **half** |

A single call is already excellent when the case record contains a written factual
narrative, and nearly useless when it does not. In those failures the missing information
was almost always sitting in the NTSB's public docket of supporting documents: of the 17
misses examined by hand, none were cases where the model misread evidence it had been
given.

So the agent exists to go and read the docket. Nothing beyond that is justified by
measurement, and nothing beyond that is being built. Similar-case retrieval, regulation
lookup and airframe history were all considered and dropped, because the labelled failures
never asked for them.

Full numbers, method and the script behind each figure:
[floyda/ntsb-spike](https://github.com/floyda/ntsb-spike) — start with
[the spike report](https://github.com/floyda/ntsb-spike/blob/main/docs/spike-report.md),
then [the build brief](https://github.com/floyda/ntsb-spike/blob/main/docs/build-brief.md).

## What the agent has to beat

Stated in advance, so the result can be checked rather than narrated:

- At least **50% top-1** on no-narrative cases, up from 12%. Below about 30% would mean the
  docket tool is not delivering the evidence the labels said was there.
- Overall held-out top-1 above the one-shot ceiling, measured like-for-like.
- An **ablation** with the docket tool removed must show the loss concentrated in
  no-narrative cases. If it does not, the tool is not doing what is claimed.
- **Abstention stays sensible**: it should fall as the docket supplies evidence, but hold
  where only physical evidence could decide the case.
- Average cost under **£0.05 per case**, enforced by a cap in code rather than watched.

The one-shot ceiling is being re-measured before the agent is built. The 57% above was
scored on free text by a human; output here is constrained to NTSB codes so scoring needs
no judge, and that is a different enough task that the old number is a reference point
rather than a bar.

## How it will be checkable in public

A live board runs the agent on investigations that are still open and records each
prediction with a timestamp and a fingerprint of the evidence it was made from. When the
NTSB publishes its verdict — a median of 140 days later — that standing prediction is
scored automatically. Predictions are append-only and committed as a hashed ledger, so
"it predicted this on day 3" is something a stranger can verify rather than something they
have to believe.

**Live numbers will be worse than the held-out numbers, and that is said here first.**
Simple cases close quickly, so cases still open are disproportionately the hard ones. In
the first six months the board will have a handful of resolutions, which is an anecdote,
not a statistic. The held-out numbers carry the weight; the board demonstrates that the
system runs unattended and can be proved wrong.

## Architecture in one paragraph

One library with thin entrypoints over it, so the agent that is evaluated and the agent
that is deployed are the same code with the same commit identifier. A deterministic router
sends cases with a narrative down a cheap single-call path and the rest into a tool loop
with a step budget and a hard cost cap. Scheduled work runs as a single container task in
its own AWS account, writing to a single-writer store. The public site is a pure function
of that store — generated files, no server, no request-time database — so hosting cost does
not move with traffic.

## Build order

| stage | what it delivers |
|---|---|
| S0 | repository foundation, ingestion, the evidence/answer split and its leakage test, CI |
| S1 | code-constrained output, judge-free scoring, evaluation harness, the re-measured ceiling |
| S2 | docket client, PDF classification and text extraction |
| S2.5 | the recorder — polls open dockets and timestamps when each document first appears |
| S3 | the agent loop, and the headline evaluation |
| S4 | predictions store, resolution watcher, hashed ledger |
| S5 | deployment and the public board |

S2.5 is deliberately out of dependency order. The timing of evidence arrival cannot be
reconstructed afterwards — the API deletes preliminary text when a case closes, and docket
listings carry no per-document dates — so it has to be recorded prospectively or not at
all. It needs the docket client and a table, not the agent.

Detail: [`docs/specs/2026-09-12-architecture-and-roadmap.md`](docs/specs/2026-09-12-architecture-and-roadmap.md).

## Repository layout

```
docs/specs/       architecture and build order
docs/decisions/   numbered decision records — context, choice, reasoning, alternatives
docs/runbooks/    operational procedures
```

Every significant decision is written down with what it rules out, including the ones that
turned out to be wrong. See [`docs/decisions/`](docs/decisions/).

## A note on tone

These are fatal accidents. The writing here is clinical, no victim names appear anywhere in
this repository or in any output it produces, and nothing is presented as a game or a
score to beat.

## Licence

MIT — see [LICENSE](LICENSE). NTSB investigation data is a work of the US federal
government and is in the public domain.
