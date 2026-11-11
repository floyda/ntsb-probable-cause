# Everything in `scripts/`

Run any Python script with `uv run python -m scripts.<name>`; most have a `make` target, listed in
the `Makefile`. **Every script's module docstring opens with a `Status` block** saying which kind
it is and what it produced. Read that block before reading the file. The kinds are:

- *live tool* or *live check*: rerun it when its input changes;
- *live measurement*: it reads finished runs and writes a committed result, counts only;
- *one-shot, complete*: it produced a committed file and its job is done. It is kept because this
  project publishes no number without the script behind it;
- *exploratory* (decision 0059): it decides nothing and sets no bar;
- *deprecated*: the mechanism it measured no longer exists, and the script is usually the
  evidence that removed it.

Result files named below are under `docs/results/`.

## Checks, fixtures and tables

| script | kind | what it produced |
|---|---|---|
| `check_docs` | live check | nothing; fails CI when the docs disagree (0017) |
| `check_fixtures_redacted` | live check | nothing; runs in CI and pre-commit (0015, 0046, 0049, 0058) |
| `check_guidance` | live check | nothing; exits 1 if a guidance sentence matches any development case's withheld text. Local only, since CI has no data (S2.7) |
| `make_fixture` | live tool | the redacted record fixtures (0015) |
| `make_docket_fixture` | live tool | the docket fixture pool and the title hand-check sheet (0037) |
| `build_code_tables` | live tool | the scoring code tables, `s1-code-tables.txt` |
| `build_title_vocab` | live tool | `docket/vocab/title_words.txt` (0046, 0058) |
| `coding_stats` | one build per stage | the statistics pool's coding counts: `--stage s27` (0094) and `--stage s3` (0129), with `s27-coding-stats.txt` and `s3-coding-stats.txt` |
| `openrouter_probe` | live tool | the recorded OpenRouter response fixtures |
| `copy_eval_ids` | one-shot | the evaluation ID fixtures (0015) |
| `draw_samples` | one-shot | the fixed `heldout-400` / `dev-400` ID lists. **Do not redraw** (0026) |
| `draw_sealed` | one-shot per sample | the sealed samples `dev-seal-400` (0095) and `dev-seal-s3-400` (0129); `--verify` re-draws and compares |
| `stage_spend` | live check | nothing; a stage's spend by commit against its line. Every paid target of S2.7, S3, S3.3 and S4 runs it first (0098, 0128, 0163, 0170) |
| `_live_fence` | live helper | nothing; refuses a live run's cases before any report script reads them (0024) |

## S0 to S2: the corpus and the docket

| script | kind | what it produced |
|---|---|---|
| `reconcile_spike` | one-shot | `s0-reconciliation.txt` |
| `corpus_scan` | live tool | `s0-corpus-scan.txt`; `--docket` → `s2-threshold.txt` |
| `docket_scan` | live tool | `s2-shape-dev.txt`, and the dev-400 docket cache five other scripts read |
| `docket_shape_open` | one-shot | `s2-shape-open.txt` (0024, 0040) |
| `docket_leak_scan` | one-shot | `s2-docket-leak.txt`, the evidence for 0050 |
| `name_coverage` | one-shot | `s2-name-coverage.txt`, the evidence for 0046, which is live |
| `narrative_coverage` | one-shot | the two `s2-narrative-coverage` files; **rerun if the guard changes** |
| `handcheck_page` | one-shot | the private marking page behind the committed hand-check sheet (0049) |
| `doctype_scan` | **deprecated** | `s2-doctype.txt`; the photograph exclusion it measured was removed by 0052 |
| `score_handcheck` | **deprecated** | `s2-handcheck.txt`; all three mechanisms it grades were removed by 0051, 0052 and 0056 |

One committed result has no script: `s2-filter-compare.txt` was produced by
`scripts/filter_compare.py`, added at commit `74c22b9` and removed at `3856a04` when decision 0052
made arm B attach every readable document and 0054 retired the comparison. The file is cited by
decisions 0043 and 0052; the script is recoverable from git history.

## S2.5: the recorder

| script | kind | what it produced |
|---|---|---|
| `change_feed_probe` | one-shot | `tests/fixtures/api/change_feed_shape.json` and `s25-change-feed.txt` (spec S2.5 §5.3, 0065) |
| `recorder_report` | live tool | the recorder reports (`s25-`, `s3-` and `s5-recorder-report-<date>.txt`) from `NTSB_STORE`, counts only (spec S2.5 §10.2) |
| `ongoing_docket_probe` | one-shot | `s25-ongoing-dockets.txt`; fixed the recorder's `no-docket` outcome (spec §10.1). `outcome_for_error` and its "not released" check have since moved into the library (0059) |

`scripts/recorder_bridge.sh` is a shell script with the same `Status` block (0059). It wrapped
`uv run ntsb-record run` on Andy's Mac before the recorder moved to AWS; see
`docs/runbooks/recorder-bridge.md`.

## S2.6 and S2.7: transcription and coding guidance

| script | kind | what it produced |
|---|---|---|
| `page_kinds` | live tool | `s26-page-kinds.txt`, and the private page frame the inventory and transcriber test sample from (spec S2.6 §6.2) |
| `analysis_handcheck` | one-shot | `s26-analysis-handcheck.txt`, the evidence for 0077 |
| `marking_page` | live helper | the private marking pages every hand-check renders through |
| `page_inventory` | one-shot | `s26-inventory.txt`: what image-bearing pages show (spec S2.6 §6) |
| `transcriber_test` | one-shot | `s26-transcriber-test.txt` and `s26-transcriber-test-pass2.txt` (0080, 0086, 0087); `estimate` prints the stage's spend |
| `reply_budget` | one-shot | `s26-reply-budget-dev.txt`, the evidence for 0084 |
| `occurrence_misses` | live tool | `s26-occurrence-misses-dev.txt` and `s5-occurrence-misses-s3-dev.txt`; counts only, development runs only |
| `judge_outcomes` | live tool | the four outcomes from the judge's labels, per run (S2.7, 0099); counts only |
| `round0_handread` | one-shot | Round 0's private marking cards and the narrative-label validation in `s27-round0-dev.txt` (0099) |
| `round1_report` | one-shot | `s27-round1-dev.txt`: the ordering check's four ways on two answer sets (0096) |
| `round1_jev2_report` | one-shot | `s27-round1-jev2-dev.txt`: the registered second Jev check (0103) |
| `round_result` | live tool | a guidance round's or tuning round's result, appended to its registration (0098, 0136) |
| `round_comparisons` | one-shot | `s27-round-comparisons-dev.txt`, the numbers decision 0106 cites |
| `sealed_report` | one-shot | `s27-sealed-dev.txt`: the sealed sample beside `dev-400` and 0098's prediction |
| `page_value` | one-shot | `s27-page-value.txt`: what each page rule keeps of the transcriptions (0100) |
| `transcriber_shortlist` | repeatable | `s27-transcriber-shortlist.txt`: newer vision models by 0100's fixed filter, then probed |
| `transcriber_retest` | one-shot | `s27-transcriber-retest.txt`, `s27-transcriber-retest-readable.txt` and the routing tallies (S2.7 §7.4, 0120) |

## S3.1 and S3.2: the agent loop and its claims

| script | kind | what it produced |
|---|---|---|
| `s3_probe` | one-shot | `s3-probe-dev.txt`, the S3 learning probe (`select`, `run`, `report`, `trails`); not a result, sets no bar |
| `relabel_probe_spend` | one-shot | relabelled the learning probe's spend rows to the kind `probe` (0131) |
| `s3_shape_probe` | one-shot | `s3-shape-probe.txt` and the `tests/fixtures/openrouter/s3/` pairs: the native-tool shape probe on an invented case (spec S3.1 §5.5); paid, cents |
| `s3_noise_floor` | live measurement | `s3-noise-floor-dev.txt`: the loop's noise floor, format gate and third-run rule from two or three identical arm C runs on `dev-400` (spec S3 §10.2 to §10.4, 0130) |
| `_s3_runs` | live helper | nothing; the shared loader of finished `dev-400` arm C runs behind `s3_noise_floor` and the dev-only `s32_*` readings |
| `s3_case_groups` | live tool | `s3-case-groups-dev.txt`: `dev-400` sorted into always right, always wrong and flipping (0136). The case lists go under `NTSB_RUNS_DIR`, never committed |
| `s3_trail_pages` | live tool | nothing committed: private trail reading pages under `NTSB_RUNS_DIR/s3-trail-pages/`, each call in order beside the NTSB's verdict |
| `miss_kinds` | live helper | nothing; the classifier behind `exploratory/s3_miss_kinds` and the trail pages |
| `s32_cap_check` | live measurement | `s32-cap-check-dev.txt`: whether the $0.30 cap stands (spec S3.2 §5, 0144) |
| `s32_noise` | live measurement | `s32-noise-dev.txt`: the noise-floor pair under the claim's failure rule (spec S3.2 §7.3) |
| `s32_calibration` | live measurement | `s32-calibration-dev.txt` and `scoring/tables/calibration_s3.json`, the confidence curve frozen before held-out (spec S3.2 §8.2) |
| `s32_behaviour` | live measurement | `s32-behaviour-dev.txt`: results 1 and 4's measures from the noise-floor trails (spec S3.2 §9.1, §9.4) |
| `s32_context_ratio` | live measurement | `s32-context-ratio-dev.txt`: how far the characters-over-four estimate undercounts a prompt; it sets `sources.PROMPT_TOKEN_CEILING` (0152) |
| `s32_coding_ablation` | live measurement | `s32-coding-ablation-dev.txt`: the loop without its coding tools on `dev-400` (spec S3.2 §11, §12) |
| `s32_claims` | live measurement | `s32-claims-heldout.txt`: the registered held-out verdict, cost band, the four results, the ablations and the nine predictions (spec S3.2 §6 to §12). The only script that reads held-out runs, and only once the registration is committed |

## S3.3, S4 and S5: live nights and the site

| script | kind | what it produced |
|---|---|---|
| `s33_fingerprint_continuity` | one-shot | `s33-fingerprint-continuity.txt`: the rendered-text fingerprint is the same on the frozen commit and on the tree (S3.3 §7.2) |
| `s33_mutation_sweep` | live check | nothing; every model-text literal, edited in turn, must move the `+t` fingerprint (0143, 0161) |
| `s33_live_report` | live tool | `s33-live-shadow.txt`: the live shadow's mornings, counts only (0024) |
| `board_schema` | live tool | `docs/schemas/board-1.schema.json`, the `board/1` export's JSON Schema (0173) |
| `s4_seen_pairs` | one-shot | `scoring/tables/seen_pairs_dev.json`: the development split's primary occurrence codes, for the live container, which holds no case file |
| `s4_names_probe` | one-shot | `s4-names-dev.txt`: can personal names reach the board past the names rule (0180) |
| `ledger_append` | live tool | appends new run and night manifest hashes to `ledger.jsonl` on the `ledger` branch; run only by `.github/workflows/ledger.yml` (0178) |
| `s4_live_report` | live tool | `s4-live.txt`: the cloud nights, counts only (0024) |
| `site_numbers` | live tool | `site/data/numbers.json`: every figure the site prints, each read from one line of one committed result. Pytest fails while it is stale |
| `site_example_case` | live tool | `site/data/example-case.json`: question 1's case on the Path page, from a committed redacted fixture |

Three more shell scripts carry the same `Status` block:

- `paid_run.sh` runs one paid `make` target from a separate clean checkout reset to
  `origin/$NTSB_PAID_BRANCH`, reads keys from `pass` without printing them, and commits a held-out
  ledger row (S3.2, S3.3).
- `live_env.sh` prints the shell settings an `ntsb-live` command needs: the AWS profile, the store
  and the live bucket (0158, 0171).
- `build_live_image.sh` builds the live image from a clean commit, pushes it as `live-<sha>` and
  prints the digest `cdk deploy` needs (0171).

## `scripts/exploratory/`

Per-stage design arithmetic and probes. Nothing here is a result, and nothing sets a bar.

| script | what it produced |
|---|---|
| `s0_design_measurements`, `s1_design_measurements`, `s2_design_measurements` | the arithmetic behind the S0, S1 and S2 specifications; no committed result |
| `s3_probe_candidates`, `s3_probe_confidence`, `s3_probe_noise` | the S3 learning probe's ad-hoc readings, printed only |
| `s3_miss_kinds` | `s3-miss-kinds-dev.txt`: how the loop's first code misses, per case group |
| `s3_precedent_probe` | `s3-precedent-probe-dev.txt`: whether the nearest earlier cases hold the NTSB's first code |
| `s3_precedent_pages` | nothing committed: the private reading page the probe's "in between" rule asks for |
| `s3_coding_consistency` | `s3-coding-consistency-dev.txt`: how far the NTSB's own cause sentence settles its first code |
| `s3_finding_consistency` | `s3-finding-consistency-dev.txt`: the same question for flagged findings |
| `s3_finding_precedent` | `s3-finding-precedent-dev.txt`: whether the nearest earlier cases' findings beat the loop's (0138) |
| `s3_finding_misses` | `s3-finding-misses-dev.txt`: where the loop's findings are lost |
| `s32_heldout_diagnosis` | `s32-heldout-diagnosis.txt`: where the loop lost to the fixed pipeline on held-out (0153) |
| `s5_belief_path` | `s5-belief-path-heldout.txt`: question 7's figure on the site, one counts-only reading of the held-out trail (0186) |
| `s5_one_sentence` | `s5-one-sentence-dev.txt`: question 6's figure, one cause sentence and its many first codes |
| `pypdf_text_check` | `pypdf-text-dev.txt`: does pypdf 6.21 read `dev-400`'s dockets as 6.19 did (0218) |
