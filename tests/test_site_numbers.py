"""The site's numbers file (S5 spec §17.3): every number from a committed results file."""

import json
import re
import subprocess
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
        site_numbers.build(tmp_path, recorded=_fake_recorded, added=_fake_added)


def test_a_changed_number_is_read_as_changed(tmp_path: Path) -> None:
    _copy_results(tmp_path)
    target = tmp_path / "s32-heldout-diagnosis.txt"
    target.write_text(target.read_text().replace("the loop top-1: 23.5%", "the loop top-1: 24.0%"))
    built = site_numbers.build(tmp_path, recorded=_fake_recorded, added=_fake_added)
    assert built.entries["ladder.loop.top1"].value == 24.0


def test_a_line_matched_twice_fails(tmp_path: Path) -> None:
    # A pattern must find exactly one line, so a duplicated line is not read silently.
    _copy_results(tmp_path)
    target = tmp_path / "s32-heldout-diagnosis.txt"
    line = next(x for x in target.read_text().splitlines() if x.startswith("the loop top-1:"))
    target.write_text(target.read_text() + line + "\n")
    with pytest.raises(site_numbers.ExtractError, match=r"ladder\.loop\.top1.*2 lines"):
        site_numbers.build(tmp_path, recorded=_fake_recorded, added=_fake_added)


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
        site_numbers.build(tmp_path, recorded=_fake_recorded, added=_fake_added)


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


def test_question_6_carries_its_sentence_and_codes_from_the_results_file() -> None:
    numbers = site_numbers.build(_RESULTS)
    sentence = numbers.texts["q6.one.sentence"]
    assert sentence == "A loss of engine power for undetermined reasons."
    assert numbers.entries["q6.one.distinct"].value == 18
    assert numbers.entries["q6.one.cases"].value == 33
    codes = numbers.lists["q6.one.codes"]
    assert len(codes) == 18
    assert sum(int(c["count"]) for c in codes) == 33
    assert codes[0] == {
        "count": 4,
        "code": "350342",
        "label": "Initial Climb / Loss of engine power (partial)",
    }


def test_question_6s_counts_must_add_up(tmp_path: Path) -> None:
    _copy_results(tmp_path)
    target = tmp_path / "s5-one-sentence-dev.txt"
    target.write_text(target.read_text().replace("cases: 33", "cases: 34"))
    with pytest.raises(site_numbers.ExtractError, match=r"q6\.one\.codes"):
        site_numbers.build(tmp_path, recorded=_fake_recorded, added=_fake_added)


def test_question_7s_belief_path_is_read_from_decision_0186s_reading() -> None:
    e = site_numbers.build(_RESULTS).entries
    got = {k.removeprefix("q7.path."): v.value for k, v in e.items() if k.startswith("q7.path.")}
    assert got == {
        "cases": 394,
        "no_belief_after": 25,
        "before": 43,
        "after": 82,
        "answer": 94,
        "reading.stayed_right": 35,
        "reading.fixed": 47,
        "reading.broken": 8,
        "reading.stayed_wrong": 304,
        "coding.stayed_right": 74,
        "coding.fixed": 20,
        "coding.broken": 8,
        "coding.stayed_wrong": 292,
    }
    assert e["q7.path.before"].run == "20261004T140804-e0dc881-heldout-400-C"
    assert e["q7.path.before"].sample == "heldout-400"


# Step 5 (the Methods page): commits, history, limits and the predictions.

_FAKE_SHA = "0" * 40


def _fake_recorded(_path: str) -> str:
    return _FAKE_SHA


def _fake_added(_path: str) -> tuple[str, str]:
    return _FAKE_SHA, "2026-01-01"


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", *args],  # noqa: S607 -- git from PATH
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )


def test_every_entry_names_the_commit_that_recorded_its_file() -> None:
    # Andy, 2026-10-14, plan step 5 choice 2: both commits, where both exist.
    for key, entry in site_numbers.build(_RESULTS).entries.items():
        assert re.fullmatch(r"[0-9a-f]{40}", entry.recorded_in), key
        log = _git("log", "-1", "--format=%H", "--", entry.results_file).stdout.strip()
        assert entry.recorded_in == log, key


def test_a_run_entry_names_the_commit_in_its_run() -> None:
    entries = site_numbers.build(_RESULTS).entries
    assert entries["ladder.loop.top1"].run_commit == "e0dc881"
    assert entries["ladder.fixed.top1"].run_commit == "dd64854"
    assert entries["q6.twins"].run_commit is None
    for key, entry in entries.items():
        assert (entry.run is None) == (entry.run_commit is None), key


# S1 (pull request 5) was squash-merged before decision 0033, so its ceiling run's commit is not
# in main's history. GitHub keeps it through the pull request's refs (checked 2026-10-14), and
# the Methods page says so beside the entry.
SQUASHED_BEFORE_0033 = frozenset({"c717ab5"})


def test_every_commit_named_is_in_the_branch_history() -> None:
    # A commit outside main's history would be a dead link on GitHub after the merge (0033).
    for key, entry in site_numbers.build(_RESULTS).entries.items():
        for sha in (entry.recorded_in, entry.run_commit):
            if sha is not None and sha not in SQUASHED_BEFORE_0033:
                assert _git("merge-base", "--is-ancestor", sha, "HEAD").returncode == 0, key


def test_recorded_in_refuses_a_changed_or_untracked_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Review, 2026-10-14: the refusal itself, in a real repository, not an injected one.
    def git(*args: str) -> None:
        subprocess.run(  # noqa: S603 -- fixed argv, no shell
            ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],  # noqa: S607
            cwd=tmp_path,
            check=True,
            capture_output=True,
        )

    git("init", "-q")
    (tmp_path / "kept.txt").write_text("one\n")
    git("add", "kept.txt")
    git("commit", "-q", "-m", "kept")
    monkeypatch.setattr(site_numbers, "_REPO", tmp_path)
    assert re.fullmatch(r"[0-9a-f]{40}", site_numbers.recorded_in("kept.txt"))
    (tmp_path / "kept.txt").write_text("two\n")
    with pytest.raises(site_numbers.UncommittedError, match=r"kept\.txt"):
        site_numbers.recorded_in("kept.txt")
    (tmp_path / "new.txt").write_text("new\n")
    with pytest.raises(site_numbers.UncommittedError, match=r"new\.txt"):
        site_numbers.recorded_in("new.txt")


def test_a_results_file_with_uncommitted_changes_is_refused() -> None:
    def dirty(path: str) -> str:
        raise site_numbers.UncommittedError(path)

    with pytest.raises(site_numbers.UncommittedError, match=r"docs/results/\S+\.txt"):
        site_numbers.build(_RESULTS, recorded=dirty)


def test_the_history_entries() -> None:
    # Spec §9 item 6: the bars the ladder replaced.
    e = site_numbers.build(_RESULTS).entries
    s1 = e["history.s1_ceiling.top1"]
    assert (s1.value, s1.low, s1.high, s1.n) == (10.8, 8.1, 14.2, 399)
    assert s1.model == "openai/gpt-5.6-luna"
    assert s1.run == "20260917T061527-c717ab5-heldout-400-ceiling"
    fixed = e["history.s24_fixed.top1"]
    assert (fixed.value, fixed.low, fixed.high, fixed.n) == (26.5, 22.1, 31.5, 336)
    assert fixed.run == "20260924T185800-7071800-heldout-400-B"
    ceiling = e["history.s24_ceiling.top1"]
    assert (ceiling.value, ceiling.low, ceiling.high, ceiling.n) == (10.5, 7.9, 13.9, 399)
    assert ceiling.run == "20260924T070202-05c5c5b-heldout-400-ceiling"


def test_a_block_printed_twice_must_read_the_same_both_times(tmp_path: Path) -> None:
    # s24-bars.txt prints arm B's report twice; a difference between the two copies is refused.
    _copy_results(tmp_path)
    target = tmp_path / "s24-bars.txt"
    text = target.read_text()
    last = text.rindex("| all | 336 | 26.5%")
    target.write_text(text[:last] + text[last:].replace("26.5%", "26.6%", 1))
    with pytest.raises(site_numbers.ExtractError, match=r"history\.s24_fixed\.top1"):
        site_numbers.build(tmp_path, recorded=_fake_recorded, added=_fake_added)


def test_the_limits_entries() -> None:
    e = site_numbers.build(_RESULTS).entries
    assert (e["limits.cap"].value, e["limits.cap"].unit) == (0.30, "usd")
    assert (e["limits.loop.failed"].value, e["limits.loop.failed"].n) == (6, 400)
    assert (e["limits.loop.format"].value, e["limits.loop.format"].n) == (4, 400)
    assert (e["limits.noise_a.format"].value, e["limits.noise_a.format"].n) == (5, 401)
    assert (e["limits.noise_b.format"].value, e["limits.noise_b.format"].n) == (8, 401)
    assert e["limits.noise_a.format"].sample == "dev-400"


def test_the_nine_predictions_are_the_registrations_words() -> None:
    # Andy, 2026-10-14, plan step 5 choice 3: as written, copied, never retyped.
    items = site_numbers.build(_RESULTS).lists["s32.predictions"]
    assert [p["number"] for p in items] == list(range(1, 10))
    registration = " ".join((_REPO / "docs/rounds/s3-registration.md").read_text().split())
    for p in items:
        assert str(p["text"]) in registration.replace("*", "").replace("`", ""), p["number"]
    first = items[0]
    assert first["title"] == "Top-1"
    assert first["scope"] == "held-out"
    assert str(first["text"]).startswith("the loop matches but does not beat arm B")
    assert first["outcome"] == "not met"
    assert [p["colon"] for p in items] == [":"] * 7 + [""] + [":"]  # item 8 has none
    assert site_numbers.build(_RESULTS).texts["s32.not_predicted"] == (
        "Not predicted: the level of top-1."
    )
    assert str(first["result"]).startswith("top-1: the loop matches but does not beat arm B")
    met = [p["number"] for p in items if p["outcome"] == "met"]
    assert met == [3, 7, 8, 9]


def test_predictions_must_be_nine_on_both_sides(tmp_path: Path) -> None:
    _copy_results(tmp_path)
    target = tmp_path / "s32-claims-heldout.txt"
    target.write_text(
        "\n".join(x for x in target.read_text().splitlines() if not x.startswith("P9:")) + "\n"
    )
    with pytest.raises(site_numbers.ExtractError, match=r"s32\.predictions"):
        site_numbers.build(tmp_path, recorded=_fake_recorded, added=_fake_added)


def test_the_predictions_read_as_they_did_before_the_held_out_run(tmp_path: Path) -> None:
    # The registration gained a dated note after its first commit; the predictions above it must
    # be the words committed before any S3.2 run.
    numbers = site_numbers.build(_RESULTS)
    first = numbers.texts["s32.registered_in"]
    then = tmp_path / "s3-registration.md"
    then.write_text(_git("show", f"{first}:docs/rounds/s3-registration.md").stdout)
    before = site_numbers.build(_RESULTS, registration=then).lists["s32.predictions"]
    assert before == numbers.lists["s32.predictions"]
    assert numbers.texts["s32.registered_on"] == "2026-10-04"
    log = _git("log", "--diff-filter=A", "--format=%H", "--", "docs/rounds/s3-registration.md")
    assert first == log.stdout.strip()
