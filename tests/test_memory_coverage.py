"""Lesson coverage, the gate and the choices file of decision 0213. Offline; invented lessons."""

import json
import re
import textwrap
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from scripts import memory_coverage as mc
from scripts import memory_embed

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.memory import checks, coverage, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, Support
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.settings import Settings

NOW = datetime(2026, 10, 17, 12, 0, tzinfo=UTC)
WORDS = {"L1": "one", "L2": "two", "L3": "three", "L4": "four"}
LOC, STALL, OTHER = "550240", "500241", "552230"
APPLY_RUN = "20261017T090550Z-abc1234-memory-cause-apply-t"
SMALL, LARGE, QWEN = (
    "openai/text-embedding-3-small",
    "openai/text-embedding-3-large",
    "qwen/qwen3-embedding-8b",
)


def _predicts(
    lid: str,
    first: tuple[str, ...] = (),
    cats: tuple[str, ...] = (),
    applies: int = 20,
    agrees: int = 10,
) -> Lesson:
    kind = "evidence" if not first else ("split" if len(first) > 1 else "convention")
    return Lesson(
        lesson_id=lid,
        kind=kind,
        statement=f"lesson {WORDS[lid]}",
        scope="a scope",
        predicts=Prediction(first_occurrence=first, finding_categories=cats),
        written_in=2010,
        support=Support(applies=applies, agrees=agrees),
    )


def _case(case_id: str, occ: tuple[str, ...], findings: tuple[str, ...] = ()) -> LearningCase:
    return LearningCase(case_id, 0, "a cause", occ, findings)


def _raw(occ: list[str], findings: list[str] | None = None) -> dict[str, object]:
    events = [
        {"eventCode": code, "isDefiningEvent": i == 0, "sequenceNumber": i + 1}
        for i, code in enumerate(occ)
    ]
    flagged = [
        {"findingCode": code, "inProbableCause": True, "findingNumber": i + 1}
        for i, code in enumerate(findings or [])
    ]
    return {
        "narratives": [{"probableCause": "a cause"}],
        "aircrafts": [{"events": events, "findings": flagged}],
    }


# --- coverage --------------------------------------------------------------------------------


def test_coverage_counts_hits_and_precision() -> None:
    cases = {"A": _case("A", (LOC,), ("0101010101",)), "B": _case("B", (OTHER,))}
    chosen = {"A": [_predicts("L1", first=(LOC,)), _predicts("L2", first=(STALL,))], "B": []}
    cov = coverage.coverage(chosen, cases)
    assert cov.hits == {"A": True, "B": False}
    assert (cov.hit_rate, cov.precision) == (0.5, 0.5)
    assert (cov.handed_out, cov.agreeing) == (2, 1)


def test_agreement_needs_every_part_a_lesson_predicts() -> None:
    cases = {"A": _case("A", (LOC,), ("0101010101",))}
    both = _predicts("L1", first=(LOC,), cats=("020630",))
    category = _predicts("L2", cats=("010101",))
    cov = coverage.coverage({"A": [both, category]}, cases)
    assert (cov.agreeing, cov.hits["A"]) == (1, True)


def test_a_case_missing_from_the_choices_has_no_lesson_and_misses() -> None:
    cov = coverage.coverage({}, {"A": _case("A", (LOC,))})
    assert cov.hits == {"A": False}
    assert (cov.hit_rate, cov.precision, cov.handed_out) == (0.0, 0.0, 0)


def test_verdict_cases_leaves_out_a_case_without_occurrence_codes() -> None:
    cases, left_out = coverage.verdict_cases(
        ["A", "B"], [_raw([LOC], ["0101010101", "0202020202"]), _raw([])]
    )
    assert list(cases) == ["A"]
    assert left_out == 1
    assert cases["A"].occurrence == (LOC,)
    assert cases["A"].findings == ("0101010101", "0202020202")


# --- the gate --------------------------------------------------------------------------------


def _cov(hits: dict[str, bool], handed: int, agreeing: int) -> coverage.Coverage:
    return coverage.Coverage(hits=hits, handed_out=handed, agreeing=agreeing)


IDS = [f"C{i:03d}" for i in range(40)]
TODAY = _cov({i: n < 10 for n, i in enumerate(IDS)}, 60, 30)  # hit rate 25%, precision 50%
PRICES = {SMALL: 2e-08, LARGE: 1.3e-07, QWEN: 1e-08}


def _better(extra: int, precision_agreeing: int) -> coverage.Coverage:
    return _cov({i: n < 10 + extra for n, i in enumerate(IDS)}, 100, precision_agreeing)


def test_gate_one_passes() -> None:
    winner, lines = mc.gate_rule(TODAY, {SMALL: _better(20, 50), LARGE: TODAY}, PRICES)
    assert winner == SMALL
    assert any(line.startswith(f"{SMALL}:") and line.endswith("passed") for line in lines)
    assert any(line.startswith(f"{LARGE}:") and "not passed" in line for line in lines)


def test_gate_tie_goes_to_the_lower_price() -> None:
    same = _better(20, 60)
    winner, _ = mc.gate_rule(TODAY, {LARGE: same, SMALL: same, QWEN: same}, PRICES)
    assert winner == QWEN


def test_gate_highest_hit_rate_goes_forward() -> None:
    winner, _ = mc.gate_rule(TODAY, {QWEN: _better(15, 60), LARGE: _better(25, 60)}, PRICES)
    assert winner == LARGE


def test_gate_higher_hit_rate_but_lower_precision_fails() -> None:
    winner, lines = mc.gate_rule(TODAY, {SMALL: _better(25, 49)}, PRICES)
    assert winner is None
    assert "precision" in lines[0]


def test_gate_interval_touching_zero_fails() -> None:
    winner, lines = mc.gate_rule(TODAY, {SMALL: _better(1, 60)}, PRICES)
    assert winner is None
    assert "interval" in lines[0]


def test_gate_none_pass_gives_none() -> None:
    worse = _cov(dict.fromkeys(IDS, False), 100, 60)
    assert mc.gate_rule(TODAY, {SMALL: worse, LARGE: worse}, PRICES)[0] is None


def test_gate_docstring_matches_the_registration() -> None:
    text = Path("docs/rounds/memory-embed-lookup.md").read_text()
    section = text.split("## 5. The gate, word for word", 1)[1]
    block = re.search(r"```text\n(.*?)\n```", section, re.DOTALL)
    assert block is not None
    assert textwrap.dedent(mc.gate_rule.__doc__ or "").strip() == block.group(1).strip()


# --- the reading -----------------------------------------------------------------------------


LESSONS = (
    _predicts("L1", first=(LOC,)),
    _predicts("L2", first=(STALL,)),
    _predicts("L3", first=(OTHER,), applies=30, agrees=3),
    _predicts("L4", first=(LOC,), applies=5, agrees=5),  # below the floor
)
CASES = {"A": _case("A", (LOC,)), "B": _case("B", (STALL,))}


def _snapshot(directory: Path) -> str:
    directory.mkdir(parents=True)
    memory = Memory(name="t", periods=(2010,), lessons=LESSONS[:2], pushed_out=LESSONS[2:])
    path = snapshots.save(memory, directory)
    stamp = checks.Stamp(
        snapshot="t",
        sha256=snapshots.sha256_of(path),
        withheld_texts_compared=1,
        causes_compared=1,
        checked_on=date(2026, 10, 17),
        commit="abc1234",
        dirty=False,
    )
    snapshots.stamp_path("t", directory).write_text(stamp.model_dump_json())
    return snapshots.sha256_of(path)


def _apply_run(
    settings: Settings, sha: str, applies: dict[str, list[str]], **changes: object
) -> None:
    folder = settings.runs_dir / APPLY_RUN
    folder.mkdir(parents=True)
    summary: dict[str, object] = {"sample": "dev-steer-400", "snapshot": "t"}
    summary |= {"snapshot_sha256": sha, "cases_sent": 2, "failed": 0}
    summary |= {"model": "claude-sonnet-5-5", "effort": "high", **changes}
    (folder / "apply.json").write_text(json.dumps(summary))
    (folder / "applies.json").write_text(json.dumps(applies))


def _embed_run(
    settings: Settings, model: str, sha: str, cases: dict[str, list[float]], **changes: object
) -> str:
    run_id = f"20261017T120000Z-abc1234-memory-embed-dev-steer-400-{memory_embed.slug(model)}"
    folder = settings.runs_dir / run_id
    folder.mkdir(parents=True)
    body: dict[str, object] = {
        "model": model,
        "sample": "dev-steer-400",
        "snapshot": "t",
        "snapshot_sha256": sha,
        "lessons": {"L1": [1.0, 0.0], "L2": [0.0, 1.0], "L3": [0.7, 0.7], "L4": [1.0, 0.0]},
        "cases": cases,
        "failed_cases": [],
        "commit": "abc1234",
        **changes,
    }
    (folder / memory_embed.VECTORS_FILE).write_text(json.dumps(body))
    return run_id


@pytest.fixture
def setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, str]:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", False))
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): True)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(mc, "verdict_cases_for", lambda processed, sample: (dict(CASES), 0))
    settings = Settings(data_dir=tmp_path / "data")
    path = settings.data_dir / memory_embed.MODELS_FILE
    path.parent.mkdir(parents=True)
    rows = [{"id": m, "pricing": {"prompt": str(p)}} for m, p in PRICES.items()]
    path.write_text(json.dumps({"data": rows}))
    return settings, _snapshot(tmp_path / "snapshots")


def _main(settings: Settings, *argv: str) -> int:
    out = [] if "--out" in argv else ["--out", str(settings.data_dir.parent / "coverage.txt")]
    return mc.main(["--snapshot", "t", *argv, *out], settings=settings, now=lambda: NOW)


def test_steering_reading_gates_and_writes_the_winners_choices(
    setup: tuple[Settings, str], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = setup
    _apply_run(settings, sha, {"A": ["L2"], "B": []})  # today: no hit on A or B
    near_truth = {"A": [1.0, 0.1], "B": [0.1, 1.0]}  # closest: A -> L1, B -> L2
    runs = [_embed_run(settings, m, sha, near_truth) for m in (SMALL, LARGE, QWEN)]
    out = tmp_path / "coverage.txt"
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs, "--out", str(out)) == 0
    text = capsys.readouterr().out
    assert out.read_text() == text
    assert text.splitlines()[-1] == f"winner: {QWEN}"  # three equal: the cheapest
    choices_run = re.search(r"choices run: (\S+)", text)
    assert choices_run is not None
    folder = settings.runs_dir / choices_run.group(1)
    chosen = json.loads((folder / mc.CHOICES_FILE).read_text())
    assert chosen["A"][0] == "L1"
    assert chosen["B"][0] == "L2"
    assert "L4" not in chosen["A"]  # below the floor
    summary = json.loads((folder / mc.CHOICE_SUMMARY_FILE).read_text())
    assert summary == {
        "sample": "dev-steer-400",
        "snapshot": "t",
        "snapshot_sha256": sha,
        "k": 5,
        "min_applies": 10,
        "method": "embedding",
        "model": QWEN,
        "source_run": runs[2],
        "commit": "abc1234",
        "dirty": False,
    }


def test_no_winner_writes_no_choices(
    setup: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = setup
    _apply_run(settings, sha, {"A": ["L1"], "B": ["L2"]})  # today: both hit, precision 100%
    near = {"A": [1.0, 0.1], "B": [0.1, 1.0]}
    runs = [_embed_run(settings, m, sha, near) for m in (SMALL, LARGE, QWEN)]
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs) == 0
    text = capsys.readouterr().out
    assert text.splitlines()[-1] == "winner: none"
    assert "choices run:" not in text
    assert not list(settings.runs_dir.glob("*-memory-choices-*"))


@pytest.mark.parametrize(
    "changes", [{"sample": "dev-400"}, {"snapshot": "other"}, {"snapshot_sha256": "0" * 64}]
)
def test_a_vectors_file_for_another_sample_or_snapshot_is_refused(
    setup: tuple[Settings, str], capsys: pytest.CaptureFixture[str], changes: dict[str, object]
) -> None:
    settings, sha = setup
    _apply_run(settings, sha, {"A": [], "B": []})
    run = _embed_run(settings, SMALL, sha, {"A": [1.0, 0.0], "B": [0.0, 1.0]}, **changes)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", run) == 1
    assert "refused" in capsys.readouterr().out


def test_two_runs_of_one_model_are_refused(
    setup: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = setup
    _apply_run(settings, sha, {"A": [], "B": []})
    first = _embed_run(settings, SMALL, sha, {"A": [1.0, 0.0]})
    second = settings.runs_dir / f"{first}-again"
    (settings.runs_dir / first).rename(second)
    _embed_run(settings, SMALL, sha, {"A": [1.0, 0.0]})
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", first, second.name) == 1
    assert "two embedding runs" in capsys.readouterr().out


def _steering_winner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, model: str) -> None:
    path = tmp_path / "memory-coverage-dev.txt"
    path.write_text(f"lesson coverage ...\nwinner: {model}\n")
    monkeypatch.setattr(memory_embed, "STEERING_COVERAGE", path)


def test_dev_seal_reading_names_no_winner_and_writes_the_named_models_choices(
    setup: tuple[Settings, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, sha = setup
    _steering_winner(tmp_path, monkeypatch, SMALL)
    monkeypatch.setattr(mc, "verdict_cases_for", lambda processed, sample: (dict(CASES), 0))
    _apply_run(settings, sha, {"A": ["L1"], "B": []}, sample="dev-seal-400")
    run = _embed_run(
        settings, SMALL, sha, {"A": [1.0, 0.1], "B": [0.1, 1.0]}, sample="dev-seal-400"
    )
    argv = ["--sample", "dev-seal-400", "--applies", APPLY_RUN, "--embeds", run, "--model", SMALL]
    assert _main(settings, *argv) == 0
    text = capsys.readouterr().out
    assert text.splitlines()[-1] == "description only (decision 0213)"
    assert "gate" not in text
    choices_run = re.search(r"choices run: (\S+)", text)
    assert choices_run is not None
    assert "-memory-choices-dev-seal-400-" in choices_run.group(1)


def test_dev_seal_reading_needs_the_model(
    setup: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = setup
    _apply_run(settings, sha, {"A": [], "B": []}, sample="dev-seal-400")
    run = _embed_run(settings, SMALL, sha, {"A": [1.0, 0.0]}, sample="dev-seal-400")
    assert _main(settings, "--sample", "dev-seal-400", "--applies", APPLY_RUN, "--embeds", run) == 1
    assert "--model" in capsys.readouterr().out


def test_dev_seal_reading_is_refused_before_registration(
    setup: tuple[Settings, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = setup
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): False)
    _apply_run(settings, sha, {"A": [], "B": []}, sample="dev-seal-400")
    run = _embed_run(settings, SMALL, sha, {"A": [1.0, 0.0]}, sample="dev-seal-400")
    argv = ["--sample", "dev-seal-400", "--applies", APPLY_RUN, "--embeds", run, "--model", SMALL]
    assert _main(settings, *argv) == 1
    assert "0213" in capsys.readouterr().out


def test_steering_gate_needs_all_three_candidates(
    setup: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = setup
    _apply_run(settings, sha, {"A": [], "B": []})
    near = {"A": [1.0, 0.1], "B": [0.1, 1.0]}
    runs = [_embed_run(settings, m, sha, near) for m in (SMALL, QWEN)]
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs) == 1
    assert "all three" in capsys.readouterr().out
    assert not list(settings.runs_dir.glob("*-memory-choices-*"))


def test_a_dirty_tree_is_refused_before_choices_are_written(
    setup: tuple[Settings, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = setup
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", True))
    _apply_run(settings, sha, {"A": ["L2"], "B": []})
    near = {"A": [1.0, 0.1], "B": [0.1, 1.0]}
    runs = [_embed_run(settings, m, sha, near) for m in (SMALL, LARGE, QWEN)]
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs) == 1
    assert "uncommitted changes" in capsys.readouterr().out
    assert not list(settings.runs_dir.glob("*-memory-choices-*"))


def test_choices_record_a_clean_tree(setup: tuple[Settings, str]) -> None:
    settings, sha = setup
    _apply_run(settings, sha, {"A": ["L2"], "B": []})
    near = {"A": [1.0, 0.1], "B": [0.1, 1.0]}
    runs = [_embed_run(settings, m, sha, near) for m in (SMALL, LARGE, QWEN)]
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs) == 0
    (summary,) = settings.runs_dir.glob(f"*-memory-choices-*/{mc.CHOICE_SUMMARY_FILE}")
    assert json.loads(summary.read_text())["dirty"] is False


def test_dev_seal_reading_takes_one_run_of_the_steering_winner(
    setup: tuple[Settings, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, sha = setup
    _steering_winner(tmp_path, monkeypatch, SMALL)
    _apply_run(settings, sha, {"A": [], "B": []}, sample="dev-seal-400")
    near = {"A": [1.0, 0.1], "B": [0.1, 1.0]}
    small = _embed_run(settings, SMALL, sha, near, sample="dev-seal-400")
    large = _embed_run(settings, LARGE, sha, near, sample="dev-seal-400")
    base = ["--sample", "dev-seal-400", "--applies", APPLY_RUN]
    assert _main(settings, *base, "--embeds", small, large, "--model", SMALL) == 1
    assert "one embedding run" in capsys.readouterr().out
    assert _main(settings, *base, "--embeds", large, "--model", LARGE) == 1
    assert f"only the steering winner {SMALL}" in capsys.readouterr().out
    assert not list(settings.runs_dir.glob("*-memory-choices-*"))


# --- the picking call's run (decision 0213's fallback) -----------------------------------------

PICK_RUN = "20261017T190000Z-abc1234-memory-cause-pick-dev-steer-400-openai-text-embedding-3-large"
EIGHT = {cid: _case(cid, (LOC,) if i % 2 == 0 else (STALL,)) for i, cid in enumerate("ABCDEFGH")}
NEAR_EIGHT = {cid: [1.0, 0.1] if i % 2 == 0 else [0.1, 1.0] for i, cid in enumerate("ABCDEFGH")}
RIGHT_PICKS = {cid: ["L1"] if i % 2 == 0 else ["L2"] for i, cid in enumerate("ABCDEFGH")}


def _pick_run(
    settings: Settings, sha: str, source: str, picks: dict[str, list[str]], **changes: object
) -> str:
    folder = settings.runs_dir / PICK_RUN
    folder.mkdir(parents=True)
    summary: dict[str, object] = {
        "sample": "dev-steer-400",
        "snapshot": "t",
        "snapshot_sha256": sha,
        "embed_run": source,
        "embed_model": LARGE,
        "model": "claude-sonnet-5-5",
        "effort": "high",
        "shortlist": 20,
        "cases_sent": len(picks),
        "failed": 0,
        "commit": "abc1234",
        **changes,
    }
    (folder / "pick.json").write_text(json.dumps(summary))
    (folder / "picks.json").write_text(json.dumps(picks))
    return PICK_RUN


@pytest.fixture
def eight(setup: tuple[Settings, str], monkeypatch: pytest.MonkeyPatch) -> tuple[Settings, str]:
    """Eight cases; today's lookup hits one with one lesson; the embeddings hit all at 33%."""
    settings, sha = setup
    monkeypatch.setattr(mc, "verdict_cases_for", lambda processed, sample: (dict(EIGHT), 0))
    _apply_run(settings, sha, {"A": ["L1"]})
    return settings, sha


def _three(settings: Settings, sha: str) -> list[str]:
    return [_embed_run(settings, m, sha, NEAR_EIGHT) for m in (SMALL, LARGE, QWEN)]


def test_picks_are_scored_and_gated_the_same_way(
    eight: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = eight
    runs = _three(settings, sha)
    pick = _pick_run(settings, sha, runs[1], RIGHT_PICKS)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs, "--picks", pick) == 0
    text = capsys.readouterr().out
    assert f"pick:{LARGE}: hit rate +87.5 points" in text
    assert f"{SMALL}: hit rate +87.5 points" in text  # passes the interval, not precision
    assert text.splitlines()[-1] == f"winner: pick:{LARGE}"
    (summary_path,) = settings.runs_dir.glob(f"*-memory-choices-*/{mc.CHOICE_SUMMARY_FILE}")
    assert "-memory-choices-dev-steer-400-pick-openai-text-embedding-3-large" in str(summary_path)
    summary = json.loads(summary_path.read_text())
    assert (summary["method"], summary["model"], summary["source_run"]) == ("pick", LARGE, pick)
    chosen = json.loads((summary_path.parent / mc.CHOICES_FILE).read_text())
    assert chosen == RIGHT_PICKS


def test_picks_past_two_percent_failed_replies_are_refused(
    eight: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = eight
    runs = _three(settings, sha)
    pick = _pick_run(settings, sha, runs[1], RIGHT_PICKS, cases_sent=401, failed=9)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs, "--picks", pick) == 1
    assert "9 of 401" in capsys.readouterr().out
    assert not list(settings.runs_dir.glob("*-memory-choices-*"))


def test_eight_failed_replies_of_401_are_allowed(eight: tuple[Settings, str]) -> None:
    settings, sha = eight
    runs = _three(settings, sha)
    pick = _pick_run(settings, sha, runs[1], RIGHT_PICKS, cases_sent=401, failed=8)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs, "--picks", pick) == 0


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"sample": "dev-seal-400"}, "differs in sample"),
        ({"snapshot_sha256": "0" * 64}, "differs in snapshot_sha256"),
        ({"embed_run": "another-run"}, "not one of the --embeds runs"),
        ({"embed_model": SMALL}, "differs in embed_model"),
    ],
)
def test_a_pick_run_that_does_not_belong_is_refused(
    eight: tuple[Settings, str],
    capsys: pytest.CaptureFixture[str],
    changes: dict[str, object],
    message: str,
) -> None:
    settings, sha = eight
    runs = _three(settings, sha)
    pick = _pick_run(settings, sha, runs[1], RIGHT_PICKS, **changes)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs, "--picks", pick) == 1
    assert message in capsys.readouterr().out


@pytest.mark.parametrize(
    "picks", [{"A": ["L1", "L9"]}, {"A": ["L1", "L2", "L3", "L4", "L1", "L2"]}]
)
def test_pick_ids_must_be_lessons_and_at_most_five(
    eight: tuple[Settings, str], capsys: pytest.CaptureFixture[str], picks: dict[str, list[str]]
) -> None:
    settings, sha = eight
    runs = _three(settings, sha)
    pick = _pick_run(settings, sha, runs[1], picks)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", *runs, "--picks", pick) == 1
    assert "refused" in capsys.readouterr().out


def test_dev_seal_reading_takes_the_picks_when_the_picking_call_won(
    setup: tuple[Settings, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, sha = setup
    _apply_run(settings, sha, {"A": [], "B": []}, sample="dev-seal-400")
    near = {"A": [1.0, 0.1], "B": [0.1, 1.0]}
    run = _embed_run(settings, LARGE, sha, near, sample="dev-seal-400")
    pick = _pick_run(settings, sha, run, {"A": ["L1"], "B": ["L2"]}, sample="dev-seal-400")
    base = ["--sample", "dev-seal-400", "--applies", APPLY_RUN, "--embeds", run, "--model", LARGE]
    _steering_winner(tmp_path, monkeypatch, f"pick:{LARGE}")
    assert _main(settings, *base) == 1
    assert "the picking call" in capsys.readouterr().out
    assert _main(settings, *base, "--picks", pick) == 0
    text = capsys.readouterr().out
    assert "-memory-choices-dev-seal-400-pick-" in text
    _steering_winner(tmp_path, monkeypatch, LARGE)
    assert _main(settings, *base, "--picks", pick) == 1
    assert "the embedding lookup alone" in capsys.readouterr().out
