.PHONY: check lint type test ingest build scan probe bars

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
	uv run ntsb-eval report --latest ceiling heldout-400 --against-latest A heldout-400 --out docs/results/s1-bars.txt
