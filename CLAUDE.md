# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this repo is

The agent itself: it determines the probable cause of a US general-aviation accident from
investigator-gathered evidence, scored against the NTSB's own published verdict. It is built on
the decision made in `../ntsb-spike/` (spike complete, decision: build — see
`../ntsb-spike/docs/spike-report.md` and `../ntsb-spike/docs/build-brief.md`, especially §6
"Evaluation plan" and §7 "What a build repo needs that this one does not have"). **S0
(foundation) is built**: strict tooling, data ingestion, the evidence/synthesis/verdict split
with its layered leakage guard, and a model seam — see "Commands" below. The agent loop, the
docket tool and the evaluation harness are not built yet. Read build-brief §7 before writing
any code, then
`docs/specs/2026-09-12-architecture-and-roadmap.md`, the agency design
(`docs/specs/2026-09-14-agency-hypothesis-trail-design.md`, which every stage from S1 to S5
takes a part of), and the current stage's specification (S0, closed:
`docs/specs/2026-09-13-s0-foundation-design.md`), which amend the brief where they differ.

## Required components (build-brief §7)

- **Agent loop and tool interface**, with a step budget, an abstain path, and a log of every
  step and its cost. Each step records the agent's hypothesis as codes with probabilities, and
  the trail is scored per step (0021). Tools are grouped by source and measured arrival; day-1
  fields are start facts, and every tool result goes through `split_record` with the other
  roles excluded, never a second assembler (0023). Tool #1 is the docket; the record's weather
  fields are a tool in S3; the Iowa Mesonet archive (params already verified in the spike's
  `config.yaml`) comes later, with its own provenance rule.
- **Docket client and PDF classifier/extractor** as an importable module with test fixtures
  (the spike's probe scripts hard-code temporary paths and are not reusable as-is). **Built in
  S2**: `docket/client.py` (caching, polite rate limit), `docket/listing.py` and
  `docket/manifest.py` (the document listing), `docket/classify.py` and `docket/extract.py`
  (born-digital text extraction and classification), `docket/filter.py` (arm B's document
  filter) and `docket/attach.py`, with offline fixtures under `tests/fixtures/docket` and arm
  `B` wired into the eval harness.
- **Code-constrained output**: the model picks from a supplied list of NTSB occurrence/finding
  codes with their meanings, not free text, so scoring is exact-match. Seed the code lookup
  table from the spike's `decidability_form.build_code_lookups()`.
- **Eval harness**: one command, fixed case list, ablation flags, per-slice reporting
  (slices decided in S1; narrative presence no longer applies, 0013; fatal / non-fatal is
  proposed before investigation class, whose mix differs by era), confidence intervals,
  cost per run, the three arms (0022) and the full and masked availability conditions (0023).
  The spike's `baseline.py` and `oneshot.py` are numerical anchors, not a harness.
- **SQLite predictions store**: case, evidence-hash, timestamp, answer, cost per row; docket
  document lists with first-seen timestamps; resolution outcomes.
- **Scheduler and resolution watcher**: poll open cases and dockets, run the watcher, lock
  predictions (design notes suggest committing hashed rows to git for tamper-evidence).
- **Tests and CI**: the layered leakage guard's tests, including a mutation test that proves
  the boundary test can fail (0016); docket parser fixtures; a check that held-out cases never
  appear in development fixtures, judged by event date; a redaction check on fixtures (0015);
  from S2, a test that docket documents classified as synthesis never reach the model; and a
  retrieval-contamination test if similar-case search is ever added.
- **Data ingestion as a job** (not `fetch.py <start> <end>`): S0 fetches by event month into a
  hashed manifest and rebuilds one processed file of index columns plus the raw record (0014);
  incremental updates by modification date and status arrive with the recorder in S2.5. Raw
  data kept out of git.
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
11. **Squash merges; each closed stage is a tagged release** (0018). Pull requests are
    squash-merged only, titled `<stage>: <name>`. The close-out sets `version` in
    `pyproject.toml`; after the merge Andy runs `gh release create --generate-notes`. There is
    no `CHANGELOG.md`. From S1, every evaluation run and prediction row records the commit SHA
    and whether the tree had uncommitted changes.

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

The two numbers to hold in mind, both on `heldout-400` at commit `c717ab5`:

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

**S2 measured arm B on `heldout-400`; the numbers live in `docs/results/s2-bars.txt`.** Arm B
calls every tool in a fixed order (here, the docket) and answers once. Of the 400 sample
cases, 358 were scored (42 failed). Occurrence top-1 is 22.3% [18.3%, 26.9%] and top-3 is
37.2% [32.3%, 42.3%]. Paired against the S1 one-shot ceiling run on 357 shared, scored cases:
occurrence top-1 +11.2% [+6.2%, +16.2%], occurrence top-3 +16.0% [+10.6%, +21.0%].

**Arm B clears the honest no-model baseline on occurrence top-1**: the lower end of its
interval, 18.3%, sits above the baseline's 17.7%.

**On finding codes arm B is far below that same baseline, and this is stated plainly rather
than softened.** The baseline's finding recall@10 is 23.2% (flagged) and 21.0% (all); arm B's
is 9.1% [6.8%, 11.6%] (flagged) and 9.6% [7.4%, 11.9%] (all) — under half the baseline's
recall on both measures. Reading the docket in a fixed order without choosing what to read
raises the occurrence-code result and lowers the finding-code result.

## Model access

**Claude Code develops and maintains this project.** Every model call the *product* makes —
evaluation runs and live scheduled calls alike — goes through OpenRouter
(`https://openrouter.ai/api/v1/chat/completions`, bearer token from the environment, never
in git). One transport for both, so the evaluated agent and the deployed agent are identical
at the transport layer too. Decision record: `docs/decisions/0009-model-access-via-openrouter.md`,
which supersedes the spike's "Claude exclusively" rule.

The agent's model is `openai/gpt-5.6-luna`, batch variant for evaluation (decision 0031,
which supersedes the earlier plan to start at `anthropic/claude-sonnet-5` for continuity with
the spike). Model choice is a harness parameter, not a constant, and the model axis is measured
after S3 — the bar and the agent are always compared on the same model (0022, 0031). Evaluation runs use the `:batch` variant
(half price, no latency requirement); the live path does not.

Two consequences to hold on to:
- The spike's £0.034/case and 57% top-1 were measured on a different transport, with the
  factual narrative as evidence. They are historical reference points, not bars. The bar is
  whatever S1 measures on this stack.
- `../ntsb-spike/config.yaml` prices Sonnet 5 at $3/$15 per MTok. It is $2/$10 (that is
  Sonnet 4.6's rate). S0 records the correct price in `sources.py` (0012).

A per-case cost cap is enforced in code, not just measured, because these calls are metered.
The spike's line was £0.05/case; it is re-measured in S1 and S3, because every case now reads
the docket (0013).

**S2.4 model switch to GPT-6-Luna.** The agent's default model is now `openai/gpt-6-luna` (batch
variant for evaluation), at reasoning level `medium` (0073, replacing decision 0031 item 1). The
reasoning level is stated on every agent call and recorded on every run's spec file and run record.
GPT-6-Luna passed a one-case shape probe and a format gate on `dev-400` with 0 of 401 format
failures (documented in `docs/results/s24-gate-dev.txt`). GPT-5.6-Luna results elsewhere in this
file are historical reference points, not bars. The reasoning-level axis is examined with the model
axis after S3.

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
make docket-scan       # uv run python -m scripts.docket_scan — dev-400 docket shape, cached and resumable (S2)
make scan-docket       # uv run python -m scripts.corpus_scan --docket — the deny-list threshold, from the docket-scan cache (S2)
make armb               # arm B on dev-400, the stage's headline result (S2)
make s2-bars            # arm B on heldout-400 — ONCE; appends to docs/results/heldout-ledger.md (S2)
make docket-shape-open  # uv run python -m scripts.docket_shape_open — open-split docket shape, numbers only, nothing cached (S2, 0024/0040)
make s24-probe        # the S2.4 shape probe: one dev case on GPT-6 Luna, standard then batch
make s24-gate         # the S2.4 format gate: ceiling on dev-400 with GPT-6 Luna (about $0.22)
make s24-bars-ceiling # the ceiling on heldout-400 with GPT-6 Luna -- ONCE; commit its ledger row before s24-bars-b
make s24-bars-b       # arm B on heldout-400 with GPT-6 Luna -- ONCE, after s24-bars-ceiling's row is committed
```

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
to compare — it prints a `failures by reason:` line and labels cross-model comparisons; `judge` refuses a non-`dev-400` run without `--validated` (§8).

`uv run python -m scripts.make_fixture` creates redacted development-split fixtures (0015);
`uv run python -m scripts.check_docs` is the documentation check decision 0017's stage
close-out depends on. Settings come from the environment (`NTSB_` prefix, 0012) or `.env`:
`NTSB_API_KEY` (the NTSB Enterprise API key, required for `make ingest`, never printed or
committed), `NTSB_DATA_DIR` (default `data`; nothing under it is committed),
`OPENROUTER_API_KEY` (the model access decision 0009 uses), `NTSB_RUNS_DIR` (default
`data/runs`, never committed), `NTSB_MONTHLY_BUDGET_USD` (default 25),
`NTSB_EXPECTED_COST_PER_CASE_USD` (unset until `make probe` measures one; falls back to the
cost cap), `NTSB_DOCKET_DIR` (where fetched docket documents are cached; defaults to
`<NTSB_DATA_DIR>/docket`, so it moves with `NTSB_DATA_DIR` unless set explicitly; never
committed) and `NTSB_DOCKET_SECONDS_PER_REQUEST` (the floor between requests to
`data.ntsb.gov`, default 2.0 seconds, enforced in code so it cannot be set to 0 in
production). A run from a git worktree needs `NTSB_DATA_DIR` pointed at the main checkout's `data/` (a worktree's own `data/` is empty), which also moves `runs_dir` and `docket_dir` (0057).
