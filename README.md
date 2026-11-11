# NTSB probable-cause agent

An agent that determines the **probable cause** of a US general-aviation accident from the
evidence investigators gathered, scored against the verdict the National Transportation
Safety Board publishes.

**It is live.** The agent runs as **Ellery, version 1**. Each night it codes every case the NTSB
closed the day before, and the public site shows its answer beside the NTSB's:
**<https://ellery.demo.floyda.dev>**.

> **TL;DR**: The NTSB publishes a determined cause for every aviation accident it
> investigates, coded into a fixed taxonomy. That gives a hard judgement task with free,
> authoritative ground truth. **Nobody here labels anything**, so the evaluation cannot
> become an argument with itself.
>
> The agent reads the evidence for a case and returns a cause, chosen from the NTSB's own
> codes, so scoring is exact match with no judge in the loop. The structured case record is
> thin, so the agent also reads the investigation's public document folder, the docket.
>
> **The agent loop was measured against a simpler fixed method, and it lost.** On 400
> held-out accidents, the fixed method's first code matched the NTSB's 33.0% of the time and
> the loop's 23.5%, at an equal bill. The registered verdict was written before the run: "On
> held-out cases, the loop was not shown to improve on the fixed pipeline: it was worse." The
> loop runs on the site anyway, because it is the version being improved, and every later
> version is measured against that fixed method. The site says this on its first screen.
>
> **Status: S0 to S5 are built and released.** S5, the public site, launched on 2026-11-03.
> The measurement work that justified building at all is complete and frozen at
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
| **Occurrence codes** | The categories for *what happened*, in order, from a taxonomy of about 58 |
| **Finding codes** | The categories for *why*: the contributing factors |
| **Docket** | A public folder of supporting documents: wreckage examinations, records of conversation, the pilot's own accident form, photographs |

All of it is a work of the US federal government and therefore public domain. There is no
licence friction, and the docket needs no login.

- [NTSB Enterprise API developer portal](https://developer.ntsb.gov/): `https://api.ntsb.gov/public`, the interface this project is built against
- [CAROL](https://data.ntsb.gov/carol-main-public/basic-search): the public search tool
- [Bulk downloads](https://data.ntsb.gov/avdata): **retiring 5 April 2027**, which is why this is built on the API rather than the file
- [An example docket](https://data.ntsb.gov/Docket?ProjectID=104739): one investigation's documents

**What the agent does, and does not, do.** An investigation has two halves. Field
investigators gather evidence: wreckage examinations, witness statements, maintenance
records, weather. Then an analyst reads that evidence and writes the verdict. **The agent
only does the second half.** It never sees the wreckage; it sees what the investigators
wrote down. That keeps the claim honest and matches what the data can support.

**The split that makes the evaluation honest.** Each record is split three ways. The
structured observations and the docket's evidence documents are *evidence* the agent may
read. The factual narrative and the analysis are *synthesis*: the investigator's write-up,
produced at the end of the investigation and directed toward the cause they reached. The
probable cause and the codes are the *verdict*. Synthesis and verdict are never passed to a
model except to score it. That boundary is enforced in one function,
`records/split.py:split_record()`, with a layered guard and tests, including a mutation test
that proves the boundary test can fail (decisions 0013, 0016). It is not left to convention,
because convention is what fails silently. The same split and guard run in evaluation and on
every live case.

## Why this dataset, for a demonstration

The usual problem with a portfolio project is that it cannot be checked: the system is
asserted to work and the reader takes your word. This dataset removes that.

- **A federal agency wrote the labels.** There is no self-labelling, so no risk that the
  evaluation measures agreement with its own author.
- **Part of the scoring needs no judge.** The answer is a code from a fixed list, so it is
  exact match: no model, no rubric. That matters because model judges are unreliable in ways
  the spike measured directly: one agreed with a human on only 62.5% of the same answers, and
  its errors were one-sided.
- **Every result traces to a public URL.** A reader who doubts an output can open the same
  record and disagree specifically.
- **New cases keep arriving.** Roughly 1,000 to 1,400 general-aviation cases close each year,
  so the live board is a steady supply of cases newer than anything the agent was developed on.

The honest caveat, measured rather than glossed: these accidents are repetitive, so a
trivial "guess the commonest cause" strategy does better than you would like. That baseline
is reported next to every result, and on held-out cases it beats a single model call.

## Why an agent, and not a single model call

The spike asked that question before anything was built. With the factual narrative as
evidence, one model call was excellent when the narrative existed and nearly useless when it
did not. In those failures the missing information was almost always in the NTSB's public
docket. Of the 17 misses examined by hand, none were cases where the model misread evidence
it had been given. So the agent exists to read the docket.

The build then withheld the factual narrative from every case (decision 0013): it is the
investigator's summary, written once the cause is known, and a new case never has one. That
made the spike's figures history, not bars, and made every case depend on the docket.
Full numbers, method and the script behind each figure:
[floyda/ntsb-spike](https://github.com/floyda/ntsb-spike). Start with
[the spike report](https://github.com/floyda/ntsb-spike/blob/main/docs/spike-report.md),
then [the build brief](https://github.com/floyda/ntsb-spike/blob/main/docs/build-brief.md).

## What was measured

Every figure here is on the fixed held-out sample `heldout-400` (events 2020 to 2023), on
GPT-6 Luna, from a committed results file. Each figure is occurrence top-1: the share of cases
where the first occurrence code matched the NTSB's.

| method | top-1 | source |
|---|---|---|
| No model: the commonest cause for the case's facts (all 4,241 held-out cases) | 17.7% | `docs/results/s1-bars.txt` |
| One model call, no docket (the "ceiling") | 10.5% [7.9%, 13.9%] | `docs/results/s24-bars.txt` |
| Arm A: start facts only | 5.0% [3.0%, 7.2%] | `docs/results/s32-claims-heldout.txt` |
| **Arm B, the fixed pipeline**: read every document, call every coding tool in a fixed order, answer, check the order | **33.0% [28.5%, 37.5%]** | `docs/results/s32-claims-heldout.txt` |
| **Arm C, the loop** (Ellery, version 1): chooses what to read and which coding tools to call | **23.5% [19.2%, 27.5%]** | `docs/results/s32-claims-heldout.txt` |
| The loop, with the docket removed | 15.0% [11.5%, 18.5%] | `docs/results/s32-claims-heldout.txt` |

What this says:

- **The docket carries the case.** Without it the loop loses 8.5 points [−13.0, −3.8] and falls
  below the no-model baseline.
- **Choosing what to read did not help.** Paired on the same 400 cases, the loop is 9.5 points
  [−14.0, −5.2] behind the fixed pipeline. Their billed costs were equal: $2.0610 against
  $2.1347 for the 400 cases. The claim was registered before the run
  (`docs/rounds/s3-registration.md`), and the result is published as it came out.
- **The fixed pipeline is the bar for every later version.** `heldout-400` has been used and
  cannot test a later version (decision 0153). The next version is measured on a sealed
  development sample and on the live board.

A single model call scores below the no-model baseline. This is also published as it stands:
it is why the bar is the baseline, not the ceiling. Every docket-reading result above read
pypdf 6.19.0's text; decision 0218 records what changed when pypdf moved on.

How each was measured, with intervals, failures and costs: the "Eval bars" section of
[`CLAUDE.md`](CLAUDE.md), and the results files it names.

## How it is checkable in public

**The agent codes each case at closure.** The original plan was to lock predictions on open
cases and wait for the verdict. The recorder (S2.5) watched open cases nightly and found that
dockets almost always arrive on the night a case closes, and without the docket the agent does
no better than guessing. So the live run is made from the docket as published at closure, with the
verdict withheld by the same split and guard as in evaluation (decision 0154). The cases are
still newer than anything the agent was developed on, and every run records its commit.

**Each night**, at 06:00 UTC, a scheduled AWS Fargate task:

1. codes every newly closed case once, as Ellery version 1, pinned by its prompt fingerprint
   and model name (decisions 0168, 0169), under a per-case cap and a monthly limit on its own
   key (0170);
2. scores it against the NTSB's codes, or later when the codes arrive (0174);
3. writes each run folder to a private bucket that the task never deletes from (0172);
4. builds the export `board/1` for the site (0173).

A GitHub job then appends the SHA-256 of every new run and night manifest to `ledger.jsonl` on
the public, protected
[`ledger` branch](https://github.com/floyda/ntsb-probable-cause/tree/ledger) (0178). A
rewritten run would no longer match its published hash. When the export finishes, the site
rebuilds itself.

**Live numbers and held-out numbers are never shown together** (decision 0021). Live cases are
few, and they enter any report as counts only (0024). The held-out numbers carry the weight; the
board shows that the system runs unattended and can be proved wrong, case by case.

## Architecture in one paragraph

One library, `ntsb_probable_cause`, with thin entrypoints over it, so the agent that is
evaluated and the agent that is deployed are the same code with the same commit identifier.
Every model call goes through OpenRouter, for evaluation and live runs alike (decision 0009).
Every case goes through a tool loop with a step budget and a hard cost cap. Two scheduled
container tasks run in their own AWS account: the recorder at 03:00 UTC and the live night at
06:00 UTC. The public site is a pure function of the night's export: generated files, no server,
no request-time database. It is built with Astro and served by CloudFront on a flat-rate plan, so
hosting cost does not move with traffic.

## Build order

| stage | what it delivered | status |
|---|---|---|
| S0 | repository foundation, ingestion, the evidence / synthesis / verdict split and its leakage guard, CI | done |
| S1 | code-constrained output, judge-free scoring, the evaluation harness, the re-measured bars | done |
| S2 | docket client, PDF classification and text extraction, arm B | done |
| S2.4 | the model switch to GPT-6 Luna | done |
| S2.5 | the recorder: polls open cases and dockets nightly and timestamps what appears | done |
| S2.6 | the widened docket: transcription of words in page images, now off by default | done |
| S2.7 | coding guidance and the ordering check | done |
| S3 | the agent loop (S3.1), its registered held-out claims (S3.2), a live shadow (S3.3) | done |
| S4 | live nights in the cloud, scoring at closure, the board export, the public ledger | done |
| S5 | the public site at `ellery.demo.floyda.dev` | done, launched 2026-11-03 |

**What comes next** is a second version of the agent, with a precedent tool that it questions
(decision 0140; design note
[`docs/specs/2026-10-03-s3-precedent-tool-design.md`](docs/specs/2026-10-03-s3-precedent-tool-design.md),
a Draft). It is measured on the sealed sample `dev-seal-s3-400` and on the live board (0141,
0153). It replaces version 1 on the board when it beats version 1 in a registered comparison.
The fixed pipeline stays the bar for calling the loop warranted.

Detail: [`docs/specs/2026-09-12-architecture-and-roadmap.md`](docs/specs/2026-09-12-architecture-and-roadmap.md),
and each stage's specification under [`docs/specs/`](docs/specs/), whose As-built section
records what was delivered.

## Repository layout

```
src/ntsb_probable_cause/   the library
  records/                  field roles, the evidence/synthesis/verdict split, its guard, case marks
  docket/                   docket client, listing, classifier, text extraction, transcription
  scoring/                  code tables, the evaluation harness, claims, calibration, guidance
  agent/                    the loop (arm C), its tools, its texts and arm B's tool post-pass
  model/                    the model seam: OpenRouter transport, tool text
  recorder/, store/         the nightly recorder and its SQLite store
  live/                     live nights: closure runs, later scores, the board export, the ledger
apps/                       thin entrypoints: ntsb-ingest, ntsb-eval, ntsb-record, ntsb-live
infra/                      AWS CDK stacks: recorder, live nights, the site
site/                       the public site (Astro, strict TypeScript, pnpm)
scripts/                    measurement and maintenance scripts, catalogued in docs/scripts.md
tests/                      unit tests and fixtures
docs/specs/                 architecture, build order and each stage's specification
docs/decisions/             numbered decision records: context, choice, reasoning, what it rules out
docs/rounds/                registrations written before a measured run
docs/results/               committed output of scripts that report a number
docs/runbooks/              operational procedures
docs/schemas/               the board/1 JSON Schema
```

Every significant decision is written down with what it rules out, including the ones that
turned out to be wrong. See [`docs/decisions/`](docs/decisions/).

## Commands

Requires [`uv`](https://docs.astral.sh/uv/). `uv sync` installs the project and its dev
dependencies. The site also needs Node (the version in `site/.node-version`) and pnpm 11.28.4.

```bash
make check        # lint, mypy --strict, pytest and the site's checks: what CI runs
make lint         # ruff format --check, ruff check, import-linter, deptry, vulture
make type         # mypy
make test         # pytest
make site-check   # the site: lint, format, astro check, types, build, Vitest, axe in a browser
make site-numbers # the site's numbers file, from committed results; pytest fails while it is stale
make ingest       # fetch event months into data/raw (uv run ntsb-ingest fetch <first> <last>)
make build        # build data/processed/cases.parquet from the raw store
make record       # one recorder pass (uv run ntsb-record run)
```

Each stage's own targets (`s24-*`, `s26-*`, `s27-*`, `s3-*`, `s32-*`, `s33-*`, `s4-*`) are in
the `Makefile`, each with a comment. Every paid target checks its stage's spend line first; the
held-out targets ran once and are closed.

`ntsb-eval` is the evaluation harness:

```bash
ntsb-eval baseline   [--sample heldout-400]
ntsb-eval run        --arm ceiling|A|B|C --sample <sample> [--evidence-version v1|v2]
                     [--guidance NAME ...] [--without suggest_codes|coding] [--round N]
                     [--exclude ROLE ...] [--include case_number] [--limit N]
                     [--model ID] [--price-variant batch|standard] [--max-output-tokens 8000]
                     [--cap-usd USD] [--budget-usd USD] [--expected-cost-per-case-usd USD]
                     [--sync] [--resume RUN_ID]
ntsb-eval tools      <run id>                       # arm B's fixed coding-tool post-pass
ntsb-eval check      <run id> --way rule|luna|jev|jev2 [--stats s27|s3]   # the ordering check
ntsb-eval report     <run id>|--latest ARM SAMPLE [--against <run id>|--against-latest ARM SAMPLE]
ntsb-eval judge      <run id> [--validated]
ntsb-eval threshold  <run id>
ntsb-eval release    <run id>                       # clear a dead run's budget reservation
ntsb-eval transcribe --sample dev-400 --expected-cost-per-page-usd USD [--dry-run]
```

Every subcommand accepts `--out PATH` to also write the printed text to a file. The sealed and
live samples are refused until their rules allow them. `ntsb-live run|report|export|verify-ledger`
runs and reports the live nights; read
[`docs/runbooks/live-cloud-nights.md`](docs/runbooks/live-cloud-nights.md) first. The site's
deployment is [`docs/runbooks/site-deploy.md`](docs/runbooks/site-deploy.md).

Every script in `scripts/`, what kind it is and what it produced:
[`docs/scripts.md`](docs/scripts.md).

### Settings

Settings are read from the environment (`NTSB_` prefix, decision 0012), or a local `.env`
file. Nothing under the data folders is committed.

- `NTSB_API_KEY`: the NTSB Enterprise API key. Required for `make ingest`; never printed or
  committed.
- `OPENROUTER_API_KEY`: the OpenRouter key every model call goes through (decision 0009).
- `TYPESAFE_API_KEY`: Jev, for the S2.7 ordering check on development runs only (0097).
- `NTSB_DATA_DIR`: where raw and processed data live (default `data`). A git worktree needs it
  pointed at the main checkout's `data/` (0057).
- `NTSB_RUNS_DIR`: where evaluation runs are written (default `data/runs`).
- `NTSB_MONTHLY_BUDGET_USD`: the monthly spend cap a run refuses to exceed (default 40,
  decision 0083); transcription and inventory spend count against it (0081).
- `NTSB_EXPECTED_COST_PER_CASE_USD`: the measured cost per case a run projects against the
  budget; falls back to the cost cap when unset.
- `NTSB_DOCKET_DIR`, `NTSB_TRANSCRIPTION_DIR`, `NTSB_LIVE_DOCKET_DIR`: the caches of docket
  documents, page transcriptions and live cases' documents (defaults under `NTSB_DATA_DIR`).
- `NTSB_DOCKET_SECONDS_PER_REQUEST`: the minimum time between requests to `data.ntsb.gov`
  (default 2.0 seconds), enforced in code as a floor above zero.
- `NTSB_STORE`: the recorder's SQLite store, a local path or an `s3://` URL.
- `NTSB_LIVE_BUCKET`, `NTSB_LIVE_ALERT_TOPIC_ARN`: the live bucket and alert topic. Set inside
  the cloud task and by `scripts/live_env.sh`, unset elsewhere.
- `NTSB_COMMIT_SHA`: set only inside container images, which have no `.git`.

## A note on tone

These are fatal accidents. The writing here and on the site is clinical. No victim names
appear anywhere in this repository or in any output it produces, and every built page is checked
to show no aircraft registration. Nothing is presented as a game or a score to beat.

## Licence

MIT; see [LICENSE](LICENSE). NTSB investigation data is a work of the US federal
government and is in the public domain.
