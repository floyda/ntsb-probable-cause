"""The choices of decision 0214's four candidates. Offline; ``test_memory_coverage``'s lessons."""

import json
import re
from pathlib import Path

import pytest
from scripts import memory_embed
from scripts import memory_embed_choices as ec
from tests.test_memory_coverage import (
    APPLY_RUN,
    LARGE,
    NOW,
    PICK_RUN,
    SMALL,
    _apply_run,
    _embed_run,
    _pick_run,
    setup,  # noqa: F401 -- the fixture, as `ready` below
)

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.settings import Settings


@pytest.fixture
def ready(
    setup: tuple[Settings, str],  # noqa: F811 -- the imported fixture
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[Settings, str]:
    """``test_memory_coverage``'s settings and snapshot; its runs stand for the registered ones."""
    large = f"20261017T120000Z-abc1234-memory-embed-dev-steer-400-{memory_embed.slug(LARGE)}"
    monkeypatch.setattr(
        ec, "STEERING_RUNS", {"applies": APPLY_RUN, "embeds": large, "picks": PICK_RUN}
    )
    return setup


NEAR = {"A": [1.0, 0.1], "B": [0.1, 1.0]}  # closest: A -> L1, B -> L2


def _main(settings: Settings, *argv: str) -> int:
    out = ["--out", str(settings.data_dir.parent / "choices.txt")]
    return ec.main(["--snapshot", "t", *argv, *out], settings=settings, now=lambda: NOW)


def _summaries(settings: Settings) -> dict[str, dict[str, object]]:
    found = {}
    for path in settings.runs_dir.glob(f"*-memory-choices-*/{ec.CHOICE_SUMMARY_FILE}"):
        summary = json.loads(path.read_text())
        found[str(summary["method"])] = summary | {"run": path.parent.name}
    return found


def _choices(settings: Settings, run: str) -> dict[str, list[str]]:
    return dict(json.loads((settings.runs_dir / run / ec.CHOICES_FILE).read_text()))


def _steering(settings: Settings, sha: str) -> tuple[str, str]:
    _apply_run(settings, sha, {"A": ["L2"], "B": []})  # today: A gets L2, B none
    run = _embed_run(settings, LARGE, sha, NEAR)
    pick = _pick_run(settings, sha, run, {"A": ["L1"], "B": []})
    return run, pick


def test_the_steering_slice_writes_every_candidates_choices(
    ready: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = ready
    run, pick = _steering(settings, sha)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", run, "--picks", pick) == 0
    text = capsys.readouterr().out
    found = _summaries(settings)
    assert set(found) == {"embedding", "pick", "fit", "fill"}
    assert {s["model"] for s in found.values()} == {LARGE}
    assert all(s["dirty"] is False for s in found.values())
    assert _choices(settings, str(found["embedding"]["run"]))["A"][0] == "L1"
    assert _choices(settings, str(found["pick"]["run"])) == {"A": ["L1"], "B": []}
    # fill keeps today's L2 for A and gives B, which today leaves empty, its nearest: L2.
    assert _choices(settings, str(found["fill"]["run"])) == {"A": ["L2"], "B": ["L2"]}
    assert found["fill"]["applies_run"] == APPLY_RUN
    for method in ("embedding", "fit", "fill"):
        assert found[method]["source_run"] == run
    assert found["pick"]["source_run"] == pick
    assert text.count("choices run: ") == 4
    assert "finding part: case hit" in text
    assert text.splitlines()[-1] == ec.LAST_LINE


def test_the_names_of_the_choices_runs_tell_the_candidates_apart(
    ready: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = ready
    run, pick = _steering(settings, sha)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", run, "--picks", pick) == 0
    runs = re.findall(r"choices run: (\S+)", capsys.readouterr().out)
    tails = {name.split("-memory-choices-dev-steer-400-")[1] for name in runs}
    assert tails == {
        memory_embed.slug(memory_embed.candidate_name(m, LARGE))
        for m in ("embedding", "pick", "fit", "fill")
    }


def test_choices_are_refused_until_the_registration_is_committed(
    ready: tuple[Settings, str], monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = ready
    run, pick = _steering(settings, sha)
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): path != ec.REGISTRATION)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", run, "--picks", pick) == 1
    assert "memory-embed-coding.md is not committed" in capsys.readouterr().out
    assert not _summaries(settings)


def test_a_dirty_tree_is_refused_before_choices_are_written(
    ready: tuple[Settings, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    settings, sha = ready
    run, pick = _steering(settings, sha)
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", True))
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", run, "--picks", pick) == 1
    assert not _summaries(settings)


def test_the_steering_slice_needs_the_large_models_run_and_its_picks(
    ready: tuple[Settings, str], capsys: pytest.CaptureFixture[str]
) -> None:
    settings, sha = ready
    _apply_run(settings, sha, {"A": [], "B": []})
    small = _embed_run(settings, SMALL, sha, NEAR)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", small, "--picks", "a-pick-run") == 1
    assert "--embeds, --picks must name the registered run" in capsys.readouterr().out
    large = _embed_run(settings, LARGE, sha, NEAR)
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", large) == 1
    assert "--picks" in capsys.readouterr().out
    assert _main(settings, "--applies", APPLY_RUN, "--embeds", large, "--candidate", LARGE) == 1
    assert "--candidate" in capsys.readouterr().out
    assert not _summaries(settings)


# --- dev-seal-400: the steering winner only ---------------------------------------------------


def _winner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    path = tmp_path / "memory-embed-coding-dev.txt"
    path.write_text(f"embedding lookups ...\nwinner: {name}\n")
    monkeypatch.setattr(memory_embed, "STEERING_READING", path)


def _seal(settings: Settings, sha: str) -> list[str]:
    _apply_run(settings, sha, {"A": [], "B": []}, sample="dev-seal-400")
    run = _embed_run(settings, LARGE, sha, NEAR, sample="dev-seal-400")
    return ["--sample", "dev-seal-400", "--applies", APPLY_RUN, "--embeds", run]


def test_dev_seal_400_writes_only_the_winners_choices(
    ready: tuple[Settings, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, sha = ready
    _winner(tmp_path, monkeypatch, f"fill:{LARGE}")
    base = _seal(settings, sha)
    assert _main(settings, *base) == 1
    assert "--candidate" in capsys.readouterr().out
    assert _main(settings, *base, "--candidate", f"fit:{LARGE}") == 1
    assert "the steering winner is" in capsys.readouterr().out
    assert not _summaries(settings)
    assert _main(settings, *base, "--candidate", f"fill:{LARGE}") == 0
    found = _summaries(settings)
    assert set(found) == {"fill"}
    assert found["fill"]["sample"] == "dev-seal-400"
    assert capsys.readouterr().out.count("choices run: ") == 1


def test_dev_seal_400_takes_picks_only_when_the_picking_call_won(
    ready: tuple[Settings, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    settings, sha = ready
    base = _seal(settings, sha)
    pick = _pick_run(settings, sha, base[-1], {"A": ["L1"], "B": []}, sample="dev-seal-400")
    _winner(tmp_path, monkeypatch, f"pick:{LARGE}")
    assert _main(settings, *base, "--candidate", f"pick:{LARGE}") == 1
    assert "--picks" in capsys.readouterr().out
    _winner(tmp_path, monkeypatch, LARGE)
    assert _main(settings, *base, "--candidate", LARGE, "--picks", pick) == 1
    assert "--picks" in capsys.readouterr().out
    _winner(tmp_path, monkeypatch, f"pick:{LARGE}")
    assert _main(settings, *base, "--candidate", f"pick:{LARGE}", "--picks", pick) == 0
    assert set(_summaries(settings)) == {"pick"}


def test_the_outputs_are_the_registered_files() -> None:
    assert {
        "dev-steer-400": Path("docs/results/memory-embed-choices-dev.txt"),
        "dev-seal-400": Path("docs/results/memory-embed-choices-devseal.txt"),
    } == ec.OUTS


def test_the_registered_steering_runs_are_0213s() -> None:
    assert ec.STEERING_RUNS == {
        "applies": "20261017T090550Z-0b949a6-memory-cause-apply-pilot-2010-recount",
        "embeds": "20261017T180227Z-2e3e730-memory-embed-dev-steer-400-"
        "openai-text-embedding-3-large",
        "picks": "20261017T181956Z-8627513-memory-cause-pick-dev-steer-400-"
        "openai-text-embedding-3-large",
    }


@pytest.mark.parametrize("flag", ["--applies", "--embeds", "--picks"])
def test_the_steering_slice_refuses_any_run_but_the_registered_ones(
    ready: tuple[Settings, str], capsys: pytest.CaptureFixture[str], flag: str
) -> None:
    settings, sha = ready
    run, pick = _steering(settings, sha)
    argv = {"--applies": APPLY_RUN, "--embeds": run, "--picks": pick}
    argv[flag] = "20261018T000000Z-abc1234-another-run"
    assert _main(settings, *(x for pair in argv.items() for x in pair)) == 1
    assert "registered" in capsys.readouterr().out
    assert not _summaries(settings)
