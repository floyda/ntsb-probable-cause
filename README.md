# NTSB probable-cause agent

An agent that determines the **probable cause** of a US general-aviation accident from the
evidence investigators gathered, scored against the verdict the National Transportation
Safety Board later publishes.

> **TL;DR** — The NTSB publishes a determined cause for every aviation accident it
> investigates, coded into a fixed taxonomy. That gives a hard judgement task with free,
> authoritative ground truth: **nobody here labels anything**, so the evaluation cannot
> become an argument with itself.
>
> The agent reads the evidence for a case, writes its own account of what that evidence
> shows, and returns a cause, chosen from the NTSB's own codes so scoring is exact match
> with no judge in the loop. The structured case record is thin, so it goes and fetches the
> investigation's public document folder — which is the one place a measurement showed an
> agent earns its keep, rather than the one place it looked impressive.
>
> It will run on **open** investigations, publishing timestamped predictions that the NTSB
> scores months later by publishing its own verdict. Predictions are append-only and hashed,
> so "it predicted this on day 3" is checkable by a stranger rather than something they have
> to take on trust.
>
> **Status: S0 (foundation) built; no agent yet.** The repository has strict tooling, data
> ingestion, the evidence/synthesis/verdict split with its layered leakage guard, and a model
> seam — see "Commands" below to run it. The agent loop, the docket tool and the evaluation
> harness are not built yet. The architecture, the build order, and the decisions behind both
> are also here. The measurement work that justifies building at all is complete and frozen at
> [floyda/ntsb-spike](https://github.com/floyda/ntsb-spike).

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

**The split that makes the evaluation honest.** Each record is split three ways. The
structured observations and the docket's evidence documents are *evidence* the agent may
read. The factual narrative and the analysis are *synthesis*: the investigator's write-up,
produced at the end of the investigation and directed toward the cause they reached. The
probable cause and the codes are the *verdict*. Synthesis and verdict are never passed to a
model except to score it. A live case has no factual narrative yet, so writing one is part
of the agent's job, not an input to it. That boundary is enforced in one function with a
layered guard and tests — not by convention, because convention is what fails silently.

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
measurement, and nothing beyond that is being built.

**One change since the spike.** Those figures treated the factual narrative as evidence. The
build does not: the narrative is the investigator's summary, written once the cause is known,
and a live case never has one. Withholding it means every case depends on the docket rather
than about half, which strengthens the argument above — and it means the 57% and 88% figures
are history, not bars. The nearest precedent for what the agent faces is the 12%. Similar-case retrieval, regulation
lookup and airframe history were all considered and dropped, because the labelled failures
never asked for them.

Full numbers, method and the script behind each figure:
[floyda/ntsb-spike](https://github.com/floyda/ntsb-spike) — start with
[the spike report](https://github.com/floyda/ntsb-spike/blob/main/docs/spike-report.md),
then [the build brief](https://github.com/floyda/ntsb-spike/blob/main/docs/build-brief.md).

## What the agent has to beat

Stated in advance, so the result can be checked rather than narrated. The exact figures
are set in build stage S1, before the agent exists, because the spike's bars were written
against the narrative split that no longer applies. What they will require, in kind:

- Held-out top-1 above a **one-shot ceiling re-measured on this stack**: code-constrained
  output, no factual narrative, the same 40 cases first.
- An **ablation** with the docket tool removed must show a real loss. If it does not, the
  tool is not doing what is claimed.
- **Abstention stays sensible**: it should fall as the docket supplies evidence, but hold
  where only physical evidence could decide the case.
- Average cost per case under a **cap enforced in code** rather than watched. The spike's
  £0.05 line is re-measured, because every case now reads the docket.

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
that is deployed are the same code with the same commit identifier. Every case goes through a tool loop with a step budget and a hard cost
cap. Scheduled work runs as a single container task in
its own AWS account, writing to a single-writer store. The public site is a pure function
of that store — generated files, no server, no request-time database — so hosting cost does
not move with traffic.

## Build order

| stage | what it delivers |
|---|---|
| S0 | repository foundation, ingestion, the evidence / synthesis / verdict split and its leakage guard, CI |
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
src/ntsb_probable_cause/   the library: settings, data ingestion, field roles, the
                            evidence/synthesis/verdict split and its leakage guard, model seam
apps/                       thin entrypoints over the library (e.g. apps/ingest)
scripts/                    one-off and maintenance scripts (fixtures, the corpus scan,
                            documentation checks) — not part of the library
tests/                      unit tests and fixtures
docs/specs/                 architecture and build order
docs/decisions/             numbered decision records — context, choice, reasoning, alternatives
docs/plans/                 implementation plans for the stage currently in progress
docs/results/               committed output of scripts that report a number
docs/runbooks/              operational procedures
```

Every significant decision is written down with what it rules out, including the ones that
turned out to be wrong. See [`docs/decisions/`](docs/decisions/).

## Commands

Requires [`uv`](https://docs.astral.sh/uv/). `uv sync` installs the project and its dev
dependencies.

```bash
make check   # lint, type-check (mypy --strict) and test — what CI runs
make lint    # ruff format --check, ruff check, import-linter, deptry, vulture
make type    # mypy
make test    # pytest
make ingest  # fetch event months into data/raw (uv run ntsb-ingest fetch <first> <last>)
make build   # build data/processed/cases.parquet from the raw store
make scan    # scripts/corpus_scan.py — guard statistics over the whole processed corpus
make probe   # scripts/openrouter_probe.py — the S1 fixture-recording probe (spec §7.1)
make bars    # baseline + ceiling/A runs on heldout-40/heldout-400 + the S1 bars report (spec §6.5)
```

`ntsb-eval` (spec §6.5) is the S1 evaluation harness, installed by `uv sync`:

```bash
ntsb-eval baseline  [--sample heldout-400]                 # spec §6.3
ntsb-eval run       --arm ceiling|A --sample heldout-40|heldout-400|dev-400
                     [--exclude ROLE ...] [--include case_number] [--limit N]
                     [--model ID] [--price-variant batch|standard]
                     [--cap-usd 0.05] [--budget-usd 25] [--sync]
ntsb-eval report     <run id>|--latest ARM SAMPLE [--against <run id>|--against-latest ARM SAMPLE]
ntsb-eval judge      <run id> [--validated]                 # spec §8; dev-400 until validated
ntsb-eval threshold  <run id>                                # spec §9
```

Every subcommand accepts `--out PATH` to also write the printed text to a file.

Other scripts, run with `uv run python -m scripts.<name>`:

- `scripts.make_fixture` — create redacted development-split fixtures (decision 0015); see
  its module docstring for the `records` / `auto` / `api` subcommands.
- `scripts.check_docs` — the documentation check decision 0017's stage close-out depends on.

Settings are read from the environment (`NTSB_` prefix, decision 0012), or a local `.env`
file:

- `NTSB_API_KEY` — the NTSB Enterprise API key. Required for `make ingest`; never printed or
  committed.
- `NTSB_DATA_DIR` — where raw and processed data live (default `data`). Nothing under it is
  committed.
- `OPENROUTER_API_KEY` — the OpenRouter key `ntsb-eval run`/`judge` call the model through
  (decision 0009).
- `NTSB_RUNS_DIR` — where evaluation runs are written (default `data/runs`); never committed.
- `NTSB_MONTHLY_BUDGET_USD` — the monthly spend cap a run refuses to exceed (default 25).
- `NTSB_EXPECTED_COST_PER_CASE_USD` — measured cost per case a run projects against the
  budget from, once `make probe` has one; falls back to the cost cap when unset.

## A note on tone

These are fatal accidents. The writing here is clinical, no victim names appear anywhere in
this repository or in any output it produces, and nothing is presented as a game or a
score to beat.

## Licence

MIT — see [LICENSE](LICENSE). NTSB investigation data is a work of the US federal
government and is in the public domain.
