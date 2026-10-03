# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The agent itself: it determines the probable cause of a US general-aviation accident from
investigator-gathered evidence, scored against the NTSB's own published verdict. It is built on
the decision made in `../ntsb-spike/` (spike complete, decision: build — see
`../ntsb-spike/docs/spike-report.md` and `../ntsb-spike/docs/build-brief.md`, especially §6
"Evaluation plan" and §7 "What a build repo needs that this one does not have"). **S0 to
S2.4 are built and released**: S0 the foundation (strict tooling, data ingestion, the
evidence/synthesis/verdict split with its layered leakage guard, a model seam), S1 scoring and
the evaluation harness, S2 the docket tool and arm B, S2.4 the model switch. **S2.5 (the
recorder) and S2.6 (the widened docket) are built and released**: S2.5 a nightly job that
records when each open case's evidence fields and docket documents first appear, into its own
SQLite store, running on AWS; S2.6 the transcription of words in page images (evidence
version v2), off by default since S2.7 for cost (decision 0120). **S2.7 (coding guidance) is
built**: an ordering check after the answer (`ntsb-eval check`), coding guidance files named
on every run (`run --guidance`), the statistics pool behind both, and a sealed development
sample opened once. S2.8 (a coding lookup) is cancelled (decision 0132). **S3.1 (the agent loop)
is built**, the first of S3's three sub-stages under one spend line (0128): arm C, the loop in
the `agent` package, on native tool calling, with a read-or-skip choice over the docket and four
coding tools; S3's own statistics file and sealed sample; arm B's fixed tool post-pass; and the
loop's noise floor and format gate on `dev-400`. Tuning closed without a registered round
(0139): the loop frozen at `fd6053f` is S3.1's result and the loop S3.2 measures. The precedent
tool the agent would question is built after S4, as a measured second version (0140). **S3.2
(the claims) is next**: predictions registered first, arm C against arm B at equal cost, the
ablations, the calibration fit, then S3's sealed sample and `heldout-400` once each; S3.3 is
live shadow. Read build-brief §7 before writing any code, then
`docs/specs/2026-09-12-architecture-and-roadmap.md`, the agency design
(`docs/specs/2026-09-14-agency-hypothesis-trail-design.md`, which every stage from S1 to S5
takes a part of; its 2026-09-30 note says what 0121 to 0130 changed), and each stage's
specification under `docs/specs/` (its As-built section records what was delivered), which
amend the brief where they differ. S3's specification
(`docs/specs/2026-09-30-s3-agent-loop-design.md`) holds the shared design and S3.1 in full, S3.2
and S3.3 in outline; the precedent tool's design note
(`docs/specs/2026-10-03-s3-precedent-tool-design.md`) is a Draft for after S4.

## Required components (build-brief §7)

- **Agent loop and tool interface**, with a step budget, an abstain path, and a log of every
  step and its cost; every tool result goes through `split_record` with the other roles
  excluded, never a second assembler (0023). **Built in S3.1** as `agent/`, on the design of
  0121 to 0127: the agency is the read choice and the coding step; the hypothesis is recorded at
  checkpoints (H0 before reading, H1 and H2 after a read choice that read something, the answer),
  not after every call; structured evidence is not behind tools, so H0 uses all non-docket
  evidence (0122); the masked condition is paused (0123). `loop.py`'s `CaseLoop` is one case's
  state machine: it hands out its next call and takes the reply, and never calls a model;
  `steps.py` is its step table (the forced `tool_choice` per step; at most 2 read choices and 6
  coding calls; one retry per broken call); `drive.py` holds `drive_sync` and `drive_batch`
  (each batch round sends every unfinished case's next call; `replies.jsonl` and `rounds.jsonl`
  make a resume exact, waiting on a round already sent); `run.py`'s `AgentRunner` is arm C in
  the harness (folder, budget, scoring, records, `trail.jsonl`); `armb.py` is arm B's fixed tool
  post-pass (0127); `schemas.py` the seven strict tool definitions and argument parsing;
  `tools.py` the four coding tools (`describe_codes`, `occurrence_usage`, `past_findings`,
  `suggest_codes`, 0125), pure over the code tables and statistics; `texts.py` the fixed texts
  and the prompt version; `documents.py` the only place a record or docket becomes model text
  (the evidence, the listing and the documents read, each its own split); `trail.py` the
  per-call `AgentCall` rows and `LoopOutcome`; `later.py` a later trigger's opening (0122; built
  and tested, first used live in S3.3); `facts.py` a document's numbers. Non-evidence tool text
  is `model/tool_text.py`'s `ToolText`; import-linter contracts keep the library from importing
  `agent` and its tools and texts from any case record, and the boundary test reads every tool
  text. Tool #1 is the docket at evidence v1: scan-only documents are listed as not readable,
  with no transcription tool in S3.1 or S3.2. The Iowa Mesonet archive (params already verified
  in the spike's `config.yaml`) comes later, with its own provenance rule.
- **Docket client and PDF classifier/extractor** as an importable module with test fixtures
  (the spike's probe scripts hard-code temporary paths and are not reusable as-is). **Built in
  S2**: `docket/client.py` (caching, polite rate limit), `docket/listing.py` and
  `docket/manifest.py` (the document listing), `docket/classify.py` and `docket/extract.py`
  (born-digital text extraction and classification), `docket/filter.py` (arm B's document
  filter) and `docket/attach.py`, with offline fixtures under `tests/fixtures/docket` and arm
  `B` wired into the eval harness. **Widened in S2.6**: `docket/pages.py` (per-page facts),
  `docket/render.py` (pages drawn to images with `pypdfium2`, 0075) and `docket/transcribe.py`
  (words in page images read once per page by the transcriber into a cache under
  `NTSB_DATA_DIR`, evidence preparation costed apart from the per-case cap, 0079, 0081, 0085);
  a v2 run reads those transcriptions through the same attach step, split and guard.
- **Code-constrained output**: the model picks from a supplied list of NTSB occurrence/finding
  codes with their meanings, not free text, so scoring is exact-match. Seed the code lookup
  table from the spike's `decidability_form.build_code_lookups()`.
- **Eval harness**: one command, fixed case list, ablation flags, per-slice reporting
  (slices decided in S1; narrative presence no longer applies, 0013; fatal / non-fatal is
  proposed before investigation class, whose mix differs by era), confidence intervals,
  cost per run, the three arms (0022; in S3, 0127: arm A start facts, arm B the fixed pipeline
  of S2.7's answer, every coding tool in a fixed order, one more answer and the ordering check,
  arm C the loop) and the full availability condition (the masked condition is paused, 0123).
  From S3.1 every S3 run (the loop's tools, arm B's post-pass and its check) counts in
  `load_stats("s3")` (`scoring/coding_stats.py`; `scoring/tables/coding_stats_s3.json`,
  `docs/results/s3-coding-stats.txt`: the development pool less `dev-400`, `dev-seal-400` and
  `dev-seal-s3-400`, 12,090 cases), and S2.7's `load_stats("s27")` file is never rewritten;
  `dev-seal-s3-400` is S3's sealed sample (401 cases, seed 20260930), refused until S3.2's
  registration is committed and used once there (0129).
  The spike's `baseline.py` and `oneshot.py` are numerical anchors, not a harness. From S2.6
  every run records its **evidence version** (0076): v1 is text layers, v2 adds
  transcriptions, v3 (pictures alongside text) is a name only and every run refuses it (0090);
  v2 is refused on arm A and the ceiling, which read no docket (0091); `report --against`
  refuses two versions unless `--versions-compared` labels the comparison.
- **Case marks** (S2.6, `records/marks.py`, computed inside `split_record`): a docket
  sentence shared with the analysis narrative reaches the agent and marks the case
  `analysis_sentence` (0077); a case whose largest single document holds at least 50% of the
  factual narrative is marked `narrative_coverage`, and the share is stored (0078). A mark
  never enters the agent's text; the report prints every result for all cases and again for
  unmarked cases, with each marked group's own row.
- **SQLite predictions store**: case, evidence-hash, timestamp, answer, cost per row; docket
  document lists with first-seen timestamps; resolution outcomes. **The store's first tables
  are built in S2.5**: `store/` (`db.py`, `schema.py` with numbered migrations, `models.py`,
  `sync.py` for a local or `s3://` location) is the only code that touches SQLite, and holds
  what the recorder observes, never a synthesis or verdict field. The predictions tables come
  in S4 (S3 specification §11); S3.1's trails are JSONL in the run folder, never committed.
- **Scheduler and resolution watcher**: poll open cases and dockets, run the watcher, lock
  predictions (design notes suggest committing hashed rows to git for tamper-evidence). **The
  polling half is built in S2.5**: the recorder (`recorder/window.py`, `recorder/cases.py`,
  `recorder/dockets.py`, `recorder/run.py`; the command `ntsb-record run` in
  `apps/recorder/`) polls every watched open case and its docket listing each night at 03:00
  UTC, as one scheduled AWS Fargate task defined in `infra/` (`NtsbRecorderStack`), with the
  store in S3. The resolution watcher and prediction locking come in S4.
- **Tests and CI**: the layered leakage guard's tests, including a mutation test that proves
  the boundary test can fail (0016); docket parser fixtures; a check that held-out cases never
  appear in development fixtures, judged by event date; a redaction check on fixtures (0015);
  from S2, a test that docket documents classified as synthesis never reach the model; and a
  retrieval-contamination test if similar-case search is ever added.
- **Data ingestion as a job** (not `fetch.py <start> <end>`): S0 fetches by event month into a
  hashed manifest and rebuilds one processed file of index columns plus the raw record (0014);
  the S2.5 recorder re-fetches the event months of every watched case nightly, with the
  change feed stored beside them for comparison, not used as the source (0065). Raw data kept
  out of git.
- **Live board**: the public surface — a page for open cases and a trajectory view of the
  agent's steps and costs, in the clinical tone the design notes require.

## Rules that carry from the spike

1. **Evidence / synthesis / verdict split in one function, with a layered guard.** Factual
   narrative and analysis narrative are synthesis; probable cause, occurrence codes and finding
   codes are verdict. Neither is ever passed to a model except for scoring (0013). The split is
   `records/split.py:split_record()`, guarded as in 0016; the spike's
   `assert_no_answer_fields()` only checked key names and is not the model to copy. Never a
   second payload assembler.
2. **Never guess API details.** Endpoints, params, field paths come from the NTSB's OpenAPI spec
   (`../ntsb-spike/public.yaml`) or a saved real response, not invention.
3. **Every reported number comes from a script.** No numbers from memory.
4. **Raw data never goes in git.** Keep `data/raw/`, `data/processed/`, `*.zip`, `*.mdb` ignored.
5. **Splits are fixed**: dev ≤2019, held-out 2020–2023, open ≥2024, **by event date — never by
   case number**, whose year is the federal fiscal year (0015). Held-out is touched rarely;
   open cases feed the live board only. An open-split case, closed or ongoing, may enter a
   measurement only as numbers — counts and distributions, no case numbers, no text, no cached
   documents — so nothing from it can reach development or evaluation work (0024). Filter live
   cases on `completionStatus == "Ongoing"`, not `!= "Completed"` (foreign `N/A` cases carry
   verdicts).
6. **Clinical tone.** These are fatalities. No victim names in any output; nothing that reads as
   a game.
7. **Documents Andy must sign off** (briefs, plans, reports) are written in simplified technical
   English: say why each datum matters and why each decision is made, give examples, end with a
   glossary. Numbers stay exact and scripted.

## Rules that start here

8. **Every significant decision gets a record.** Architecture, scope, tooling and
   methodology choices are written to `docs/decisions/` as a numbered record stating the
   context, the decision, why it was taken, and what it rules out. A decision that exists
   only in a commit message or a conversation is not recorded. The reasoning is the
   substance of this project: a reader who disagrees with a choice should be able to find
   the argument for it and say precisely where it fails, rather than guess at what was
   considered. Records are append-only — a superseded decision gets a new record naming
   the one it replaces, and the old record stays in place. Format:
   `docs/decisions/README.md`.
9. **The toolchain is strict from the first commit** (0011): uv on hatchling with a committed
   `uv.lock`, Python 3.14, ruff, `mypy --strict`, import-linter contracts, deptry, vulture,
   pip-audit, and pre-commit hooks run the same checks locally. The library package is
   `ntsb_probable_cause`. Fixture records are real development-split records, redacted of owner
   and operator fields, made only by `scripts/make_fixture.py` (0015). On amateur-built
   aircraft, the make and model evidence fields hold the label `Amateur-built`, never the
   recorded values, which are usually the builder's name (0020).
10. **Specifications close with an As-built record; plans are deleted at merge** (0017). Plans go
    in `docs/plans/`, not the superpowers default. Tick plan tasks in the same commit as their
    code and log deviations in the plan. The pull request that finishes a stage runs the
    `close-stage` skill; `scripts/check_docs.py` fails CI if the close-out is missing.
11. **A pull request that closes a stage is merged with a merge commit, never squashed or
    rebased** (0018, amended by 0033); each closed stage is a tagged release. Squash merges
    stay the default for incidental pull requests that produce no measurements (documentation
    fixes, tooling, dependency bumps); rebase merging stays disabled entirely. A stage-closing
    pull request is titled `<stage>: <name>`. The close-out sets `version` in
    `pyproject.toml`; after the merge Andy runs `gh release create --generate-notes`. There is
    no `CHANGELOG.md`. From S1, every evaluation run and prediction row records the commit SHA
    and whether the tree had uncommitted changes -- 0033 is why: a squashed stage merge would
    have left that recorded SHA unreachable from `main`'s history.

## What to carry over from the spike

- The field paths in `../ntsb-spike/config.yaml`, as typed constants (0012) — there is no
  `config.yaml` here.
- The field roles, **changed**: the factual narrative moves from evidence to synthesis (0013).
- The idea of `build_evidence()` as the only payload assembler; its assertion is replaced by
  the layered guard (0016).
- The split definitions (dev / held-out / open, above).
- The two labelling sheets (`../ntsb-spike/labelling/leakage.filled.csv`,
  `../ntsb-spike/labelling/decidability.filled.csv`) as regression fixtures.

## Eval bars to beat (held-out split)

**S1 measured the bars; they live in `docs/results/s1-bars.txt`, with the scoring targets
fixed by decision 0025 and the samples and ledger by 0026.** The spike's 57% / 65% one-shot
figures are gone from this section: they were measured on free-text output through the
`claude` CLI with the factual narrative as evidence, and the stack that runs now is
code-constrained (0006), transported over OpenRouter (0009), and withholds the factual
narrative from every case (0013).

The two numbers to hold in mind, both on `heldout-400` at commit `c717ab5`, on GPT-5.6 Luna:

| metric | honest baseline (no model) | one-shot ceiling |
|---|---|---|
| occurrence top-1 | 17.7% [16.6, 18.9] | 10.8% [8.1, 14.2] |
| occurrence top-3 | 35.7% [34.2, 37.1] | 20.3% [16.6, 24.5] |

**The one-shot ceiling is below the no-model baseline.** That is the measured result and it
is published as it stands. It also fixes what "the agent wins" has to mean: the bar is the
baseline's 17.7%, not the ceiling's 10.8%. Arm A (start facts only) scores 8.0 points
[4.8, 11.3] below the ceiling on paired cases, so the investigators' findings do carry
information the model uses — which is the case for reading the docket at all.

The first like-for-like evaluation set is the 40 case IDs in
`../ntsb-spike/labelling/decidability.filled.csv`; `heldout-40` is that set, and at n=40 its
interval is far too wide to carry a claim on its own.

**Beating the ceiling is not enough to show agency** (0022). The spike's docket-shape addendum
(report §10) found about four in five development-era dockets readable in one call, so the loop
(arm C) must also beat arm B — every tool called in a fixed order, a fixed document filter, one
answer — at equal cost, in both availability conditions. Arm A is start facts only; S1's
one-shot ceiling is arm B without the docket; arm B with the docket runs before any loop code
exists. The four results that count against the loop and the six predictions are fixed in
decision 0022 and are published whichever way they come out.

**S2 measured arm B on `heldout-400` on GPT-5.6 Luna; the numbers live in
`docs/results/s2-bars.txt`.** Arm B calls every tool in a fixed order (here, the docket)
and answers once. Of the 400 sample cases, 358 were scored (42 failed). Occurrence top-1
is 22.3% [18.3%, 26.9%] and top-3 is 37.2% [32.3%, 42.3%]. Paired against the S1 one-shot
ceiling run on 357 shared, scored cases: occurrence top-1 +11.2% [+6.2%, +16.2%],
occurrence top-3 +16.0% [+10.6%, +21.0%].

**Arm B clears the honest no-model baseline on occurrence top-1**: the lower end of its
interval, 18.3%, sits above the baseline's 17.7%.

**On finding codes arm B is far below that same baseline, and this is stated plainly rather
than softened.** The baseline's finding recall@10 is 23.2% (flagged) and 21.0% (all); arm B's
is 9.1% [6.8%, 11.6%] (flagged) and 9.6% [7.4%, 11.9%] (all) — under half the baseline's
recall on both measures. Reading the docket in a fixed order without choosing what to read
raises the occurrence-code result and lowers the finding-code result.

**S2.4 re-measured the bars on GPT-6 Luna, the default model from S2.4 (decision 0073); the
numbers live in `docs/results/s24-bars.txt`.** Arm B on `heldout-400`: 336 of 400 cases
scored; occurrence top-1 26.5% [22.1%, 31.5%], top-3 39.9% [34.8%, 45.2%], finding
recall@10 (flagged) 9.9% [7.5%, 12.4%]. The lower end of its top-1 interval, 22.1%, is
above the no-model baseline's 17.7%; on finding codes it remains far below the baseline's
23.2%. Paired against the GPT-6 Luna ceiling on 336 cases: top-1 +14.3% [+9.2%, +19.3%],
top-3 +15.2% [+9.8%, +20.5%], finding recall@10 +7.3% [+4.8%, +9.8%] (319 cases). The
ceiling itself scores top-1 10.5% [7.9%, 13.9%], top-3 21.8% [18.0%, 26.1%] (399 of
400 cases scored), -0.3% [-3.8%, +3.3%] top-1 against GPT-5.6 Luna's ceiling. Paired against GPT-5.6
Luna's arm B on 334 cases (a model comparison, decision 0031 item 2, different commits):
top-1 +4.5% [+0.0%, +9.0%], finding recall@10 +1.4% [-0.8%, +3.6%]. **Arm B on GPT-6 Luna
is the bar**: S2.6 deferred its own held-out runs (decisions 0089, 0090), so no later bar
replaces it yet. Its 64 failures are 40 guard refusals
(analysis-narrative sentences in docket documents) and 24 reply-format failures, most of
them truncated replies (an ad-hoc split, not a scripted one: the S2.4 plan's Deviations,
2026-09-24/25). S2.6 re-examined the reply budget on `dev-400` and set it to 8,000 tokens
for every run from then on (decision 0084); S2.4's held-out run keeps its 2,000. Failed
cases are excluded from `n`, not counted wrong, and they cluster in fatal cases: 42 of 200
fatal cases failed against 22 of 200 non-fatal (`s24-bars.txt`'s `failed` column).

**S2.6 measured arm B with transcriptions on `dev-400` only; the numbers live in
`docs/results/s26-armB-v2-dev.txt`.** Its held-out runs are deferred (decisions 0089, 0090),
so S2.4's held-out arm B above stays the bar. B-v2 (text layers plus the transcriber's
reading of words in page images) against B-v1 (text layers only), both on GPT-6 Luna at one
commit, paired on 399 cases: occurrence top-1 +1.3% [-2.5%, +4.8%], top-3 +2.0% [-2.3%,
+6.3%], finding recall@10 +0.6% [-0.9%, +2.1%] (397 cases); fatal top-1 +2.5% [-3.0%,
+8.6%], non-fatal +0.0% [-5.0%, +4.5%]. The three overall differences are positive and every
interval includes zero: on development cases, transcription has not been shown to help. B-v2 alone
scores top-1 22.1% [18.3%, 26.4%], top-3 35.1% [30.6%, 39.9%]. **Most of what B-v2 misses on
occurrence codes is the NTSB's coding order, not missing evidence**
(`docs/results/s26-occurrence-misses-dev.txt`): the model's first guess is somewhere in the
NTSB's ordered sequence of occurrence codes on 140 of 399 cases (35.1%), but is its first
code on only 88 (22.1%); the commonest miss (33 cases) is "loss of control in flight" coded
first where the model said "aerodynamic stall/spin". The model receives the code tables as
bare labels, with no conventions or examples, so coding guidance is the next lever (an S2.7
Andy has proposed, before S3; decision 0089).

**S2.7 measured coding guidance on `dev-400` and checked it once on a sealed development
sample; it ran no held-out case, so S2.4's held-out arm B above stays the bar.** Two identical
arm B runs differ by occurrence top-1 +4.0% [+0.5%, +7.5%] and keep the same first guess on
only 246 of 399 cases (`docs/results/s27-round0-dev.txt`): a round must beat that noise. Andy's
hand-read of 40 misses put 34 down to coding (19 convention, 15 wrong phase) and 4 to a misread
or missing fact; the judge's narrative label failed its validation (32 of 46 agreements,
69.6%, against 75%) and carries no claim. **The GPT-6 Luna ordering check** (a second call that
re-orders the answer's occurrence codes with the pool's counts and the model's own account)
raised top-1 by +6.8% [+3.3%, +10.3%] and +9.8% [+6.0%, +13.8%] on two answer sets and beat
the plain lookup rule on both (`docs/results/s27-round1-dev.txt`); Jev did not
(`docs/results/s27-round1-jev2-dev.txt`). Of five guidance rounds, round 3 (loss of control
against stall/spin, +4.8% [+0.8%, +8.8%]) was kept, round 6 (the Aircraft control / Pilot
finding: finding recall@10 +11.4% [+8.2%, +14.6%], top-1 -6.3% [-10.5%, -2.5%]) was kept by
Andy's override of the do-no-harm rule (decision 0106), and rounds 2, 4 and 5 were dropped
(`docs/rounds/`). **The final setup on the sealed sample** (`docs/results/s27-sealed-dev.txt`):
top-1 27.5% [23.3%, 32.0%] against `dev-400`'s 25.1% [21.1%, 29.5%]; finding recall@10 22.0%
against 22.6%. The prediction that `dev-400` top-1 would end between 30% and 36% was not met.

**S3.1 measured the loop's noise floor on `dev-400` and read the loop against arm B there; it
ran no held-out case and makes no claim (0128), so S2.4's held-out arm B above stays the bar.
What follows is a noise floor and development readings, not a bar.** Two identical arm C runs
at `fd6053f` (prompt `s3-v1+ge17fecdc66ec+p947fac1c86a4`) score occurrence top-1 26.4% [22.3%,
31.0%] (394 scored) and 28.1% [23.9%, 32.8%] (391), finding recall@10 (flagged) 27.7% and
25.4% (each run's own table: `docs/results/s3-armc-a-vs-s3-armb-full-dev.txt`, `-b-`). Paired
on 387 cases they differ by top-1 -2.1% [-5.9%, +1.6%], top-3 +1.3% [-2.6%, +5.2%], finding
recall@10 +2.2% [-0.4%, +4.9%], and the first code changes on 162 of 387
(`docs/results/s3-noise-floor-dev.txt`); no third run was needed (within 4.0 points, 0130).
The runs agree on 2392 of 2608 read-or-skip decisions but make the same coding calls on only 3
of 387 cases. The format gate passed on both, 5 and 8 of 401 cases failing for format or tool
reasons against at most 8 (run b at the limit); an S3 round over the gate is dropped, and its
failed cases count as wrong (0136). Cost: $4.5711 and $4.4476 computed, $1.8400 and $1.9738
billed, with 71.6% and 66.7% of prompt tokens cached. **Against S3's full arm B** (0127), which
scores top-1 27.6%, top-3 50.1%, finding recall@10 27.3% (the S3.1 plan's 2026-10-03
Deviations entry), runs a and b differ by top-1 -1.0% [-5.3%, +3.3%] and +1.0% [-3.6%, +5.6%],
top-3 -11.4% [-16.0%, -6.9%] and -12.8% [-17.9%, -8.2%], finding recall@10 +0.4% [-2.0%,
+2.9%] and -1.5% [-3.9%, +0.6%] (`docs/results/s3-armc-a-vs-s3-armb-full-dev.txt`, `-b-`):
level on top-1 and findings, behind on top-3, at $4.57 and $4.45 computed ($1.84 and $1.97
billed) against arm B's $2.43 computed (about $2.19 billed) for its three parts. S3.2's
registration defines equal cost (0135 item 6). The loop's finding lead over S2.7's final arm B
(+5.1% [+2.5%, +7.7%] and +2.9% [+0.5%, +5.1%], `docs/results/s3-armc-a-vs-s27-armb-dev.txt`,
`-b-`) came from the coding tools, which arm B now calls in a fixed order: that step alone adds
finding recall@10 +4.7% [+2.5%, +7.0%] and top-1 +6.8% [+4.0%, +9.8%] to S2.7's answer
(`docs/results/s3-armb-tools-vs-s27-armb-answer-dev.txt`).

**S3.1's tuning record is its probes, not a round (0139).** The ordering check, run once over
run a as a diagnostic, does not raise the loop's top-1: +1.3% [-1.5%, +4.1%], 75 first codes
changed, 18 fixes and 13 breaks (`docs/results/s3-check-diagnostic-dev.txt`, 0137); the loop's
own `occurrence_usage` calls do that job. Cases whose NTSB probable-cause sentences match word
for word share their first occurrence code in only 619 of 1650 (37.5%; the event 71.9%, the
phase 49.2%; `docs/results/s3-coding-consistency-dev.txt`), but their flagged findings far more
(recall@10 74.1% [72.2%, 75.9%]; `docs/results/s3-finding-consistency-dev.txt`). Precedent
used mechanically does not help: the five nearest earlier cases to the loop's cause sentence
hold the NTSB's first code in 48 of 266 "always wrong" cases, "in between" by its rule
(`docs/results/s3-precedent-probe-dev.txt`), and their findings fall below the loop's own, and
only come level under the whole pool (0138), "not promising" both ways
(`docs/results/s3-finding-precedent-dev.txt`). Of run a's 1085 flagged findings, 499 (46.0%)
are in a category the loop never named, 213 (19.6%) lose the item and 80 (7.4%) the modifier;
the NTSB's item is the pool's commonest in only 46 of those 213, so item choice reads as
case-specific (`docs/results/s3-finding-misses-dev.txt`).

## Model access

**Claude Code develops and maintains this project.** Every model call the *product* makes —
evaluation runs and live scheduled calls alike — goes through OpenRouter
(`https://openrouter.ai/api/v1/chat/completions`, bearer token from the environment, never
in git). One transport for both, so the evaluated agent and the deployed agent are identical
at the transport layer too. Decision record: `docs/decisions/0009-model-access-via-openrouter.md`,
which supersedes the spike's "Claude exclusively" rule.

The agent's model was `openai/gpt-5.6-luna`, batch variant for evaluation (decision 0031,
which superseded the earlier plan to start at `anthropic/claude-sonnet-5` for continuity
with the spike), until S2.4. From S2.4 it is `openai/gpt-6-luna`, batch variant for
evaluation, at reasoning level `medium` (decision 0073, replacing 0031 item 1). The
reasoning level is stated on every agent call and recorded on every run's spec file and
run record; comparing reasoning levels is part of the model axis, examined with the model
axis after S3. GPT-6 Luna passed a one-case shape probe and a format gate on `dev-400`
with 0 of 401 format failures (`docs/results/s24-gate-dev.txt`). Model choice is a harness
parameter, not a constant, and the bar and the agent are always compared on the same model
(0022, 0031). Evaluation runs use the `:batch` variant (half price, no latency
requirement); the live path does not.

**The transcriber is a second model, not the agent's** (S2.6): `qwen/qwen3.5-122b-a10b`, at
its lowest reasoning level, instruction `t1`, pages drawn at 150 dots per inch
(`docket.transcribe.TRANSCRIBER`). The choice is **provisional and post hoc** (decision 0087):
no candidate passed the transcriber test's rule in either pass
(`docs/results/s26-transcriber-test.txt`, `docs/results/s26-transcriber-test-pass2.txt`), and
0087 overrode that outcome openly. It runs synchronously at the standard price, because the
batch service does not accept images. It copies words only; it never describes or interprets
a page (0079). **S2.7 kept it and turned transcription off by default** (decision 0120): none
of eight newer, cheaper vision models met the re-test's rule against Qwen
(`docs/results/s27-transcriber-retest.txt`), and transcribing a sample cost about ten times
answering it; a run reads transcriptions only at `--evidence-version v2`, and the S3 loop may
choose them as a tool. Every v2 run records its transcriber and page rule.

**The ordering check** (S2.7, decisions 0096, 0101, 0103) is a GPT-6 Luna call after the
answer, synchronous at the standard price (about $0.12 per 400 cases), run as a post-pass over
a finished run. **Jev** (TypeSafe's System One model) is admitted on a second transport for
the ordering check on development runs only (decision 0097), with `TYPESAFE_API_KEY`; it was
not kept. In S3 it runs in arm B only (0127), and once over arm C as a diagnostic (0137).

**Arm C** (S3.1) calls GPT-6 Luna at reasoning `medium` with native tool calling (0124): the
seven strict tool definitions identical on every call, `tool_choice` forcing each step's tool
(`"required"` during coding), parallel tool calls off, and an append-only conversation so the
provider's prompt cache holds. Evaluation runs go in batch rounds at the `:batch` price; smoke
runs use `--sync` at the standard price. The shape probe (`docs/results/s3-shape-probe.txt`)
found strict tools and forced tool choice honoured at both prices, and no need to pass the
reasoning back (`loop.PASS_REASONING` is `False`). Arm C's prompt version is
`s3-v1+g<12>+p<12>` (`+r<N>` for a tuning round): `+g` fingerprints the guidance, `+p` the
source of every module that composes model-facing text, so any edit to those files, a comment
included, changes it (0133). Batch replies carry no cost of their own, so a run's computed cost
prices every prompt token at the batch input rate, while the provider bills cached tokens
lower: for arm C and arm B's tool post-pass, S3's spend line and the monthly guard count what
was billed when every round reported it, else the computed price (0135). Both figures stay in
every record.

Two consequences to hold on to:
- The spike's £0.034/case and 57% top-1 were measured on a different transport, with the
  factual narrative as evidence. They are historical reference points, not bars. The bar is
  whatever S1 measures on this stack.
- `../ntsb-spike/config.yaml` prices Sonnet 5 at $3/$15 per MTok. It is $2/$10 (that is
  Sonnet 4.6's rate). S0 records the correct price in `sources.py` (0012).

A per-case cost cap is enforced in code, not just measured, because these calls are metered.
The spike's line was £0.05/case; it is re-measured in S1 and S3, because every case now reads
the docket (0013). Arm C's cap is $0.15 a case (`agent/run.py:CAP_USD`, the learning probe's;
S3.2 fixes it before any comparison run); the noise-floor runs cost $0.0114 and $0.0111 a case
computed, $0.0046 and $0.0049 billed (`docs/results/s3-noise-floor-dev.txt`). GPT-5.6 Luna
results elsewhere in this file are historical reference points, not bars.

## Commands

```bash
make check   # lint, mypy --strict and pytest — what CI runs
make lint    # ruff format --check, ruff check, import-linter, deptry, vulture
make type    # mypy
make test    # pytest
make ingest  # fetch event months into data/raw (uv run ntsb-ingest fetch <first> <last>)
make build   # build data/processed/cases.parquet from the raw store
make scan    # uv run python -m scripts.corpus_scan — guard statistics, counts only
make probe   # uv run python -m scripts.openrouter_probe — the S1 fixture-recording probe (§7.1)
make bars    # baseline + ceiling/A runs on heldout-40/heldout-400 + the S1 bars report (§6.5)
make docket-scan       # uv run python -m scripts.docket_scan — dev-400 docket shape,
                        #   cached and resumable (S2)
make scan-docket       # uv run python -m scripts.corpus_scan --docket — the deny-list
                        #   threshold, from the docket-scan cache (S2)
make armb               # arm B on dev-400, the stage's headline result (S2)
make s2-bars            # arm B on heldout-400 — ONCE; appends to
                         #   docs/results/heldout-ledger.md (S2)
make docket-shape-open  # uv run python -m scripts.docket_shape_open — open-split docket
                         #   shape, numbers only, nothing cached (S2, 0024/0040)
make s24-probe        # the S2.4 shape probe: one dev case on GPT-6 Luna, standard then batch
make s24-gate         # the S2.4 format gate: ceiling on dev-400 with GPT-6 Luna (about $0.22)
make s24-bars-ceiling # the ceiling on heldout-400 with GPT-6 Luna -- ONCE; commit its
                      #   ledger row before s24-bars-b
make s24-bars-b       # arm B on heldout-400 with GPT-6 Luna -- ONCE, after
                      #   s24-bars-ceiling's row is committed
make ongoing-probe      # uv run python -m scripts.ongoing_docket_probe — fixes the recorder's
                         #   no-docket outcome, numbers only (S2.5 §10.1)
make record             # uv run ntsb-record run — one nightly pass (S2.5, Task 10); --verbose
                         #   and --dry-run also accepted
make change-feed-probe  # uv run python -m scripts.change_feed_probe — the change feed's shape,
                         #   one-shot (S2.5 §5.3, 0065)
make recorder-report    # uv run python -m scripts.recorder_report — the recorder's counts-only
                         #   report, from NTSB_STORE (S2.5 §10.2)
make page-kinds               # scripts.page_kinds — dev-400 page kinds, counts only; free (S2.6)
make analysis-handcheck       # scripts.analysis_handcheck sheet — the private marking page for
                              #   analysis sentences in dev-400 dockets; free (S2.6, 0077)
make s26-reply-budget         # arm B on dev-400 at the old 2,000-token reply budget (S2.6, 0084)
make s26-reply-budget-roomy   # the same at 16,000 tokens, to size the budget (S2.6, 0084)
make s26-inventory-probe      # scripts.page_inventory sample + probe: draws the 330 pages,
                              #   labels one (under a cent)
make s26-inventory            # scripts.page_inventory label + check (about $0.20)
make s26-transcriber-keys     # scripts.transcriber_test keys — the answer keys (cents)
make s26-transcriber-probe    # one invented page per candidate; records the fixtures
make s26-transcriber-run      # every candidate on every key page, one retry, Andy's pages
make s26-transcriber-resolution MODEL=<id>  # the chosen model at 200 dpi, one retry
make s26-transcriber-recheck  # decision 0086's second-pass marking pages; free
make s26-transcribe-dev-dry PER_PAGE=<usd>  # counts and prices dev-400's pages; free
make s26-transcribe-dev PER_PAGE=<usd>      # reads dev-400's image pages once, into the
                                            #   cache (paid; run with 0.0017 on 2026-09-26)
make s26-dev-runs PER_CASE=<usd>            # arm B v1 then v2 on dev-400, one commit
                                            #   (run with 0.0042 on 2026-09-26)
```

S2.7's targets (`s27-*`; each paid one first runs `make stage-spend EST=<usd>`, which refuses a
step past the stage's $25 line, counted by commit on S2.7's own branches, decisions 0098, 0107):

```bash
make stage-spend EST=<usd>          # S2.7's spend so far; exit 1 past the $25 line; free
make s27-coding-stats               # the statistics pool's coding counts, once (0094); free
make s27-noise-floor PER_CASE=<usd> # B-v1 repeated: the noise floor (paid)
make s27-judge RUN=<id>             # the judge on a development run (paid, standard price)
make s27-round0-cards RUN=<id>      # Andy's Round 0 marking page; free
make s27-round0-results REPEAT=<id> MARKS=<csv> LABELS=<v>  # Round 0's results file; free
make s27-check RUN=<id> WAY=rule|luna|jev|jev2  # the ordering check as a post-pass
make s27-round1-results REPEAT=<id> # Round 1's reading rule; free
make s27-round1-jev2-results        # the registered second Jev check (0103); free
make s27-check-guidance GUIDANCE="<names>"  # no guidance sentence in withheld text; free, local
make s27-round GUIDANCE="<names>" PER_CASE=<usd>  # one guidance round's run (paid)
make s27-round-result N=<n> RUN=<id> REFERENCE=<id> NOISE="<a> <b>" [FINDING=1]  # its reading
make s27-round-comparisons          # the numbers decision 0106 cites; free
make s27-sealed-run PER_CASE=<usd>  # the final setup on dev-seal-400, ONCE (paid)
make s27-sealed-results SEALED=<id> # the sealed result and the prediction; free
make s27-page-value                 # what each page rule keeps, from the dev-400 cache; free
make s27-models-fetch               # OpenRouter's public model list, saved; free
make s27-shortlist                  # decision 0100's filter over the saved list; free
make s27-transcriber-probe          # one invented page per shortlisted model (paid, cents)
make s27-batch-image                # one batch request with an image (paid, a fraction of a cent)
make s27-retest-verify              # Qwen's second pass reproduced from the cache; free
make s27-retest-run                 # every candidate on S2.6's four keys (paid)
make s27-retest-automatic           # the candidates still in the running before marking; free
make s27-retest-pages MODELS="<ids>"  # Andy's photo and scan marking pages; free
make s27-retest-score MARKED="<ids>"  # decision 0100's rule applied; free
make s27-routing-pages / s27-routing-tally  # exploratory: text-and-image page routing; free
make s27-retest-readable            # the post-hoc readable-lines check; free
```

S3's targets (`s3-*`; each paid one first runs `scripts.stage_spend --stage s3 --estimate <usd>`,
which refuses a step past S3's $50 line, counted by commit on `s3-` branches holding S3's first
commit `777c2a5`; S3.1's share is $20, decision 0128; runs count what was billed, 0135):

```bash
make s3-spend EST=<usd>             # S3's spend so far; exit 1 past the $50 line; free
make s3-draw-sealed                 # draws dev-seal-s3-400, ONCE (seed 20260930); free
make s3-coding-stats                # S3's statistics file, the pool less dev-seal-s3-400; free
make s3-shape-probe                 # the native-tool shape probe, ONCE (paid, cents)
make s3-smoke-sync                  # arm C on dev-400's first case, standard price (cents)
make s3-smoke-batch                 # arm C on dev-400's first 20 cases, batch rounds (paid)
make s3-noise-floor                 # arm C on dev-400 from the frozen commit; run twice (paid)
make s3-noise-report RUNS="<a> <b>" # noise floor, format gate, third-run rule; free
make s3-armb-tools RUN=<id>         # arm B's tool post-pass over a finished arm B run (paid)
make s3-check-diagnostic RUN=<id>   # the ordering check over arm C's run a, ONCE (paid, 0137)
make s3-round N=<n>                 # a registered tuning round's arm C run (paid; none run, 0139)
make s3-round-result N=<n> RUN=<id> REFERENCE=<id> NOISE="<a> <b>"  # its reading (0136); free
make s3-case-groups RUNS="<ids>"    # always right / always wrong / flipping, counts only; free
make s3-trail-pages RUN=<id> GROUPS=<json>  # private trail reading pages, never committed; free
make s3-miss-kinds RUNS="<ids>" GROUPS=<json>  # how the loop's first code misses; free
make s3-precedent-probe RUNS="<a> <b>" GROUPS=<json>  # precedent for first codes; free
make s3-precedent-pages RUN=<id> GROUPS=<json>  # its private reading page; free
make s3-coding-consistency          # do identical cause sentences share a first code; free
make s3-finding-consistency         # the same for flagged findings; free
make s3-finding-precedent RUNS="<a> <b>"  # precedent's findings against the loop's; free
make s3-finding-misses RUNS="<a> <b>"     # where the loop's findings miss; free
```

The targets from `s3-miss-kinds` on run exploratory scripts (decision 0059, `scripts/exploratory/`):
no model call, and they decide nothing. What any `s3-*` target commits is counts only; the
reading pages and case lists go under `NTSB_RUNS_DIR`, never committed.

The `s26-*` targets that take `MODEL`, `PER_PAGE` or `PER_CASE` stop with a `make` error when
the variable is unset. S2.6 wrote no held-out target: its held-out runs are deferred (0090).

`ntsb-eval` is the evaluation harness (S1 spec §6.5; arm `B` and `release` added in S2):
`ntsb-eval baseline|run|report|judge|threshold|release`,
each with `--out PATH` to also write the printed text to a file; `run` takes `--arm` (`A`, `B`
or `ceiling` — `B` reads the docket), `--sample`, `--exclude ROLE`, `--include case_number`,
`--limit N`, `--sync`, `--cap-usd`, `--budget-usd`, `--resume RUN_ID` and
`--expected-cost-per-case-usd`; the last is required for any large `--arm B` run rather than
optional, because without it the budget guard projects the run at the per-case cap (e.g.
401 x $0.05 for `dev-400`) and refuses it against the monthly budget before a single model
call, so a deliberate, still-conservative estimate (`armb`, `s2-bars` pass `0.01` against a
real cost of about $0.0075/case) is needed to get the guard to let a legitimate run start;
`release RUN_ID` clears a dead run's budget reservation (0045) so its held budget can be
reused; `report` takes a run id or `--latest ARM SAMPLE`, and `--against`/`--against-latest`
to compare — it prints a `failures by reason:` line and labels cross-model comparisons;
`judge` refuses a non-`dev-400` run without `--validated` (§8).

S2.6 added: `run --evidence-version v1|v2|v3` (default `v1`; v2 needs arm B and a sample
`transcribe` has finished; v3 is refused, 0076, 0090, 0091) and `run --max-output-tokens N`
(default 8,000, recorded on every run, 0084); `report --versions-compared`, which allows a
comparison across evidence versions under a labelled heading; `report --against` now prints
each paired block again for fatal and non-fatal cases, and adds blocks for the cases with
transcribed pages (across versions) and for cases unmarked in both runs (where marks exist); and
`transcribe --sample S --expected-cost-per-page-usd USD [--workers 8] [--retry-failed]
[--dry-run]`, which reads a sample's image pages once into the transcription cache (0081). The
expected cost per page must be above zero; it sets the job's budget reservation, and the job
stops once that is spent. The finished-transcription marker, which a v2 run checks for, is
written only when at most 2% of the chosen pages failed. `transcribe` refuses a held-out
sample (0090). A fresh run, or a preparation job, refuses a run folder that already exists.

S2.7 added: `run --guidance NAME` (repeatable, in stacking order; files
`scoring/guidance/r<N>-<slug>.md`; refused unless the round's registration
`docs/rounds/s27-round-<N>.md` is committed, 0098; a guided run's prompt version is the base,
`s1-v6` since decision 0105, plus `+g` and 12 characters of the guidance fingerprint, and the
run record names the files); `run --transcriber MODEL --page-rule all|image-only|image-only+thin-layer`
(v2 only; a v2 run must name both and a v1 run neither, and `report --against` refuses two v2
runs that read differently unless `--versions-compared`); `check RUN_ID --way
rule|luna|jev|jev2`, the ordering check as a post-pass writing a derived run folder
`<run id>-check-<way>` whose cost is the check's alone (0096; `resolve_latest` skips derived
and guided runs); and `transcribe --model --page-rule` (every finished-transcription marker names
its page rule). The sample `dev-seal-400` (the sealed development sample, 0095) is refused by
every command until `docs/rounds/s27-sealed.md` is committed; it was used once, on 2026-09-29.

S3.1 added: `run --arm C`, the loop (`agent/run.py:AgentRunner`): evidence v1 only; the
guidance `r3-loc-stall` and `r6-aircraft-control` when none is named, any other refused outside
a round; a $0.15 per-case cap by default; S3's statistics; batch rounds unless `--sync` (with
`--price-variant standard`), and `--resume RUN_ID` waits on a round already sent rather than
sending it again. Its folder adds `trail.jsonl` (one `AgentCall` per model call: tool, arguments,
result size, tokens, cost, never a document's text), `replies.jsonl` and `rounds.jsonl` to arm
B's files, so `report --against` compares it unchanged; for arm C, `report` prints an `unread`
line and the cached share of prompt tokens. `run --without suggest_codes|coding` (arm C only,
repeatable) is a tool ablation, and `run --round N` a tuning round, refused unless
`docs/rounds/s3-round-<N>.md` is committed; `resolve_latest` skips both, and every derived run.
`tools RUN_ID [--sync] [--budget-usd]` is arm B's fixed tool post-pass (0127), writing
`<run id>-tools` (prompt `<source>+tools-s3+p<12>`); then `check <run id>-tools --way luna
--stats s3` completes arm B. `check` gains `--stats s27|s3` (default `s27`); a `-tools` run or
an arm C run is checked with `s3` only, and an arm C run with `--way luna` only, as a
diagnostic (0137): `report <check id> --against <source>` prints the first codes changed, with
fixes and breaks. Arm C and
the post-pass refuse `dev-seal-400`; `dev-seal-s3-400` is refused by every command until
`docs/rounds/s3-registration.md` is committed (0129). Spend rows gain the kind `probe` (paid
work that tests a shape or a flow, 0131): the learning probe's three jobs were relabelled to
it, their original rows kept beside them as `spend-before-relabel.jsonl`, which the budget code
never reads; the probe's $1.1954 is outside S3's line (0128).

`uv run python -m scripts.make_fixture` creates redacted development-split fixtures (0015);
`uv run python -m scripts.check_docs` is the documentation check decision 0017's stage
close-out depends on. Settings come from the environment (`NTSB_` prefix, 0012) or `.env`:
`NTSB_API_KEY` (the NTSB Enterprise API key, required for `make ingest`, never printed or
committed), `NTSB_DATA_DIR` (default `data`; nothing under it is committed),
`OPENROUTER_API_KEY` (the model access decision 0009 uses), `NTSB_RUNS_DIR` (default
`data/runs`, never committed), `NTSB_MONTHLY_BUDGET_USD` (default 40 during development,
decision 0083; it also counts transcription and inventory spend rows, 0081; set to 50 in the
environment of every paid command in September 2026 only, decision 0104),
`TYPESAFE_API_KEY` (Jev, for the S2.7 ordering check on development runs only, 0097; never
printed or committed),
`NTSB_EXPECTED_COST_PER_CASE_USD` (unset until `make probe` measures one; falls back to the
cost cap), `NTSB_DOCKET_DIR` (where fetched docket documents are cached; defaults to
`<NTSB_DATA_DIR>/docket`, so it moves with `NTSB_DATA_DIR` unless set explicitly; never
committed), `NTSB_DOCKET_SECONDS_PER_REQUEST` (the floor between requests to
`data.ntsb.gov`, default 2.0 seconds, enforced in code so it cannot be set to 0 in
production) and `NTSB_TRANSCRIPTION_DIR` (where per-page transcriptions are cached; defaults
to `<NTSB_DATA_DIR>/transcriptions`, so it moves with `NTSB_DATA_DIR` unless set explicitly;
never committed, S2.6 decision 0081). A run from a git worktree needs `NTSB_DATA_DIR` pointed at the main checkout's `data/` (a worktree's own `data/` is empty), which also moves `runs_dir` and `docket_dir` (0057). S3.1 added no setting.

The recorder (`ntsb-record run`, S2.5 Task 10) reads two more: `NTSB_STORE` (where the SQLite
store lives — a local path, default `<NTSB_DATA_DIR>/recorder.sqlite`, or an `s3://bucket/key`
URL; `store/sync.py` pulls and pushes it around an S3 working file under `NTSB_DATA_DIR`) and
`NTSB_COMMIT_SHA` (set only inside the container image, which has no `.git`; everywhere else
this stays unset and `git` itself supplies the commit).
