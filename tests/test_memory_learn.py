"""The learner script (decisions 0201-0204). Offline; made-up replies and a fake SDK."""

import json
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import anthropic
import pytest
from scripts import memory_learn as ml
from tests.conftest import coded_record, write_cases

from ntsb_probable_cause import fields, gitinfo
from ntsb_probable_cause.memory import claude, pool, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction
from ntsb_probable_cause.memory.prompts import LessonDraft, LessonEdit, ProposeReply, ReviseReply
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.settings import Settings

TABLES = load_tables()


def _draft(**changes: object) -> LessonDraft:
    base: dict[str, object] = {
        "kind": "convention",
        "statement": "the NTSB codes it so",
        "scope": "a scope",
        "first_occurrence": ["552230"],
        "finding_categories": [],
    }
    base.update(changes)
    return LessonDraft.model_validate(base)


def _lesson(**changes: object) -> Lesson:
    base: dict[str, object] = {
        "lesson_id": "L001",
        "kind": "convention",
        "statement": "old",
        "scope": "s",
        "predicts": Prediction(first_occurrence=("552230",)),
        "written_in": 2009,
    }
    base.update(changes)
    return Lesson.model_validate(base)


def test_ids_continue_after_the_highest() -> None:
    assert ml.next_lesson_id([]) == "L001"
    assert ml.next_lesson_id(["L001", "L007"]) == "L008"


def test_new_lessons_get_ids_and_bad_codes_are_dropped() -> None:
    ids = iter(["L001", "L002"])
    reply = ProposeReply(new=[_draft(), _draft(first_occurrence=["999999"])], edits=[], retire=[])
    memory, dropped = ml.merge_proposal(
        Memory(name="d", periods=(2009,)), reply, 2009, TABLES, lambda: next(ids)
    )
    assert [lesson.lesson_id for lesson in memory.lessons] == ["L001"]
    assert len(dropped) == 1


def test_a_bad_category_a_bad_split_and_an_identifier_are_dropped() -> None:
    ids = iter(f"L{i:03d}" for i in range(1, 9))
    reply = ProposeReply(
        new=[
            _draft(first_occurrence=[], finding_categories=["000000"], kind="evidence"),
            _draft(kind="split"),
            _draft(statement="in 2009 the pilot of a Cessna lost control"),
            _draft(scope="a scope with 5 digits"),
        ],
        edits=[],
        retire=[],
    )
    memory, dropped = ml.merge_proposal(
        Memory(name="d", periods=(2009,)), reply, 2009, TABLES, lambda: next(ids)
    )
    assert memory.lessons == ()
    assert len(dropped) == 4


def test_more_than_five_new_lessons_are_cut_to_five() -> None:
    counter = iter(f"L{i:03d}" for i in range(1, 20))
    reply = ProposeReply(new=[_draft()] * 7, edits=[], retire=[])
    memory, dropped = ml.merge_proposal(
        Memory(name="d", periods=(2009,)), reply, 2009, TABLES, lambda: next(counter)
    )
    assert len(memory.lessons) == 5
    assert len(dropped) == 2


def test_an_edit_replaces_a_lesson_and_keeps_its_history() -> None:
    edit = LessonEdit(lesson_id="L001", **_draft(statement="new").model_dump())
    reply = ProposeReply(new=[], edits=[edit], retire=["L404"])
    memory, dropped = ml.merge_proposal(
        Memory(name="d", periods=(2009,), lessons=(_lesson(),)), reply, 2010, TABLES, lambda: "L002"
    )
    assert memory.lessons[0].statement == "new"
    assert memory.lessons[0].history == ("edited in 2010",)
    assert any("L404" in d for d in dropped)


def test_a_retirement_removes_a_lesson() -> None:
    reply = ProposeReply(new=[], edits=[], retire=["L001"])
    memory, dropped = ml.merge_proposal(
        Memory(name="d", periods=(2009,), lessons=(_lesson(),)), reply, 2010, TABLES, lambda: "L002"
    )
    assert memory.lessons == ()
    assert dropped == []


def test_a_revision_can_retire() -> None:
    reply = ReviseReply(action="retire", **_draft().model_dump())
    memory, _ = ml.merge_revision(
        Memory(name="d", periods=(2009,), lessons=(_lesson(),)), "L001", reply, 2009, TABLES
    )
    assert memory.lessons == ()


def test_a_revision_edits_and_a_bad_one_keeps_the_old_lesson() -> None:
    start = Memory(name="d", periods=(2009,), lessons=(_lesson(),))
    good = ReviseReply(action="edit", **_draft(statement="new").model_dump())
    memory, dropped = ml.merge_revision(start, "L001", good, 2009, TABLES)
    assert memory.lessons[0].statement == "new"
    assert memory.lessons[0].history == ("revised in 2009",)
    assert dropped == []
    bad = ReviseReply(action="edit", **_draft(first_occurrence=["999999"]).model_dump())
    memory, dropped = ml.merge_revision(start, "L001", bad, 2009, TABLES)
    assert memory.lessons == start.lessons
    assert len(dropped) == 1


def test_the_applier_is_read_from_the_agreement_result() -> None:
    assert (
        ml.parse_applier("pairs either marked: 40\nchosen applier: haiku-medium\n")
        == "haiku-medium"
    )
    with pytest.raises(ValueError, match="applier"):
        ml.parse_applier("no choice here")


def test_cases_go_in_thirties_in_id_order() -> None:
    assert [len(c) for c in ml.chunks(list(range(65)))] == [30, 30, 5]


# The subcommands, over a fake SDK. -------------------------------------------------------


def _message(text: str) -> SimpleNamespace:
    usage = SimpleNamespace(
        input_tokens=1000,
        output_tokens=200,
        cache_creation_input_tokens=0,
        cache_read_input_tokens=0,
    )
    content = [SimpleNamespace(type="text", text=text)]
    return SimpleNamespace(content=content, stop_reason="end_turn", usage=usage)


Responder = Callable[[dict[str, object]], str]


class FakeMessages:
    """Answers every request from a function of its parameters, sync or in a batch."""

    def __init__(self, responder: Responder) -> None:
        self.responder = responder
        self.created: list[dict[str, object]] = []
        self.requests: dict[str, dict[str, object]] = {}
        self.batch_keys: dict[str, list[str]] = {}
        self.batches = SimpleNamespace(
            create=self._create_batch, retrieve=self._retrieve, results=self._results
        )

    def create(self, **params: object) -> SimpleNamespace:
        self.created.append(params)
        return _message(self.responder(params))

    def _create_batch(self, *, requests: list[dict[str, object]]) -> SimpleNamespace:
        batch_id = f"batch-{len(self.batch_keys)}"
        self.batch_keys[batch_id] = [str(r["custom_id"]) for r in requests]
        for request in requests:
            self.requests[str(request["custom_id"])] = cast(dict[str, object], request["params"])
        return SimpleNamespace(id=batch_id)

    def _retrieve(self, batch_id: str) -> SimpleNamespace:
        return SimpleNamespace(id=batch_id, processing_status="ended")

    def _results(self, batch_id: str) -> list[SimpleNamespace]:
        return [
            SimpleNamespace(
                custom_id=key,
                result=SimpleNamespace(type="succeeded", message=_message(self.responder(params))),
            )
            for key, params in ((k, self.requests[k]) for k in self.batch_keys[batch_id])
        ]


class Harness:
    def __init__(self, tmp_path: Path, responder: Responder, years: tuple[str, ...]) -> None:
        raw = coded_record()
        write_cases(
            tmp_path / "data" / "processed",
            [(f"A{i:03d}", f"{y}-05-01", "dev", "C", raw) for i, y in enumerate(years)],
        )
        self.raw = raw
        self.settings = Settings(data_dir=tmp_path / "data")
        self.messages = FakeMessages(responder)
        self.snapshots = tmp_path / "snapshots"
        self.snapshots.mkdir()

    def factory(
        self, settings: Settings, run_id: str, commit: tuple[str, bool], forbidden: frozenset[str]
    ) -> claude.LearningClient:
        sdk = cast(anthropic.Anthropic, SimpleNamespace(messages=self.messages))
        return claude.LearningClient(
            sdk, settings.runs_dir, run_id, commit=commit, forbidden=forbidden
        )

    def run(self, *argv: str) -> int:
        return ml.main(list(argv), settings=self.settings, client_factory=self.factory)

    def run_folder(self, run_id: str) -> Path:
        folder = self.settings.runs_dir / run_id
        folder.mkdir(parents=True, exist_ok=True)
        return folder


@pytest.fixture(autouse=True)
def _clean_tree(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", False))
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    monkeypatch.setattr(ml, "AGREEMENT_FILE", tmp_path / "agreement.txt")


def _user(params: dict[str, object]) -> str:
    messages = cast(list[dict[str, str]], params["messages"])
    return messages[0]["content"]


def test_propose_sends_one_call_per_thirty_cases_and_writes_a_draft(tmp_path: Path) -> None:
    def respond(params: dict[str, object]) -> str:
        new = [_draft().model_dump()] if "K30" in _user(params) else []
        return json.dumps({"new": new, "edits": [], "retire": []})

    h = Harness(tmp_path, respond, ("2009",) * 31)
    assert h.run("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a") == 0
    assert len(h.messages.created) == 2
    run_id = next(p.name for p in h.settings.runs_dir.iterdir() if p.is_dir())
    assert run_id.endswith("-abc1234-memory-2009")
    draft = Memory.model_validate_json((h.settings.runs_dir / run_id / "draft.json").read_text())
    assert draft.periods == (2009,)
    assert [lesson.lesson_id for lesson in draft.lessons] == ["L001"]
    assert draft.name == "pilot-a"


def test_a_dirty_tree_is_refused(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", True))
    h = Harness(tmp_path, lambda p: "{}", ("2009",))
    assert h.run("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a") == 1
    assert h.messages.created == []


def _applies(ids_by_model: dict[str, list[str]]) -> Responder:
    def respond(params: dict[str, object]) -> str:
        return json.dumps({"applies": ids_by_model[str(params["model"])]})

    return respond


def _write_draft(h: Harness, run_id: str, lesson: Lesson, periods: tuple[int, ...]) -> None:
    memory = Memory(name="pilot-a", periods=periods, lessons=(lesson,))
    (h.run_folder(run_id) / "draft.json").write_text(memory.model_dump_json())


def test_agreement_chooses_haiku_low_when_the_models_answer_alike(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        _applies({claude.HAIKU: ["L001"], claude.SONNET: ["L001"]}),
        ("2009",) * 5,
    )
    _write_draft(h, "run-x", _lesson(), (2009,))
    assert h.run("agreement", "--resume", "run-x", "--out", str(ml.AGREEMENT_FILE)) == 0
    text = ml.AGREEMENT_FILE.read_text()
    assert text.splitlines()[-1] == "chosen applier: haiku-low"
    assert "A00" not in text
    assert ml.parse_applier(text) == "haiku-low"


def test_agreement_falls_back_to_sonnet_when_haiku_never_agrees(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        _applies({claude.HAIKU: [], claude.SONNET: ["L001"]}),
        ("2009",) * 5,
    )
    _write_draft(h, "run-x", _lesson(), (2009,))
    assert h.run("agreement", "--resume", "run-x", "--out", str(ml.AGREEMENT_FILE)) == 0
    text = ml.AGREEMENT_FILE.read_text()
    assert "haiku-medium" in text
    assert text.splitlines()[-1] == "chosen applier: sonnet-high"


def test_agreement_stops_when_no_lesson_covers_any_case(tmp_path: Path) -> None:
    h = Harness(tmp_path, _applies({claude.HAIKU: [], claude.SONNET: []}), ("2009",) * 3)
    _write_draft(h, "run-x", _lesson(), (2009,))
    assert h.run("agreement", "--resume", "run-x", "--out", str(ml.AGREEMENT_FILE)) == 1
    assert "chosen applier" not in ml.AGREEMENT_FILE.read_text()


def test_agreement_refuses_a_draft_of_other_periods(tmp_path: Path) -> None:
    h = Harness(tmp_path, _applies({claude.HAIKU: [], claude.SONNET: []}), ("2009",))
    _write_draft(h, "run-x", _lesson(), (2009, 2010))
    assert h.run("agreement", "--resume", "run-x", "--out", str(ml.AGREEMENT_FILE)) == 1
    assert h.messages.requests == {}


def test_finish_refuses_while_the_agreement_file_is_uncommitted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gitinfo, "is_committed", lambda *a, **k: False)
    h = Harness(tmp_path, _applies({claude.HAIKU: ["L001"]}), ("2009",) * 4)
    ml.AGREEMENT_FILE.write_text("chosen applier: haiku-low\n")
    first = pool.learning_part(h.settings.data_dir / "processed", years={2009}, excluded=set())[0]
    lesson = _lesson(predicts=Prediction(first_occurrence=(first.occurrence[0],)))
    _write_draft(h, "run-x", lesson, (2009,))
    assert h.run("finish", "--resume", "run-x", "--to", "pilot-a") == 1
    assert snapshots.names(snapshots.SNAPSHOT_DIR) == []


def test_finish_counts_support_and_saves_an_unchecked_snapshot(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gitinfo, "is_committed", lambda *a, **k: True)
    h = Harness(tmp_path, _applies({claude.HAIKU: ["L001"]}), ("2009",) * 4)
    ml.AGREEMENT_FILE.write_text("chosen applier: haiku-low\n")
    cases = pool.learning_part(h.settings.data_dir / "processed", years={2009}, excluded=set())
    lesson = _lesson(predicts=Prediction(first_occurrence=(cases[0].occurrence[0],)))
    _write_draft(h, "run-x", lesson, (2009,))
    assert h.run("finish", "--resume", "run-x", "--to", "pilot-a") == 0
    saved = snapshots.load("pilot-a", snapshots.SNAPSHOT_DIR)
    assert [lesson.lesson_id for lesson in saved.lessons] == ["L001"]
    support = saved.lessons[0].support
    assert support is not None
    assert (support.applies, support.agrees) == (4, 4)
    assert not snapshots.stamp_path("pilot-a", snapshots.SNAPSHOT_DIR).exists()
    counts = json.loads((h.settings.runs_dir / "run-x" / "finish.json").read_text())
    assert counts["kept"] == 1
    assert counts["revised"] == 0


def test_finish_revises_a_lesson_that_disagrees_and_applies_again(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gitinfo, "is_committed", lambda *a, **k: True)
    wrong = fields.occurrence_codes(coded_record())[0]
    other = "552230" if wrong != "552230" else "551230"

    def respond(params: dict[str, object]) -> str:
        if params["model"] == claude.HAIKU:
            return json.dumps({"applies": ["L001"]})
        edit = _draft(statement="revised", first_occurrence=[wrong]).model_dump()
        return json.dumps({"action": "edit", **edit})

    h = Harness(tmp_path, respond, ("2009",) * 4)
    ml.AGREEMENT_FILE.write_text("chosen applier: haiku-low\n")
    _write_draft(h, "run-x", _lesson(predicts=Prediction(first_occurrence=(other,))), (2009,))
    assert h.run("finish", "--resume", "run-x", "--to", "pilot-a") == 0
    saved = snapshots.load("pilot-a", snapshots.SNAPSHOT_DIR)
    assert saved.lessons[0].statement == "revised"
    assert saved.lessons[0].support is not None
    assert saved.lessons[0].support.agrees == 4
    counts = json.loads((h.settings.runs_dir / "run-x" / "finish.json").read_text())
    assert counts["revised"] == 1


def test_finish_retires_a_lesson_no_case_falls_under(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(gitinfo, "is_committed", lambda *a, **k: True)
    h = Harness(tmp_path, _applies({claude.HAIKU: []}), ("2009",) * 2)
    ml.AGREEMENT_FILE.write_text("chosen applier: haiku-low\n")
    _write_draft(h, "run-x", _lesson(), (2009,))
    assert h.run("finish", "--resume", "run-x", "--to", "pilot-a") == 0
    saved = snapshots.load("pilot-a", snapshots.SNAPSHOT_DIR)
    assert saved.lessons == ()
    counts = json.loads((h.settings.runs_dir / "run-x" / "finish.json").read_text())
    assert counts["retired"] == 1
