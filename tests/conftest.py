import csv
import json
import os
from datetime import UTC, datetime
from pathlib import Path

import pytest
from hypothesis import settings

from ntsb_probable_cause.scoring.records import RunRecord

FIXTURES = Path(__file__).parent / "fixtures"

# Final review, item E2: derandomize hypothesis under CI so a flaky-looking failure there is
# reproducible, without changing local runs (which keep exploring new examples each run).
settings.register_profile("ci", derandomize=True)
if os.environ.get("CI"):
    settings.load_profile("ci")


def load_record_fixtures() -> list[dict[str, object]]:
    return [
        json.loads(p.read_text())["record"] for p in sorted((FIXTURES / "records").glob("*.json"))
    ]


@pytest.fixture
def record_fixtures() -> list[dict[str, object]]:
    return load_record_fixtures()


@pytest.fixture
def eval_ids() -> dict[str, dict[str, str]]:
    # Only the "*_ids.csv" lists: case id and event date, one row per case (spec §5). The
    # spike's full labelling sheets are not in this repository at all -- every case in them
    # is held-out and their cause, code and factual-account columns are withheld data
    # (0013). `scripts/check_fixtures_redacted.py` fails if such a column reappears.
    lists: dict[str, dict[str, str]] = {}
    for path in sorted((FIXTURES / "eval").glob("*_ids.csv")):
        with path.open(newline="") as handle:
            lists[path.stem] = {row["case_id"]: row["event_date"] for row in csv.DictReader(handle)}
    return lists


@pytest.fixture
def run_record() -> RunRecord:
    """A RunRecord with fixed values, for tests that only need a well-formed record."""
    return RunRecord(
        run_id="20260915-0001-abc1234",
        sample="heldout-40",
        arm="ceiling",
        exclusions=(),
        includes=(),
        prompt_version="v1",
        model="openai/gpt-5.6-luna",
        price_variant="sync",
        cap_usd=0.50,
        budget_usd=25.0,
        commit_sha="abc1234",
        dirty=False,
        started=datetime(2026, 9, 15, tzinfo=UTC),
        finished=datetime(2026, 9, 15, 1, tzinfo=UTC),
        cases=40,
        cost_usd=1.23,
    )
