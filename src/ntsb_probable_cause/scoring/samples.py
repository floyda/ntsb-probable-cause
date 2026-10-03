"""The three fixed samples, arms as exclusion sets, and the day-N mask (spec §5, §6.1)."""

import csv
import json
import random
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path
from typing import Literal

import pyarrow.parquet as pq

from ntsb_probable_cause import fields, gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.splits import Split

SAMPLES = ("heldout-40", "heldout-400", "dev-400", "dev-seal-400", "dev-seal-s3-400")
_FILES = {
    "heldout-40": "decidability_ids.csv",
    "heldout-400": "heldout_400_ids.csv",
    "dev-400": "dev_400_ids.csv",
    "dev-seal-400": "dev_seal_400_ids.csv",
    "dev-seal-s3-400": "dev_seal_s3_400_ids.csv",
}
EVAL_DIR = Path("tests/fixtures/eval")
# Decisions 0095 and 0129: a sealed development sample opens once, when its own registration,
# naming the setup it will be used on, is committed. Every command that would score, read,
# fetch or transcribe one calls :func:`refuse_sealed` first. S2.7's registration does not open
# S3's sample, and S3's does not open S2.7's.
SEALED_REGISTRATIONS: Mapping[str, Path] = {
    "dev-seal-400": Path("docs/rounds/s27-sealed.md"),
    # Decision 0141: kept sealed for v2 (0140); S3.2's registration does not open it.
    "dev-seal-s3-400": Path("docs/rounds/s3-sealed.md"),
}
SEALED = frozenset(SEALED_REGISTRATIONS)
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


def arm_exclusions(arm: Literal["A", "B", "ceiling", "C"]) -> frozenset[EvidenceRole]:
    """Arm A keeps only the start facts; B, C and the ceiling exclude nothing (0022, 0023)."""
    return frozenset(set(EvidenceRole) - START_FACTS) if arm == "A" else frozenset()


def masked_exclusions(day: int) -> frozenset[EvidenceRole]:
    """What a live case would not yet have at day N; the preliminary narrative never (0023).

    The docket is excluded regardless of day: a provisional rule until the S2.5 recorder has
    arrival numbers to mask by (agency design §6.2), not a claim that dockets never arrive early.
    """
    late = _LATE_BEFORE_DAY_14 if day < MASK_LIFTS_AT_DAY else frozenset()
    return frozenset(
        late
        | {
            EvidenceRole.PRELIM_NARRATIVE,
            EvidenceRole.DOCKET_LISTING,
            EvidenceRole.DOCKET_DOCUMENTS,
        }
    )


def refuse_sealed(sample: str, *, is_committed: Callable[[Path], bool]) -> None:
    """Refuse a sealed sample until its own registration is committed (decisions 0095, 0129).

    Raises:
        ConfigurationError: ``sample`` is sealed and its registration is not committed.
    """
    if sample not in SEALED:
        return
    registration = SEALED_REGISTRATIONS[sample]
    if not is_committed(registration):
        raise ConfigurationError(
            f"{sample} is sealed: commit {registration}, naming the final setup, "
            "before anything reads it (decisions 0095, 0129)"
        )


def refuse_unless_development(run_id: str, sample: str | None) -> None:
    """Refuse a run the S2.7 report scripts must never read: held-out, or an unopened seal.

    Every one of those scripts (``occurrence_misses``, ``judge_outcomes``,
    ``round0_handread``, ``round1_report``, ``round1_jev2_report``, ``round_result``) checked
    the same two things in a slightly different, hand-copied way (final review, Important 1 /
    deferred Task 5): the run id, which is known before ``run.jsonl`` exists to read, and the
    sample ``run.jsonl`` itself records (``record.sample``), which catches a renamed or
    relabelled run whose id says nothing about it. Call once with ``sample=None`` before
    ``run.jsonl`` is opened (a missing or renamed run folder is still refused by its id
    alone), then again with the loaded record's ``sample``. Takes the sample name, not the
    whole ``RunRecord``, so this module -- one of the "Only the splitter constructs synthesis
    and verdict" contract's source modules -- never has to import ``scoring.records``, which
    reaches ``records.verdict`` through ``scoring.metrics``.

    The sealed samples (``dev-seal-400``, ``dev-seal-s3-400``) pass the "development" checks --
    each one's own registration is what gates it (decisions 0095, 0129) -- so they are refused
    last, through :func:`refuse_sealed`.

    Raises:
        ConfigurationError: ``run_id`` or ``sample`` names a held-out sample, or the sample is
            sealed and its registration is not committed.
    """
    if "heldout" in run_id:
        raise ConfigurationError(f"{run_id} is a held-out run; development runs only")
    if sample is None:
        return
    if sample.startswith("heldout"):
        raise ConfigurationError(f"{run_id} is a held-out run ({sample}); development runs only")
    if not sample.startswith("dev"):
        raise ConfigurationError(f"{sample} is not a development sample")
    refuse_sealed(sample, is_committed=gitinfo.is_committed)


def sample_path(name: str) -> Path:
    """The committed list of a named sample's case IDs (under :data:`EVAL_DIR`)."""
    return EVAL_DIR / _FILES[name]


def sample_ids(name: str) -> tuple[str, ...]:
    """Case IDs of a named sample, in file order."""
    with sample_path(name).open(newline="") as handle:
        return tuple(row["case_id"] for row in csv.DictReader(handle))


def load_cases(processed: Path, ids: Sequence[str]) -> list[dict[str, object]]:
    """Raw records for the given IDs from cases.parquet, in the IDs' order (decision 0014).

    Streams row batches instead of ``pq.read_table`` + ``to_pylist()`` over the whole
    ``raw_json`` column: reading all 19,641 rows to keep 401 held ~1750 MB resident for an
    evaluation run's whole 30-100 minute life. Batch streaming with only the wanted rows kept
    measured 259 MB for the same query (``filters=`` was measured too, at 1021 MB, and
    rejected: pyarrow still reads whole row groups, which ``dev-400`` spans). Do not revert
    this to ``read_table``.
    """
    wanted = set(ids)
    by_id: dict[str, str] = {}
    with pq.ParquetFile(processed / "cases.parquet") as parquet_file:
        for batch in parquet_file.iter_batches(batch_size=256, columns=["ntsb_number", "raw_json"]):
            for ntsb_number, raw_json in zip(
                batch.column("ntsb_number").to_pylist(),
                batch.column("raw_json").to_pylist(),
                strict=True,
            ):
                if ntsb_number in wanted:
                    by_id[ntsb_number] = raw_json
    missing = [i for i in ids if i not in by_id]
    if missing:
        raise ValueError(f"cases not in the processed file: {missing[:5]}")
    return [json.loads(by_id[i]) for i in ids]


def seen_pairs(processed: Path) -> frozenset[str]:
    """Every primary occurrence code in the development split (a top-1 outside it is unseen).

    Streams row batches for the same reason as ``load_cases``: reading the whole ``raw_json``
    column to accumulate 829 codes held ~600 MB resident for the run's whole life. Batch
    streaming measured +43.5 MB. Do not revert this to ``read_table``.
    """
    seen: set[str] = set()
    with pq.ParquetFile(processed / "cases.parquet") as parquet_file:
        for batch in parquet_file.iter_batches(batch_size=512, columns=["split", "raw_json"]):
            for split_value, raw_json in zip(
                batch.column("split").to_pylist(),
                batch.column("raw_json").to_pylist(),
                strict=True,
            ):
                if split_value == Split.DEV.value and (
                    codes := fields.occurrence_codes(json.loads(raw_json))
                ):
                    seen.add(codes[0])
    return frozenset(seen)


def draw(
    processed: Path,
    split: Split,
    *,
    per_slice: int = 200,
    seed: int = 20260914,
    exclude: AbstractSet[str] = frozenset(),
) -> list[tuple[str, str]]:
    """200 fatal and 200 non-fatal, each stratified by class C/F/L in proportion (0026).

    Classes I, M and T are excluded (decision 0026 point 1); ``scripts/draw_samples.py``
    prints how many cases of those classes were excluded per split and fatal slice.

    ``exclude``: case ids never drawn (``dev-seal-400`` excludes ``dev-400``, decision 0095;
    ``dev-seal-s3-400`` excludes both, decision 0129).
    """
    columns = ["ntsb_number", "event_date", "split", "investigation_class", "raw_json"]
    table = pq.read_table(processed / "cases.parquet", columns=columns)
    by_column = {col: table[col].to_pylist() for col in columns}
    rows = [
        (str(n), str(d), str(c), json.loads(r)["highestInjuryLevel"] == "Fatal")
        for n, d, s, c, r in zip(*(by_column[col] for col in columns), strict=True)
        if s == split.value and c in {"C", "F", "L"} and n not in exclude
    ]
    rng = random.Random(seed)  # noqa: S311 -- reproducible sampling, not security
    chosen: list[tuple[str, str]] = []
    for fatal in (True, False):
        pool = [r for r in rows if r[3] is fatal]
        if not pool:
            continue
        by_class = {c: [r for r in pool if r[2] == c] for c in ("C", "F", "L")}
        quota = {c: round(per_slice * len(v) / len(pool)) for c, v in by_class.items()}
        for c, members in by_class.items():
            chosen.extend((n, d) for n, d, _, _ in rng.sample(members, min(quota[c], len(members))))
    return sorted(chosen)
