.PHONY: check lint type test ingest build scan probe bars armb s2-bars docket-scan scan-docket docket-shape-open s24-probe s24-gate s24-bars

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
# S2.4 spec §3.2. About $0.20. The report is made from the explicit run id afterwards.

s24-bars:
	uv run ntsb-eval run --arm ceiling --sample heldout-400 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.005
	uv run ntsb-eval run --arm B --sample heldout-400 --model openai/gpt-6-luna --expected-cost-per-case-usd 0.01
# S2.4 spec §5 -- ONCE, only after the gate has passed; appends two rows to the held-out ledger.

docket-shape-open:
	uv run python -m scripts.docket_shape_open --out docs/results/s2-shape-open.txt
# Read and discard (decision 0040): no cache, nothing written under data/. Roughly 500 polite
# requests to data.ntsb.gov. Launched by the project owner, not CI.
