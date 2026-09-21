"""The three fixed samples, arms as exclusion sets, and the day-N mask (spec §5, §6.1)."""

import json
import tracemalloc
from collections.abc import Sequence
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.splits import Split

# The five columns the functions under test read from cases.parquet, with the real file's
# own names and types (checked against the processed file's schema).
_SCHEMA = pa.schema(
    [
        ("ntsb_number", pa.string()),
        ("event_date", pa.date32()),
        ("split", pa.string()),
        ("investigation_class", pa.string()),
        ("raw_json", pa.string()),
    ]
)


def _raw(*, fatal: bool, occurrence_codes: Sequence[tuple[str, bool, int]] = ()) -> str:
    """The minimum raw-record shape ``fields.occurrence_codes`` and ``draw`` read.

    ``occurrence_codes`` is a sequence of ``(eventCode, isDefiningEvent, sequenceNumber)``.
    """
    events = [
        {"eventCode": code, "isDefiningEvent": defining, "sequenceNumber": seq}
        for code, defining, seq in occurrence_codes
    ]
    return json.dumps(
        {
            "highestInjuryLevel": "Fatal" if fatal else "Minor",
            "aircrafts": [{"events": events}],
        }
    )


def _write_cases(tmp_path: Path, rows: Sequence[tuple[str, str, str, str, str]]) -> Path:
    """Write a synthetic cases.parquet under ``tmp_path/processed`` and return that directory."""
    processed = tmp_path / "processed"
    processed.mkdir()
    ids, dates, splits, classes, raws = zip(*rows, strict=True) if rows else ((), (), (), (), ())
    table = pa.table(
        {
            "ntsb_number": pa.array(ids, type=pa.string()),
            "event_date": pa.array([date.fromisoformat(d) for d in dates], type=pa.date32()),
            "split": pa.array(splits, type=pa.string()),
            "investigation_class": pa.array(classes, type=pa.string()),
            "raw_json": pa.array(raws, type=pa.string()),
        },
        schema=_SCHEMA,
    )
    pq.write_table(table, processed / "cases.parquet")
    return processed


def test_arm_a_keeps_only_start_facts() -> None:
    kept = set(EvidenceRole) - samples.arm_exclusions("A")
    assert kept == samples.START_FACTS
    assert samples.arm_exclusions("ceiling") == frozenset()


def test_mask_hides_late_fields_early() -> None:
    day1 = samples.masked_exclusions(1)
    assert EvidenceRole.PILOT_TOTAL_HOURS in day1
    assert EvidenceRole.WEATHER_METAR in day1
    assert EvidenceRole.PRELIM_NARRATIVE in samples.masked_exclusions(400)
    assert EvidenceRole.PHASE_OF_FLIGHT not in day1


def test_mask_lifts_late_fields_at_day_14() -> None:
    day14 = samples.masked_exclusions(14)
    assert EvidenceRole.PILOT_TOTAL_HOURS not in day14
    assert EvidenceRole.WEATHER_METAR not in day14
    # The docket is absent in the masked condition regardless of day (0023's provisional rule,
    # until the S2.5 recorder has arrival numbers): only the narrative lifts at day 14.
    assert day14 == frozenset(
        {EvidenceRole.PRELIM_NARRATIVE, EvidenceRole.DOCKET_LISTING, EvidenceRole.DOCKET_DOCUMENTS}
    )


def test_masked_condition_treats_the_docket_as_absent() -> None:
    excluded = samples.masked_exclusions(1)
    assert EvidenceRole.DOCKET_LISTING in excluded
    assert EvidenceRole.DOCKET_DOCUMENTS in excluded
    assert EvidenceRole.DOCKET_DOCUMENTS in samples.masked_exclusions(400)


def test_arm_a_excludes_the_docket_and_arm_b_excludes_nothing() -> None:
    assert EvidenceRole.DOCKET_DOCUMENTS in samples.arm_exclusions("A")
    assert samples.arm_exclusions("B") == frozenset()


def test_sample_ids_are_loaded(eval_ids: dict[str, dict[str, str]]) -> None:
    assert len(samples.sample_ids("heldout-40")) == 40


def test_sample_ids_are_in_file_order(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(samples, "EVAL_DIR", tmp_path)
    monkeypatch.setitem(samples._FILES, "heldout-40", "ordered.csv")
    (tmp_path / "ordered.csv").write_text("case_id,event_date\nB2,2021-01-01\nA1,2020-01-01\n")
    assert samples.sample_ids("heldout-40") == ("B2", "A1")


def test_load_cases_returns_records_in_requested_order(tmp_path: Path) -> None:
    rows = [
        ("A1", "2018-01-01", "dev", "C", _raw(fatal=False)),
        ("B2", "2018-01-02", "dev", "L", _raw(fatal=True)),
        ("C3", "2018-01-03", "dev", "F", _raw(fatal=True)),
    ]
    processed = _write_cases(tmp_path, rows)
    cases = samples.load_cases(processed, ["C3", "A1"])
    assert [c["highestInjuryLevel"] for c in cases] == ["Fatal", "Minor"]


def test_load_cases_raises_on_missing_ids(tmp_path: Path) -> None:
    processed = _write_cases(tmp_path, [("A1", "2018-01-01", "dev", "C", _raw(fatal=False))])
    with pytest.raises(ValueError, match="X9"):
        samples.load_cases(processed, ["A1", "X9"])


def test_load_cases_truncates_missing_ids_to_five(tmp_path: Path) -> None:
    # Pins the brief's explicit `missing[:5]` truncation: with 7 missing ids, only the first
    # 5 (in `ids` order) may appear in the message and the last 2 must not.
    processed = _write_cases(tmp_path, [("A1", "2018-01-01", "dev", "C", _raw(fatal=False))])
    missing = [f"X{i}" for i in range(7)]
    with pytest.raises(ValueError, match="cases not in the processed file") as excinfo:
        samples.load_cases(processed, ["A1", *missing])
    message = str(excinfo.value)
    for case_id in missing[:5]:
        assert case_id in message
    for case_id in missing[5:]:
        assert case_id not in message


def test_load_cases_does_not_retain_the_whole_corpus_in_memory(tmp_path: Path) -> None:
    # Guards the memory property itself, not just correctness: dropping the
    # `if ntsb_number in wanted` filter would still return the right 2 records (every other
    # test here would stay green) while retaining every row's raw_json in `by_id`. Padding
    # each row's raw_json to 5 KB and using 2,000 rows makes that retention plainly visible
    # in peak Python-heap use: the correct code's peak is roughly one in-flight 256-row batch
    # (~1.3 MB) plus the 2 wanted rows; the bug's peak is roughly all 2,000 rows (~10 MB).
    filler = "x" * 5_000
    rows = [
        (
            f"R{i}",
            "2018-01-01",
            "dev",
            "C",
            json.dumps({"highestInjuryLevel": "Minor", "aircrafts": [], "pad": filler}),
        )
        for i in range(2_000)
    ]
    processed = _write_cases(tmp_path, rows)
    tracemalloc.start()
    try:
        samples.load_cases(processed, ["R0", "R1"])
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert peak < 3_000_000


def test_load_cases_crosses_a_batch_boundary(tmp_path: Path) -> None:
    # load_cases streams in batches of 256 rows; a wanted id sitting past the first batch is
    # the property streaming is most likely to break, so use enough rows to cross it.
    rows = [(f"R{i}", "2018-01-01", "dev", "C", _raw(fatal=i == 300)) for i in range(500)]
    processed = _write_cases(tmp_path, rows)
    cases = samples.load_cases(processed, ["R300", "R0"])
    assert [c["highestInjuryLevel"] for c in cases] == ["Fatal", "Minor"]


def test_load_cases_repeats_a_duplicate_requested_id(tmp_path: Path) -> None:
    processed = _write_cases(tmp_path, [("A1", "2018-01-01", "dev", "C", _raw(fatal=True))])
    cases = samples.load_cases(processed, ["A1", "A1"])
    assert len(cases) == 2
    assert cases[0] == cases[1]


def test_seen_pairs_returns_only_dev_primary_codes(tmp_path: Path) -> None:
    dev_primary = _raw(
        fatal=False,
        occurrence_codes=[("111000", True, 1), ("222000", False, 2)],
    )
    heldout_row = _raw(fatal=False, occurrence_codes=[("333000", True, 1)])
    open_row = _raw(fatal=False, occurrence_codes=[("444000", True, 1)])
    rows = [
        ("A1", "2018-01-01", "dev", "C", dev_primary),
        ("B2", "2021-01-01", "heldout", "C", heldout_row),
        ("C3", "2024-01-01", "open", "C", open_row),
    ]
    processed = _write_cases(tmp_path, rows)
    # Only the dev case's primary (defining-event) code is seen; its own non-primary code
    # ("222000") and the heldout/open rows' codes are excluded.
    assert samples.seen_pairs(processed) == frozenset({"111000"})


def test_seen_pairs_crosses_a_batch_boundary(tmp_path: Path) -> None:
    # seen_pairs streams in batches of 512 rows; a code that appears only in rows past the
    # first batch is the property most likely to break if the loop were truncated to one
    # batch. 512 dev rows carry "AAA000" (entirely inside the first batch); a further 88 dev
    # rows past the boundary carry "BBB000" only, so both sides of the boundary are dev rows
    # and truncating the loop would silently drop "BBB000" from the seen set.
    rows = [
        (
            f"A{i}",
            "2018-01-01",
            "dev",
            "C",
            _raw(fatal=False, occurrence_codes=[("AAA000", True, 1)]),
        )
        for i in range(512)
    ]
    rows += [
        (
            f"B{i}",
            "2018-01-01",
            "dev",
            "C",
            _raw(fatal=False, occurrence_codes=[("BBB000", True, 1)]),
        )
        for i in range(88)
    ]
    processed = _write_cases(tmp_path, rows)
    assert samples.seen_pairs(processed) == frozenset({"AAA000", "BBB000"})


def test_draw_is_deterministic_for_a_fixed_seed(tmp_path: Path) -> None:
    rows = [(f"D{i}", "2018-01-01", "dev", "L", _raw(fatal=i % 2 == 0)) for i in range(20)]
    processed = _write_cases(tmp_path, rows)
    first = samples.draw(processed, Split.DEV, per_slice=5)
    second = samples.draw(processed, Split.DEV, per_slice=5)
    assert first == second


def test_draw_keeps_only_the_requested_split(tmp_path: Path) -> None:
    rows = [
        ("D1", "2018-01-01", "dev", "C", _raw(fatal=True)),
        ("D2", "2018-01-02", "dev", "C", _raw(fatal=False)),
        ("H1", "2021-01-01", "heldout", "C", _raw(fatal=True)),
        ("H2", "2021-01-02", "heldout", "C", _raw(fatal=False)),
    ]
    processed = _write_cases(tmp_path, rows)
    drawn = {case_id for case_id, _ in samples.draw(processed, Split.DEV, per_slice=5)}
    assert drawn == {"D1", "D2"}


def test_draw_excludes_classes_outside_c_f_l(tmp_path: Path) -> None:
    rows = [
        ("D1", "2018-01-01", "dev", "C", _raw(fatal=True)),
        ("D2", "2018-01-02", "dev", "I", _raw(fatal=True)),
        ("D3", "2018-01-03", "dev", "M", _raw(fatal=False)),
        ("D4", "2018-01-04", "dev", "T", _raw(fatal=False)),
    ]
    processed = _write_cases(tmp_path, rows)
    drawn = {case_id for case_id, _ in samples.draw(processed, Split.DEV, per_slice=5)}
    assert drawn == {"D1"}


def test_draw_applies_proportional_quotas_per_class(tmp_path: Path) -> None:
    # Non-fatal pool of 10: C=5, F=3, L=2; per_slice=10 divides exactly, so every member is
    # drawn (quota == pool size in every class) and the hand-computed quotas are exact.
    rows = [(f"C{i}", "2018-01-01", "dev", "C", _raw(fatal=False)) for i in range(5)]
    rows += [(f"F{i}", "2018-01-01", "dev", "F", _raw(fatal=False)) for i in range(3)]
    rows += [(f"L{i}", "2018-01-01", "dev", "L", _raw(fatal=False)) for i in range(2)]
    processed = _write_cases(tmp_path, rows)
    drawn = {case_id for case_id, _ in samples.draw(processed, Split.DEV, per_slice=10)}
    assert drawn == {r[0] for r in rows}


def test_draw_clamps_a_class_quota_larger_than_its_pool(tmp_path: Path) -> None:
    # Fatal pool of 5: C=3, F=1, L=1. With per_slice=10, the proportional quotas
    # (round(10*3/5)=6, round(10*1/5)=2, round(10*1/5)=2) all exceed their class's pool size,
    # so drawing must clamp to what exists rather than raise or repeat a case.
    rows = [(f"C{i}", "2018-01-01", "dev", "C", _raw(fatal=True)) for i in range(3)]
    rows += [("F0", "2018-01-01", "dev", "F", _raw(fatal=True))]
    rows += [("L0", "2018-01-01", "dev", "L", _raw(fatal=True))]
    processed = _write_cases(tmp_path, rows)
    drawn = {case_id for case_id, _ in samples.draw(processed, Split.DEV, per_slice=10)}
    assert drawn == {r[0] for r in rows}
