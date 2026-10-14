"""The site's numbers file (S5 spec §17.3): every number from a committed results file."""

import json
from pathlib import Path

import pytest
from scripts import site_numbers

_REPO = Path(__file__).resolve().parents[1]
_RESULTS = _REPO / "docs/results"


def _copy_results(into: Path) -> None:
    for f in _RESULTS.glob("*.txt"):
        (into / f.name).write_text(f.read_text())


def test_reads_the_ladder_from_the_committed_results() -> None:
    numbers = site_numbers.build(_RESULTS)
    loop = numbers.entries["ladder.loop.top1"]
    assert (loop.value, loop.low, loop.high, loop.n) == (23.5, 19.2, 27.5, 400)
    assert loop.results_file == "docs/results/s32-heldout-diagnosis.txt"
    baseline = numbers.entries["ladder.baseline.top1"]
    assert (baseline.value, baseline.low, baseline.high, baseline.n) == (17.7, 16.6, 18.9, 4241)
    no_docket = numbers.entries["ladder.no_docket.top1"]
    assert (no_docket.value, no_docket.low, no_docket.high) == (15.0, 11.5, 18.5)
    assert numbers.entries["ladder.loop.billed"].value == pytest.approx(2.0610)
    assert numbers.entries["ladder.fixed.billed"].value == pytest.approx(2.1347)
    # Billed costs only (Andy, 2026-10-14): no list-price entry reaches the site.
    assert not [key for key in numbers.entries if key.endswith(".cost")]


def test_every_entry_names_a_file_and_script_that_exist() -> None:
    for key, entry in site_numbers.build(_RESULTS).entries.items():
        assert (_REPO / entry.results_file).is_file(), key
        script = entry.script.split(" ")[0]
        assert (_REPO / script).exists(), key


def test_the_committed_numbers_file_is_current() -> None:
    # Review Focus 1: a re-run results file must be followed by a regenerated numbers file.
    committed = json.loads((_REPO / "site/data/numbers.json").read_text())
    assert committed == json.loads(site_numbers.build(_RESULTS).model_dump_json())


def test_a_missing_line_fails_loudly_naming_entry_and_file(tmp_path: Path) -> None:
    # Review Focus 2.
    _copy_results(tmp_path)
    target = tmp_path / "s32-heldout-diagnosis.txt"
    target.write_text(target.read_text().replace("the loop top-1:", "the agent top-1:"))
    with pytest.raises(
        site_numbers.ExtractError, match=r"ladder\.loop\.top1.*s32-heldout-diagnosis"
    ):
        site_numbers.build(tmp_path)


def test_a_changed_number_is_read_as_changed(tmp_path: Path) -> None:
    _copy_results(tmp_path)
    target = tmp_path / "s32-heldout-diagnosis.txt"
    target.write_text(target.read_text().replace("the loop top-1: 23.5%", "the loop top-1: 24.0%"))
    assert site_numbers.build(tmp_path).entries["ladder.loop.top1"].value == 24.0


def test_a_line_matched_twice_fails(tmp_path: Path) -> None:
    # A pattern must find exactly one line, so a duplicated line is not read silently.
    _copy_results(tmp_path)
    target = tmp_path / "s32-heldout-diagnosis.txt"
    line = next(x for x in target.read_text().splitlines() if x.startswith("the loop top-1:"))
    target.write_text(target.read_text() + line + "\n")
    with pytest.raises(site_numbers.ExtractError, match=r"ladder\.loop\.top1.*2 lines"):
        site_numbers.build(tmp_path)


def test_check_names_the_first_stale_key(tmp_path: Path) -> None:
    stale = json.loads(site_numbers.build(_RESULTS).model_dump_json())
    stale["entries"]["q3.docket_gain"]["value"] = 0.0
    path = tmp_path / "numbers.json"
    path.write_text(json.dumps(stale))
    assert site_numbers.first_difference(path, site_numbers.build(_RESULTS)) == (
        "entries.q3.docket_gain"
    )


def test_a_missing_overall_block_is_not_read_from_the_fatal_block(tmp_path: Path) -> None:
    # Review, 2026-10-14: the section must not run on into the fatal block's own top-1 line.
    _copy_results(tmp_path)
    target = tmp_path / "s26-armB-v2-dev.txt"
    lines = target.read_text().splitlines()
    start = next(i for i, x in enumerate(lines) if x.startswith("evidence-version comparison"))
    del lines[start + 1 : start + 5]  # the overall "paired difference" line and its three rows
    target.write_text("\n".join(lines) + "\n")
    with pytest.raises(site_numbers.ExtractError, match=r"q4\.v2_gain.*no line"):
        site_numbers.build(tmp_path)


def test_ties_at_the_cut_off_are_all_shown() -> None:
    pairs = site_numbers.build(_RESULTS).lists["q5.pairs"]
    counts = [int(p["count"]) for p in pairs]
    assert counts == sorted(counts, reverse=True)
    assert len(pairs) >= 5
    assert counts[-1] == counts[4]


def test_question_5_holds_s26_and_s3_side_by_side() -> None:
    # Andy, 2026-10-14: keep S2.6's figure, which led to coding guidance, and add S3's rerun.
    numbers = site_numbers.build(_RESULTS)
    s26, s3 = numbers.entries["q5.first_right"], numbers.entries["q5.s3.first_right"]
    assert (s26.value, s26.n) == (88, 399)
    assert (s3.value, s3.n) == (110, 399)
    assert s26.run == "20260926T085904-d19aafa-dev-400-B"
    assert s3.run == "20260929T053953-674c92e-dev-400-B-tools-check-luna"
    assert numbers.entries["q5.s3.in_sequence"].value == 148
    assert numbers.lists["q5.s3.pairs"][0] == {
        "count": 14,
        "ntsb": "Aerodynamic stall/spin",
        "agent": "Loss of control in flight",
    }
