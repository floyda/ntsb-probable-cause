"""The picking call (decision 0213's fallback). Offline: a fake SDK, invented lessons, vectors."""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import anthropic
import pytest
from scripts import memory_cause_pick as cp
from scripts import memory_coding_test, memory_embed
from scripts import memory_learn as ml
from tests.test_memory_cause_apply import FakeMessages

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import BudgetError
from ntsb_probable_cause.memory import checks, claude, pool, prompts, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, Support
from ntsb_probable_cause.settings import Settings

LARGE = "openai/text-embedding-3-large"
WORDS = [
    *("alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india"),
    *("juliett", "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo"),
    *("sierra", "tango", "uniform", "victor", "whiskey", "xray", "yankee", "zulu"),
]
LESSON_IDS = [f"L{i:03d}" for i in range(1, 27)]  # L001..L026; L026 is below the floor
CAUSES: dict[str, str | None] = {
    "XXX09LA001": "The pilot's loss of directional control during the landing roll.",
    "XXX09LA002": "The pilot's failure to maintain airspeed, which resulted in a stall.",
    "XXX09LA003": None,
    "XXX09LA004": "The total loss of engine power for reasons that could not be determined.",
}


def _lesson(index: int) -> Lesson:
    lid = LESSON_IDS[index]
    return Lesson(
        lesson_id=lid,
        kind="convention",
        statement=f"lesson {WORDS[index]} says how the NTSB codes it",
        scope="a scope",
        predicts=Prediction(first_occurrence=("552230",)),
        written_in=2010,
        support=Support(applies=5 if lid == "L026" else 20, agrees=4),
    )


def _snapshot(directory: Path) -> str:
    directory.mkdir()
    every = [_lesson(i) for i in range(len(LESSON_IDS))]
    memory = Memory(
        name="t", periods=(2010,), lessons=tuple(every[:15]), pushed_out=tuple(every[15:])
    )
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


def _embed_run(settings: Settings, sha: str, sample: str = "dev-steer-400") -> str:
    """Lesson i lies at angle i: L001 is nearest the cases' query, L025 farthest; L026 nearest."""
    run_id = f"20261017T180227Z-abc1234-memory-embed-{sample}-{memory_embed.slug(LARGE)}"
    folder = settings.runs_dir / run_id
    folder.mkdir(parents=True)
    lessons = {lid: [1.0, i * 0.1] for i, lid in enumerate(LESSON_IDS)}
    lessons["L026"] = [1.0, 0.0]
    body = {
        "model": LARGE,
        "sample": sample,
        "snapshot": "t",
        "snapshot_sha256": sha,
        "lessons": lessons,
        # XXX09LA004 failed to embed; XXX09LA003 has no cause sentence.
        "cases": {"XXX09LA001": [1.0, 0.0], "XXX09LA002": [1.0, 0.0]},
        "failed_cases": ["XXX09LA004"],
        "no_cause_cases": ["XXX09LA003"],
        "commit": "abc1234",
    }
    (folder / memory_embed.VECTORS_FILE).write_text(json.dumps(body))
    return run_id


class Harness:
    def __init__(self, tmp_path: Path, respond: Callable[[str], str]) -> None:
        self.settings = Settings(data_dir=tmp_path / "data")
        self.messages = FakeMessages(respond)
        self.sha = _snapshot(tmp_path / "snapshots")
        self.embed_run = _embed_run(self.settings, self.sha)

    def factory(
        self, settings: Settings, run_id: str, commit: tuple[str, bool], forbidden: frozenset[str]
    ) -> claude.LearningClient:
        sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=self.messages))
        return claude.LearningClient(
            sdk, settings.runs_dir, run_id, commit=commit, forbidden=forbidden
        )

    def run(self, *argv: str, embeds: str | None = None) -> int:
        args = ["--embeds", embeds or self.embed_run, "--snapshot", "t", *argv]
        return cp.main(args, settings=self.settings, client_factory=self.factory)

    def folder(self) -> Path:
        (folder,) = self.settings.runs_dir.glob("*-memory-cause-pick-*")
        return folder

    def systems(self) -> list[str]:
        return [
            cast(list[dict[str, str]], p["system"])[0]["text"]
            for p in self.messages.requests.values()
        ]


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", False))
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): True)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(memory_coding_test, "causes", lambda processed, sample=None: dict(CAUSES))
    monkeypatch.setattr(pool, "excluded_ids", lambda: frozenset({"XXX09LA001", "OTHER01"}))
    monkeypatch.setattr(cp, "allowed_ids", lambda sample=None: frozenset(CAUSES))


def _answer(ids: list[str]) -> Callable[[str], str]:
    return lambda user: json.dumps({"applies": ids})


def test_each_case_sees_its_twenty_closest_lessons_in_id_order_without_codes(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path, _answer([]))
    assert h.run() == 0
    systems = h.systems()
    assert len(systems) == 2  # no cause sentence, or no vector: not sent
    for system in systems:
        assert system.startswith(prompts.SYSTEM_PICK)
        shown = [lid for lid in LESSON_IDS if f"[{lid}]" in system]
        assert shown == LESSON_IDS[:20]  # the 20 nearest eligible; L026 is below the floor
        positions = [system.index(f"[{lid}]") for lid in shown]
        assert positions == sorted(positions)
        assert "552230" not in system  # never a code (render_for_apply)
    users = [
        cast(list[dict[str, str]], p["messages"])[0]["content"]
        for p in h.messages.requests.values()
    ]
    assert any("landing roll" in u for u in users)
    assert all("XXX09" not in u for u in users)
    params = list(h.messages.requests.values())
    assert {p["model"] for p in params} == {claude.SONNET}


def test_unknown_ids_are_dropped_order_kept_and_a_sixth_cut(tmp_path: Path) -> None:
    reply = ["L999", "L005", "L003", "L005", "L022", "L001", "L002", "L004", "L006"]
    h = Harness(tmp_path, _answer(reply))
    assert h.run() == 0
    picks = json.loads((h.folder() / cp.PICKS_FILE).read_text())
    # L999 is no lesson, L022 is not on the shortlist, the second L005 is a repeat.
    assert picks == {
        "XXX09LA001": ["L005", "L003", "L001", "L002", "L004"],
        "XXX09LA002": ["L005", "L003", "L001", "L002", "L004"],
    }


def test_the_summary_counts_cases_and_failed_replies(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    h = Harness(tmp_path, lambda user: "not json" if "stall" in user else '{"applies": ["L002"]}')
    assert h.run() == 0
    picks = json.loads((h.folder() / cp.PICKS_FILE).read_text())
    assert picks == {"XXX09LA001": ["L002"], "XXX09LA002": []}
    summary = cp.PickSummary.model_validate_json((h.folder() / cp.SUMMARY_FILE).read_text())
    assert (summary.cases_sent, summary.failed, summary.shortlist) == (2, 1, 20)
    assert (summary.embed_run, summary.embed_model) == (h.embed_run, LARGE)
    assert (summary.sample, summary.snapshot, summary.snapshot_sha256) == (
        "dev-steer-400",
        "t",
        h.sha,
    )
    assert (summary.model, summary.effort) == ml.APPLIERS["sonnet-high"]
    out = capsys.readouterr().out
    assert "failed replies: 1" in out
    assert "XXX09" not in out
    assert "landing roll" not in out


def test_a_run_that_died_before_its_summary_resumes_without_sending_again(tmp_path: Path) -> None:
    h = Harness(tmp_path, _answer(["L001"]))
    assert h.run() == 0
    run_id = h.folder().name
    (h.folder() / cp.SUMMARY_FILE).unlink()
    sent = len(h.messages.batch_keys)
    assert h.run("--resume", run_id) == 0
    assert len(h.messages.batch_keys) == sent


def test_a_finished_run_is_never_resumed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    h = Harness(tmp_path, _answer(["L001"]))
    assert h.run() == 0
    assert h.run("--resume", h.folder().name) == 1
    assert "is finished" in capsys.readouterr().out


def test_dev_seal_400_is_refused_before_registration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    h = Harness(tmp_path, _answer([]))
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): False)
    seal = _embed_run(h.settings, h.sha, sample="dev-seal-400")
    assert h.run("--sample", "dev-seal-400", embeds=seal) == 1
    assert "is not committed" in capsys.readouterr().out
    assert not h.messages.batch_keys


def test_dev_seal_400_needs_the_picking_call_to_have_won_on_steering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    h = Harness(tmp_path, _answer(["L001"]))
    reading = tmp_path / "memory-coverage-dev.txt"
    monkeypatch.setattr(memory_embed, "STEERING_COVERAGE", reading)
    seal = _embed_run(h.settings, h.sha, sample="dev-seal-400")
    reading.write_text(f"...\nwinner: {LARGE}\n")
    assert h.run("--sample", "dev-seal-400", embeds=seal) == 1
    assert "picking call" in capsys.readouterr().out
    reading.write_text(f"...\nwinner: pick:{LARGE}\n")
    assert h.run("--sample", "dev-seal-400", embeds=seal) == 0
    assert "-memory-cause-pick-dev-seal-400-" in h.folder().name


def test_the_budget_is_checked_before_anything_is_sent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    def over(settings: Settings, calls: object, *, batch: bool, label: str) -> None:
        raise BudgetError("past the learner line")

    monkeypatch.setattr(ml, "check_budget", over)
    h = Harness(tmp_path, _answer([]))
    assert h.run() == 1
    assert "past the learner line" in capsys.readouterr().out
    assert not h.messages.batch_keys


def test_an_embedding_run_of_another_sample_is_refused(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    h = Harness(tmp_path, _answer([]))
    seal = _embed_run(h.settings, h.sha, sample="dev-seal-400")
    assert h.run(embeds=seal) == 1
    assert "differs in sample" in capsys.readouterr().out


def test_a_dirty_tree_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", True))
    h = Harness(tmp_path, _answer([]))
    assert h.run() == 1
    assert "refused" in capsys.readouterr().out
    assert not h.messages.batch_keys
