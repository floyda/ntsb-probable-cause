"""The apply step on the steering slice (decision 0211). Offline; a fake SDK; invented lessons."""

import json
from collections.abc import Callable
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import anthropic
import pytest
from scripts import memory_cause_apply as ca
from scripts import memory_coding_test
from scripts import memory_learn as ml

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import checks, claude, pool, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, Support
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings

CAUSES: dict[str, str | None] = {
    "XXX09LA001": "The pilot's loss of directional control during the landing roll.",
    "XXX09LA002": "The pilot's failure to maintain airspeed, which resulted in a stall.",
    "XXX09LA003": None,
}
WORDS = {"L001": "one", "L002": "two", "L003": "three", "L010": "ten"}


def _message(text: str) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=20,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    return SimpleNamespace(
        content=[SimpleNamespace(type="text", text=text)], stop_reason="end_turn", usage=usage
    )


class FakeMessages:
    """A batch-only fake: every request answered by ``respond`` from its user text."""

    def __init__(self, respond: Callable[[str], str]) -> None:
        self.respond = respond
        self.requests: dict[str, dict[str, object]] = {}
        self.batch_keys: list[list[str]] = []
        self.batches = SimpleNamespace(
            create=self._create, retrieve=self._retrieve, results=self._results
        )

    def _create(self, *, requests: list[dict[str, object]]) -> SimpleNamespace:
        self.batch_keys.append([str(r["custom_id"]) for r in requests])
        for r in requests:
            self.requests[str(r["custom_id"])] = cast(dict[str, object], r["params"])
        return SimpleNamespace(id=f"b{len(self.batch_keys) - 1}")

    def _retrieve(self, batch_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=batch_id, processing_status="ended")

    def _results(self, batch_id: str) -> list[SimpleNamespace]:
        out = []
        for key in self.batch_keys[int(batch_id.removeprefix("b"))]:
            messages = cast(list[dict[str, str]], self.requests[key]["messages"])
            text = self.respond(messages[0]["content"])
            out.append(
                SimpleNamespace(
                    custom_id=key,
                    result=SimpleNamespace(type="succeeded", message=_message(text)),
                )
            )
        return out


def _lesson(lid: str, applies: int, agrees: int) -> Lesson:
    return Lesson(
        lesson_id=lid,
        kind="convention",
        statement=f"lesson {WORDS[lid]} says how the NTSB codes it",
        scope="a scope",
        predicts=Prediction(first_occurrence=("552230",)),
        written_in=2010,
        support=Support(applies=applies, agrees=agrees),
    )


def _snapshot(directory: Path) -> None:
    directory.mkdir()
    memory = Memory(
        name="t",
        periods=(2010,),
        lessons=(_lesson("L010", 30, 10), _lesson("L002", 30, 20)),
        pushed_out=(_lesson("L001", 20, 15), _lesson("L003", 5, 5)),
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


class Harness:
    def __init__(self, tmp_path: Path, respond: Callable[[str], str]) -> None:
        self.settings = Settings(data_dir=tmp_path / "data")
        self.messages = FakeMessages(respond)
        self.forbidden: frozenset[str] | None = None
        self.out = tmp_path / "out.txt"

    def factory(
        self, settings: Settings, run_id: str, commit: tuple[str, bool], forbidden: frozenset[str]
    ) -> claude.LearningClient:
        self.forbidden = forbidden
        sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=self.messages))
        return claude.LearningClient(
            sdk, settings.runs_dir, run_id, commit=commit, forbidden=forbidden
        )

    def run(self, *argv: str) -> int:
        args = ["--snapshot", "t", "--out", str(self.out), *argv]
        return ca.main(args, settings=self.settings, client_factory=self.factory)

    def folder(self) -> Path:
        (folder,) = [p for p in self.settings.runs_dir.iterdir() if p.is_dir()]
        return folder


@pytest.fixture(autouse=True)
def _setup(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", False))
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: path == ca.REGISTRATION)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(memory_coding_test, "causes", lambda processed, sample=None: dict(CAUSES))
    monkeypatch.setattr(pool, "excluded_ids", lambda: frozenset({"XXX09LA001", "OTHER01"}))
    monkeypatch.setattr(ca, "allowed_ids", lambda sample=None: frozenset(CAUSES))
    _snapshot(tmp_path / "snapshots")


def _by_cause(user: str) -> str:
    ids = ["L001", "L002", "L003", "L999"] if "stall" in user else []
    return json.dumps({"applies": ids})


def test_each_cause_sentence_is_sent_alone_against_every_lesson_in_id_order(
    tmp_path: Path,
) -> None:
    h = Harness(tmp_path, _by_cause)
    assert h.run() == 0
    params = list(h.messages.requests.values())
    assert len(params) == 2  # the case without a cause sentence is not sent
    system = cast(list[dict[str, str]], params[0]["system"])[0]["text"]
    assert system.index("[L001]") < system.index("[L002]") < system.index("[L003]")
    assert system.index("[L003]") < system.index("[L010]")
    assert "552230" not in system  # never a code (render_for_apply)
    users = {cast(list[dict[str, str]], p["messages"])[0]["content"] for p in params}
    assert {u for u in users if "landing roll" in u}
    assert all("XXX09" not in u for u in users)
    assert {p["model"] for p in params} == {claude.SONNET}


def test_the_answers_are_saved_unknown_ids_dropped_and_the_counts_written(tmp_path: Path) -> None:
    h = Harness(tmp_path, _by_cause)
    assert h.run() == 0
    applies = json.loads((h.folder() / ca.APPLIES_FILE).read_text())
    assert applies == {"XXX09LA001": [], "XXX09LA002": ["L001", "L002", "L003"]}
    summary = ca.ApplySummary.model_validate_json((h.folder() / ca.SUMMARY_FILE).read_text())
    assert (summary.cases_sent, summary.no_cause, summary.failed) == (2, 1, 0)
    assert summary.lessons_shown == 4
    assert summary.snapshot_sha256 == snapshots.sha256_of(
        snapshots.snapshot_path("t", snapshots.SNAPSHOT_DIR)
    )
    text = h.out.read_text()
    assert "failed replies: 0" in text
    # L003 is below the floor; L001 (fit 0.75) and L002 (0.67) are the lookup's two
    assert "with 1 to 4 1; with none 1" in text
    assert "distinct lessons the lookup uses: 2" in text
    assert "XXX09" not in text


def test_a_run_that_died_before_its_summary_resumes_without_sending_again(tmp_path: Path) -> None:
    h = Harness(tmp_path, _by_cause)
    assert h.run() == 0
    run_id = h.folder().name
    (h.folder() / ca.SUMMARY_FILE).unlink()
    sent = len(h.messages.batch_keys)
    assert h.run("--resume", run_id) == 0
    assert len(h.messages.batch_keys) == sent


def test_a_finished_run_is_never_resumed_so_failed_replies_stand(tmp_path: Path) -> None:
    h = Harness(tmp_path, lambda user: "not json")
    assert h.run() == 0
    run_id = h.folder().name
    h.messages.respond = _by_cause
    sent = len(h.messages.batch_keys)
    assert h.run("--resume", run_id) == 1
    assert len(h.messages.batch_keys) == sent
    summary = ca.ApplySummary.model_validate_json((h.folder() / ca.SUMMARY_FILE).read_text())
    assert summary.failed == 2


def test_a_failed_reply_counts_as_no_lesson(tmp_path: Path) -> None:
    h = Harness(tmp_path, lambda user: "not json")
    assert h.run() == 0
    summary = ca.ApplySummary.model_validate_json((h.folder() / ca.SUMMARY_FILE).read_text())
    assert summary.failed == 2


def test_refused_without_the_registration_or_on_a_dirty_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    h = Harness(tmp_path, _by_cause)
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: False)
    assert h.run() == 1
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: True)
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", True))
    assert h.run() == 1
    assert h.messages.requests == {}


def test_refused_past_the_learning_line_before_any_call(tmp_path: Path) -> None:
    h = Harness(tmp_path, _by_cause)
    h.settings = Settings(data_dir=tmp_path / "data", learning_monthly_budget_usd=0.0)
    assert h.run() == 1
    assert h.messages.requests == {}


def test_the_client_is_given_every_excluded_case_as_forbidden(tmp_path: Path) -> None:
    h = Harness(tmp_path, _by_cause)
    assert h.run() == 0
    assert h.forbidden == frozenset({"XXX09LA001", "OTHER01"})


def test_the_steering_slice_is_the_sample_the_mem_statistics_leave_out(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.undo()
    steer = ca.allowed_ids()
    assert steer == frozenset(samples.sample_ids("dev-steer-400"))
    assert steer <= pool.excluded_ids()
    confirm = ca.allowed_ids("dev-400")
    assert confirm == frozenset(samples.sample_ids("dev-400"))
    assert confirm <= pool.excluded_ids()


def test_only_test_apply_calls_may_read_the_allowed_cases(tmp_path: Path) -> None:
    h = Harness(tmp_path, _by_cause)
    client = h.factory(h.settings, "r", ("abc1234", False), frozenset({"S1", "OTHER01"}))
    client.allow_for_test_apply(frozenset({"S1"}))
    memory = ca.apply_memory(snapshots.load_checked("t", snapshots.SNAPSHOT_DIR))
    model, effort = ml.APPLIERS[ca.APPLIER]
    ok = ml.apply_call(ca.ROLE, model, effort, memory, case_id="S1", cause="a cause")
    client.send_batch([ok])  # allowed: no refusal
    for role, case_id in (("apply", "S1"), ("propose", "S1"), (ca.ROLE, "OTHER01")):
        call = ml.apply_call(role, model, effort, memory, case_id=case_id, cause="a cause")
        with pytest.raises(ConfigurationError):
            client.send_batch([call])


def test_dev_400_is_refused_until_the_confirmation_is_registered(tmp_path: Path) -> None:
    h = Harness(tmp_path, _by_cause)
    assert h.run("--sample", "dev-400") == 1
    assert h.messages.batch_keys == []


def test_dev_400_runs_once_registered_and_names_its_sample(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    registered = {ca.REGISTRATION, memory_coding_test.CONFIRM_REGISTRATION}
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: path in registered)
    seen: list[str | None] = []
    allowed: list[str | None] = []

    def causes(processed: Path, sample: str | None = None) -> dict[str, str | None]:
        del processed
        seen.append(sample)
        return dict(CAUSES)

    def allowed_ids(sample: str | None = None) -> frozenset[str]:
        allowed.append(sample)
        return frozenset(CAUSES)

    monkeypatch.setattr(memory_coding_test, "causes", causes)
    monkeypatch.setattr(ca, "allowed_ids", allowed_ids)
    h = Harness(tmp_path, _by_cause)
    assert h.run("--sample", "dev-400") == 0
    assert seen == ["dev-400"]
    assert allowed == ["dev-400"]
    assert "-memory-cause-apply-dev-400-t" in h.folder().name
    summary = json.loads((h.folder() / ca.SUMMARY_FILE).read_text())
    assert summary["sample"] == "dev-400"


def test_the_steering_slice_keeps_decision_0211s_run_id(tmp_path: Path) -> None:
    h = Harness(tmp_path, _by_cause)
    assert h.run() == 0
    assert h.folder().name.endswith("-memory-cause-apply-t")
