# S2 — The docket tool: design

*Drafted 2026-09-17 and 2026-09-18 from a design session with Andy, after the release of S1
(`v0.2.0`, pull request #5). Status: Approved (2026-09-18, Andy); Implemented (2026-09-21, pull request #8).
This is the specification for build stage S2 in
`docs/specs/2026-09-12-architecture-and-roadmap.md` §11, restated here as decisions 0037 to
0040 amend it. It records what S2 builds, why, the decisions S2 was asked to take, and the
condition for moving on. The implementation plan is written from it separately.*

**How to read this.** Each section says what is built, then why, with an example where one
helps. Terms in **bold** on first use are in the glossary at the end. Numbers labelled
**M1–M5** come from `scripts/exploratory/s2_design_measurements.py`; its output is saved
beside this document as `2026-09-18-s2-design-measurements.txt`. That script reads no data:
it is arithmetic over the model prices in `sources.py` and the docket sizes the spike
published (`../ntsb-spike/scripts/docket_shape_probe.py`, report §10). Numbers from the
spike or from S1 cite their script. Nothing here is a result: S2 produces the results.

Decision records written with this specification: 0041 to 0045 (section 16).

---

## 1. What S2 is for

S1 measured the case for reading the docket. One model call with every structured fact in
the record scores 8.0 points [4.8, 11.3] above the same call with day-one facts only, on the
same 399 held-out cases (`docs/results/s1-bars.txt`). So the investigators' findings carry
information the model uses. The docket is where the rest of what investigators gathered
sits, and no stage has read it yet.

S2 builds the tool that reads it, and nothing that decides what to read. Three things come
out of it.

1. **A docket module.** Given a case, it fetches the docket's listing page, downloads each
   document, extracts the text of every page it can read, and returns the text with a
   **manifest** of what it could and could not read and why. It works offline from saved
   real responses in tests.
2. **Documents as evidence, behind the one split.** Docket text reaches the model only by
   passing through `split_record` and the five guard layers (0016), with the tripwire's
   sentence threshold re-measured on real document prose (0039). Every document is
   evidence, whatever its author (0038), rendered under a provenance header.
3. **Arm B with the docket, measured.** The pipeline that reads every document a fixed,
   published filter admits, then answers once (0022). It runs on `dev-400` to choose the
   filter, and once on `heldout-400` to set the bar the loop in S3 must beat.

An analogy. S1 wrote the mark scheme and recorded the score of a student who read only the
front page of the case file. S2 hands the student the whole file, in a fixed order, and
records that score. S3 will let the student choose which pages to read, and must beat the
student who read them all.

**What S2 is not.** It does not take a step or choose a document (S3), poll open cases
(S2.5), or apply OCR to scanned pages (phase 2). It is the first stage to put free text a
person wrote into a model prompt, which is why the boundary work of §3 comes first.

---

---

## 1a. Amendments after decision 0045 (appended 2026-09-20; nothing below is rewritten)

This specification was written before decisions 0046-0056 and describes, in several places, a
design the code no longer has. The original text stays, per the append-only rule; this section
is the map from what is written to what is true. Each item names the record that holds the
measurement.

**The document header (§2 item 2, §6.3).** The provenance header is gone. It claimed whose
account a document was, inferred from its title; Andy's 60-title hand-check measured that claim
at 58-72% accurate, with two categories at zero of five (0051). The category label that replaced
it went too, because it was then the last place a guess reached the model and 604 of 3,790
documents fall to `other` (0055). §6.3's example header is not what the code renders. The header
is now the listing index, the page count, and how many pages held readable text:

```
Docket item 3, 11 pages, of which 4 held readable text.
```

**The type classifier (§7.2).** It no longer matches "on the title and the page's type column".
Matching the two joined put 225 documents — witness statements, toxicology reports, examination
summaries — into `photos` because the NTSB's `Text/Image` type contains the word *image*, and 138
of them held readable text (`docs/results/s2-doctype.txt`). It matches the title alone.

**Arm B's filter (§2 item 7, §7.3, §8.3, §8.5, §10).** There is no type filter. Arm B attaches
every document extraction found text in (0052): dropping the photograph exclusion attaches 270
more documents in 27% of cases, displaces none, and moves the median attached tokens by six. The
`unfiltered` variant is removed as a synonym, and the `no-submissions` variant with it — the
`party_submission` category finds only documents the NTSB itself labels, so the comparison 0038
item 4 asks for would measure the wrong population (0054). §8.5's "three runs" is one run.

**The deny-list (§7.1, §8.3).** Removed. The measurement 0039 required was run
(`docs/results/s2-threshold.txt`): 56 tripwire hits stopping 17 of 401 cases, spread across 8 of
the 12 categories, with 33 of the 56 in `other` — the label meaning the classifier could not tell.
A category deny-list cannot be filled from that without denying two thirds of the taxonomy (0056).
`denied: write-up` is no longer a manifest status (§5.3).

**The tripwire on documents (§6.5).** Still runs on every attached document, with one measured
exemption: sentences taken from the *factual narrative* are not compared inside docket documents,
because the investigator writes that narrative from the docket, so a shared sentence is the
narrative quoting the evidence (0050). Refusals fell from 156 of 401 development cases to 17. The
analysis narrative, the probable cause and the codes are still compared, and those 17 cases still
fail closed.

**The threshold (§8.2).** `MIN_SENTENCE_CHARS` stays 20. §8.2's rule — the lowest length with zero
hits — was tried and rejected: the sweep reaches zero only at 400 characters, which would disable
the sentence check for every source and role (0050).

**Readability (§5.2).** A page with 50 **or more** characters is readable; under 50 is a scan page.
Both halves used to compare strictly against 50 in opposite directions, so a document averaging
exactly 50 was attached with zero readable pages (0053).

**The cost table (§15).** It prices a run that will not happen, so the S2 estimate is about $1.31
high. Left as the estimate that was made.

**What did not change.** Every document is evidence whatever its author (0038 item 1); the split
and the five guard layers; `attach_docket` as the only way document text enters a record; the
ordering rule — each document's own measured size, ascending (0048); the name and amateur-built
replacements (0044, 0046); and the fixture rules (0037, 0049).

## 2. The stage in one page

The work has a fixed order, set by what depends on what.

1. **Preliminaries (§3).** The batch-path boundary test, tool turns carrying a `Payload`,
   the budget reservation, the cap counting output, and the safe re-judge. No document
   reaches a model until these are green.
2. **The docket module (§4, §5).** Client, parser, extractor, classifier, cache, fixtures.
3. **One fetch of `dev-400` (§8.1).** Listings and documents cached under `data/`. One fetch
   serves every development measurement and the fixture pool (0039 item 4).
4. **The threshold (§8.2)**, re-measured on docket text before anything else is scored.
5. **The filter measurement (§8.3)**: tripwire hits by title category, the deny-list filled
   only by hits, and Andy's 60-title hand-check of the type classifier.
6. **Fixtures (§4.4)**, drawn by criteria from the fetched pool; Andy reads each committed
   document.
7. **Arm B on `dev-400` (§8.5)**: filtered, unfiltered, and without party submissions. The
   filter and the rank order are chosen by the rule in §10 and published.
8. **Arm B on `heldout-400`, once (§8.6)**, recorded in the ledger. The bar for S3.
9. **The open-split shape run (§8.4)**, numbers only (0040). Independent of the rest and run
   whenever the module is stable.
10. **Close-out** under 0017.

Steps 3 to 8 are the paid and networked part. Steps 1, 2 and 9 need no model call.

---

## 3. Preliminaries: closing the S1 gaps before any document reaches a model

S1's As-built record lists defects it knowingly left. Four of them matter more once whole
documents are in prompts, and one gap found in this design session belongs with them.

### 3.1 The batch-path boundary test

`tests/test_boundary.py` proves withheld text never reaches a system prompt, but it forces
`sync=True` and records calls through `RecordingFakeClient.complete`. The batch path, which
is the default, builds `BatchRequest` objects and hands them to the `BatchRunner` protocol;
the fake never sees them. S2 adds a recording fake batch runner, in the pattern of the
`FakeBatchClient` in `tests/test_runner.py`, that keeps every request's system text, user
payload and history. The boundary test runs the same fixtures through both paths and
asserts the same property on both. The mutation test of 0016 is extended so the batch
assertion is also shown to be able to fail.

### 3.2 Tool turns carry a `Payload`

A first message's content must be a `Payload`, a class that can only be built from checked
`Evidence`. A tool turn's content is a plain string today (`Turn.content`). Nothing stops a
future tool from putting unchecked text into a tool turn. `Turn` gains a typed form for tool
results whose content is a `Payload`, and the boundary test asserts, on both paths, that
every tool turn's content is one. This is what makes the transport question moot: whether a
tool is called in-process or through any wrapper, the only thing that can go back to the
model is a `Payload`.

### 3.3 The budget reservation (0045)

The month's spend is read once at start and a run writes its cost only at the end, so runs
launched together each see zero (S1 As-built, "Known defects"). The fix: a run takes a lock
on the runs directory, sums finished costs for the month plus every other run's open
**reservation**, refuses if its projection would take the total over budget, else writes its
projection as a reservation and releases the lock. At the end, or on abort, the reservation
is replaced by the actual cost. A run that dies leaves its reservation standing, so the
guard errs towards refusing; `ntsb-eval release RUN_ID` clears one by hand and `report`
lists open reservations. The test starts two runs in sequence against one directory and
shows the second sees the first's reservation.

### 3.4 The cap counts output

`over_cap` multiplies a character estimate of the prompt by the input price only. It becomes
prompt estimate at the input price plus the model's maximum output at the output price. At
the default model's batch price this reserves $0.0012 of the 5-cent cap and leaves room for
about 488,000 prompt tokens (M1); at Sonnet 5's standard price it reserves $0.02 and leaves
room for 15,000. So with the default model the cap does not bind on any spike-sized docket
(M3); it exists for a dearer model, and the arithmetic must be right before that day.

### 3.5 The re-judge writes to a temporary file

`_cmd_judge` opens `judge.jsonl` for writing on its first row, so a re-judge that dies after
one row has destroyed the previous paid pass. It writes to `judge.jsonl.partial` and renames
over the old file only when the pass completes. A crash leaves the paid pass intact and the
partial file beside it.

---

## 4. The docket client

### 4.1 Where the docket is

The docket is not in the NTSB Enterprise API. `../ntsb-spike/public.yaml` has no docket
endpoint. The docket is a web page at `https://data.ntsb.gov/Docket?ProjectID=<mkey>`,
where `mkey` is the case record's internal key, already stored as `docket_url` in
`cases.parquet`. The page holds a table: one row per document with its index, title, page
count, photo count, document type, and a link to the file. The spike's probe read that
table with a regular expression and downloaded files from the link. So the client is a
**scraper**, and rule 2 (never guess API details) is met by the saved real page that 0037
requires as a fixture, not by a specification. A change in the page's structure fails the
parser test loudly, which is the failure we want.

### 4.2 Fetching

- One request every two seconds, a stated user agent naming the project, and retry with
  backoff on transport errors and 5xx, as `openrouter.py` does. At that rate the `dev-400`
  fetch is 2,000 requests and about an hour at the spike's median of 4 documents per
  docket, or 2.7 hours at the 90th percentile (M5).
- Every fetch is cached under `data/docket/<mkey>/`: the listing page as received, each
  file as received, and a `fetch.json` with the time and the hash of each. Nothing is
  fetched twice. Nothing under `data/` is committed.
- The cache is keyed by case, and a case is looked up by `mkey` from `cases.parquet`, so
  the client never needs a case number to fetch, and the 0040 script can fetch and discard
  without a cache (§8.4).

### 4.3 The listing

The parser returns a **listing**: a tuple of entries, each with index, title, page count,
photo count, document type as the page gives it, file extension from the link, and the
link. It cross-checks the page's "Docket Items" count against the rows parsed and raises
if they differ. The listing is cheap and exposed on its own, so in S3 reading a document is
a choice the loop makes after seeing the titles (roadmap §11).

### 4.4 Fixtures (0037)

Every fixture comes from a `dev-400` case, drawn by seed from the fetched pool by
`scripts/make_docket_fixture.py`, which refuses any case outside the development split as
`make_fixture.py` does. The script takes the first docket meeting each criterion and records
which criterion each fixture satisfies:

| criterion | what it exercises | committed as |
|---|---|---|
| a listing with a photo-only entry and a non-PDF file | parser; "unavailable" in the manifest | the listing page |
| a docket with a scanned document | classifier | outcome only |
| a docket with a partial document | classifier, page markers | outcome only |
| a docket over the cap at Sonnet 5's standard price | the drop rule of §9.2 | outcome only |
| two or three NTSB-authored born-digital documents of different types | extraction, header, page markers, tripwire on prose | text, after redaction and Andy's read |
| a party submission | the header's author role | outcome only |

"Outcome only" means the classification and the extraction counts, for example "scan, 11
pages, 0 readable pages", never text. About five listings and about three documents of text.
`scripts/check_fixtures_redacted.py` gains a check that a docket fixture holding text carries
a `reviewed_by` field, and refuses any without one.

---

## 5. Extraction and classification

### 5.1 Text per page

The extractor uses `pypdf`, the library the spike used, added to `pyproject.toml`. It
returns the text of each page separately and keeps the boundary: the stored text has a
marker line at the start of each page, `[page 4 of 22]`. That costs nothing now and lets a
later tool read "document 3, pages 4 to 7" with a truthful header, without any sectioning
heuristic. Section reading is an S3 candidate, not a deliverable (§17).

### 5.2 Readable, scanned, partial

A page with under 50 characters of text is a **scanned page**. A document whose pages
average over 300 characters is **born-digital**; under 50, a **scan**; between, **partial**.
These are the spike's thresholds from session A9, carried over so the eras stay comparable
(0040 item 2). The `dev-400` fetch produces the characters-per-page count of every page, and
§8.1 publishes that distribution. If it is two clear humps with the thresholds in the gap,
the numbers stand on data; if not, a decision record moves them by a rule the results file
states.

### 5.3 The manifest

For each document the module returns: the listing entry, the classification, the page
count, the number of readable pages, the estimated tokens (characters divided by four, the
spike's estimate), and a status from a fixed set: `read`, `unreadable: scan`,
`unreadable: not a pdf`, `unreadable: photos`, `skipped: photo-only`, `fetch failed`. A
scanned document is reported as unavailable, never dropped silently (roadmap §11). The
manifest is what the step record's `not_available` field is filled from.

---

## 6. Documents as evidence

### 6.1 The case context and the attach step (0041)

The guard's provenance layer checks that every value the model sees equals its declared
path in the record it was split from. Docket text has no such path in the API record. So
the harness builds one **case context**: the raw record plus a `docket` subtree holding the
listing and each attached document's header, manifest entry and text. One pure function,
`attach_docket(raw, docket, documents=...)`, builds it; it is the only place document text
enters a record, and the only place it is changed (§6.4). `split_record` then reads new
evidence roles from that subtree, and layers 0 to 4 apply unchanged: the allow-list names
the docket paths, the keys are fixed, no docket path is under a withheld subtree, every value
is checked against the context, and the tripwire runs over every document.

Ruled out: a second input to the splitter, which would need a second provenance rule; and a
tool rendering its own payload, which 0023 already forbids.

### 6.2 Two roles, selection when the context is built (0042)

`EvidenceRole` gains `DOCKET_LISTING` (the table of titles, types and page counts) and
`DOCKET_DOCUMENTS` (a list of attached documents, each with its header and text). The set
of documents to attach is an argument to the attach step, so:

- arm A builds the context with no documents and excludes both roles;
- arm B builds it with the documents its filter admits, in rank order, up to the cap (§9);
- a loop step in S3, "read document 3", builds it with document 3 only;
- the masked condition builds it with the documents that had appeared by day N, once the
  recorder (S2.5) has arrival numbers; until then the docket is absent in the masked
  condition, as the agency design §6.2 says.

The chosen set is written into the step record's `arguments`, so every run is reproducible
from its records. `--exclude docket_documents` works as every other exclusion does.

### 6.3 The provenance header (0038)

**Amended — this section describes a header the code no longer renders. See §1a and decisions 0051 and 0055.**

Each attached document is rendered as a header line and then its text with page markers.
The header is built from the listing only: title, document type, page count, and the
author's role where the title or type gives it. Example:

```
Party submission, 22 pages, submitted by the engine manufacturer.
[page 1 of 22]
...
```

The agent is told what kind of document it is reading. It is never told a document is
wrong. The type comes from the classifier of §7.2, whose error rate is published beside the
header (0039 item 3).

### 6.4 Names and the amateur-built rule (0044)

The tripwire looks for withheld text, not names. No scripted redaction of free text is
reliable enough to trust (0037), so a pilot's own form or a witness statement reaches the
model with the names in it. What is protected is everything committed or published: fixtures
hold only NTSB-authored born-digital documents after Andy's read, the live board will show
the agent's steps and never document text, and the step record stores a fingerprint of the
payload, not the payload.

One rule does apply to document text, in the attach step. For an amateur-built aircraft the
record's make and model are usually the builder's name, and 0020 replaces them in evidence
with the label `Amateur-built`. The attach step replaces every case-insensitive occurrence
of those recorded strings in listing titles and document text with the same label, before
the split runs. The strings are known, so this is mechanical and testable. A variant
spelling or a bare surname passes through, so the published count of replacements is a
floor and the results file says so.

The attach step is also the slot for any later name handling: a pure function on the text
before attachment, parallel to `redact_record`. §8.1 measures how often the record's own
owner or operator name appears in documents, as counts, so that decision is taken on a
number if it is taken.

### 6.5 The tripwire on documents (0039)

**Amended — one measured exemption applies inside docket documents. See §1a and decision 0050.**

Every attached document goes through the tripwire against its case's withheld narratives,
probable cause and codes, at the threshold §8.2 re-measures. A hit fails the case closed
with a `LeakageError`, as any other hit does. The number of development cases the tripwire
stops, by document type, is published (0038 item 3). The sentence splitter's handling of
abbreviations, flagged in 0019, is re-checked on the §8.2 output: if abbreviation breaks
produce hits at the chosen threshold, the splitter is fixed and the scan re-run, and the
results file shows both runs.

---

## 7. The filter

After 0038, every document is evidence and the filter has two jobs (0039).

### 7.1 Job 1: catch a case-level write-up

**Amended — the deny-list was measured unfillable and removed. See §1a and decision 0056.**

A closed docket can hold an NTSB-written factual report, the answer's first half. The spike
found no such title in 160 development listings; rare is not never. The **deny-list** of
titles starts empty and is filled only by tripwire hits on `dev-400` (§8.3). A title on the
list is not attached and the manifest says `denied: write-up`. If the sample produces no
hits, the published result says so and the tripwire remains the only defence, which it is
in any case.

### 7.2 Job 2: the type classifier

**Amended — the classifier matches the title alone, and no longer serves the header, the rank order or a filter. See §1a and decisions 0052, 0055, 0056.**

A document type for the header (§6.3), the rank order (§9.1) and the filter. It starts from
the spike's title categories (`docket_shape_probe.py`, `CATEGORIES`: pilot form, photos,
weather, maintenance records, medical and toxicology, specialist factual, examination and
site, conversation and statement, ATC and radar data, manuals and reference, other) plus
`party_submission`, matched by regular expression on the title and the page's type column,
first match wins. It is scored by Andy's hand-check of 60 titles drawn by seed from the
`dev-400` listings; titles hold no personal data, so the sheet is committed under
`tests/fixtures/docket/title_handcheck.csv` and the error rate is published.

### 7.3 Arm B's filter

**Amended — there is no type filter; arm B attaches every document extraction found text in. See §1a and decision 0052.**

The set of types arm B attaches, and their rank order, chosen on `dev-400` by the rule in
§10 and published in `docs/results/s2-filter.txt` before the held-out run. The unfiltered
version is reported on development cases only (0022).

---

## 8. Measurements

Every number below is produced by a script, written to a results file under `docs/results/`,
and holds counts and quantiles only: no case numbers, no text.

### 8.1 The `dev-400` fetch and the development-era shape

`scripts/docket_scan.py` fetches every `dev-400` docket into the cache once, then computes
over the cache: documents and non-photo pages per docket; estimated tokens per docket and
per document; the share of dockets under 10,000 tokens; scanned pages and the share of
scan-only dockets; the share of pilot forms with a text layer; party-submission presence;
non-PDF share; the title-category mix; the characters-per-page distribution of §5.2; the
count of documents and cases containing the record's owner or operator name, by type
(§6.4); and the count of amateur-built replacements, by type. Fatal and non-fatal, and
overall. Written to `docs/results/s2-shape-dev.txt`. The same statistics as the spike's, so
the three eras (spike 2015–2019, `dev-400`, 0040's open split) sit side by side.

### 8.2 The threshold

`scripts/corpus_scan.py` gains a docket mode: every readable `dev-400` document through the
tripwire at candidate minimum sentence lengths, the same rule S0 used. The lowest length
with zero hits on ordinary evidence is the threshold; the hit counts at each length are
published in `docs/results/s2-threshold.txt`, with the 0019 abbreviation check. `MIN_SENTENCE_CHARS`
is set from it, and the corpus scan's header reports the threshold it used (roadmap done
means).

### 8.3 The filter measurement

At the re-measured threshold, every readable `dev-400` document through the tripwire against
its case's withheld text. A document with a withheld sentence is a **hit**. Published by
title category in `docs/results/s2-filter.txt`: hits, misses (a hit whose title is not on the
deny-list) and false denies (a listed title with no hit), plus the 60-title hand-check error
rate. The tripwire stops by document type of §6.5 come from the same pass.

### 8.4 The open-split shape (0040)

`scripts/docket_shape_open.py`: closed open-split cases, `completionStatus == "Completed"`,
event date 2024 or later, 40 fatal and 40 non-fatal by a committed seed and rule. It streams
each listing and document through the parser and extractor and keeps only the numbers of
§8.1; it writes nothing under `data/`, and a test asserts so. Written to
`docs/results/s2-shape-open.txt`, with the note that the 111 closed fatal cases are a small
population of which 40 is over a third. About half an hour of fetching at the 90th
percentile (M5).

### 8.5 Arm B on `dev-400`

**Amended — one run, not three. See §1a and decisions 0052, 0054.**

Three runs, filtered, unfiltered and without party submissions, each reported with the
count of cases where the cap bound and documents dropped, by fatal and non-fatal. The
paired differences choose the filter (§10). At the default price a case with a
10,000-token docket costs about $0.0023 (M4), so each run is under a dollar.

### 8.6 Arm B on `heldout-400`, once

The filtered arm B, on the same 400 cases as S1's bars, paired against the S1 ceiling run
(`20260917T061527-c717ab5-heldout-400-ceiling`). One row in
`docs/results/heldout-ledger.md`. The held-out dockets are fetched once into the cache and
never appear under `tests/`; `tests/test_contamination.py` is extended to docket fixtures.
Written to `docs/results/s2-bars.txt` (0043).

---

## 9. Arm B in the harness

### 9.1 A new arm

`RunSpec.arm` and the CLI gain `B`. Arm B builds each case context with the listing and the
filtered documents in rank order, then makes the same two-turn call the ceiling makes. The
ceiling remains arm B without the docket. The step record for an arm B case lists the
documents attached, the documents not read and why, and the payload fingerprint.

### 9.2 When the cap binds (0043)

Documents are added whole, in the published rank order, and the run stops before the first
that would take the case over the cap as §3.4 estimates it. A document left out is written
to the step record as `not read: cap` with its estimated tokens, and the report counts cases
that hit the cap and documents dropped, by fatal and non-fatal, so a reader sees how much of
the docket the bar was measured on. Truncating a document was rejected: the model would read
half a document under a header claiming all of it.

---

## 10. Decisions S2 takes

Each is decided by a rule written here before the run, so the answer is read off, not
chosen.

| decision | rule | recorded in |
|---|---|---|
| **The thresholds of §5.2.** | Stand if the characters-per-page distribution of §8.1 has a gap containing both 50 and 300 (fewer than 5% of pages between the humps); else a decision record moves them to the gap's bounds. | As-built; a decision record if moved |
| **The tripwire threshold.** | The lowest candidate length with zero hits on ordinary `dev-400` document text (§8.2). | `docs/results/s2-threshold.txt`; `guard.py` |
| **The deny-list.** | Every title category with a hit in §8.3. Empty if none. | `docs/results/s2-filter.txt`; the filter module |
| **Party submissions in arm B.** | Kept unless the paired top-1 difference "with minus without" on cases holding one has an interval entirely below zero (0038 item 4). | `s2-filter.txt` |
| **Arm B's types and rank order.** | Types: every type the filter admits, minus any dropped by the rule above. Order: by each type's median estimated tokens per document on `dev-400`, ascending, so small documents come first and the cap drops the largest. A per-type ablation (one run per type) is not affordable at useful precision and is not attempted. Published before the held-out run. | `s2-filter.txt`; 0043 |
| **The bar for S3.** | Arm B's top-1 and finding recall on `heldout-400`, with intervals, paired against the S1 ceiling. The loop must beat arm B by a paired difference whose interval excludes zero on the same cases and model, at equal cost (0022). | `docs/results/s2-bars.txt`; the roadmap's S3 done-means |

---

## 11. Repository changes

```
src/ntsb_probable_cause/
  docket/
    __init__.py
    client.py       §4.2 fetching, the cache, polite rate
    listing.py      §4.3 the parser; the Listing model
    extract.py      §5.1 text per page with page markers
    classify.py     §5.2 readable / scan / partial; §7.2 the type classifier
    manifest.py     §5.3 the manifest and its statuses
    filter.py       §7 the deny-list and arm B's types and rank order
    attach.py       §6.1 attach_docket: the case context; §6.4 the amateur-built replacement
  fields.py         DOCKET_LISTING and DOCKET_DOCUMENTS roles and their paths
  records/guard.py  MIN_SENTENCE_CHARS re-set from §8.2
  model/client.py   Turn gains the Payload-carrying tool form (§3.2)
  scoring/
    samples.py      arm B in arm_exclusions; masked condition treats the docket as absent
    runner.py       arm B; the cap with output (§3.4); the reservation (§3.3)
    records.py      documents attached and not read in StepRecord
apps/eval/__main__.py   --arm B; release RUN_ID; open reservations in report; judge.partial
scripts/
  docket_scan.py            §8.1
  docket_shape_open.py      §8.4
  make_docket_fixture.py    §4.4
  corpus_scan.py            docket mode (§8.2)
  check_fixtures_redacted.py  reviewed_by on docket text fixtures
  exploratory/s2_design_measurements.py
tests/fixtures/docket/      listings, outcome-only manifests, reviewed documents, title_handcheck.csv
docs/results/s2-shape-dev.txt, s2-shape-open.txt, s2-threshold.txt, s2-filter.txt, s2-bars.txt
```

- `ntsb_probable_cause.docket` is added to the import-linter contract "Only the splitter
  constructs synthesis and verdict" and to `tests/test_import_boundaries.py`; it can never
  import synthesis, verdict or the split. `attach.py` reads the raw record and the docket
  output only.
- `pyproject.toml` gains `pypdf`. `pytest-socket` already refuses the network in tests.
- `Settings` gains `docket_dir` (default `data/docket`) and `docket_seconds_per_request`.
- `sources.py` records the docket page's URL pattern and the user agent, with the saved
  page as their source.
- `Makefile` gains `docket-scan`, `docket-shape-open`, `armb` (the three `dev-400` runs and
  the reports) and `s2-bars` (the held-out run and `s2-bars.txt`).

---

## 12. Tests and continuous integration

- **Boundary, both paths (§3.1, §3.2)**, with the mutation test extended.
- **Parser fixtures**: the saved listing pages of §4.4 parse to the expected entries, the
  items-count cross-check raises on a doctored page, and a photo-only or non-PDF entry gets
  its manifest status.
- **Extractor and classifier**: the reviewed documents extract with page markers; the
  outcome-only fixtures reproduce their recorded classification from recorded per-page
  counts.
- **Attach and split**: a document in the context renders under its header; a document
  holding a withheld sentence fails the split closed; a document not in the selection is
  absent from the payload; the amateur-built replacement runs on titles and text.
- **The synthesis-document test** (roadmap §9): a docket fixture carrying a doctored NTSB
  write-up title on the deny-list never reaches the payload, and a document holding
  withheld text is stopped by the tripwire whatever its title.
- **Cap and drop rule**: the over-cap fixture drops the right documents in rank order and
  records them.
- **Reservation**: two runs in sequence against one directory; the dead-reservation release.
- **Re-judge**: a pass that fails mid-way leaves the old file intact.
- **Contamination**: no docket fixture from a held-out or open case, by event date; the
  `docket_shape_open.py` test asserts nothing is written under `data/`.
- **Redaction check**: docket text fixtures carry `reviewed_by`.

---

## 13. Build order within S2

1. §3 preliminaries, each with its test, merged to the branch before any docket code.
2. `docket/listing.py`, `extract.py`, `classify.py`, `manifest.py` from a first saved
   page and a first reviewed document; `client.py` with the cache.
3. The `dev-400` fetch (§8.1) and the shape file.
4. `corpus_scan.py` docket mode and the threshold (§8.2).
5. `attach.py`, the roles in `fields.py`, and the boundary tests on documents.
6. The filter measurement, the hand-check sheet, and the fixtures (§8.3, §4.4).
7. Arm B in the runner and the three `dev-400` runs; the filter published.
8. The held-out run and `s2-bars.txt`.
9. `docket_shape_open.py` and its results file, any time after step 2.
10. Close-out.

---

## 14. Done means

1. Given a case identifier, `ntsb_probable_cause.docket` returns extracted text with page
   markers and a manifest of what it could and could not read; the tests run without
   network access on saved real pages and reviewed documents (roadmap done means).
2. The boundary test covers the batch path and tool turns, and its mutation test fails when
   the assertion is removed.
3. The budget reservation, the cap with output, and the safe re-judge are in code with tests.
4. `docs/results/s2-threshold.txt` records the re-measured threshold with its curve, and the
   corpus scan reports the threshold it used.
5. `docs/results/s2-filter.txt` records hits, misses and false denies by category, the
   hand-check error rate, the submission difference, and the published types and rank order.
6. `docs/results/s2-shape-dev.txt` and `s2-shape-open.txt` hold the shape statistics of the
   two eras, and the open-split script wrote nothing under `data/`.
7. `docs/results/s2-bars.txt` holds arm B on `heldout-400` paired against the S1 ceiling,
   with the cap-bound counts, and the ledger has exactly one new row.
8. Every committed docket text fixture carries `reviewed_by`, and no docket fixture is from
   outside the development split.
9. No run exceeded its budget flag, and the total S2 spend is stated in the As-built record.
10. Continuous integration is green; the documentation check passes; this specification is
    closed out under 0017.

---

## 15. Cost of S2

In US dollars (0030). At the default model's batch price, a case whose whole docket is
10,000 tokens costs about $0.0023 with the S1 prompt (M4); nine in ten development dockets
are under that size (spike §10). Sonnet 5 at its standard price would be about fifteen
times dearer per case (M2) and is not used in S2.

| runs | cases | estimate (upper bound) |
|---|---|---|
| `dev-400` arm B: filtered, unfiltered, without submissions | 1,200 | about $2.75 |
| `dev-400` re-runs while the header and rank order settle | 800 | about $1.80 |
| `heldout-400` arm B, once | 400 | about $0.90 |
| **total** | 2,400 | **about $5.45** (M4) |

S1 spent $7.17 of the month's $25. S2 fits in the remainder with room. Fetching costs no
money and about one to three hours of polite requests per 400 dockets (M5). The As-built
record states the actual spend.

---

## 16. Documents written with this specification

| record | decision |
|---|---|
| 0041 | Docket text enters through a case context built by one attach step, before the split |
| 0042 | Two docket evidence roles; the documents attached are chosen when the context is built |
| 0043 | Arm B adds whole documents in a published rank order and stops at the cap; omissions are recorded and counted |
| 0044 | The amateur-built replacement applies to document text, in the attach step, counted as a floor |
| 0045 | The monthly budget is a reservation taken under a lock at run start and settled at the end |

The roadmap's S2 entry gains a line pointing here; its original text stays, marked amended
(0037 item 5).

---

## 17. Not in S2

| item | where | why |
|---|---|---|
| the loop, tool calling in action, arm C | S3 | nothing in S2 chooses a document |
| reading a document by page range or section | S3 candidate | needs the trail to show whole-document reads are wasted; page markers make it cheap then |
| OCR for scanned pages | phase 2 | the manifest reports them unavailable; counts say how many |
| the recorder, arrival times, the masked condition on real data | S2.5 | the docket is absent in the masked condition until then |
| an MCP or other out-of-process wrapper for the tools | none planned | the harness and the live job call the functions in-process; §3.2 makes any wrapper safe by type |
| name handling in document text beyond 0020 | reconsidered on §8.1's count | the attach step is the slot |
| the model axis | after S3 | needs arms B and C |

---

## 18. Risks and open questions

- **The listing page changes shape.** The parser fails loudly on the saved page's test, and
  the fetch stops. Accepted: the alternative is silent wrong answers (roadmap §15).
- **The tripwire fires on ordinary prose at every length.** Then no threshold has zero hits
  and §8.2 has to publish the curve and choose by a stated rule, as 0019 did for weather.
  The results file would say so.
- **Documents overwhelm the start facts.** A 20,000-token submission beside a dozen fields.
  Arm B measures it; the "without submissions" run is the check (0038 item 4).
- **Held-out dockets in the cache.** Under `data/`, outside git, but on disk. The
  contamination test covers `tests/`; a developer's cache is a matter of rule 5.
- **The characters-per-page distribution has no gap.** Then the thresholds are a judgement
  and §10 says so in a decision record rather than pretending otherwise.

---

## Glossary

- **Docket**: the NTSB's public folder of supporting documents for one case, served as a web
  page listing PDFs.
- **Listing**: the table on that page: one row per document with its title, type, page count
  and link.
- **Scraper**: a client that reads a web page meant for people rather than a documented API.
- **Manifest**: the per-case list of what the docket tool read and could not read, with a
  status for each document.
- **Born-digital / scan / partial**: a PDF with a real text layer, one with none, and one
  with pages of each.
- **Page marker**: a line in the stored text saying where each PDF page starts.
- **Case context**: the raw API record with the docket listing and attached documents added,
  the single input the split reads.
- **Attach step**: the one function that builds the case context, and the only place
  document text is changed before the split.
- **Evidence role**: a named group of fields that can be excluded as a unit; the docket adds
  two.
- **Provenance header**: the line above each document giving its title, type, page count and
  author role.
- **Tripwire**: the guard layer that fails a case if any withheld sentence or code appears in
  the evidence.
- **Hit / miss / false deny**: a document containing a withheld sentence; a hit whose title
  is not on the deny-list; a listed title with no hit.
- **Deny-list**: titles the filter never attaches, filled only by hits.
- **Rank order**: the fixed sequence in which arm B adds document types.
- **Cap**: the most one case may cost, estimated before the call from prompt and output.
- **Reservation**: a run's projected cost, counted against the monthly budget from its start
  until it settles.
- **Arm A / B / C**: start facts only; every admitted document then one answer; the loop.
- **Masked condition**: an evaluation where the model sees only what a live case would have
  at day N.
- **Paired difference**: two arms compared on the same cases, with an interval.
- **Fingerprint**: a hash of the exact text sent to the model, stored instead of the text.
- **Floor**: a count that can only undercount.

---

## As built

*Closed 2026-09-21 in pull request #8.*

### Delivered

- **The docket package**, `src/ntsb_probable_cause/docket/`: `client.py` (a cached, rate-limited
  client, one request every two seconds to `data.ntsb.gov`), `listing.py` (the docket page
  parser), `extract.py` (`pypdf` text extraction with page markers), `classify.py` (readable /
  scan / partial, and a title-based document category), `manifest.py` (`read_docket`: fetch,
  extract, and record what could and could not be read), `filter.py` (arm B's document
  selection), `attach.py` (the attach step that builds a case context).
- **Documents as evidence**: `attach_docket` copies the raw record and adds a `docket` subtree
  *before* `split_record` runs, under two new roles, `DOCKET_LISTING` and `DOCKET_DOCUMENTS`
  ([0041](../decisions/0041-docket-text-enters-through-a-case-context.md),
  [0042](../decisions/0042-two-docket-roles-selection-when-the-context-is-built.md)). There is
  still exactly one payload assembler and one split.
- **Arm B in the harness**: `ntsb-eval run --arm B`, which attaches every document extraction
  found text in, ordered by each document's own measured size, and stops at the per-case cap.
- **Three S1 gaps closed** before any document reached a model: the boundary test extended to the
  batch path and tool turns, the monthly budget as a reservation taken under `fcntl.flock`
  ([0045](../decisions/0045-monthly-budget-is-a-reservation-under-a-lock.md)), and a cap that
  counts output tokens across both answering turns.
- **The measurements**, all under `docs/results/`, all written by a script: `s2-shape-dev.txt`,
  `s2-shape-open.txt`, `s2-threshold.txt`, `s2-doctype.txt`, `s2-docket-leak.txt`,
  `s2-handcheck.txt`, `s2-filter-compare.txt`, `s2-name-coverage.txt`, `s2-armB-dev.txt`,
  `s2-bars.txt`, and one new row in `heldout-ledger.md`.

**The result, on `heldout-400` (358 scored of 400), at commit `3bc3a51`:**

| | top-1 | top-3 | finding recall@10 |
|---|---|---|---|
| honest baseline, no model | 17.7% [16.6, 18.9] | 35.7% [34.2, 37.1] | 23.2% |
| one-shot ceiling (no docket) | 10.8% [8.1, 14.2] | 20.3% [16.6, 24.5] | — |
| **arm B, every readable document** | **22.3% [18.3, 26.9]** | **37.2% [32.3, 42.3]** | **9.1% [6.8, 11.6]** |

Paired on the 357 cases both runs scored: occurrence top-1 **+11.2 points [+6.2, +16.2]**, top-3
**+16.0 [+10.6, +21.0]**, finding recall@10 **+5.9 [+3.6, +8.3]**.

**This is the first result in the project to clear the honest baseline on held-out data.** The
bar S1 fixed was the baseline's 17.7%, not the ceiling's 10.8%, and arm B's interval begins at
18.3%. Development ran 23.7%, so held-out lost 1.4 points — inside the noise, and no sign that
anything was tuned to the development split.

**On finding codes arm B is well below the same baseline: 9.1% against 23.2%.** Reading the
docket helps (+5.9 points over the ceiling) and is still not close. Occurrence codes say *what*
happened; finding codes say *why*. On *why*, this agent is not yet useful, and the figure is
published as measured.

**Total S2 spend: $4.13**, summing `cost_usd` over every run record started on or after
2026-09-18 — the same field the budget guard's `month_spent` reads, so the published figure
cannot disagree with what was enforced. Three runs: a 2-case smoke run ($0.01), arm B on
`dev-400` ($2.12, 401 cases) and arm B on `heldout-400` ($2.00, 400 cases). September 2026 stood
at $11.77 of the $25 monthly budget at close-out. Measured cost per case at the batch price:
**$0.0053** on `dev-400`, **$0.0050** on `heldout-400`, against a $0.05 cap.

### Done means, with evidence

1. **Extracted text and a manifest, tested without network access** — met —
   `docket/manifest.py:read_docket` returns page-marked text
   (`extract.py:PAGE_MARKER`) and a per-document status. `pytest-socket` refuses sockets for
   the whole suite; the tests run against saved real listing pages and reviewed documents under
   `tests/fixtures/docket/`.
2. **The boundary test covers the batch path and tool turns; its mutation test fails when the
   assertion is removed** — met — `tests/test_boundary.py`:
   `::test_batch_runner_never_sends_withheld_text_in_any_request`,
   `::test_batch_boundary_assertion_reads_tool_turn_payloads`,
   `::test_boundary_holds_on_a_case_context_with_documents`,
   `::test_synthesis_document_never_reaches_the_payload`; the mutation tests are
   `::test_boundary_test_fails_when_the_splitter_leaks`,
   `::test_boundary_test_fails_when_a_value_comes_from_the_wrong_place`,
   `::test_boundary_fails_when_only_the_tripwire_can_catch_a_leak`,
   `::test_batch_boundary_test_fails_when_a_system_prompt_leaks`.
3. **Reservation, cap with output, safe re-judge, in code with tests** — met —
   `scoring/budget.py` (`month_spent`, `budget_lock`, `open_reservations`),
   `scoring/runner.py:estimated_cost_usd` (`ANSWERING_TURNS * call_cost`, output reserve
   included), and the re-judge's temporary-file write in `scoring/judge.py`.
4. **The threshold, with its curve, and the scan reports the threshold it used** — met —
   `docs/results/s2-threshold.txt`, four candidate minimum sentence lengths with hits by
   category and kind.
5. **NOT MET AS WRITTEN.** §14.5 asked for one file, `docs/results/s2-filter.txt`, holding five
   things. There is no such file, and three of the five were retired by measurement rather than
   delivered:
   - *hits, misses and false denies by category* — in `docs/results/s2-threshold.txt`, which is
     the evidence [0056](../decisions/0056-the-deny-list-cannot-be-filled-from-titles.md) rests
     on;
   - *the hand-check error rate* — in `docs/results/s2-handcheck.txt`, 60 rows, every row marked;
   - *the submission difference* — **retired**
     ([0054](../decisions/0054-the-party-submission-comparison-is-retired.md)): the category
     finds documents the NTSB happened to title as submissions, not the population of party
     submissions, so the comparison was measuring the wrong thing;
   - *the published types* — **retired**
     ([0052](../decisions/0052-arm-b-attaches-every-readable-document.md)): arm B attaches every
     readable document, so there is no admitted-type list to publish;
   - *the rank order* — delivered, but as each document's own measured size
     ([0048](../decisions/0048-arm-b-ranks-by-each-documents-measured-size.md)), not a rank over
     categories.
   Recorded unmet rather than redefined to fit what was built.
6. **Both shape files exist, and the open-split script wrote nothing under `data/`** — met —
   `docs/results/s2-shape-dev.txt` (401 dockets) and `docs/results/s2-shape-open.txt` (80
   dockets, 40 per stratum). `scripts/docket_shape_open.py` constructs its client with no cache
   directory ([0040](../decisions/0040-docket-shape-remeasured-on-closed-open-split-cases.md));
   the committed file was scanned for case numbers and holds none.
7. **`s2-bars.txt` holds arm B paired against the S1 ceiling, with cap-bound counts, and the
   ledger gained exactly one row** — met — the cap bound on 5 of 400 cases, 6 documents unread,
   all in the fatal stratum; `docs/results/heldout-ledger.md` has one new row, dated 2026-09-21,
   commit `3bc3a51`, $2.00.
8. **Every committed docket text fixture carries `reviewed_by`, none from outside the
   development split** — met — enforced by `scripts/check_fixtures_redacted.py`, which exits
   clean. `ERA17LA217` carries a listing page and no documents, so it has no text fixture to
   mark.
9. **No run exceeded its budget flag; the total spend is stated** — met — $4.13, above.
10. **CI green, documentation check passes, closed out under 0017** — met — this close-out
    commit; `uv run python -m scripts.check_docs` clean.

### Departures from this specification

**Five mechanisms this specification describes were removed during the stage, each on a
measurement.** S2 was written expecting to *build* a filter. What it mostly did was measure one
and find it did not earn its place. Each removal is a numbered decision; the figures are the
reason:

- **The deny-list is gone** ([0056](../decisions/0056-the-deny-list-cannot-be-filled-from-titles.md)).
  §7.1 planned a list of document categories too likely to carry the investigators' own
  conclusions. The tripwire's hits spread across 8 of the 12 categories, and 33 of the 56 fell in
  `other` — the label meaning the classifier could not tell what the document was. A list that
  would catch them denies two thirds of the taxonomy. The hand-check found 0 of 60 documents
  carrying a case-level conclusion.
- **The photograph exclusion is gone**
  ([0052](../decisions/0052-arm-b-attaches-every-readable-document.md)). It dropped 270
  documents to save about 6 tokens each, and the hand-check showed it was wrong in both
  directions: 1 of 60 dropped that was not a photograph, 5 kept that were.
- **The provenance clause is gone**
  ([0051](../decisions/0051-the-document-header-drops-the-provenance-clause.md)). The header used
  to tell the model whose account a document was. Hand-checked against 60 documents, it agreed
  with the human mark on 32 of the 55 it made a claim about — **58%**. A clause that is wrong
  two times in five is worse than no clause.
- **The party-submission comparison is retired**
  ([0054](../decisions/0054-the-party-submission-comparison-is-retired.md)). §8.3 asked for a
  run with submissions excluded. The category identified 9 documents in 401 dockets, which is
  not the population of party submissions but the population the NTSB happened to title that
  way — the same labelling weakness the other removals rest on.
- **The category label is gone from the document header**
  ([0055](../decisions/0055-the-document-header-carries-the-listing-number.md)). 604 of 3,790
  development documents classify as `other`, so the label most often said nothing. The header now
  gives the listing number and the page counts, both of which are facts rather than guesses.

**Other departures:**

- **§5.3's `unreadable: photos` status was folded into `skipped: photo-only`.** The listing
  already says which entries are photograph sets, and a PDF of photographs with no text layer is
  a scan like any other. One status fewer to explain.
- **§6.1's case context does not store each document's manifest entry.** It holds the rendered
  header-and-text strings plus an index of what was attached. Nothing downstream needed the
  entry, and storing it would have put a second copy of the document metadata inside the payload
  builder.
- **§6.4 said the attach step was "the slot for any later name handling". It stopped being
  later.** Mid-stage the owner and operator details the record already holds were added to the
  replacement, covering addresses, postcodes and a certificate number, not only the five
  name-bearing fields
  ([0046](../decisions/0046-known-owner-and-operator-names-are-replaced-in-document-text.md)).
- **§4.3 and §7.2 describe "the page's type column" as a document type. It is not.** The real
  listing page's Type column holds the file format ("Adobe PDF file"). `document_category`
  therefore classifies on the title alone; the specification's sentence describes something the
  page does not provide.
- **§8.5's tripwire refused 38.9% of development cases before any model call.** Almost all were
  the *factual* narrative, which investigators quote verbatim from documents that are themselves
  in the docket — the guard was catching the docket reproducing its own sources, not a leak of
  the answer. Factual-narrative sentences are now skipped **in docket documents only**, every
  other source and role compared exactly as before
  ([0050](../decisions/0050-tripwire-skips-factual-narrative-sentences-in-docket-documents.md)).
  Refusals fell to 4.2%, and the 17 cases that remained on `dev-400` were predicted exactly.
- **The held-out refusal rate is more than double the development one: 40 of 400 (10.0%) against
  17 of 401 (4.2%).** Every held-out refusal was an *analysis* narrative sentence inside a docket
  document — the investigators' reasoning, not their factual account. This was not predicted and
  is an era difference worth carrying into S2.5: the more recent the case, the more often the
  published docket contains the conclusion.
- **`pypdf` gained the `[crypto]` extra, and it was a memory fix, not a feature.** Without it
  `pypdf` falls back to a pure-Python RC4 implementation on encrypted documents, which allocated
  **24.1 GB** over a 40-case fetch against **13.6 GB** with the extra, measured with `memray`.
  Three repeated out-of-memory kills were traced to it. Peak resident memory is flat with case
  count (1,086 MB at 5 cases, 1,195 MB at 40), so the application does not leak; the kills were
  the machine, not a growth bug.
- **`--docket-filter` never shipped.** The flag existed to select between filter variants; with
  the deny-list and the type list gone there is one behaviour and nothing to select.
- **`.gitattributes` was added** (`tests/fixtures/docket/** -text`). Byte-exact docket fixtures
  ([0037](../decisions/0037-docket-fixtures-from-development-dockets-only.md)) otherwise depend
  on each clone's `core.autocrlf` setting rather than on anything in the repository.
- **§15's cost model is a floor, not an estimate to trust.** It modelled about $0.0023 a case and
  about $5.45 for the stage, counting the docket's tokens once when a case sends the same payload
  on both answering turns. Measured: $0.0053 and $0.0050 a case, $4.13 for the stage.

### What a later reader must not assume

1. **The cap is a floor on a case's cost, not a ceiling.** It covers both answering turns but
   excludes retries, so a retried case costs more than the cap nominally allows.
2. **`fcntl` makes the scoring package POSIX-only** (0045). Windows is out of scope, not
   untested.
3. **The judge enforces the read half of the budget rule and not the write half.** It refuses to
   start when other runs' open reservations would fill the budget, but takes no reservation of
   its own; the reason is in `judge.py`'s docstring.
4. **A cached `listing.html` never expires.** Correct for a stage that reads closed dockets only.
   It becomes a precondition to fix in S2.5, when open dockets gain documents between fetches.
5. **The published development shape covers documents arm B would not read.** The docket scan
   fetches with nothing excluded, because the same fetch feeds the filter measurement and the
   fixture pool.
6. **`scripts/corpus_scan.py` still carries an `_EMPTY_DENY_LIST`.** It keeps the shape of the
   measurement decision 0039 asked for, so the published table can be read as the evidence for
   removing the deny-list. It is not a live mechanism, and `docs/results/s2-threshold.txt` says
   so in its closing paragraph.
7. **There is no OCR in S2** ([0047](../decisions/0047-pypdf-extracts-docket-text-no-ocr.md)). A
   page `pypdf` cannot read counts zero characters. `docs/results/s2-shape-open.txt` measures what
   that costs on recent cases: the pilot's own accident-report form carries a text layer in 261 of
   335 development-era dockets but only 19 of 75 recent ones, and scanned pages per docket roughly
   tripled. **The live board should therefore be expected to score below the held-out figure**,
   and that prediction is recorded here before the live board runs.

### Decisions taken during the stage, and an audit of them

S2 produced **21 numbered records, 0037 to 0057** — more than S0 and S1 together. That prompted a
fair question from the project owner: how many of them were changing decisions already made? The
close-out audited all of them against the code rather than against their own status lines.

**The answer, over the 20 records 0037–0056:** 4 decide new ground, 6 extend an existing
principle to a new case, 2 amend an earlier record's scope, 2 fix an error in an earlier record,
and 6 supersede part of one. **Nothing from S0 or S1 was reversed.** 0057, written at close-out,
is new ground.

**Most of the churn is S2 relitigating S2.** Five mechanisms proposed early in the stage — a
title-based deny-list, a provenance clause, a photograph exclusion, a party-submission comparison,
and ranking documents by category — were each measured and then removed by a later S2 record. That
is the stage working as intended: the measurements were commissioned precisely to decide whether
those mechanisms earned their place, and they did not.

**The two records that touch pre-S2 decisions most directly both leave the target standing.**
0038 amends 0013, the evidence/synthesis/verdict split, by settling what counts as evidence;
0045 fixes 0030's budget guard by changing how it is enforced, not whether it is.

**What the audit found wrong**, all now corrected append-only and none of it an edit to an
existing claim: 0052's item 4 listed three jobs the document category still did, two of which had
been removed hours earlier by 0054 and 0055 and the third by 0056; 0030 carried no forward pointer
to the record that fixed its guard; 0047 and 0052 carried none to 0053, which closed a defect 0052
itself had flagged as open; and 0047's text named the dependency as `pypdf` where the code pins
`pypdf[crypto]`, which is a memory fix rather than packaging detail. The index now surfaces a
later correction on the *earlier* record of each pair, which it previously showed only on the
later one.

**One standing property, stated rather than fixed.** Three separate records — 0052, 0054 and 0056
— each concluded independently that title-based classification cannot be trusted to gate what the
model sees, for three different jobs. The classifier still runs, for a published statistic and one
line in the step log, and `other` remains the largest category at 604 of 3,790 documents. The
docket's defence is now the tripwire alone; there is no second, structural layer. That is a
deliberate position (0056 says so plainly) and it is the thing to revisit first if the tripwire
ever proves insufficient.

### The gap decision 0050 leaves, measured

The close-out audit found a gap in the tripwire and the close-out measured it rather than
reasoning about it. `docs/results/s2-narrative-coverage.txt` and
`docs/results/s2-narrative-coverage-heldout.txt` are that measurement
(`scripts/narrative_coverage.py`, counts only, no model call, no matched text printed).

**The gap.** 0050 stopped the guard comparing factual-narrative *sentences* against
`docket_documents`, because the narrative is written from the docket and was tripping on its own
sources — that is what cut refusals from 38.9% of development cases to 4.2%. The backstop is the
whole-text needle, which is *not* exempt: an exact, complete copy of the narrative inside a
document still stops the case. A **near**-complete copy does not. One sentence missing, or one
word altered, and no whole-text needle matches while every sentence is exempt. The factual
narrative is the most informative thing that could leak — the spike measured 88% top-1 with it
present against 12% without — so the size of this gap decides whether S2's numbers can be
believed.

**The measurement.** For every case, what share of the factual narrative's sentences appear
inside the docket, and how much of it does any *single* document carry?

| | cases measured | median | p90 | max | single document ≥80% | ≥90% |
|---|---|---|---|---|---|---|
| `dev-400` | 379 | 0.0% | 17.3% | 98.5% | 2 of 379 | 2 of 379 |
| `heldout-400` | 270 | 9.1% | 32.4% | 74.6% | 0 of 270 | 0 of 270 |

**The published held-out figure stands.** No held-out case has a single document carrying more
than 74.6% of the narrative's sentences, and a document at that level is missing a quarter of it.
Only 5 of 270 exceed half. No case in either split reproduced the narrative whole, so the
whole-text backstop never had to fire.

**The gap is nevertheless real, and development shows it.** Two of 379 development cases have a
single document carrying **more than 90%** of the narrative — one at 98.5%. Those cases are
exactly the shape the audit described, and today nothing stops them.

**Recommended, not done: replace the exact whole-text backstop with a coverage threshold** —
refuse a case when one document reproduces more than a set share of the narrative's sentences. On
this evidence a threshold at 80% would have refused 2 development cases and nothing at all on
held-out, so it costs almost no sample and closes the gap. That is a change to the guard and
therefore Andy's decision, not one to take at a close-out; it is the first item for S2.5.

**One corpus fact behind these figures**, consistent with `docs/results/s0-corpus-scan.txt`: 125
of the 400 held-out cases carry no factual narrative at all, against 0 of 401 development ones.
For those cases the risk described here cannot arise.

### Implementation record

Twenty tasks, executed by subagents against `docs/plans/2026-09-18-s2-docket-tool.md`, which this
record replaces and the merge deletes (0017). Each task was reviewed for specification compliance
and code quality before the next began; the plan's deviation log is curated into "Departures"
above rather than carried verbatim.

- **Repository additions the specification's §11 list omits**: `scripts/build_title_vocab.py`,
  `scripts/handcheck_page.py`, `scripts/doctype_scan.py`, `scripts/docket_leak_scan.py`,
  `scripts/name_coverage.py` (0046), `scripts/score_handcheck.py` and
  `scripts/narrative_coverage.py` (this close-out); the results files `s2-doctype.txt`,
  `s2-docket-leak.txt`, `s2-handcheck.txt`, `s2-filter-compare.txt`, `s2-name-coverage.txt`,
  `s2-armB-dev.txt`, `s2-narrative-coverage.txt` and `s2-narrative-coverage-heldout.txt`;
  `.gitattributes`; and decision records 0046, 0047 and 0050–0057.
- **§11 says `Settings` gains `docket_dir` with a default of `data/docket`.** Since
  [0057](../decisions/0057-unset-directory-settings-derive-from-data-dir.md) an unset directory
  setting derives from `data_dir` instead, so the literal default only applies when `data_dir`
  is itself the default. `runs_dir` changed with it.
- **§11 names `filter.py` as "the deny-list and arm B's types and rank order".** None of those
  three survive; the module holds one function, which returns every readable document in size
  order.
- **Removed during the stage**: `scripts/filter_compare.py`, whose comparison 0054 retired.
- **Model**: `openai/gpt-5.6-luna` at the batch price throughout (0031).
- **Total spend**: $4.13, stated above.
- **Version**: `0.3.0`.
