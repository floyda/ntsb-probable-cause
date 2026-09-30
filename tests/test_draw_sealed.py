"""scripts/draw_sealed.py: the two sealed samples, drawn once, never overwritten (0095, 0129)."""

import csv
from pathlib import Path

import pytest
from scripts import draw_sealed
from tests.test_samples import _raw, _write_cases

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.splits import Split

_S27_SEED = 20260926
_S3_SEED = 20260930
# Fatal and non-fatal pools, each with classes C, F and L in a 5:3:2 ratio, so the 200-case
# slices hold quotas of 100, 60 and 40 and the draw has a real choice to make.
_POOL = (("C", 250), ("F", 150), ("L", 100))


def _pool_rows() -> list[tuple[str, str, str, str, str]]:
    rows: list[tuple[str, str, str, str, str]] = []
    for fatal in (True, False):
        for klass, count in _POOL:
            for i in range(count):
                case = f"{'Fatal' if fatal else 'Minor'}-{klass}{i:03d}"
                rows.append((case, f"{2015 + i % 4}-06-01", "dev", klass, _raw(fatal=fatal)))
    return rows


def _earlier_sample(ids: list[str], part: int) -> list[str]:
    """10% of each fatal-and-class stratum (part 0 or 1), so the pool stays in proportion."""
    chosen: list[str] = []
    for slice_start in (0, 500):
        for klass_start, size in ((0, 25), (250, 15), (400, 10)):  # C, F and L within a slice
            first = slice_start + klass_start + part * size
            chosen.extend(ids[first : first + size])
    return chosen


def _write_list(path: Path, cases: list[str]) -> None:
    path.write_text("case_id,event_date\n" + "".join(f"{case},2016-01-01\n" for case in cases))


def _env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> tuple[Path, Path, list[str], list[str]]:
    """A pool file, the two earlier sample lists in a scratch folder, and the data folder.

    Returns the processed folder, the scratch folder, and the two lists' case ids (dev-400's,
    then dev-seal-400's). The scratch folder stands in for ``tests/fixtures/eval``.
    """
    rows = _pool_rows()
    processed = _write_cases(tmp_path, rows)
    ids = [row[0] for row in rows]
    dev400, seal27 = _earlier_sample(ids, 0), _earlier_sample(ids, 1)
    lists = tmp_path / "lists"
    lists.mkdir()
    _write_list(lists / "dev_400_ids.csv", dev400)
    _write_list(lists / "dev_seal_400_ids.csv", seal27)
    monkeypatch.setattr(samples, "EVAL_DIR", lists)
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    return processed, lists, dev400, seal27


def test_the_s3_draw_uses_its_own_seed_and_leaves_out_both_earlier_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processed, _lists, dev400, seal27 = _env(tmp_path, monkeypatch)
    rows = draw_sealed.drawn("dev-seal-s3-400")
    assert rows == samples.draw(
        processed, Split.DEV, seed=_S3_SEED, exclude=frozenset(dev400) | frozenset(seal27)
    )
    cases = {case for case, _date in rows}
    assert len(rows) == 400
    assert not cases & set(dev400)
    assert not cases & set(seal27)
    # The seed matters: S2.7's seed on S2.7's exclusions draws a different sample.
    assert rows != samples.draw(processed, Split.DEV, seed=_S27_SEED, exclude=frozenset(dev400))


def test_the_s27_draw_is_unchanged_seed_and_exclusion(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processed, _lists, dev400, _seal27 = _env(tmp_path, monkeypatch)
    assert draw_sealed.drawn("dev-seal-400") == samples.draw(
        processed, Split.DEV, seed=_S27_SEED, exclude=frozenset(dev400)
    )


def test_the_s3_sample_is_written_once_to_its_own_file_and_printed_by_fatal_and_class(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _processed, lists, _dev400, _seal27 = _env(tmp_path, monkeypatch)
    assert draw_sealed.main(["--sample", "dev-seal-s3-400"]) == 0
    written = lists / "dev_seal_s3_400_ids.csv"
    with written.open(newline="") as handle:
        listed = [(r["case_id"], r["event_date"]) for r in csv.DictReader(handle)]
    assert listed == draw_sealed.drawn("dev-seal-s3-400")
    out = capsys.readouterr().out
    assert out.startswith("dev-seal-s3-400: 400 cases written to ")
    assert (
        "by fatal and class {'fatal': {'C': 100, 'F': 60, 'L': 40}, "
        "'non-fatal': {'C': 100, 'F': 60, 'L': 40}}"
    ) in out
    with pytest.raises(SystemExit, match="drawn once"):
        draw_sealed.main(["--sample", "dev-seal-s3-400"])


def test_the_default_sample_is_still_dev_seal_400_and_writes_its_own_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    processed, lists, dev400, _seal27 = _env(tmp_path, monkeypatch)
    (lists / "dev_seal_400_ids.csv").unlink()
    assert draw_sealed.main([]) == 0
    assert not (lists / "dev_seal_s3_400_ids.csv").exists()
    written = samples.sample_ids("dev-seal-400")
    assert len(written) == 400
    assert not set(written) & set(dev400)
    expected = samples.draw(processed, Split.DEV, seed=_S27_SEED, exclude=frozenset(dev400))
    assert list(written) == [case for case, _date in expected]


def test_verify_compares_the_committed_list_with_a_redraw_for_both_samples(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    _processed, lists, _dev400, _seal27 = _env(tmp_path, monkeypatch)
    (lists / "dev_seal_400_ids.csv").unlink()
    assert draw_sealed.main(["--sample", "dev-seal-400"]) == 0
    assert draw_sealed.main(["--sample", "dev-seal-s3-400"]) == 0
    capsys.readouterr()
    for name in ("dev-seal-400", "dev-seal-s3-400"):
        assert draw_sealed.main(["--sample", name, "--verify"]) == 0
        assert capsys.readouterr().out == f"{name}: 400 committed, 400 re-drawn, identical: True\n"
    changed = lists / "dev_seal_s3_400_ids.csv"
    changed.write_text(changed.read_text().replace("Fatal-C", "Fatal-X", 1))
    assert draw_sealed.main(["--sample", "dev-seal-s3-400", "--verify"]) == 1
    assert "identical: False" in capsys.readouterr().out


def test_the_s3_draw_needs_the_s27_list_and_writes_nothing_without_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _processed, lists, _dev400, _seal27 = _env(tmp_path, monkeypatch)
    (lists / "dev_seal_400_ids.csv").unlink()
    with pytest.raises(FileNotFoundError):
        draw_sealed.main(["--sample", "dev-seal-s3-400"])
    assert not (lists / "dev_seal_s3_400_ids.csv").exists()


def test_an_unknown_sample_is_refused_by_the_parser() -> None:
    with pytest.raises(SystemExit) as stopped:
        draw_sealed.main(["--sample", "dev-400"])
    assert stopped.value.code == 2


def test_strata_count_fatal_and_class_for_the_listed_cases_only(tmp_path: Path) -> None:
    processed = _write_cases(
        tmp_path,
        [
            ("A", "2016-01-01", "dev", "C", _raw(fatal=True)),
            ("B", "2016-01-01", "dev", "C", _raw(fatal=False)),
            ("C", "2016-01-01", "dev", "F", _raw(fatal=False)),
            ("D", "2016-01-01", "dev", "L", _raw(fatal=False)),
            ("E", "2016-01-01", "dev", "L", _raw(fatal=True)),  # not listed
        ],
    )
    assert draw_sealed.strata(processed, ["A", "B", "C", "D"]) == {
        "fatal": {"C": 1, "F": 0, "L": 0},
        "non-fatal": {"C": 1, "F": 1, "L": 1},
    }
