.PHONY: check lint type test ingest build scan probe bars armb s2-bars docket-scan scan-docket docket-shape-open ongoing-probe record change-feed-probe recorder-report s24-probe s24-gate s24-bars-ceiling s24-bars-b page-kinds analysis-handcheck s26-reply-budget s26-reply-budget-roomy s26-inventory-probe s26-inventory s26-transcriber-keys s26-transcriber-probe s26-transcriber-run s26-transcriber-resolution s26-transcriber-recheck s26-transcribe-dev-dry s26-transcribe-dev s26-dev-runs stage-spend s3-spend s3-draw-sealed s3-coding-stats s3-shape-probe s3-armb-tools s3-smoke-sync s3-smoke-batch s3-noise-floor s3-noise-report s3-round s3-round-result s27-coding-stats s27-round0-cards s27-noise-floor s27-judge s27-round0-results s27-check s27-round1-results s27-round1-jev2-results s27-round s27-check-guidance s27-round-result s27-round-comparisons s27-page-value s27-models-fetch s27-shortlist s27-transcriber-probe s27-batch-image s27-retest-verify s27-retest-run s27-retest-pages s27-retest-automatic s27-retest-score s27-routing-pages s27-routing-tally s27-retest-readable s27-sealed-run s27-sealed-results

check: lint type test

lint:
	uv run ruff format --check .
	uv run ruff check .
	uv run lint-imports
	uv run deptry .
	uv run vulture

type:
	uv run mypy

test:
	uv run pytest

ingest:
	uv run ntsb-ingest fetch 2009-01 $(shell date -v-1m +%Y-%m 2>/dev/null || date -d "last month" +%Y-%m)

build:
	uv run ntsb-ingest build

scan:
	uv run python -m scripts.corpus_scan

probe:
	uv run python -m scripts.openrouter_probe

bars:
	uv run ntsb-eval baseline --out docs/results/s1-baseline.txt
	uv run ntsb-eval run --arm ceiling --sample heldout-40
	uv run ntsb-eval run --arm ceiling --sample heldout-400
	uv run ntsb-eval run --arm A --sample heldout-400
	uv run ntsb-eval report --latest ceiling heldout-40 --out docs/results/s1-heldout-40.txt
	uv run ntsb-eval report --latest A heldout-400 --out docs/results/s1-armA-heldout.txt
	uv run ntsb-eval report --latest ceiling heldout-400 --against-latest A heldout-400 --out docs/results/s1-bars.txt
# Arm A gets its own table as well as the paired difference in s1-bars.txt: spec section 13
# asks for each of the three runs "with counts, intervals and cost", and a paired difference
# carries none of those. The three runs are launched here one after another, but they are
# independent and can be run in parallel; on 2026-09-17 they were, which turned nine hours of
# queue into thirty-six minutes. `docs/results/heldout-ledger.md` must exist with its header
# first, or two runs finishing together race to create it and one row is lost.

# --expected-cost-per-case-usd is REQUIRED, not a nicety. Without it the budget guard projects a
# run at the per-case CAP, which for dev-400 is 401 x $0.05 = $20.05, and refuses the run against
# the $25 monthly budget before a single model call. The real cost is about $0.0075 a case
# (docs/specs/2026-09-18-s2-design-measurements.txt), so 0.01 is a deliberate over-estimate: high
# enough that the guard still means something, low enough that a legitimate run is not refused.
# One run since decision 0054 retired the party-submission comparison.
armb:
	uv run ntsb-eval run --arm B --sample dev-400 --expected-cost-per-case-usd 0.01
# The reports are generated from explicit run ids afterwards, never `--latest`, as S1 learned.

docket-scan:
	uv run python -m scripts.docket_scan --out docs/results/s2-shape-dev.txt
# Long-running (roughly 2,000 polite requests to data.ntsb.gov, one every two seconds) and
# resumable: DocketClient's cache means an interrupted run picks up where it left off rather
# than re-fetching. Launched by the project owner, not CI.

scan-docket:
	uv run python -m scripts.corpus_scan --docket --out docs/results/s2-threshold.txt
# Reads the dev-400 cache docket-scan built; never fetches. A case not yet cached is skipped
# and counted, not fetched here.

# The held-out run: ONCE, and it appends a permanent row to docs/results/heldout-ledger.md.
# --expected-cost-per-case-usd is required for the same reason as `armb` above: without it the
# guard projects 400 x $0.05 = $20 and refuses the run. Held-out dockets have never been fetched,
# so this spends one to two hours politely fetching before the batch is submitted.
s2-bars:
	uv run ntsb-eval run --arm B --sample heldout-400 --expected-cost-per-case-usd 0.01

s24-probe:
	uv run ntsb-eval run --arm ceiling --sample dev-400 --limit 1 --sync --price-variant standard --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
	uv run ntsb-eval run --arm ceiling --sample dev-400 --limit 1 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
# S2.4 spec §3.1: one development case, both stages, standard then batch.

s24-gate:
	uv run ntsb-eval run --arm ceiling --sample dev-400 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
# S2.4 spec §3.2. About $0.22. The report is made from the explicit run id afterwards.

s24-bars-ceiling:
	uv run ntsb-eval run --arm ceiling --sample heldout-400 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
# S2.4 spec §5 -- ONCE, only after the gate has passed. Appends a ledger row: commit it before
# running s24-bars-b, because the held-out guard refuses a run from a dirty tree (decision 0026).

s24-bars-b:
	uv run ntsb-eval run --arm B --sample heldout-400 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.01
# S2.4 spec §5 -- ONCE, after s24-bars-ceiling's ledger row is committed.

docket-shape-open:
	uv run python -m scripts.docket_shape_open --out docs/results/s2-shape-open.txt
# Read and discard (decision 0040): no cache, nothing written under data/. Roughly 500 polite
# requests to data.ntsb.gov. Launched by the project owner, not CI.

ongoing-probe:
	uv run python -m scripts.ongoing_docket_probe --out docs/results/s25-ongoing-dockets.txt
# Read and discard (decision 0024): no cache, nothing written under data/, no case number
# printed. 100 polite requests to data.ntsb.gov, about 4 minutes at the 2-second floor --
# that estimate assumes no retries; each persistent retried status (429/500/502/503/504)
# adds roughly 30 seconds of backoff for that one case (docket/client.py's exponential
# backoff over up to 5 attempts). Fixes the recorder's "no-docket" outcome (spec S2.5 S10.1)
# from what the site actually returns for an ongoing case. Launched by the project owner,
# not CI.

record:
	uv run ntsb-record run
# One nightly pass (spec S2.5 §9.1): fetches the month window, the change feed and every
# watched docket, and writes the result to NTSB_STORE (a local path by default, or an
# `s3://` URL -- store/sync.py, Task 10). Takes about 40 minutes on a normal night. This is
# the same command the Mac bridge and the AWS Fargate task both run
# (docs/runbooks/recorder-bridge.md); `--verbose` and `--dry-run` are also accepted, e.g.
# `uv run ntsb-record run --dry-run`.

change-feed-probe:
	uv run python -m scripts.change_feed_probe --out docs/results/s25-change-feed.txt
# One-shot (spec S2.5 §5.3, decision 0065): calls GetCasesByModifiedDateRange once for the
# last 7 days and saves tests/fixtures/api/change_feed_shape.json (key -> sorted value type
# names, never values, decision 0024) alongside docs/results/s25-change-feed.txt (counts
# only). Needs NTSB_API_KEY. Run once; review both files, then commit them -- once the
# fixture exists, tests/test_api.py::test_cases_modified_parses_the_confirmed_live_shape
# stops skipping.

recorder-report:
	uv run python -m scripts.recorder_report --out docs/results/s25-recorder-report.txt
# Repeatable (spec S2.5 §10.2): reads NTSB_STORE (local path or s3:// URL, read-only) and
# prints the run summaries, arrival percentiles per evidence field and for the docket, the
# feed comparison, regulation changes, the 30-day closure tail, suspected re-numbers and
# compressed listing-page sizes. Counts only (decision 0024). Its first citable output needs
# 14 or more recorded nights (spec "Done means" §14).

page-kinds:
	uv run python -m scripts.page_kinds --sample dev-400 --include-photo-only --out docs/results/s26-page-kinds.txt
# S2.6 spec §6.2 step 1: free, reads the docket cache; writes the private page frame under data/.

analysis-handcheck:
	uv run python -m scripts.analysis_handcheck sheet --sample dev-400
# S2.6 spec §4.2: free; writes the private marking page under data/handcheck/s26-analysis/.

s26-reply-budget:
	uv run ntsb-eval run --arm B --sample dev-400 --max-output-tokens 2000 --expected-cost-per-case-usd 0.005
# S2.6 Task 9A: arm B on dev-400 at the old reply budget, to confirm why replies were truncated.

s26-reply-budget-roomy:
	uv run ntsb-eval run --arm B --sample dev-400 --max-output-tokens 16000 --expected-cost-per-case-usd 0.008
# S2.6 Task 9A (Andy's decision B): the same run with a roomy reply budget, to measure uncut need.

s26-inventory-probe:
	uv run python -m scripts.page_inventory sample
	uv run python -m scripts.page_inventory probe
# S2.6 spec §6.2: draws the 330-page sample (free), then labels ONE page (under a cent).

s26-inventory:
	uv run python -m scripts.page_inventory label
	uv run python -m scripts.page_inventory check
# S2.6 spec §6.2: labels the 330 (about $0.20), then writes Andy's 60-page check.

s26-transcriber-keys:
	uv run python -m scripts.transcriber_test keys
# S2.6 spec §7.3: draws the three answer keys; labels top-up pages if the inventory is short (cents).

s26-transcriber-probe:
	uv run python -m scripts.transcriber_test probe
# One invented page per candidate (under a cent in all); records each reply as a test fixture.

s26-transcriber-run:
	uv run python -m scripts.transcriber_test run
	uv run python -m scripts.transcriber_test run --retry-failed
	uv run python -m scripts.transcriber_test handwriting
	uv run python -m scripts.transcriber_test photos
	uv run python -m scripts.transcriber_test mixed
# All four candidates on every key page at 150 dpi (~$4-8 at standard prices), then one retry
# of any page that failed (decision 3: a page still failed after this retry counts as wrong;
# `--retry-failed` pays only for pages that failed, and this recipe calls it once), then
# Andy's three pages (handwriting, photos, mixed).

s26-transcriber-resolution:
	$(if $(MODEL),,$(error MODEL is required: the chosen transcriber, e.g. MODEL=qwen/qwen3.5-122b-a10b))
	uv run python -m scripts.transcriber_test resolution --model $(MODEL)
	uv run python -m scripts.transcriber_test resolution --model $(MODEL) --retry-failed
# The chosen model at 200 dpi on the handwriting and typed keys (~$0.30-1), then one retry of
# any page that failed there too. Run on 2026-09-25 with MODEL=qwen/qwen3.5-122b-a10b (decision
# 0087; docs/results/s26-transcriber-test-pass2.txt, "resolution").

s26-transcriber-recheck:
	uv run python -m scripts.transcriber_test photos-recheck
	uv run python -m scripts.transcriber_test handwriting-recheck
# Decision 0086's second pass (free: no model call): Andy's two recheck pages, read against the
# first pass's CSVs kept under <data_dir>/s26/transcriber-test/pass1/.

s26-dev-runs:
	$(if $(PER_CASE),,$(error PER_CASE is required: the expected cost per case in USD, e.g. PER_CASE=0.0042))
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version v1 --expected-cost-per-case-usd $(PER_CASE)
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version v2 --expected-cost-per-case-usd $(PER_CASE)
# S2.6 spec §9.1: both at one commit, marks in force. Development runs write no ledger row, so
# the tree stays clean and one recipe is safe. PER_CASE: S2.4's arm B cost per case on
# heldout-400 (docs/results/s24-bars.txt, $0.0028), rounded up by half for v2's added text.
# Run on 2026-09-26 with PER_CASE=0.0042 (spec.json of 20260926T082427-d19aafa-dev-400-B and
# 20260926T085904-d19aafa-dev-400-B).

s26-transcribe-dev-dry:
	$(if $(PER_PAGE),,$(error PER_PAGE is required: the expected cost per page in USD, above zero, e.g. PER_PAGE=0.0017))
	uv run ntsb-eval transcribe --sample dev-400 --expected-cost-per-page-usd $(PER_PAGE) --dry-run
# S2.6 spec §8.3, free: counts and prices the pages dev-400 needs. Read its projection before
# running s26-transcribe-dev (Task 15 Step 2: stop if it is more than a quarter over the estimate).

s26-transcribe-dev:
	$(if $(PER_PAGE),,$(error PER_PAGE is required: the expected cost per page in USD, above zero, e.g. PER_PAGE=0.0017))
	uv run ntsb-eval transcribe --sample dev-400 --expected-cost-per-page-usd $(PER_PAGE)
# S2.6 spec §8.3, paid: reads every image page dev-400 needs, once, into the cache. PER_PAGE is
# the transcriber's measured cost per page (docs/results/s26-transcriber-test-pass2.txt), rounded
# up. Kept apart from the dry run (Task 14 review, I2) so there is a point to stop between them.
# Run on 2026-09-26 with PER_PAGE=0.0017. The job reserves pages x PER_PAGE and stops once that
# is spent (final review, I1), so a PER_PAGE set too low stops the job early, within a few in-flight pages of its reservation.

stage-spend:
	uv run python -m scripts.stage_spend --estimate $(or $(EST),0)
# S2.7 (decision 0098 item 6): the stage's spend by commit on both branches, free. Every paid
# S2.7 target runs this first with its estimate and stops if the $25 line would be passed.

s3-spend:
	uv run python -m scripts.stage_spend --stage s3 --estimate $(or $(EST),0)
# S3 (spec §14, decision 0128 item 2): the stage's spend by commit on its own s3- branches, free.
# Every paid S3 target runs this first with its estimate and stops if the $50 line would be
# passed. The learning probe's $1.1954 (s3-probe, decision 0131) is outside the line.

s3-draw-sealed:
	uv run python -m scripts.draw_sealed --sample dev-seal-s3-400
# S3 spec §12 (decision 0129 item 1), free, ONCE: draws dev-seal-s3-400 (seed 20260930,
# excluding dev-400 and dev-seal-400) into tests/fixtures/eval/dev_seal_s3_400_ids.csv and
# refuses to overwrite it. Check it with: uv run python -m scripts.draw_sealed --sample
# dev-seal-s3-400 --verify. Refused by every command until S3.2's registration is committed.

s3-coding-stats:
	uv run python -m scripts.coding_stats --stage s3 --out docs/results/s3-coding-stats.txt
# S3 spec §12 (decision 0129 item 4), free: S3's statistics from the pool without
# dev-seal-s3-400. Writes scoring/tables/coding_stats_s3.json and the readable results file;
# run it after s3-draw-sealed. S2.7's file and s27-coding-stats are not touched.

s3-shape-probe:
	uv run python -m scripts.stage_spend --stage s3 --estimate 0.05
	uv run python -m scripts.s3_shape_probe --out docs/results/s3-shape-probe.txt
# S3.1 spec §5.5 (plan Task 4), paid (cents), ONCE, on or after 1 October 2026: the native-tool
# shape probe. Sends the loop's own tool definitions and system text on an invented case to
# GPT-6 Luna, standard then batch, and prints the six checks. Needs OPENROUTER_API_KEY in the
# environment (from pass, never printed); the stage line is checked first and the probe reserves
# $0.05 against the monthly guard. Writes docs/results/s3-shape-probe.txt and the saved pairs
# under tests/fixtures/openrouter/s3/; commit both, then apply the plan's Task 4 outcome.

s3-armb-tools:
	$(if $(RUN),,$(error RUN is required: the finished development arm B run id))
	uv run python -m scripts.stage_spend --stage s3 --estimate 0.80
	uv run ntsb-eval tools $(RUN)
# S3.1 spec §7.1 (decision 0127; plan Task 12), paid (about $0.80 a dev-400 run, estimate; the
# command reserves $0.004 a case): arm B's parts 2 and 3 as a post-pass over a finished arm B
# run, in batch rounds. Writes the derived run <RUN>-tools; part 4 is then
# uv run ntsb-eval check <RUN>-tools --way luna --stats s3.

s3-smoke-sync:
	uv run python -m scripts.stage_spend --stage s3 --estimate 0.05
	uv run ntsb-eval run --arm C --sample dev-400 --limit 1 --sync --price-variant standard --expected-cost-per-case-usd 0.05
# S3.1 spec §10.1 step 6 (plan Task 14), paid (cents): arm C on dev-400's first case, at the
# standard price, synchronously. Read its trail by eye: calls in order, tool choice honoured,
# costs recorded, no protocol breaks.

s3-smoke-batch:
	uv run python -m scripts.stage_spend --stage s3 --estimate 0.40
	uv run ntsb-eval run --arm C --sample dev-400 --limit 20 --expected-cost-per-case-usd 0.02
# S3.1 spec §10.1 step 6 (plan Task 14), paid (about $0.20): arm C on dev-400's first 20 cases,
# in batch rounds. Its cost per case re-estimates s3-noise-floor's --expected-cost-per-case-usd.

s3-noise-floor:
	uv run python -m scripts.stage_spend --stage s3 --estimate 5.00
	uv run ntsb-eval run --arm C --sample dev-400 --expected-cost-per-case-usd 0.012
# S3.1 spec §10.2 (decision 0130), paid (about $3.50 a run): arm C on the whole of dev-400, in
# batch rounds, from a clean tree on the frozen commit. Run it twice, then s3-noise-report; a
# third time only if that report prints "third run: needed".

s3-noise-report:
	$(if $(RUNS),,$(error RUNS is required: two or three arm C run ids))
	uv run python -m scripts.s3_noise_floor $(RUNS) --out docs/results/s3-noise-floor-dev.txt
# S3.1 spec §10.2 to §10.4 (decision 0130), free: the noise floor, the format gate and the
# third-run rule from the noise-floor runs, counts only. RUNS="<a> <b>" or "<a> <b> <c>".

s3-round:
	$(if $(N),,$(error N is required: the round number))
	uv run python -m scripts.stage_spend --stage s3 --estimate 5.00
	uv run ntsb-eval run --arm C --sample dev-400 --round $(N) --expected-cost-per-case-usd 0.012
# S3.1 spec §10.3, paid (about $3.50): one registered tuning round's arm C run on dev-400. Refused
# unless docs/rounds/s3-round-<N>.md is committed; the round is recorded in spec.json and the
# prompt version (+r<N>).

s3-round-result:
	$(if $(N),,$(error N is required: the round number))
	$(if $(RUN),,$(error RUN is required))$(if $(REFERENCE),,$(error REFERENCE is required))$(if $(NOISE),,$(error NOISE is required: two noise-floor run ids))
	uv run python -m scripts.round_result --run $(RUN) --reference $(REFERENCE) --noise $(NOISE) --append docs/rounds/s3-round-$(N).md
# S3.1 spec §10.3, free: decision 0098 item 4's reading against the loop's own noise floor,
# appended to the round's registration. NOISE="<a> <b>", two of the noise-floor runs, in quotes.

s27-coding-stats:
	uv run python -m scripts.coding_stats --out docs/results/s27-coding-stats.txt
# S2.7 spec §3.2, free: the statistics pool's coding counts, once (decision 0094). Writes the
# committed JSON beside the code tables and the readable results file.

s27-round0-cards:
	$(if $(RUN),,$(error RUN is required: the B-v1 run id))
	uv run python -m scripts.round0_handread cards --run $(RUN)
# S2.7 spec §4.4, free: writes Andy's private marking page under data/handcheck/s27-round0/.

s27-noise-floor:
	$(if $(PER_CASE),,$(error PER_CASE is required: B-v1's cost per case rounded up, e.g. PER_CASE=0.0042))
	uv run python -m scripts.stage_spend --estimate 1.40
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version v1 --expected-cost-per-case-usd $(PER_CASE)
# S2.7 spec §4.2, paid (about $1.18, B-v1's cost): B-v1 again, identical settings, at S2.7's
# commit. The noise floor every round is read against.

s27-judge:
	$(if $(RUN),,$(error RUN is required: a development run id to judge))
	uv run python -m scripts.stage_spend --estimate 0.60
	uv run ntsb-eval judge $(RUN)
# S2.7 spec §4.3, paid (about $0.50 at the judge's conservative $0.00125 a case; standard
# price only): writes judge.jsonl into the run's folder and a <run>-judge cost row.

s27-round0-results:
	$(if $(REPEAT),,$(error REPEAT is required: the noise-floor run id))
	$(if $(MARKS),,$(error MARKS is required: Andy's downloaded marks CSV))
	$(if $(LABELS),,$(error LABELS is required: validated or unvalidated, from the score line))
	{ uv run python -m scripts.occurrence_misses --run 20260926T082427-d19aafa-dev-400-B --against $(REPEAT); \
	  echo; uv run python -m scripts.occurrence_misses --run 20260926T085904-d19aafa-dev-400-B --against 20260926T082427-d19aafa-dev-400-B; \
	  echo; uv run python -m scripts.occurrence_misses --run $(REPEAT); \
	  echo; uv run ntsb-eval report 20260926T082427-d19aafa-dev-400-B --against $(REPEAT); \
	  echo; uv run python -m scripts.judge_outcomes --runs 20260926T082427-d19aafa-dev-400-B $(REPEAT) 20260926T085904-d19aafa-dev-400-B --label-status $(LABELS); \
	  echo; uv run python -m scripts.round0_handread score $(MARKS) --run 20260926T082427-d19aafa-dev-400-B; } > docs/results/s27-round0-dev.txt
# S2.7 spec §4.5, free: Round 0's results file from committed scripts only.

s27-check:
	$(if $(RUN),,$(error RUN is required: the answer run id))
	$(if $(WAY),,$(error WAY is required: rule, luna, jev or jev2))
	uv run python -m scripts.stage_spend --estimate $(if $(filter luna,$(WAY)),0.90,0.05)
	uv run ntsb-eval check $(RUN) --way $(WAY)
# S2.7 spec §5, post-pass. rule: free. luna: about $0.36 per 400 cases at the standard price
# (plan W3). jev: a fraction of a cent (self-reported price); needs TYPESAFE_API_KEY.
# jev2: the registered second Jev check (decision 0103), the same price and key as jev.

s27-sealed-run:
	$(if $(PER_CASE),,$(error PER_CASE is required: the final setup's cost per case rounded up, e.g. PER_CASE=0.0042))
	uv run python -m scripts.stage_spend --estimate 1.80
	uv run ntsb-eval run --arm B --sample dev-seal-400 --evidence-version v1 --guidance r3-loc-stall --guidance r6-aircraft-control --expected-cost-per-case-usd $(PER_CASE)
# S2.7 spec §9.1, paid, ONCE (about $1.21 on batch, Round 6's cost on dev-400): the final setup
# named in docs/rounds/s27-sealed.md on the sealed sample. Refused until that registration is
# committed (decision 0095). Fetches the sealed dockets as it goes (2 s a request, some hours).
# Then the check: make s27-check RUN=<this run's id> WAY=luna.

s27-sealed-results:
	$(if $(SEALED),,$(error SEALED is required: the sealed run's checked folder, <run id>-check-luna))
	uv run python -m scripts.sealed_report --dev 20260929T053953-674c92e-dev-400-B-check-luna --sealed $(SEALED) --misread-moved unvalidated --out docs/results/s27-sealed-dev.txt
# S2.7 spec §9.1-9.2, free: the sealed result beside dev-400's, and decision 0098 item 7 scored.

s27-round1-results:
	$(if $(REPEAT),,$(error REPEAT is required: the noise-floor run id))
	uv run python -m scripts.round1_report --answers 20260926T082427-d19aafa-dev-400-B $(REPEAT) --out docs/results/s27-round1-dev.txt

s27-round1-jev2-results:
	uv run python -m scripts.round1_jev2_report --answers 20260926T082427-d19aafa-dev-400-B 20260927T111202-fbab38a-dev-400-B --out docs/results/s27-round1-jev2-dev.txt
# S2.7 Task 12a, free: jev2 against no check, the rule, Luna and Round 1's Jev on the two answer
# sets the registration names (docs/rounds/s27-round1-jev2.md), and decision 0103's outcome.

s27-round:
	$(if $(PER_CASE),,$(error PER_CASE is required: the last run's cost per case rounded up))
	$(if $(or $(GUIDANCE),$(NO_GUIDANCE)),,$(error GUIDANCE is required: every kept file and the new one, in stacking order (NO_GUIDANCE=1 for a run with none)))
	uv run python -m scripts.stage_spend --estimate $(or $(EST),1.40)
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version $(or $(EVIDENCE),v1) --expected-cost-per-case-usd $(PER_CASE) $(foreach g,$(GUIDANCE),--guidance $(g))
# S2.7 spec §6, paid (about $1.18 at v1): one guidance round's arm B run on dev-400. GUIDANCE
# lists every kept file and the new one, in stacking order (each needs its registration
# committed); pass NO_GUIDANCE=1 instead for a deliberate run with no guidance at all
# (Task 17's v2 run, if every round is dropped).

s27-check-guidance:
	$(if $(GUIDANCE),,$(error GUIDANCE is required))
	uv run python -m scripts.check_guidance $(GUIDANCE)
# S2.7 plan W6, free and local: no guidance sentence may appear in a development case's withheld text.

s27-round-result:
	$(if $(N),,$(error N is required: the round number))
	$(if $(RUN),,$(error RUN is required))
	$(if $(REFERENCE),,$(error REFERENCE is required))
	$(if $(NOISE),,$(error NOISE is required: the two identical runs, space-separated, in quotes))
	uv run python -m scripts.round_result --run $(RUN) --reference $(REFERENCE) --noise $(NOISE) $(if $(FINDING),--finding-round,) $(if $(SUPPLEMENT),--supplement,) --append docs/rounds/s27-round-$(N).md
# S2.7 spec §6.4, free: decision 0098 item 4's reading, appended to the round's registration.
# SUPPLEMENT=1 adds decision 0105 item 4's line (Round 5: its run has the added codes, its reference not).

s27-round-comparisons:
	uv run python -m scripts.round_comparisons --out docs/results/s27-round-comparisons-dev.txt
# Final review (I2, M2), free: every number decision 0106 and Round 6's note cite (B-v1, the
# repeat, Rounds 2-6's own checked scores; Round 6 paired against Round 3/4/5/the repeat; the
# decision 0105 supplement line for Round 6 against Round 3), from committed code.

s27-page-value:
	uv run python -m scripts.page_value --sample dev-400 --out docs/results/s27-page-value.txt
# S2.7 spec §7.3 (T3), free: reads the dev-400 docket and transcription caches; no model call.

s27-models-fetch:
	uv run python -m scripts.transcriber_shortlist fetch
# S2.7 spec §7.2, free: saves OpenRouter's public model list under <data_dir>/s27/.

s27-shortlist:
	$(if $(MODELS),,$(error MODELS is required: the saved list, e.g. MODELS=$$NTSB_DATA_DIR/s27/openrouter-models-2026-09-27.json))
	uv run python -m scripts.transcriber_shortlist shortlist --models $(MODELS) --out docs/results/s27-transcriber-shortlist.txt
# S2.7 spec §7.2, free: decision 0100 item 1's filter over the saved list.

s27-transcriber-probe:
	uv run python -m scripts.stage_spend --estimate 0.10
	uv run python -m scripts.transcriber_shortlist probe
# S2.7 spec §7.2, paid (estimate under $0.10): one invented page to each shortlisted model,
# replacing failures in order, until eight pass. Every reply is saved under
# <data_dir>/s27/probe-replies/; only passed models' replies are also written to
# tests/fixtures/openrouter/transcription/.

s27-batch-image:
	$(if $(MODEL),,$(error MODEL is required: a passed candidate with a batch variant))
	uv run python -m scripts.stage_spend --estimate 0.01
	uv run python -m scripts.transcriber_shortlist batch-image --model $(MODEL)
# S2.7 spec §7.2 and walkthrough W2, paid (a fraction of a cent): one batch request carrying
# the invented probe image.

# S2.7 walkthrough W7 (pre-flight 1.1): S2.6's second-pass recheck CSV pair, defined once here
# and used by every s27-retest target. The pass2/ pair is the default because Andy recalls it
# as final; the top-level pair (.../transcriber-test/handwriting-key-pass2.csv and
# .../transcriber-test/photo-words-pass2.csv) is the other one S2.6 left on disk.
HW_RECHECK ?= $$NTSB_DATA_DIR/s26/transcriber-test/pass2/handwriting-key-pass2-2.csv
PHOTO_RECHECK ?= $$NTSB_DATA_DIR/s26/transcriber-test/pass2/photo-words-pass2.csv

s27-retest-verify:
	uv run python -m scripts.transcriber_retest verify --handwriting-recheck $(HW_RECHECK) --photos-recheck $(PHOTO_RECHECK)
# S2.7 walkthrough W7, free: Qwen's second pass must be reproduced exactly from the cache before
# any candidate is scored. If the default pair does not reproduce it, try the top-level pair by
# overriding HW_RECHECK and PHOTO_RECHECK; if neither pair reproduces it, stop and report.
# Run on 2026-09-27: the default pass2/ pair reproduced every count; the top-level pair did not
# (1551 handwriting key lines and 55 inventing lines, against the published 1548 and 54).

s27-retest-run:
	uv run python -m scripts.stage_spend --estimate 2.50
	uv run python -m scripts.transcriber_retest run
	uv run python -m scripts.transcriber_retest run --retry-failed
# S2.7 spec §7.4, paid (estimate up to $2.50, standard price, synchronous): every candidate on
# the four keys, and one retry of failed pages. No marking page yet (walkthrough W3).

s27-retest-pages:
	$(if $(MODELS),,$(error MODELS is required: the candidates still in the running, from s27-retest-automatic))
	uv run python -m scripts.transcriber_retest pages --models $(MODELS)
# Free: Andy's two pages under <data_dir>/s27/transcriber-retest/, for the candidates still in
# the running only (walkthrough W3); MODELS is space-separated. Rebuilding with the same
# candidates keeps marks already made (they reload from the browser); a different set is refused,
# because it would renumber the cards those marks belong to.

s27-retest-automatic:
	uv run python -m scripts.transcriber_retest automatic --handwriting-recheck $(HW_RECHECK) --photos-recheck $(PHOTO_RECHECK)
# S2.7 walkthrough W3, free: the candidates still in the running before any marking. Re-verifies
# Qwen's row with the shared recheck pair first (pre-flight 1.1: the pair Task 8 verified).

s27-retest-score:
	uv run python -m scripts.transcriber_retest score --handwriting-recheck $(HW_RECHECK) --photos-recheck $(PHOTO_RECHECK) $(if $(MARKED),--photos $$NTSB_DATA_DIR/s27/transcriber-retest/s27-photo-words.csv --mixed $$NTSB_DATA_DIR/s27/transcriber-retest/s27-mixed-words.csv,) --marked $(MARKED) --out docs/results/s27-transcriber-retest.txt
# S2.7 spec §7.4, free: decision 0100 item 3 applied; the CSV pair is the one Task 8 verified.
# MARKED: the candidates Andy marked (s27-retest-automatic's "to mark" line); empty if none.
# It refuses a candidate still in the running that is not in MARKED.

s27-routing-pages:
	$(if $(MODELS),,$(error MODELS is required: the candidates whose full-page scan readings Andy marks))
	uv run python -m scripts.transcriber_retest routing-pages --models $(MODELS)
# Andy, 2026-09-27, free and exploratory (outside decision 0100 item 3's rule): the full-page
# scan page alone, for the named candidates, under <data_dir>/s27/transcriber-retest/routing/,
# for routing text-and-image pages to a cheaper model. MODELS is space-separated.

s27-routing-tally:
	$(if $(MODELS),,$(error MODELS is required: the candidates s27-routing-pages was built for))
	uv run python -m scripts.transcriber_retest routing-tally --models $(MODELS) --mixed $$NTSB_DATA_DIR/s27/transcriber-retest/routing/s27-routing-scan-words.csv --out docs/results/s27-routing-scans.txt
# Free: the tally of Andy's marks from s27-routing-pages; refuses an unmarked card.

s27-retest-readable:
	uv run python -m scripts.transcriber_retest readable-split --handwriting-recheck $(HW_RECHECK) --photos-recheck $(PHOTO_RECHECK) --out docs/results/s27-transcriber-retest-readable.txt
# Free, post-hoc (Andy's challenge, 2026-09-28): Qwen's and each candidate's handwriting counts
# on fully readable pages and on pages whose key holds [illegible], from the committed scorer,
# checked to add up to its committed totals. Changes neither decision 0100's rule nor the verdict.
