.PHONY: check lint type test ingest build scan probe bars armb s2-bars docket-scan scan-docket docket-shape-open ongoing-probe record change-feed-probe recorder-report s24-probe s24-gate s24-bars-ceiling s24-bars-b page-kinds analysis-handcheck s26-reply-budget

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
