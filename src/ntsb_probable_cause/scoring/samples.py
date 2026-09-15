"""The three fixed samples, arms as exclusion sets, and the day-N mask (spec §5, §6.1)."""

import csv
import json
import random
from collections.abc import Sequence
from pathlib import Path
from typing import Literal

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.splits import Split

SAMPLES = ("heldout-40", "heldout-400", "dev-400")
_FILES = {
    "heldout-40": "decidability_ids.csv",
    "heldout-400": "heldout_400_ids.csv",
    "dev-400": "dev_400_ids.csv",
}
EVAL_DIR = Path("tests/fixtures/eval")
START_FACTS = frozenset(
    {
        EvidenceRole.PHASE_OF_FLIGHT,
        EvidenceRole.INJURY_LEVEL,
        EvidenceRole.AIRCRAFT_MAKE,
        EvidenceRole.AIRCRAFT_MODEL,
        EvidenceRole.ENGINE_TYPE,
        EvidenceRole.REGISTRATION,
    }
)
# ../ntsb-spike/scripts/fresh_case_profile.py: pilot hours on 0% of cases in the first two weeks,
# METAR in the record on 17%; the preliminary narrative is deleted at closure (decision 0023).
MASK_LIFTS_AT_DAY = 14
_LATE_BEFORE_DAY_14 = frozenset(
    {
        EvidenceRole.PILOT_CERTIFICATES,
        EvidenceRole.PILOT_TOTAL_HOURS,
        EvidenceRole.PILOT_HOURS_IN_TYPE,
        EvidenceRole.WEATHER_METAR,
        EvidenceRole.WEATHER_CONDITION,
    }
)


def arm_exclusions(arm: Literal["A", "ceiling"]) -> frozenset[EvidenceRole]:
    """Arm A keeps only the start facts; the ceiling excludes nothing (0022, 0023)."""
    return frozenset(set(EvidenceRole) - START_FACTS) if arm == "A" else frozenset()


def masked_exclusions(day: int) -> frozenset[EvidenceRole]:
    """What a live case would not yet have at day N; the preliminary narrative never (0023)."""
    late = _LATE_BEFORE_DAY_14 if day < MASK_LIFTS_AT_DAY else frozenset()
    return frozenset(late | {EvidenceRole.PRELIM_NARRATIVE})


def sample_ids(name: str) -> tuple[str, ...]:
    """Case IDs of a named sample, in file order."""
    with (EVAL_DIR / _FILES[name]).open(newline="") as handle:
        return tuple(row["case_id"] for row in csv.DictReader(handle))


def load_cases(processed: Path, ids: Sequence[str]) -> list[dict[str, object]]:
    """Raw records for the given IDs from cases.parquet, in the IDs' order (decision 0014)."""
    table = pq.read_table(processed / "cases.parquet", columns=["ntsb_number", "raw_json"])
    by_id = dict(zip(table["ntsb_number"].to_pylist(), table["raw_json"].to_pylist(), strict=True))
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"cases not in the processed file: {missing[:5]}")
    return [json.loads(by_id[i]) for i in ids]


def seen_pairs(processed: Path) -> frozenset[str]:
    """Every primary occurrence code in the development split (a top-1 outside it is unseen)."""
    table = pq.read_table(processed / "cases.parquet", columns=["split", "raw_json"])
    return frozenset(
        codes[0]
        for s, r in zip(table["split"].to_pylist(), table["raw_json"].to_pylist(), strict=True)
        if s == Split.DEV.value and (codes := fields.occurrence_codes(json.loads(r)))
    )


def draw(
    processed: Path, split: Split, *, per_slice: int = 200, seed: int = 20260914
) -> list[tuple[str, str]]:
    """200 fatal and 200 non-fatal, each stratified by class C/F/L in proportion (0026)."""
    columns = ["ntsb_number", "event_date", "split", "investigation_class", "raw_json"]
    table = pq.read_table(processed / "cases.parquet", columns=columns)
    by_column = {col: table[col].to_pylist() for col in columns}
    rows = [
        (str(n), str(d), str(c), json.loads(r)["highestInjuryLevel"] == "Fatal")
        for n, d, s, c, r in zip(*(by_column[col] for col in columns), strict=True)
        if s == split.value and c in {"C", "F", "L"}
    ]
    rng = random.Random(seed)  # noqa: S311 -- reproducible sampling, not security
    chosen: list[tuple[str, str]] = []
    for fatal in (True, False):
        pool = [r for r in rows if r[3] is fatal]
        by_class = {c: [r for r in pool if r[2] == c] for c in ("C", "F", "L")}
        quota = {c: round(per_slice * len(v) / len(pool)) for c, v in by_class.items()}
        for c, members in by_class.items():
            chosen.extend((n, d) for n, d, _, _ in rng.sample(members, min(quota[c], len(members))))
    return sorted(chosen)
