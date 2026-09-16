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
  (the spike's probe scripts hard-code temporary paths and are not reusable as-is).
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

## Eval bars to beat (build-brief §6, held-out split)

**These are the spike's numbers, measured on free-text output through the `claude` CLI,
with the factual narrative as evidence. Output is now code-constrained (0006), the transport
is OpenRouter (0009), and the factual narrative is withheld (0013). None of the one-shot
figures below is a bar, and the 88/12 narrative split no longer exists: every case lacks a
narrative. The nearest precedent is 12% (n=16). S1 re-measures the ceiling on the stack that
will actually run and sets the bars. The baseline is unaffected; the cost ceiling is
re-measured because every case now reads the docket.**

| metric | baseline (n=1,000) | one-shot ceiling (n=40) |
|---|---|---|
| occurrence top-1 | 16.2% | 57% |
| occurrence top-3 | 32.2% | 65% |
| no-narrative cases, top-1 | not computed | 12% (n=16) |
| cost per case | — | £0.034 measured |

*Historical — the build brief's definition, written against the narrative split and replaced
by the bars S1 sets:* "The agent wins" means: ≥50% top-1 on no-narrative cases (below ~30% means the docket tool
isn't delivering); overall held-out top-1 above 57%, first like-for-like on the same 40 cases
then a larger sample; an ablation (docket tool on/off) shows the drop concentrated in
no-narrative cases; abstention falls on no-narrative cases as the docket supplies evidence but
stays sensible where only physical evidence could decide it; cost stays under £0.05/case on
average including tool calls, enforced by a hard cap in code.

The first like-for-like evaluation set is the 40 case IDs in
`../ntsb-spike/labelling/decidability.filled.csv`.

**Beating the ceiling is not enough to show agency** (0022). The spike's docket-shape addendum
(report §10) found about four in five development-era dockets readable in one call, so the loop
(arm C) must also beat arm B — every tool called in a fixed order, a fixed document filter, one
answer — at equal cost, in both availability conditions. Arm A is start facts only; S1's
one-shot ceiling is arm B without the docket; arm B with the docket runs before any loop code
exists. The four results that count against the loop and the six predictions are fixed in
decision 0022 and are published whichever way they come out.

## Model access

**Claude Code develops and maintains this project.** Every model call the *product* makes —
evaluation runs and live scheduled calls alike — goes through OpenRouter
(`https://openrouter.ai/api/v1/chat/completions`, bearer token from the environment, never
in git). One transport for both, so the evaluated agent and the deployed agent are identical
at the transport layer too. Decision record: `docs/decisions/0009-model-access-via-openrouter.md`,
which supersedes the spike's "Claude exclusively" rule.

The agent's model starts at `anthropic/claude-sonnet-5` to keep continuity with the spike;
model choice is a harness parameter, not a constant. Evaluation runs use the `:batch` variant
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
```

`ntsb-eval` is the S1 evaluation harness (spec §6.5): `ntsb-eval baseline|run|report|judge|threshold`,
each with `--out PATH` to also write the printed text to a file; `run` takes `--arm`, `--sample`,
`--exclude ROLE`, `--include case_number`, `--limit N`, `--sync`, `--cap-usd`, `--budget-usd`;
`report` takes a run id or `--latest ARM SAMPLE`, and `--against`/`--against-latest` to compare;
`judge` refuses a non-`dev-400` run without `--validated` (§8).

`uv run python -m scripts.make_fixture` creates redacted development-split fixtures (0015);
`uv run python -m scripts.check_docs` is the documentation check decision 0017's stage
close-out depends on. Settings come from the environment (`NTSB_` prefix, 0012) or `.env`:
`NTSB_API_KEY` (the NTSB Enterprise API key, required for `make ingest`, never printed or
committed), `NTSB_DATA_DIR` (default `data`; nothing under it is committed),
`OPENROUTER_API_KEY` (the model access decision 0009 uses), `NTSB_RUNS_DIR` (default
`data/runs`, never committed), `NTSB_MONTHLY_BUDGET_USD` (default 25) and
`NTSB_EXPECTED_COST_PER_CASE_USD` (unset until `make probe` measures one; falls back to the
cost cap).
