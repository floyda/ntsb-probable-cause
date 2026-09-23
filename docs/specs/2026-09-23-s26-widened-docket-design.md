# S2.6 — The widened docket: design

*Drafted 2026-09-22 and 2026-09-23 from a design session with Andy, while S2.5 (the recorder)
was being built. Status: Approved (2026-09-23, Andy). This is the specification for build stage S2.6,
a stage added between S2.5 and S3 of `docs/specs/2026-09-12-architecture-and-roadmap.md` §11.
It records what S2.6 builds, why, the decisions it takes, and the condition for moving on. The
implementation plan is written from it separately, in `docs/plans/`.*

**How to read this.** Each section says what is built, then why, with an example where one
helps. Terms in **bold** on first use are in the glossary at the end. Numbers in this document
are of four kinds, and each is labelled:

- **scripted** numbers cite the committed script and results file that produced them;
- **ad-hoc** numbers were counted during the design session by a throwaway probe over the
  local `dev-400` docket cache. They are not citable, and S2.6's first step re-derives them
  with a committed script before they appear anywhere else;
- **external** numbers come from a published benchmark or price list, cited by URL and date;
- **estimates** are arithmetic, and are replaced by measured figures in the As-built record.

Nothing here is a result: S2.6 produces the results.

Decision records written with this specification: 0074 to 0083, and one more, naming the
chosen transcriber, when the test ends (section 14). S2.5 uses 0060 to 0072; S2.4 (the model
switch) takes the number before this stage's first.

**Depends on S2.4.** S2.4 moves the agent's default model from GPT-5.6 Luna to GPT-6 Luna,
behind a development sanity check, and re-establishes the ceiling and the B-v1 bar on
`heldout-400` with the new model, keeping S2's guard so that its comparison isolates the model
change alone (§9.3). Everywhere below, "the agent's model" means the default S2.4
leaves. If S2.4's gate fails, the default stays GPT-5.6 Luna and nothing in this document
changes except that name.

---

## 1. What S2.6 is for

S2 taught the docket tool to read a PDF's **text layer**: the characters a PDF stores as text.
A page that is only a picture has no text layer, and S2 marks it unreadable (decision 0047,
item 3). That was a deliberate, measured loss. The spike had already found that about a third
of the cases whose missing information sits in the docket have it in a document with no text
layer (spike report §10).

Looking at the development dockets during this design session showed the loss is larger and
less tidy than "some documents are scans" (ad-hoc, over the 401 `dev-400` dockets):

| page kind | pages | what we know |
|---|---|---|
| text only | 5,006 | read today |
| image only (under 50 characters of text) | 3,281 | not read today; 2,605 of them in fatal cases |
| text **and** image | 8,403 | the most common kind, and ambiguous (below) |
| blank | 109 | nothing to read |

About one document in five (721 of 3,519 PDFs) mixes page kinds, so the **page**, not the
document, is the unit of work.

A "text and image" page can be any of three things that look the same to a program:

1. a typed report with a logo — the text layer holds everything;
2. a photo with a caption — the text layer holds "Photo 3: left wing root", the image holds
   the evidence;
3. a scan with a machine-read text layer already inside — which may be good, or garbage.

Only looking at the page tells them apart.

S2.6 does three things:

1. **It reads the words trapped in images** — handwriting, faxes, scanned forms — and adds
   them to the evidence as text, after measuring which model does this best on our own pages.
2. **It lets the agent see the pictures** — photographs and diagrams, alongside the text — as
   a development-only probe.
3. **It replaces two refusals with marks.** Cases that the guard stops today because a docket
   document shares a sentence with the analysis narrative are answered, marked, and scored
   separately. The same mechanism takes up decision 0071.

**Why this comes before the agent loop.** Decision 0022 says the loop (arm C) must beat arm B
— read everything, answer once — on **equal evidence**. If only the loop could read images,
part of any win would come from reading, not from choosing what to read. Everything that
widens *what can be read* must land before the loop, and arm B must be re-measured with it.
That is this stage.

**What S2.6 is not.** No agent loop. No live case is read. No model reads a page to describe
or interpret it: the transcriber copies words and nothing else.

---

## 2. The stage in one page

- **An evidence-version axis** (§3). v1 = text layers (S2); v2 = + transcriptions (this stage);
  v3 = + pictures as pictures (probe in this stage). Every run records its version; the report
  refuses to compare across versions except by a labelled comparison.
- **Case marks** (§4). Analysis-narrative sentences in docket documents reach the agent and the
  case is marked; so is a case whose single document carries a large share of the factual
  narrative (0071). Marks never enter the agent's text. Andy's hand-check of the matched
  sentences comes first.
- **Rendering** (§5). Every page is drawn as presented with `pypdfium2`.
- **The inventory** (§6). A vision model labels about 300 sampled pages by what they show; Andy
  checks 60.
- **The transcriber test** (§7). Four models; a free answer key for typed text; Andy's answer
  key for handwriting; an invented-text gate; a choice rule fixed before the test runs.
- **v2 in the docket tool** (§8). Transcribed text with its own page marker and `[illegible]`
  in place of guesses, cached once per page, through the same guard.
- **Measurements** (§9). B-v2 against B-v1 on `dev-400`; the v3 probe on `dev-400`; B-v1 and
  B-v2 once each on `heldout-400`, at one commit; B-v2 is the new bar for S3.
- **Cost** (§11). An estimated $17–27 of model calls in all, within about one month's budget,
  spread over two months if needed.

---

## 3. The evidence-version axis

### 3.1 What it is

The arms of decision 0022 differ in **how** evidence is gathered: start facts only (A), every
tool once (B), the loop (C). Transcription does not change how anything is gathered. It changes
**what a document holds once it has been read**. So it is a separate axis, like the model
(0031) and the availability condition (0023):

| version | the docket, as the agent receives it | built in |
|---|---|---|
| **v1** | text layers only | S2 |
| **v2** | v1 + transcriptions of words in images | S2.6 |
| **v3** | v2 + photographs and diagrams as images, alongside the text | S2.6, probe only |

Any arm can run on any version. The ceiling reads no docket, so it is the same on all three.

Read as a ladder, arm B across the versions answers one question per step:

| step | question |
|---|---|
| ceiling → B-v1 | Does reading the docket help? (S2, on GPT-5.6 Luna: +11.2 points top-1, scripted, `docs/results/s2-bars.txt`; S2.4 re-measures it on the agent's new model) |
| B-v1 → B-v2 | Do words trapped in images help? |
| B-v2 → B-v3 | Does seeing the pictures help? |

B on the highest version that earns its place is "give it everything". S3's loop, which chooses,
is compared against that.

### 3.2 How it is enforced

1. `RunSpec` gains `evidence_version: Literal["v1", "v2", "v3"]`, written to the run's spec
   file beside the commit, the model and the arm. A run started before S2.6 is read as v1.
2. `ntsb-eval report --against` **refuses** two runs on different versions, with an error
   naming both. The one exception is `--versions-compared`, which prints a labelled
   "evidence-version comparison" heading so the output cannot be mistaken for an arm
   comparison.
3. The held-out ledger gains a version column. The S2 bar stays as written and is read as
   "B, v1".

**Why.** It protects the equal-evidence rule by structure rather than care. If "B with images"
were its own arm, nothing would stop a later reader from comparing C-with-images against plain
B. It also keeps two claims apart: *transcription helps* (B-v2 against B-v1) and *choosing
helps* (C against B on one version). And nothing is overwritten: the S2 bar remains citable.

---

## 4. Case marks

### 4.1 Where the guard stands today

The tripwire (0016) compares every docket document with the case's withheld text. After
decision 0050 (scripted, `docs/results/s2-docket-leak.txt`, `docs/results/s2-threshold.txt`):

| a document sentence matches … | today | `dev-400` (matched sentences, cases) |
|---|---|---|
| the factual narrative | reaches the agent, unmarked (0050) | 1,108 in 155 cases |
| the analysis narrative | **the case is refused** | 36 in 17 cases |
| the probable cause | **the case is refused** | 3 in 1 case (one of the 17) |
| an occurrence or finding code | **the case is refused** | none |

So 17 of 401 development cases are refused today, and up to 16 of them — those refused only
for analysis sentences — would be answered under §4.2.

The refused cases' matches sit in witness statements and records of conversation (7 cases),
wreckage and site examinations (3), specialist reports (2), and one each in a medical report,
a party submission, a photo caption, a pilot form and an unclassified document (scripted,
`docs/results/s2-threshold.txt`).

### 4.2 The analysis-sentence mark

**The rule.** In the `docket_documents` role, a sentence the document shares with the analysis
narrative reaches the agent unchanged, and the case is **marked** `analysis_sentence` with the
number of such sentences. This extends 0050's source-scoped exemption from the factual
narrative to the analysis narrative, for that one role.

**Unchanged.** A probable-cause sentence, an occurrence or finding code, or a whole withheld
text in any document still refuses the case. No direction-of-copying argument covers the answer
itself.

**Why.** The argument is 0050's. The analysis narrative is written at the end of the
investigation *from* the docket. A wreckage examination that reads "Examination of the engine
revealed no mechanical anomalies that would have precluded normal operation." is often pasted
into the analysis word for word. The shared sentence is the analysis quoting the evidence.
Refusing the case refuses a document for having been important enough to quote, and 0038's
principle is that the agent gets what the analyst had.

**Checked before it is adopted.** That argument is a reading of document types, not of the
sentences. So the first task of the stage is a **hand-check**: Andy reads each matched
sentence beside its document title and marks it *quotes evidence* or *conclusion in the docket*.
The sheet holds withheld text, so it lives under `data/` and is never committed; only the
counts are published (`docs/results/s26-analysis-handcheck.txt`). If 5 or fewer of the 36 are
conclusions (about one in seven), 0077 is adopted and that count is published as the rule's
measured error. If more, the rule goes back to Andy before any model run, with a neutral
marker for such sentences as the fallback.

### 4.3 The narrative-coverage mark (takes up 0071)

Decision 0071 (S2.5) deferred to S3 the question of a document that carries a large share of
the factual narrative, reframed by Andy: *mark, do not refuse, and score the marked group
against the rest.* S2.6 takes it up now, because S2.6 re-measures arm B and the new bar should
already carry the mark. Otherwise S3 would open by changing the bar it has to beat.

**The rule.** For each case, the largest share of factual-narrative sentences found inside any
one document is recorded as a number. A case at or above **50%** is marked `narrative_coverage`.

**Why 50%.** Scripted, `docs/results/s2-narrative-coverage.txt`: 23 of 379 development cases
reach 25%, 3 reach 50%, 2 reach 80%. At 25% the mark would be common enough to blur; at 80% it
would catch two cases and say nothing. 50% catches documents that hold most of the narrative.
The number itself is stored, so any other cut can be reported later without re-running.

**What it can and cannot show.** At about 3 development cases, the marked group's own row will
carry an interval too wide to prove anything. At this size the mark makes those cases
*visible*, so a reader can inspect them; it does not settle whether coverage inflates the
score. The report says so beside the row.

### 4.4 What a mark is

- A mark is written to the case's log line in the run, to the step record when S3 exists, and
  to the results files as a count. It is **never** written into the text the agent reads. A
  marker in the text would tell the agent "the NTSB leaned on this sentence", which hints at
  the answer; and a live case, whose report is not yet written, could never carry one.
- `ntsb-eval report` prints every result **twice** where marks exist: all cases, and unmarked
  cases only, with the marked group's own row. If the marked cases score much higher, the mark
  is doing work and that is published; if they do not, the concern did not bite.
- Marks from §4.2, §4.3 and §10.3 share one type, `CaseMark`, with a kind and a count. One
  mechanism, three kinds.

---

## 5. Rendering pages

### 5.1 The choice

Every page that a model will look at is drawn to an image by **`pypdfium2`**, a Python package
that bundles PDFium, the PDF engine inside Chrome. It installs from the lock file as a
ready-built package (version 5.13.0, BSD and Apache licences, packages for macOS on Apple
silicon and Linux on x86 and ARM; external, PyPI, 2026-09-22). `Pillow` is added to save the
images.

### 5.2 Why a renderer, and not pulling images out with pypdf

The ad-hoc probe of the image-only pages in `dev-400` (3,280 by its count, one fewer than
§1's) found three things that break the
"pull the image out" route:

| finding | why extraction fails |
|---|---|
| 527 pages are rotated 90°, 180° or 270° | the rotation lives on the page, so the image comes out sideways |
| 200 pages are built from 5 or more image pieces | extraction yields strips, not a page |
| encodings include 929 fax images, 250 JPEG 2000 and 54 JBIG2 | each needs its own decoder; JBIG2 needs a system program |

A renderer draws the page the way a viewer shows it: upright, whole, every encoding handled.
One path serves every page kind.

### 5.3 Why this does not break 0047

Decision 0047 ruled out system tools (Poppler's `pdftotext`) because the machine's setup would
become part of the result. A ready-built package installed from the lock file is not the
machine's setup: `make check` still reproduces anywhere `uv sync` runs. The distinction is
recorded in its own decision (0075).

### 5.4 Resolution

Images are drawn at a fixed **resolution**, in dots per inch. The transcriber test (§7.5)
chooses between 150 and 200. The chosen value is a typed constant, recorded in every
transcription's cache key.

---

## 6. Step 1: the inventory

### 6.1 What it answers

What the image-bearing pages actually show, in measured proportions, so that what gets
transcribed is decided from numbers rather than from memory of a few files.

### 6.2 How

1. **The page-kind script.** `scripts/page_kinds.py` re-derives the ad-hoc counts of §1 and
   §5.2 over `dev-400` and writes `docs/results/s26-page-kinds.txt`, counts only. Every later
   number that depends on page kinds cites this file.
2. **The sample.** About 300 pages, seeded, drawn across the page kinds that hold images
   (text-and-image, image-only) and across fatal and non-fatal cases, with 30 text-only pages
   as a control.
3. **The labeller.** `google/gemini-3.1-flash-lite:batch`, at minimal reasoning, labels each
   page with one kind: typed text, handwriting, filled form, photograph, diagram or chart, logo
   or letterhead only, mixed, blank. It writes **categories only**, never a description, so
   nothing graphic is stored. The first call is a single test page, to confirm the model
   accepts our requests (0034 found one listed model that did not).
4. **Andy's check.** A seeded 60 of the 300, each shown with its label, marked right or wrong.
   Page images are not committed; the sheet records page identifiers and marks only.

### 6.3 Why this model

The labels matter more than the price here (about $0.10 for 300 pages, estimate). The
benchmark closest to our pages (§7.1) puts this model within 0.01 of models costing six to ten
times more, and it already works on our transport (0034). Andy's 60-label check also gives an
early look at the likeliest transcriber.

### 6.4 What it can stop

If the inventory shows the image-bearing pages rarely hold words, transcription is not worth
its cost. The stage then records that, skips §7–§8, and keeps §3–§5 and the v3 probe's
question for later.

---

## 7. Step 2: the transcriber test

### 7.1 What the benchmarks say

Most document-reading leaderboards test clean, modern, digital documents. One benchmark was
built for our kind of page — "handwritten census records, historical logbooks, degraded
administrative forms" — **socOCRbench** (external,
<https://noahdasanaike.github.io/posts/sococrbench.html>, read 2026-09-22; scores are
normalised edit similarity, 1 is perfect):

| model | handwriting | printed text | Western Europe | OpenRouter batch, $ per M tokens in / out |
|---|---|---|---|---|
| Gemini 3.1 Pro | 0.65 | 0.70 | 0.69 | not batch |
| Gemini 3.6 Flash | 0.65 | 0.77 | 0.75 | 0.375 / 1.875 |
| Gemini 3.1 Flash Lite | 0.64 | 0.75 | 0.74 | 0.125 / 0.75 |
| Qwen3.5 122B (open weights) | 0.59 | 0.73 | 0.71 | 0.26 / 2.08 (no batch) |
| Claude Sonnet 4.6 | 0.54 | 0.70 | 0.69 | 1.50 / 7.50 |
| GPT-5.6 Luna (the agent's model) | **0.39** | 0.65 | 0.59 | 0.10 / 0.60 |
| Tesseract (classic OCR) | 0.13 | 0.36 | 0.40 | free |

Limits, stated: 280 pages, private, mostly historical and multilingual; differences under
about 0.02 are noise at that size; it does not count invented text separately; Sonnet 5 and
GPT-6 Luna are not tested. It says **whom to test**, not who wins. Two findings carry into the
design regardless: classic OCR is not an option for handwriting, and the agent's own model
reads handwriting poorly, so **the agent does not read text from images itself** — a dedicated
transcriber reads once and the agent reads the text.

### 7.2 The candidates

| model | why it is in |
|---|---|
| `google/gemini-3.1-flash-lite:batch` | cheap, and the front-runner |
| `google/gemini-3.6-flash:batch` | best printed-text score in its price range; says whether 3× the price buys accuracy on our pages |
| `qwen/qwen3.5-122b-a10b` | open weights: anyone can rerun it, and it cannot be retired from under us |
| the agent's model, batch (after S2.4, `openai/gpt-6-luna:batch`) | control: the number behind "the agent does not read images itself"; the benchmark tested only its predecessor, GPT-5.6 Luna |

Each runs at its lowest reasoning setting; the benchmark found more reasoning made Flash Lite
*worse* (0.62 → 0.58 overall), consistent with a model "tidying up" what it reads. The setting
is recorded.

### 7.3 The three answer keys

**Typed text — free.** Pages that already have a good text layer (text only, born-digital) are
rendered to plain images and transcribed. The text layer is the answer. Example: pypdf reads
"left magneto replaced 12/03/17"; a transcriber writes "left magneto replaced 12/08/17" — one
character wrong in 30. About 100 pages. *Limit:* a clean rendered page is easier than a real
fax; the typed key measures a best case.

**Handwriting — Andy, where the models disagree.** About 25 handwritten pages (roughly 375
lines), drawn from pages the inventory labels handwriting, topped up from the 74 pilot forms
with no text layer (scripted, `docs/results/s2-shape-dev.txt`) if the inventory finds too few.
All four models transcribe every page. Where all four agree on a line, it is accepted. Where
they differ, Andy sees the image beside their versions and picks one or types the right text.
Andy also checks a seeded 1 in 10 of the agreed lines, because four models can share a mistake,
and the spot check measures how often. Estimated effort: 1 to 1½ hours.

**Invented text — pages with no words.** About 50 pages the inventory labels photograph with
no words. Any words a model outputs are shown to Andy: most will be real (a registration on a
tail, a placard), a few may be invented. The invented ones are counted.

The handwriting sheet and the page images hold personal text and are not committed; counts are
published in `docs/results/s26-transcriber-test.txt`.

### 7.4 The choice rule — fixed before the test runs

**Measures.**

| measure | counts | example |
|---|---|---|
| invented text | words output that are not on the page | page: "fuel selector BOTH"; model: "fuel selector BOTH, gascolator clean" |
| handwriting line accuracy | lines exactly right; `[illegible]` counts right if Andy cannot read the line either | 300 of 375 = 80% |
| typed character errors | wrong characters per 100 | "12/08/17" for "12/03/17" |

**Rule, in order.**

1. **Gate.** A model is out if it invents words on more than 2 of every 100 handwritten lines,
   or on more than 1 in 20 no-word photo pages. An invented word is weighed by the agent as a
   fact; a missed word only as absence.
2. **Choice.** Among models that pass, the cheapest whose handwriting line accuracy is within
   5 percentage points of the best, and whose typed errors are within 1 per 100 characters of
   the best.
3. **If none passes,** the stage records that, stops transcription, and keeps the rest (§13).

**Why 5 points.** At about 375 lines, a line-accuracy figure is uncertain by roughly ±4 points
(estimate). A smaller margin would choose a winner from noise; a larger one would let a clearly
worse model win on price.

### 7.5 Resolution

The chosen model transcribes the handwriting and typed keys at 150 and at 200 dots per inch.
200 is chosen only if its handwriting line accuracy is more than 5 points above 150's;
otherwise 150, which costs fewer tokens.

### 7.6 What the rule is not

It chooses a transcriber. It does not say transcription helps the agent: §9.1 does. A
transcriber can be the best of four and add nothing to a diagnosis, and that would be
published as a result.

---

## 8. v2 in the docket tool

### 8.1 What the agent reads

A transcribed page carries its own marker, and never guesses:

```
[page 2 of 4, transcribed from an image]
Engine sputtered at 800 ft. Switched to [illegible] tank, no change.
```

- A page with a text layer keeps its S2 marker, `[page 2 of 4]`.
- The transcriber is told to write `[illegible]` for a word it cannot read. The handwriting key
  measures how often it guessed where it should have written `[illegible]`.
- **Mixed pages** (text and image) keep their text layer. The transcriber is given the page's
  own text layer and asked only for words that are **not** already in it; those are added
  under the line `[words in the page's images, transcribed]`. Which mixed pages are sent at all
  follows the inventory: a page whose images are logos only is not.
- The transcription call also returns the **page kind** (the inventory's categories). v3 uses
  it (§10); v2 only records it.

**Why a marker.** A transcription can be wrong in a way a text layer cannot: the pilot wrote
"800 ft" and the transcriber read "300 ft". The agent should be able to weigh a reading
differently from typed text. The marker says only where the text came from, so a live case and
an evaluation case look the same.

**Rejected: a confidence score per line.** A model's own confidence in its reading is poorly
matched to how often it is right. It would add a number that looks meaningful and is not.

### 8.2 Where it sits

- `docket/render.py` — page to image, at the fixed resolution.
- `docket/transcribe.py` — one call per page through the model seam; returns words, page kind
  and cost; writes the cache.
- `docket/extract.py` — gains the transcribed-page marker; a page with no text layer is now
  `transcribed`, `transcription failed` or, where the inventory rule skips it, `not sent`.
- `docket/attach.py` — unchanged in role: the one place document text is changed before the
  split. Name and amateur-built replacements (0044, 0046) apply to transcribed text exactly as
  to text-layer text.
- The model seam gains an image input. The transcriber's request carries **only** the page
  image, a fixed instruction and, for mixed pages, that page's own text layer. The boundary
  test (0016, layer 5) gains a check that a transcription request holds nothing else — in
  particular no withheld text, which the transcriber has no reason ever to see.

### 8.3 The cache, and what transcription costs

- Each page is transcribed **once**. The cache key is the page image's hash, the model, the
  instruction's version and the resolution. The cache lives under `NTSB_DATA_DIR` and is never
  committed.
- Transcription is **evidence preparation**, like text extraction: it is paid once per page
  and reused by every run, every arm and, later, the loop. Its cost is recorded per page and
  reported per case, **separately** from the agent's per-case cap. The monthly budget
  reservation (0045) covers it like any other model spend.
- **Why separate from the cap.** The cap bounds what the *agent* spends deciding a case. If
  preparation counted against it, arm B and the loop would share one fixed cost, and a large
  scanned docket would squeeze the agent's answer. Reported separately, both stay visible.

### 8.4 The guard

Transcribed text passes through the same attach step, the same split and the same tripwire as
every other document, with the marks of §4. Nothing about transcription is exempt.

A page whose transcription **fails** (an error, a timeout, a reply with nothing usable) is
recorded in the manifest as `transcription failed` and, in v2, contributes no text — as an
unreadable scan does today.

---

## 9. Measurements

### 9.1 Do transcriptions help? B-v2 against B-v1 on `dev-400`

Both runs at the same commit, with the marks of §4 in force, so the only difference is v2's
added text. B-v1 is re-run rather than borrowed from S2 because the marks change which cases
are answered. The paired difference is published whichever way it comes out, overall, by
fatal and non-fatal, and for the cases that hold image pages. Output:
`docs/results/s26-armB-v2-dev.txt`.

### 9.2 Does seeing the pictures help? The v3 probe

§10.

### 9.3 The new bar: B-v1 and B-v2 on `heldout-400`, once each

After §9.1, and before any S3 code exists, B-v1 and B-v2 each run once on `heldout-400`, at one
commit, with the marks of §4 in force, and both are appended to the held-out ledger with their
version. Output: `docs/results/s26-bars.txt`. B-v2 is the bar S3's loop must beat, on v2.
Whether v3 ever runs on held-out is decided after §10, on what the probe shows.

**Why B-v1 is re-run here rather than borrowed from S2.4.** Each stage changes one thing, so
each held-out comparison isolates one change. S2.4 changes only the model: its B-v1 keeps S2's
guard, refusals included, so it differs from S2's B-v1 in the model alone. S2.6 changes only the
evidence. The marks let cases that S2.4's guard refused be answered (up to 16 on development;
not counted on held-out); paired against S2.4's run, those cases would have no partner and
would drop out of the comparison. Re-running B-v1 at S2.6's commit keeps them in both runs,
gives them their own row (§4.4), and leaves the transcriptions as the only difference between
the two runs.

---

## 10. The v3 probe

### 10.1 What it is

B-v3 against B-v2 on `dev-400`, paired, one run each. In v3, pages whose kind (§8.1) is
photograph, diagram or mixed are sent to the agent **as images, alongside the text** — never
instead of it. Text pages still arrive as text: the agent's model reads handwriting at 0.39
against the transcriber's 0.64 (§7.1), so an image of a text page would be read worse, and
could not be checked by the guard.

It is **development only and not a bar**. Its output is `docs/results/s26-v3-probe-dev.txt`.

### 10.2 Why here, and not after S3

Andy's reasoning: it builds up what "give it everything" means before S3 asks whether the loop
can do better by choosing. It is also what a human analyst does — looks at the photographs —
and 0038's principle is that the agent gets what the analyst gets.

### 10.3 The guard, for images

The leakage tripwire compares text. It cannot see inside an image. If a docket held a scanned
page of a letter quoting the probable cause, v2 would transcribe it, the tripwire would find
the sentence, and the case would stop. In v3 the image alone would let the agent read the
answer off the picture, score a win, and leave nothing in its output that looks wrong. This is
about the **score**, not about names: names are handled on the output side (0049, below).

So each image has one of three outcomes:

| its page's transcription | the image | mark |
|---|---|---|
| succeeded and passed the tripwire | sent | none |
| succeeded and tripped on the probable cause, a code or a whole withheld text | case refused, as today | refusal, counted |
| **failed** | **still sent** | case marked `unguarded_images` with the count |

The v3 result is reported **twice** from the same run, at no extra cost: all cases, and without
the `unguarded_images` cases (§4.4). If the two agree, unguarded images are not inflating the
score; if the marked cases score higher, that is the signal, and it is published.

**Limit, stated.** A transcription that *succeeds but misreads* the answer looks like a pass.
The invented-text gate and the handwriting key bound how often the transcriber misreads; they
do not close the gap.

### 10.4 Names

Decision 0049 draws the line at the public surface this project produces: the live board, a
published results file, a prediction row. Names reaching the *model* are allowed; that is
already true of document text, where only known names are replaced (0046). A name inside an
image is the same case. The probe's runs stay under `data/runs`, and its results files hold
counts only. The name check on public output that 0049 requires is S4/S5 work and applies to v2
and v3 alike.

### 10.5 The cap and the model

- **Model:** the agent's and the bar's model (0031; after S2.4, GPT-6 Luna). OpenRouter lists
  it as accepting images (external, 2026-09-22). The result is labelled with the model and "v3"
  and is not generalised: how
  much a model gains from pictures depends on how well it reads pictures, and the model axis is
  measured after S3.
- **Cost:** `dev-400` averages about 29 image-bearing pages per case (ad-hoc: 11,684 over 401),
  far more in fatal cases. Estimated at ~1,000 tokens an image and GPT-6 Luna batch's $0.05
  per million, about $0.0015 per case for the images. Luna's price doubles above 272,000 prompt
  tokens (external, 2026-09-22), so the $0.05 per-case cap, not the context window, binds
  first.
- **When the cap binds:** images are added in page order until the cap, and the number of
  cases cut short is published. A case that fails outright is reported as a failure, as in S2.

### 10.6 What it settles for S3

- If v3 shows a real gain, S3's loop gets a "look at this image" tool and is compared against
  B-v3, so the evidence stays equal (0022).
- If it does not, S3 compares on v2 and images stay out of the loop.

---

## 11. Cost

All estimates, replaced from the run records at close-out.

| item | estimate |
|---|---|
| inventory, 300 pages | $0.10 |
| transcriber test, 4 models × ~175 pages, two resolutions for the winner | $2–4 |
| transcription of `dev-400` image-bearing pages, ~11,700 pages at most, cheapest candidate | $3–6 |
| transcription of `heldout-400` image-bearing pages (not counted; assumed similar) | $3–6 |
| B-v1 re-run and B-v2 on `dev-400` | $3–4 |
| v3 probe on `dev-400` | $2–3 |
| B-v1 and B-v2 on `heldout-400`, once each | $3–4 |
| **total** | **about $17–27** |

**The budget.** Andy raised the monthly budget from $25 to **$40 for the development stages**
(2026-09-23; decision 0083, amending the default in 0030 item 2). It holds until the live board
runs (S4), whose own budget is decided there. At $40 the whole stage fits in one month on the
estimate above.

**The pause point.** The transcription rows assume the cheapest candidate. If the test chooses a
dearer one — Gemini 3.6 Flash is about three times the price — they are re-estimated from its
real price before they run. If the re-estimated stage total passes **$40**, work stops and Andy
decides: go ahead across two months, or transcribe fewer pages (for example image-only pages
first). The budget guard (0045) refuses a single run that would overrun the month; it cannot see
a stage drifting, and the pause point can.

Order of spending follows §13, so an early stop (§6.4, §7.4) spends little.

---

## 12. Tests and continuous integration

- **Renderer:** a committed development fixture page of each awkward shape (rotated, tiled,
  fax-encoded) renders upright and whole; offline.
- **Transcriber:** recorded replies (as S1's probe recorded them) drive the tests; no network.
  The cache key changes when model, instruction version or resolution changes.
- **Boundary:** a transcription request holds only the image, the instruction and that page's
  own text layer; its mutation test proves the check can fail.
- **Guard and marks:** an analysis sentence in a docket document marks, not refuses; a
  probable-cause sentence, a code or a whole withheld text still refuses; the mark never
  appears in the payload text; a failed transcription in v3 marks `unguarded_images`.
- **Evidence version:** `report --against` refuses runs on different versions; a pre-S2.6 run
  reads as v1.
- **Fixtures** come from development dockets only (0037), and no page image or transcription of
  a held-out case is ever committed.

---

## 13. Build order within S2.6

1. `scripts/page_kinds.py` — re-derive the ad-hoc counts. No model.
2. The analysis-sentence hand-check (§4.2), then the marks (§4) and the evidence-version axis
   (§3). No model.
3. The renderer (§5).
4. The inventory (§6). *Stop point:* images rarely hold words.
5. The transcriber test (§7). *Stop point:* no model passes the gate.
6. v2 in the docket tool (§8); transcription of `dev-400`.
7. B-v1 and B-v2 on `dev-400` (§9.1).
8. The v3 probe (§10).
9. Transcription of `heldout-400`; B-v1 and B-v2 on `heldout-400`, once each, at one commit (§9.3).

Branching: S2.6 works on `s26-widened-docket`, cut from `main` at S2's release. It touches the
docket package, the guard and the harness; S2.5 touches the recorder and AWS. The two barely
overlap; S2.6 merges S2.5's changes when S2.5 lands.

---

## 14. Decisions S2.6 takes

Each is a numbered record, written with this specification, one decision per record.

| # | decision |
|---|---|
| 0074 | Words in images are read in the build, not in "phase 2": replaces 0047 item 3; the inventory decides what is transcribed |
| 0075 | Pages are rendered with `pypdfium2`; a ready-built package passes 0047's reproducibility test where a system tool does not |
| 0076 | Evidence version is an axis, not an arm; every run records it; comparisons across versions are refused unless labelled |
| 0077 | Analysis-narrative sentences in docket documents reach the agent and mark the case; extends 0050; adopted after Andy's hand-check |
| 0078 | The narrative-coverage mark at 50% of one document, taken up from 0071 and moved from S3 to S2.6; the share is stored per case |
| 0079 | Transcribed text carries its own page marker and writes `[illegible]` rather than guessing; mixed pages add only words not in the text layer; no confidence score |
| 0080 | The transcriber test: three answer keys, the invented-text gate and the choice rule, fixed before the test runs |
| 0081 | Transcription is evidence preparation: cached once per page, its cost reported apart from the agent's per-case cap |
| 0082 | The v3 probe: pictures alongside text, development only, images sent only if their transcription passed or else marked, scored with and without the marked cases |
| 0083 | The monthly budget is $40 during development (to S4), amending 0030's $25 default; a stage whose re-estimated total passes the month's budget pauses for Andy |
| next free number | *(at the end of the test)* The transcriber chosen, with its resolution |

The roadmap gains an S2.6 entry, and the top-level `CLAUDE.md`'s goal 4 ("only then consider
phase 2: OCR") is amended to point at 0074. Both are appended, not rewritten.

---

## 15. Done means

1. `docs/results/s26-page-kinds.txt` exists and every page-kind number in the As-built record
   cites it.
2. The analysis hand-check counts are published and 0077 records the outcome.
3. `docs/results/s26-transcriber-test.txt` holds the three answer keys' results for every
   candidate and the rule applied to them; its decision record states the choice — or the stage records that
   no model passed.
4. If a transcriber was chosen: `s26-armB-v2-dev.txt`, `s26-v3-probe-dev.txt` and
   `s26-bars.txt` exist, each produced by a script, each with the marked and unmarked rows.
5. The held-out ledger holds S2.6's B-v1 and B-v2 rows with their version.
6. Tests and CI green; `scripts/check_docs.py` passes; the As-built record is appended and the
   plan deleted (0017).

---

## 16. Not in S2.6

- Describing photographs in words by a second model. v3 shows the agent the picture instead.
- v3 on `heldout-400`, and v3 in the live path — decided after the probe.
- Transcription of live cases. The cache is built so S4 can reuse it.
- The name check on public output (0049), which S4 and S5 build.
- Changing the agent's model: that is S2.4, a separate stage. The model axis proper — which
  model gains most from the docket — stays after S3 (0031).
- The agent loop and its tools (S3).
- **A per-case cap that scales with the amount of evidence** (Andy, 2026-09-23). Carried to
  S3, where the loop's costs are designed: a large docket may need more room to reason than a
  small one. Whatever rule S3 adopts, arm B and the loop must get the same cap on the same case
  (0022), and the cap must still be enforced before the call.

---

## 17. Risks and open questions

| risk | how it is handled |
|---|---|
| The hand-check finds many analysis matches are conclusions | 0077 is not adopted as written; a neutral marker for those sentences is the fallback, decided before any model run |
| No transcriber passes the invented-text gate | Recorded as a result; transcription stays deferred with a measured reason; marks and renderer ship |
| Andy's handwriting key is swayed by seeing the models' versions | The spot check of agreed lines measures shared error; the sheet records which lines Andy typed rather than picked |
| The typed key flatters every model (clean renders) | Stated as a best case; the handwriting key is the harder test |
| Held-out dockets differ in shape from development | Transcription of held-out is estimated, not counted, and the estimate is replaced before it runs; no held-out page is inspected |
| A benchmark result does not carry to our pages | The benchmark only chose the shortlist; the choice is made on our pages |
| A candidate model is withdrawn or rejects our requests | One test page first; the open-weights candidate is in the shortlist for this reason |
| Costs exceed a month's budget | $40 a month during development (0083); a re-estimated stage total over $40 pauses for Andy; the reservation (0045) refuses a run that would overrun |

---

## Glossary

- **Text layer**: the characters a PDF stores as text, which a program can read directly.
- **Scan**: a page stored only as a picture; it has no text layer, or a poor one.
- **Rendering**: drawing a PDF page to an image the way a viewer shows it — upright, whole.
- **Resolution / dots per inch**: how sharp a rendered image is; sharper costs more tokens.
- **Transcription**: copying the words on a page image into text, and nothing else. Not
  describing, not interpreting.
- **Transcriber**: the model chosen to transcribe; not the agent's model.
- **Inventory**: a labelled sample of pages saying what kind of thing each shows.
- **Answer key**: the true text of a page, against which a transcription is scored.
- **Invented text**: words a transcription holds that are not on the page.
- **`[illegible]`**: what the transcriber writes for a word it cannot read, instead of a guess.
- **Evidence version (v1, v2, v3)**: what the docket holds once read — text layers; plus
  transcriptions; plus pictures as pictures.
- **Arm**: how evidence is gathered — start facts only (A), every tool once (B), the loop (C).
- **Bar**: the held-out score the next stage must beat.
- **Tripwire**: the guard that stops a case if withheld text or codes appear in its evidence.
- **Mark**: a note on a case, kept in logs and results and never in the agent's text, so a
  group of cases can be scored separately.
- **Hand-check**: a person reading a sample and marking each item, to measure an error rate.
- **Paired difference**: two runs compared on the same cases, with an interval.
- **Evidence preparation**: work done once per document, before any run, and reused by all.
- **Boundary test**: a test that inspects what actually reaches a model, not what code says
  should.
- **Open weights**: a model whose files are published, so anyone can run it.
