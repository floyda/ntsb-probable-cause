"""The learning part: what the learner may read (decisions 0200, 0203).

The S3 statistics pool (development split, classes C/F/L) less every sample the ``mem``
statistics leave out, ``dev-steer-400`` among them. Only cases with a probable-cause sentence
and at least one occurrence code. Verdict fields are read through ``fields`` from the raw
record; no ``Verdict`` is built here.
"""

import json
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring import coding_stats, samples

# The statistics pool's classes; ``scripts/coding_stats.py`` holds the same literal (decision 0094).
POOL_CLASSES: Final = frozenset({"C", "F", "L"})
COLUMNS: Final = ("ntsb_number", "event_date", "split", "investigation_class", "raw_json")


@dataclass(frozen=True)
class LearningCase:
    """One learning-part case as the learner reads it."""

    case_id: str
    year: int
    cause: str
    occurrence: tuple[str, ...]
    findings: tuple[str, ...]


def excluded_ids() -> frozenset[str]:
    """The ids of every sample the ``mem`` statistics leave out."""
    return frozenset(
        i for name in coding_stats.POOL_EXCLUDED["mem"] for i in samples.sample_ids(name)
    )


def learning_part(
    processed: Path, *, years: AbstractSet[int], excluded: AbstractSet[str] | None = None
) -> list[LearningCase]:
    """Learning-part cases with event years in ``years``, sorted by case id.

    Streams row batches and parses ``raw_json`` only for rows that pass the cheap filters:
    reading the whole column holds well over a gigabyte (see ``samples.load_cases``).
    """
    leave_out = excluded_ids() if excluded is None else excluded
    found: list[LearningCase] = []
    with pq.ParquetFile(processed / "cases.parquet") as parquet_file:
        for batch in parquet_file.iter_batches(batch_size=256, columns=list(COLUMNS)):
            for case_id, day, split, klass, raw_json in zip(
                *(batch.column(c).to_pylist() for c in COLUMNS), strict=True
            ):
                year = int(str(day)[:4])
                if (
                    split != "dev"
                    or klass not in POOL_CLASSES
                    or case_id in leave_out
                    or year not in years
                ):
                    continue
                raw = json.loads(raw_json)
                cause = fields.probable_cause(raw)
                occurrence = fields.occurrence_codes(raw)
                if not cause or not occurrence:
                    continue
                found.append(
                    LearningCase(
                        str(case_id),
                        year,
                        cause,
                        occurrence,
                        fields.finding_codes_in_cause(raw),
                    )
                )
    return sorted(found, key=lambda c: c.case_id)
