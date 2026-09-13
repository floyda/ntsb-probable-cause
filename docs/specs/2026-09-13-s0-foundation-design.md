# S0 — Foundation: design

*Drafted 2026-09-13 from a design session with Andy. Status: awaiting Andy's sign-off.
This is the specification for build stage S0 in
`docs/specs/2026-09-12-architecture-and-roadmap.md` §11. It records what S0 builds, why,
and the condition for moving on. The implementation plan is written from it separately.*

**How to read this.** Each section says what is built, then why. Terms in **bold** on
first use are in the glossary at the end. Every number is labelled **M1–M7** and comes
from `scripts/exploratory/s0_design_measurements.py`; its full output is saved beside
this document as `2026-09-13-s0-design-measurements.txt`. That script reads the frozen
spike's local data, because this repository has no data yet. Any text measurement uses
the **development split** only.

Decision records written with this specification: 0011 to 0016 (section 14).

---

## 1. What S0 is for

S0 builds the parts that every later stage stands on and that are expensive to get wrong
late:

1. The repository, its tooling, and continuous integration that enforces them.
2. Ingestion: case records fetched from the NTSB API and rebuilt into a local processed
   file.
3. The single function that splits a record into what the model may see and what it may
   not, with a leakage guard and tests that prove the guard can fail.
4. The request side of the model boundary, and a fake model client for tests.
5. Real test fixtures that are safe to publish.

S0 calls no model and spends no money on model calls.

---

## 2. What the agent is given: evidence, synthesis and verdict

This section changes the plan inherited from the spike. It is the most important
decision in S0 and it drives the design of the leakage guard.

### 2.1 The change

The spike treated the NTSB **factual narrative** as evidence. It is not raw evidence. An
investigator writes it at the end of the investigation, as a summary of everything that
was found, and it is naturally directed toward the probable cause the investigator has
reached. It is the first half of the analysis, already done.

**The live agent's job is to write that narrative itself, from the evidence available,
and then to determine the probable cause.** So the factual narrative is withheld from
the model, the same as the probable cause.

Every field of a case record now has one of three roles:

| role | what it is | fields | sent to the model | used for |
|---|---|---|---|---|
| **Evidence** | Observations recorded during the investigation | aircraft make, model and registration; engine type; pilot certificate and hours; weather condition and METAR; injury level; phase of flight; preliminary narrative | yes | the agent's input |
| **Synthesis** | The investigator's write-up | factual narrative, analysis narrative | **no** | the reference the agent's own narrative is compared against |
| **Verdict** | The determination | probable cause, occurrence codes, finding codes | **no** | exact-match scoring |

The agent's output gains one field: its own **evidence narrative**, written before its
probable cause. How that narrative is graded is decided in S1, with the lay explanation,
because both have the same problem: model judges are unreliable (0006 cites 62.5%
agreement with a human).

### 2.2 Why the measurements support it

While designing the leakage guard we measured how often withheld text appears word for
word inside the factual narrative. The answer showed the factual narrative and the
analysis are often the same text.

- **M5.** In the development split, 27,607 sentences of 40 characters or more from the
  analysis or probable cause appear verbatim in the factual narrative, across 7,793
  cases. In 1,999 cases the whole analysis text is inside the factual narrative.
- **M7.** All 6,126 development C-class cases are reports of the flavour
  `Basic (no factual)`. They still carry a "factual" narrative. 62% of them duplicate
  the analysis (at least half of the analysis sentences appear verbatim).
- **M6.** The practice varies by year: between 27% (2012) and 99% (2014, 2015) of C-class
  cases are duplicated. L-class and F-class cases are at or below 6% in every year.

Example, case `CEN09CA125`: the factual and analysis fields contain the same paragraph,
which describes a tow bar left attached before take-off and a gear-up landing. The
probable cause is "the pilot's failure to remove the airplane's tow bar before takeoff."

Under the spike's roles, this text was evidence in one field and answer in another. Under
the new roles both copies are synthesis, so the question does not arise.

### 2.3 What evaluation tests, and how it differs from live

Closed cases cannot be replayed in the order their evidence arrived: the API deletes the
preliminary narrative at closure and docket listings carry no per-document dates. So
evaluation gives the agent **the closed-case record without synthesis and verdict**, plus
the docket as it is at closure.

| | held-out evaluation | live board |
|---|---|---|
| structured evidence fields | final values | values as they are on the day |
| preliminary narrative | **absent**: 0 of 13,560 development cases have one (M4) | often present |
| docket | complete | partial; documents arrive over months |
| synthesis and verdict | withheld | do not exist yet |

The two differ in both directions. Held-out scores are therefore not a forecast of live
scores. The recorder (S2.5) timestamps when each docket document first appears; that is
what makes a later time-sliced evaluation possible ("only documents that existed by day
30").

### 2.4 Consequences outside S0

These are recorded in the roadmap amendment made with this specification (section 14)
and are decided in the stages named. S0 does not decide them.

- **The narrative router goes.** The roadmap sent cases with a narrative down a cheap
  single call. No case now has a narrative, so every case goes through the docket path.
- **The spike's 57% one-shot ceiling is not a reference.** It was measured with the
  narrative as evidence. The closest precedent is the spike's 12% on the 16 cases
  without a narrative, measured on structured fields alone. S1 measures the new ceiling.
- **Slices change.** "Narrative present / absent" means nothing now. Investigation class
  (C / L / F) is the proposed replacement, because docket content differs by class.
- **Cost per case will rise**, because every case reads the docket. The £0.05 cap is
  re-measured in S1 and S3, not assumed.
- **The main leakage risk moves to the docket (S2).** A closed case's docket can contain
  NTSB-written factual reports, which are synthesis. Text matching cannot filter them,
  because the factual narrative quotes genuine evidence documents such as records of
  conversation; the genuine documents would match too. The filter must work on document
  type and title, with a reviewed allow-list and a measured error rate.
- **The occurrence code is a weak live target.** The spike found that open cases carry
  the coded defining event from day 1, and the occurrence code is read from that event.
  Finding codes and the probable cause are the genuine live unknowns. The code stays
  withheld in evaluation so evaluation and live match. S1 decides the headline metric.

---

## 3. Repository layout

```
pyproject.toml                  hatchling build backend; uv project; Python == 3.14.*
uv.lock                         committed
src/ntsb_probable_cause/        the library (0002): no CLI, no printing, no cloud code
  py.typed
  fields.py                     field roles and the raw paths each role reads
  splits.py                     split_of(event_date); filters
  sources.py                    NTSB API facts and model prices, each with its source
  settings.py                   per-run values from environment and flags
  errors.py                     exception hierarchy
  data/
    api.py                      NTSB API client
    ingest.py                   month-partitioned fetch and manifest
    build.py                    raw -> processed file
  records/
    evidence.py                 Evidence
    synthesis.py                Synthesis
    verdict.py                  Verdict
    split.py                    split_record(): the only place a record is split
    guard.py                    the leakage checks
  model/
    client.py                   Payload, ModelClient, RecordingFakeClient
apps/ingest/                    argument parsing and wiring only
scripts/
  make_fixture.py
  corpus_scan.py
  exploratory/                  one-off measurement scripts, kept so numbers stay traceable
docs/results/s0-corpus-scan.txt counts from the corpus scan (no record text)
tests/
  fixtures/records/             redacted real development records
  fixtures/api/                 one redacted API page
  fixtures/eval/                case-ID lists from the spike's labelling sheets
.github/workflows/ci.yml
.github/dependabot.yml
.pre-commit-config.yaml
Makefile  .editorconfig  .env.example  SECURITY.md
```

**The package is `ntsb_probable_cause`**, not `ntsb_pc` as the roadmap had it. It matches
the repository and distribution name, which is the Python packaging convention, and a
reader outside the project can read it. "pc" reads as "personal computer".

---

## 4. Tooling

Decision record 0011.

**uv on the hatchling build backend.** These do different jobs. hatchling turns the
project into an installable package. uv creates the virtual environment, installs the
pinned Python, resolves dependencies and writes a lockfile. The lockfile is the reason:
the laptop, continuous integration and the container image install exactly the same
versions, so "the evaluated agent is the deployed agent" holds for dependencies as well
as code.

**Python pinned to 3.14**, matching the local interpreter. The container image follows
the pin in S5.

**Static analysis**, all run through uv, so nothing is installed globally:

| tool | what it catches | why it is here |
|---|---|---|
| ruff (lint and format) | style, unused code, common bugs, insecure calls, test style, docstrings | one fast tool for many rule sets: `E F W I B UP SIM S PT D PL RUF` and others |
| mypy `--strict` with the pydantic plugin | type errors | strict from the first commit; adding strictness later means fixing everything at once |
| import-linter | forbidden imports between modules | makes the evidence/synthesis/verdict boundary and 0002 machine-checked (section 7.3) |
| deptry | unused or undeclared dependencies | keeps `pyproject.toml` honest |
| pip-audit | dependencies with known vulnerabilities | the repository is public |
| vulture | dead code | small codebase, cheap to keep clean |

A second type checker (pyright) is not used. Two checkers that disagree cost more time
than they catch.

**Pre-commit hooks:** ruff, mypy, import-linter; gitleaks (secret scanning — two API keys
live in the environment); check-added-large-files (makes "raw data never in git" an
enforced check); check-yaml, check-toml, check-json, end-of-file-fixer,
trailing-whitespace, check-merge-conflict, mixed-line-ending; no-commit-to-branch on
`main`; typos; actionlint and zizmor (workflow linting and security); `uv lock --check`;
and two local hooks: reject any committed path under `data/`, and reject fixture files
that contain a redacted field (section 9).

**Tests:** pytest; pytest-cov with branch coverage and a 90% threshold on the library;
hypothesis for property tests; pytest-socket so tests cannot reach the network; respx to
mock HTTP. The HTTP client is httpx.

---

## 5. Constants replace `config.yaml`

Decision record 0012.

The spike's `config.yaml` held three kinds of value that change for different reasons:

| kind | examples | should change | where it goes |
|---|---|---|---|
| Method constants | field roles, splits, filters | never casually: a change invalidates every reported number | `fields.py`, `splits.py`: frozen, typed |
| Facts about external services | NTSB base URL and endpoints, page size, model prices | when the outside world changes | `sources.py`: typed, each citing the spec or saved response it came from |
| Run parameters | API key, rate limit, data paths, later model and effort | every run | `settings.py`: pydantic-settings from environment and flags, recorded in each run's output |

A YAML file suits none of them well. Method constants in an editable file can be changed
without review; in code, a change appears in a diff and needs a decision record. The
spike's content carries over unchanged, with two corrections:

- Sonnet 5 price: $2 / $10 per million tokens, and $1 / $5 for the `:batch` variant (0009).
  The spike recorded $3 / $15.
- The factual narrative moves from evidence to synthesis (section 2).

---

## 6. Ingestion

### 6.1 Fetch

`data/api.py` calls `GET https://api.ntsb.gov/public/api/Common/v2/GetCasesByDateRange/`
with `startDate`, `endDate`, `mode=aviation` and a continuation `marker`. The response
carries `hasMore` and `nextMarker`, up to 1,000 records per page. The key is sent in the
`Ocp-Apim-Subscription-Key` header and read from `NTSB_API_KEY`. These details are from
the OpenAPI spec (`../ntsb-spike/public.yaml`) and the spike's saved responses, not
invented (rule 2).

- **M1.** The date range filters on event date. All 29,418 records the spike fetched month
  by month have an `eventDate` inside the month requested.

So the raw store is partitioned by event month:

```
data/raw/v2/YYYY-MM/page-NN.json     each page byte-for-byte as received
data/raw/v2/manifest.jsonl           one row per month: start, end, fetched_at,
                                     page count, record count, sha256 per page, endpoint
```

- Requests are limited to 30 per minute, self-imposed (the spec states no limit).
- 429 and 5xx responses are retried with exponential backoff and a maximum attempt count.
  Other errors stop the run.
- A month already in the manifest is skipped unless `--refresh` is given. An interrupted
  run resumes where it stopped.
- The default end is the last complete month.
- Command: `ntsb-ingest fetch 2009-01 2026-08` (via `make ingest`).

**Why fetch fresh rather than copy the spike's files:** a stranger with an API key can
reproduce the corpus end to end, and nothing reads across into the frozen spike.

`GetCasesByModifiedDateRange` exists in the spec (v1, no documented pagination). It is the
likely route for incremental ingestion in S2.5 and is not used in S0.

### 6.2 Build

`data/build.py` reads the manifest, verifies every page hash, and writes one processed
file.

1. Remove duplicate case numbers; the most recent fetch wins.
2. Filter with exact values, not the spike's pattern match:
   `completionStatus == "Completed"`, FAR part `"091"` on the first aircraft, event year
   2009 or later.
3. Write `data/processed/cases.parquet` (zstd compression), one row per case:

| column | source | purpose |
|---|---|---|
| `ntsb_number` | `ntsbNumber` | identity |
| `mkey` | `mKey` | docket URL construction |
| `event_date` | `eventDate` | the split |
| `split` | `split_of(event_date)` | dev / heldout / open |
| `completion_status` | `completionStatus` | filter audit |
| `investigation_class` | 6th character of the case number | slicing |
| `report_flavour` | `factualFinalReportFlavor` | slicing |
| `aircraft_count` | `len(aircrafts)` | the first-aircraft convention is visible |
| `docket_url` | built from `mkey` | tool binding in S2 |
| `raw_json` | the record as fetched | input to `split_record()` |

4. Write `data/processed/cases.meta.json`: the manifest hash, row counts per split and per
   class, and the build time.

**Why the raw record, not flattened columns** (decision record 0014). Live records arrive
from the API as nested JSON. If evaluation also starts from the raw record, evaluation and
live pass through the same `split_record()`. A flat table would need a second route for
live records, and the leakage path check could only see column names rather than the real
source paths.

**Why class comes from the case number.** `investigationClass` is filled on only 945 of
13,560 development records (M7). The case-number letter is always present.

**Reconciliation check.** For event years up to 2023, split counts must match the spike's
13,560 development and 4,241 held-out cases, or each difference must be explained in the
build output. The NTSB occasionally revises closed cases. This checks new code against a
known number before it is trusted, as S1 does with the baseline.

---

## 7. The split and the leakage guard

Decision record 0016. The guard exists to catch **mechanical leakage**: software that puts
withheld content into what the model sees, through a bug, a wrong path, or a careless
concatenation. **Semantic leakage** — evidence that makes the cause obvious — is a
property of the NTSB's text, not of our code. It is measured and reported as a statistic,
never used as a runtime check.

### 7.1 Field map

`fields.py` declares, for every role, the raw paths it reads. Derived roles declare every
path they read, not only their output:

```
Evidence   prelim_narrative        narratives[0].prelimNarrative
           aircraft_make           aircrafts[0].aircraftMake
           ...                     (the spike's evidence map, less the factual narrative)
           phase_of_flight         aircrafts[0].events[].isDefiningEvent,
                                   aircrafts[0].events[].sequenceNumber,
                                   aircrafts[0].events[].cicttPhaseSOEGroup
Synthesis  factual_narrative       narratives[].concatenatedFactualNarrative
           analysis_narrative      narratives[].analysisNarrative
Verdict    probable_cause          narratives[].probableCause
           occurrence_codes        aircrafts[].events[]
           finding_codes           aircrafts[].findings[]

Withheld subtrees: narratives[].concatenatedFactualNarrative, narratives[].analysisNarrative,
                   narratives[].probableCause, aircrafts[].events[], aircrafts[].findings[],
                   richNarratives
```

`richNarratives` is empty in all 29,418 raw records (M7). It is withheld anyway, because
its name says what it would hold if filled.

Bookkeeping fields on Evidence — `case_id` and `docket_url` — are never rendered into the
model's input (section 8).

### 7.2 Types

```python
records/evidence.py    class Evidence(BaseModel)    frozen, extra="forbid", one attribute per role
records/synthesis.py   class Synthesis(BaseModel)   frozen
records/verdict.py     class Verdict(BaseModel)     frozen
records/split.py       def split_record(raw: Mapping[str, object], *,
                                        exclude: frozenset[EvidenceRole] = frozenset()
                                        ) -> tuple[Evidence, Synthesis, Verdict]
```

`exclude` removes evidence roles for ablations. The spike's `build_evidence(exclude=...)`
is the precedent.

Multi-aircraft cases keep the spike's convention: the first aircraft is used. The count
is visible in `aircraft_count` and reported by the corpus scan.

### 7.3 The checks

| # | check | when it runs | what it catches |
|---|---|---|---|
| 0 | **Allow-list.** Evidence reads only declared paths. | always | a field the NTSB adds tomorrow cannot enter by default |
| 1 | **Keys.** Evidence has a fixed schema with no extra attributes; the rendered payload's keys are a subset of evidence role names. | construction, rendering | an answer name added to the payload |
| 2 | **Paths.** No evidence path lies under a withheld subtree. | module import, and a test | an evidence role pointed at a withheld field |
| 3 | **Provenance.** Each value in the payload equals the value at its declared path in the raw record. | boundary test | a value that came from somewhere else |
| 4 | **Tripwire.** No synthesis or verdict text, and no occurrence or finding code as a whole token, appears in any evidence value. Fails closed with `LeakageError`. | every `split_record()` call, which holds all three parts; the payload is rendered only from these evidence values | withheld content copied in by any route |

**The one exception to check 2** is `phase_of_flight`, which reads the defining event
inside `aircrafts[].events[]`. It is kept as evidence because open cases carry the coded
event sequence from day 1, so a live agent genuinely has it. The spike's ablation found
it contributes at most 2.5 points of the one-shot score. The exception is a named entry
in code that cites decision record 0016, so a second exception would show in review.

**The tripwire's details.**

- Text is normalised before comparison: whitespace collapsed, lower case.
- Whole withheld texts and their individual sentences are both checked.
- Known boilerplate is excluded: "this report was modified on …". These are the only
  probable-cause sentences found verbatim in development factual narratives (M5).
- **The minimum sentence length is measured, not chosen.** The corpus scan (section 10)
  reports hits at several lengths; the lowest length with zero hits on the whole corpus
  is written to `docs/results/s0-corpus-scan.txt` and used. Very short fragments such as
  "none." cannot be allowed to stop a run.
- Code tokens: 0 hits in development factual narratives, preliminary narratives or METARs
  (M5). With the factual narrative withheld, S0's payload contains only structured fields
  and short strings, so zero hits is the expectation; the scan confirms it on every split.

**What is reported, not checked:** analysis-to-factual duplication (M5–M7) and the spike's
give-away phrase rate. The corpus scan prints both. Neither can occur in the payload now,
but S1 uses them to describe the corpus honestly.

### 7.4 Import boundaries

import-linter contracts, checked in continuous integration:

- `ntsb_probable_cause` never imports `apps`.
- `ntsb_probable_cause.model` may import `records.evidence` and must not import
  `records.synthesis` or `records.verdict`.
- `records.synthesis` and `records.verdict` may be imported only by `records.split`,
  `records.guard`, and (from S1) `scoring`. Scripts outside the library, such as the corpus
  scan, are not covered by the contract.

---

## 8. The model boundary

Decision record 0016 (with the guard). Four objects, each narrower than the one before:

| object | contents | who sees it |
|---|---|---|
| raw record | everything the API returns: 332 distinct leaf paths (M3) | ingestion, `split_record()` |
| Evidence | allow-listed evidence, plus `case_id` and `docket_url` for bookkeeping | our code |
| Synthesis, Verdict | withheld fields | build, scoring |
| **Payload** | the exact text sent to the model, rendered from Evidence without bookkeeping fields or excluded roles | the model |

The Payload is what the recording fake inspects and, from S4, what the evidence
fingerprint hashes.

```python
class Payload:                    # only constructor: Payload.from_evidence(evidence)
    text: str
class ModelClient(Protocol):
    def complete(self, payload: Payload, settings: ModelSettings) -> ModelReply: ...
class ModelReply:                 # provisional: text only
class RecordingFakeClient:        # keeps every Payload received; returns scripted replies
```

**Why only the request side.** The response shape — usage, cost, tool calls — must come
from a saved real OpenRouter response (rule 2). That probe is S1's first task. S1 defines
`ModelReply` from it.

**Why the fake is built now.** In S0 it lets the boundary test check what actually crosses
to the model. Later it is required: S1's harness tests run without spending money; S3's
step budget, abstain path and £0.05 cap need deterministic triggers that a real model
cannot provide; and continuous integration never holds a model key.

**Why `case_id` and `docket_url` are not in the payload.**

- The case number encodes the investigation class. In the development split, 93.1% of
  F-class cases are fatal and 0.0% of C-class cases are (M4). That is mostly redundant
  with `injury_level`, but it is an investigator's decision, not an observation.
- A case number is an exact handle a model could use to recall a published report from
  its training data. The docket URL contains the case's internal key, so it is the same
  kind of handle.
- The spike's payload did not contain the case number either.

Docket documents print the case number, so from S3 the model will see it anyway. Keeping
it out of the payload removes a free handle; it does not solve memorisation, which must be
measured (section 13). The aircraft registration is also a handle; it stays in the payload
and is ablated in S1.

---

## 9. Fixtures

Decision record 0015. Continuous integration has no raw data and no API key, but the
leakage and contamination tests must run there, on real record shapes.

**Records.** `scripts/make_fixture.py <ntsb_number>` is the only way a record fixture is
created. It:

1. reads the record from this repository's `data/raw/`;
2. **refuses** a case whose `eventDate` year is after 2019, reading the date from the
   record itself;
3. removes a declared list of personal-data fields and asserts they are gone;
4. writes `tests/fixtures/records/<ntsb_number>.json` with a header naming the fetch date
   and the fields removed.

**Why redaction is required.** Raw records carry these fields (M3):
`registeredOwner`, `ownerIndividual`, `ownerAddress`, `ownerZip`, `operatorName`,
`operatorIndividual`, `operatorDoingBusinessAs`, `operatorAddress`, `operatorZip`,
`operatorCertificateNumber`. In general aviation the owner or operator is often the pilot,
who may have died. The repository is public, and no victim name may appear in it.

About ten records are chosen for coverage: at least one each of C, L and F class; a
multi-aircraft case; a case with no METAR; a case with several events and several
findings; a duplicated-narrative case (section 2.2).

**API page.** One `GetCasesByDateRangeV2` page trimmed to two or three records, redacted
the same way, with `hasMore` and `nextMarker` kept, for the client tests.

**Evaluation ID lists.** `tests/fixtures/eval/decidability_ids.csv` and `leakage_ids.csv`:
case numbers and event dates copied from the spike's two labelling sheets by a script,
with the spike commit (`9760e42`) recorded. The full sheets are copied in S1, when scoring
uses them.

**Why the split is never read from the case number.** NTSB numbers use the federal fiscal
year, which starts on 1 October. Of 19,641 filtered closed cases, 3,796 carry a year in
their number that differs from their event year (M2). That includes 16 of the 70 labelled
cases: `WPR24LA029` occurred on 2023-11-04, so it is held-out, although its number reads
as 2024.

---

## 10. Corpus scan

`scripts/corpus_scan.py` runs `split_record()` and the guard over every case in
`cases.parquet` and prints, per split and class:

- tripwire hits per check, at minimum sentence lengths 10, 20, 40 and 80;
- the chosen minimum length (the lowest with zero hits);
- duplication counts (the M5–M7 measures, now on this repository's data);
- multi-aircraft counts;
- records where split or class could not be determined.

Its output is written to `docs/results/s0-corpus-scan.txt` (committed; counts only, no
record text) and supersedes the exploratory script's numbers. The guard's minimum sentence
length is a constant in `records/guard.py` that cites that file. Decision record 0016 is
not edited: it names the file.

---

## 11. Tests and continuous integration

**Tests**

| area | tests |
|---|---|
| splits | `split_of` on boundary dates (2019-12-31, 2020-01-01, 2023-12-31, 2024-01-01); a hypothesis property over all dates |
| path resolver | missing hops, wrong types, out-of-range indices return nothing rather than raising |
| guard | one failing test per route: key, path, value, code token; a hypothesis property that inserting any withheld text into any evidence field raises `LeakageError` |
| boundary | every record fixture → `split_record` → `Payload` → `RecordingFakeClient`; provenance and tripwire checked on what the fake received |
| mutation | `split_record` patched to copy the factual narrative into the prelim field; the boundary test must fail |
| contamination | every record fixture has event year ≤ 2019 (read from the record); no record fixture ID is in an evaluation list; every evaluation ID is held-out by its recorded event date |
| redaction | no record or API fixture contains any redacted field |
| API client | paging to the end, marker passed, backoff on 429 and 503, missing key, page saved verbatim |
| ingest | resume skips manifest months; `--refresh` refetches; manifest hashes match files |
| build | fixture pages → parquet: duplicates removed, filters exact, index columns correct, hash mismatch rejected |

**Continuous integration** (`.github/workflows/ci.yml`), on every push and pull request:

- **lint:** `pre-commit run --all-files` (every hook in section 4).
- **test:** `pytest` with coverage.
- **audit:** `pip-audit`.

Actions are pinned to commit hashes, workflow permissions are least-privilege, and uv's
cache is used. Dependabot opens updates for Python dependencies and for Actions.

**Branch protection** on `main` — required status checks, changes by pull request — is a
repository setting on Andy's account. S0 adds the steps to a runbook; Andy applies them.

---

## 12. Build order within S0

A thin slice that puts the leakage test into continuous integration first:

1. Skeleton, tooling, pre-commit and a green CI with a trivial test.
2. `fields.py`, `splits.py`, `sources.py`, `settings.py`.
3. The API client and fetch, run on two or three development months only.
4. `make_fixture.py` and the record, API and evaluation fixtures.
5. `split_record()`, the guard, `Payload`, the recording fake, and their tests, including
   the mutation test. The leakage test now runs in CI.
6. Start the full fetch, 2009-01 to the last complete month (212 month partitions
   at 30 requests per minute), and let it run while the next step is written.
7. The build, the reconciliation check and the contamination test.
8. The corpus scan; commit `docs/results/s0-corpus-scan.txt`.

---

## 13. Done means

1. `make ingest` fetches 2009-01 to the last complete month with a complete manifest, and
   an interrupted run resumes.
2. `make build` writes `cases.parquet` and `cases.meta.json`; split counts for event years
   up to 2023 reconcile with the spike's 13,560 and 4,241, with any difference explained.
3. The corpus scan reports zero tripwire hits at the recorded minimum length, on every
   split.
4. Continuous integration is green on lint, test and audit.
5. The mutation test shows the boundary test failing when `split_record()` leaks.
6. The contamination and redaction tests pass.
7. `docs/results/s0-corpus-scan.txt` is committed and the guard's minimum sentence length
   cites it.

---

## 14. Documents written with this specification

| record | decision |
|---|---|
| 0011 | Tooling: uv on hatchling, Python 3.14, the static-analysis stack |
| 0012 | Typed constants and settings replace `config.yaml` |
| 0013 | Evidence, synthesis and verdict: the factual narrative is withheld and the agent writes its own. Amends 0006 |
| 0014 | The processed file holds index columns and the raw record |
| 0015 | Fixtures are redacted real development records |
| 0016 | The layered leakage guard, and the request-side model boundary |

The roadmap (`2026-09-12-architecture-and-roadmap.md`), `README.md` and `CLAUDE.md` are
amended in the same commit so that no document describes the narrative router. The
top-level `../CLAUDE.md` is outside this repository; its amendment is proposed to Andy
separately.

---

## 15. Not in S0

| item | where | why |
|---|---|---|
| code lookup tables, scoring, harness | S1 | nothing in S0 scores |
| OpenRouter client, response types, live probe | S1 | response shape comes from a saved real response |
| grading of the generated narrative and lay explanation | S1 | same judge-reliability problem, decided together |
| headline metric for live cases | S1 | occurrence code is often public from day 1 |
| docket client and the synthesis-document filter | S2 | the docket is where synthesis can re-enter |
| SQLite store, incremental ingestion | S2.5 | the recorder is the first writer |
| agent loop, cost cap, trajectory log | S3 | nothing in S0 takes a step or spends money |

---

## 16. Risks and open questions

| item | why it matters | handling |
|---|---|---|
| **Memorisation.** The model may have read published reports for held-out cases during training. | Held-out scores could measure recall, not reasoning. | Case number and docket URL kept out of the payload; registration ablated in S1; live cases, which no training set can contain, act as the control. Measured in S1 and S3. |
| **Recent no-narrative cases.** About half of 2020–23 cases have no factual narrative; only 9 development cases lack one (M4). | It may be that recent C-class reports put their single narrative in the analysis field only. This changes how the corpus is described, not the method: both fields are withheld. | Answerable by counting class and report flavour on held-out cases, without reading any withheld text. S1's decision. |
| **Held-out scores overstate or understate live.** | Complete dockets but no preliminary narrative (section 2.3). | Stated on the Methods page before results; time-sliced evaluation once the recorder has data. |
| **Tripwire false positives on new data.** | A fail-closed check that fires wrongly stops a run. | The threshold is measured on the full corpus; a hit reports the case and field, and the fix is recorded, not silenced. |
| **Fetch takes longer than estimated or is throttled.** | Blocks the build. | Resumable partitions; the build and scan are written while it runs. |

---

## Glossary

**Ablation.** Re-running an evaluation with one input removed, to measure what it was
contributing.

**Allow-list.** A list of what is permitted. Anything not on it is excluded by default.

**Boundary test.** A test that inspects what actually reaches the model, rather than what
the code intended to send.

**Build backend.** The tool that turns a Python project into an installable package.
Here, hatchling.

**Case number (NTSB number).** For example `CEN09CA125`: regional office (`CEN`),
fiscal year (`09`), investigation class (`C`), a second letter (`A` on the aviation cases
seen so far), sequence (`125`).

**Continuous integration (CI).** Checks that run automatically on every push.

**Defining event.** The NTSB's coded choice of the single event that defines the accident.
The occurrence code and the phase of flight are read from it.

**Development split.** Cases with event year 2019 or earlier. Used freely to build.

**Docket.** The NTSB's public folder of supporting documents for one investigation.

**Evidence.** Observations recorded during an investigation. The only role sent to the
model.

**Factual narrative.** The investigator's written account of what was found. Here it is
synthesis, not evidence.

**Fail closed.** On a failed check, stop, rather than continue without the check.

**Fiscal year (federal).** 1 October to 30 September. NTSB case numbers use it.

**Fixture.** Saved data that a test runs against.

**Held-out split.** Cases with event years 2020 to 2023. Touched rarely; reported numbers
come from here.

**Investigation class.** The NTSB's classification of how extensive an investigation is,
read from the case number. C-class cases appear to be the most limited: none of the
6,126 development cases was fatal (M4), and the spike found their dockets small.

**Leakage (mechanical).** Withheld content reaching the model because of a software fault.

**Leakage (semantic).** Evidence text that makes the verdict obvious. A property of the
data, measured rather than blocked.

**Lockfile.** A file recording the exact version of every dependency, so every
installation is identical.

**Manifest.** A record of what was fetched, when, and the hash of each file.

**Mutation test.** A test that deliberately breaks the code and checks that another test
notices.

**Open split.** Cases with event year 2024 or later. For the live board only.

**Payload.** The exact text sent to the model.

**Preliminary narrative.** A short early account the NTSB publishes during an
investigation. The API deletes it at closure.

**Protocol (Python).** A description of the methods a class must have, without saying
which class.

**Provenance check.** A check that each value came from the place it was declared to come
from.

**Redaction.** Removing fields from a record before it is saved.

**Report flavour.** The NTSB's report type: `Basic (no factual)`, `Standard report` or
`Detailed (ICAO headers)`.

**Synthesis.** The investigator's write-up: factual narrative and analysis. Withheld from
the model; used as the reference for the agent's own narrative.

**Tripwire.** A runtime check that stops everything if withheld text or codes are found
in the payload.

**Verdict.** The determination: probable cause, occurrence codes and finding codes.
Withheld; used for scoring.
