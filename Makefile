.PHONY: check lint type test ingest build scan probe bars armb docket-scan scan-docket docket-shape-open

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

armb:
	uv run ntsb-eval run --arm B --sample dev-400
	uv run ntsb-eval run --arm B --sample dev-400 --docket-filter unfiltered
	uv run ntsb-eval run --arm B --sample dev-400 --docket-filter no-submissions
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

docket-shape-open:
	uv run python -m scripts.docket_shape_open --out docs/results/s2-shape-open.txt
# Read and discard (decision 0040): no cache, nothing written under data/. Roughly 500 polite
# requests to data.ntsb.gov. Launched by the project owner, not CI.
