import csv
import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


def load_record_fixtures() -> list[dict[str, object]]:
    return [
        json.loads(p.read_text())["record"] for p in sorted((FIXTURES / "records").glob("*.json"))
    ]


@pytest.fixture
def record_fixtures() -> list[dict[str, object]]:
    return load_record_fixtures()


@pytest.fixture
def eval_ids() -> dict[str, dict[str, str]]:
    lists: dict[str, dict[str, str]] = {}
    for path in sorted((FIXTURES / "eval").glob("*.csv")):
        with path.open(newline="") as handle:
            lists[path.stem] = {row["case_id"]: row["event_date"] for row in csv.DictReader(handle)}
    return lists
