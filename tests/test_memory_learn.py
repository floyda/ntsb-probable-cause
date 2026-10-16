"""The learner script (decisions 0201-0204). Offline; made-up replies and a fake SDK."""

import dataclasses
import json
import re
import shutil
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import anthropic
import pytest
from scripts import memory_check
from scripts import memory_learn as ml
from tests.conftest import coded_record, write_cases

from ntsb_probable_cause import fields, gitinfo
from ntsb_probable_cause.memory import claude, pool, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, Support
from ntsb_probable_cause.memory.pool import LearningCase
from ntsb_probable_cause.memory.prompts import LessonDraft, LessonEdit, ProposeReply, ReviseReply
from ntsb_probable_cause.scoring import samples
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


def test_a_dropped_identifier_draft_names_no_text_in_its_message() -> None:
    reply = ProposeReply(
        new=[_draft(statement="the pilot of N123AB lost control"), _draft(scope="at N123AB")],
        edits=[LessonEdit(lesson_id="L001", **_draft(statement="N123AB again").model_dump())],
        retire=["N123AB"],
    )
    memory, dropped = ml.merge_proposal(
        Memory(name="d", periods=(2009,), lessons=(_lesson(),)), reply, 2009, TABLES, lambda: "L002"
    )
    assert len(dropped) == 4
    assert "N123AB" not in " ".join(dropped)
    assert [lesson.statement for lesson in memory.lessons] == ["old"]
    revise = ReviseReply(action="edit", **_draft(statement="N123AB").model_dump())
    _, messages = ml.merge_revision(memory, "L001", revise, 2009, TABLES)
    assert messages
    assert "N123AB" not in " ".join(messages)


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
    assert h.messages.created == []
    assert h.messages.requests == {}


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
    first_code = fields.occurrence_codes(coded_record())[0]
    other = "552230" if first_code != "552230" else "551230"

    def respond(params: dict[str, object]) -> str:
        if params["model"] == claude.HAIKU:
            return json.dumps({"applies": ["L001"]})
        edit = _draft(statement="revised", first_occurrence=[first_code]).model_dump()
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


def test_propose_prints_no_draft_text_when_it_drops_a_draft(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    bad = _draft(statement="the pilot of N123AB lost control").model_dump()
    h = Harness(
        tmp_path, lambda p: json.dumps({"new": [bad], "edits": [], "retire": []}), ("2009",)
    )
    assert h.run("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a") == 0
    out = capsys.readouterr().out
    assert "1 drafts dropped" in out
    assert "N123AB" not in out


# The shapes the first 2009 propose run returned (plan Deviations, 2026-10-16): a code with its
# label, and a ten-digit finding code where a six-digit category belongs.
CATEGORY = sorted(TABLES.categories)[0]
LABELLED = "552230 Landing-Landing Roll / Loss of control on ground"


def test_reshape_reads_codes_from_their_leading_digits_and_counts_the_changes() -> None:
    draft = _draft(
        first_occurrence=[LABELLED, "552230", "5522301", "a label alone"],
        finding_categories=[
            f"{CATEGORY}2020",
            f"{CATEGORY}20",
            f"{CATEGORY}2020 a label",
            CATEGORY,
        ],
    )
    reshaped, changed = ml.reshape(draft)
    assert reshaped.first_occurrence == ["552230", "552230", "5522301", "a label alone"]
    assert reshaped.finding_categories == [CATEGORY] * 4
    assert changed == 4


def test_a_draft_in_the_copied_shapes_is_kept_with_six_digit_codes() -> None:
    ids = iter(["L001", "L002"])
    shaped = _draft(first_occurrence=[LABELLED], finding_categories=[f"{CATEGORY}2020"])
    reply = ProposeReply(new=[shaped, _draft(first_occurrence=["5522301"])], edits=[], retire=[])
    memory, dropped = ml.merge_proposal(
        Memory(name="d", periods=(2009,)), reply, 2009, TABLES, lambda: next(ids)
    )
    assert [lesson.predicts.first_occurrence for lesson in memory.lessons] == [("552230",)]
    assert memory.lessons[0].predicts.finding_categories == (CATEGORY,)
    assert len(dropped) == 1


def test_an_edit_and_a_revision_in_the_copied_shapes_are_kept() -> None:
    shaped = _draft(statement="new", first_occurrence=[LABELLED]).model_dump()
    reply = ProposeReply(new=[], edits=[LessonEdit(lesson_id="L001", **shaped)], retire=[])
    start = Memory(name="d", periods=(2009,), lessons=(_lesson(),))
    memory, dropped = ml.merge_proposal(start, reply, 2010, TABLES, lambda: "L002")
    assert dropped == []
    assert memory.lessons[0].predicts.first_occurrence == ("552230",)
    revise = ReviseReply(action="edit", **shaped)
    revised, messages = ml.merge_revision(start, "L001", revise, 2010, TABLES)
    assert messages == []
    assert revised.lessons[0].predicts.first_occurrence == ("552230",)


def test_propose_prints_how_many_codes_it_read_from_their_leading_digits(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    shaped = _draft(first_occurrence=[LABELLED], finding_categories=[f"{CATEGORY}2020"])
    h = Harness(
        tmp_path,
        lambda p: json.dumps({"new": [shaped.model_dump()], "edits": [], "retire": []}),
        ("2009",),
    )
    assert h.run("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a") == 0
    out = capsys.readouterr().out
    assert "1 lessons, 0 drafts dropped, 2 codes read from their leading digits" in out


def test_a_resumed_propose_makes_no_new_calls(tmp_path: Path) -> None:
    h = Harness(
        tmp_path,
        lambda p: json.dumps({"new": [_draft().model_dump()], "edits": [], "retire": []}),
        ("2009",) * 31,
    )
    assert h.run("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a") == 0
    run_id = next(p.name for p in h.settings.runs_dir.iterdir() if p.is_dir())
    sent = len(h.messages.created)
    assert sent == 2
    first = (h.settings.runs_dir / run_id / "draft.json").read_text()
    args = ("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a")
    assert h.run(*args, "--resume", run_id) == 0
    assert len(h.messages.created) == sent
    assert (h.settings.runs_dir / run_id / "draft.json").read_text() == first


def test_a_phase_over_the_learning_line_is_refused_before_any_call(tmp_path: Path) -> None:
    h = Harness(tmp_path, lambda p: "{}", ("2009",) * 3)
    h.settings = Settings(data_dir=tmp_path / "data", learning_monthly_budget_usd=0.0)
    assert h.run("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a") == 1
    assert h.messages.created == []
    assert h.messages.requests == {}


def test_finish_refuses_an_agreement_file_with_no_chosen_applier(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(gitinfo, "is_committed", lambda *a, **k: True)
    h = Harness(tmp_path, _applies({claude.HAIKU: []}), ("2009",))
    ml.AGREEMENT_FILE.write_text("no lesson covered any case: the pilot cannot proceed\n")
    _write_draft(h, "run-x", _lesson(), (2009,))
    assert h.run("finish", "--resume", "run-x", "--to", "pilot-a") == 1
    assert "refused:" in capsys.readouterr().out
    assert h.messages.requests == {}


def test_finish_drops_a_lesson_that_copies_a_cause_and_the_snapshot_then_passes_the_check(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Final review I1: finish removes what make mem-check would refuse, kept or pushed out.
    monkeypatch.setattr(gitinfo, "is_committed", lambda *a, **k: True)
    h = Harness(tmp_path, _applies({claude.HAIKU: ["L001", "L002"]}), ("2009",) * 4)
    ml.AGREEMENT_FILE.write_text("chosen applier: haiku-low\n")
    cause = fields.probable_cause(h.raw)
    assert cause is not None
    copied = "when " + " ".join(re.findall(r"[a-z0-9']+", cause.lower())[:8]) + " happens"
    first = fields.occurrence_codes(h.raw)[0]
    good = _lesson(predicts=Prediction(first_occurrence=(first,)))
    bad = _lesson(lesson_id="L002", statement=copied)
    draft = Memory(name="pilot-a", periods=(2009,), lessons=(good,), pushed_out=(bad,))
    (h.run_folder("run-x") / "draft.json").write_text(draft.model_dump_json())
    assert h.run("finish", "--resume", "run-x", "--to", "pilot-a") == 0
    out = capsys.readouterr().out
    assert "L002 dropped: copying check" in out
    assert copied not in out
    saved = snapshots.load("pilot-a", snapshots.SNAPSHOT_DIR)
    assert [lesson.lesson_id for lesson in saved.lessons] == ["L001"]
    assert saved.pushed_out == ()
    counts = json.loads((h.settings.runs_dir / "run-x" / "finish.json").read_text())
    assert counts["dropped_by_checks"] == 1
    assert "dropped by checks 1" in out
    cases_file = h.settings.data_dir / "processed" / "cases.parquet"
    monkeypatch.setattr(memory_check, "processed_path", lambda: cases_file)
    assert memory_check.main(["--snapshot", "pilot-a"]) == 0


def test_the_2009_finish_with_sonnet_as_applier_projects_under_the_learning_line() -> None:
    # Controller ruling I2: Sonnet apply calls get MAX_TOKENS_SONNET_APPLY, so a 2009 finish
    # (1,201 learning cases) fits under the $90 learner line, both applies and every revision.
    cause = fields.probable_cause(coded_record())
    assert cause is not None
    cases = [LearningCase(f"C{i:04d}", 2009, cause, ("552230",), ()) for i in range(1201)]
    lessons = tuple(_lesson(lesson_id=f"L{i:03d}") for i in range(1, 6))
    memory = Memory(name="d", periods=(2009,), lessons=lessons)
    model, effort = ml.APPLIERS["sonnet-high"]
    calls = [ml._call_for_apply("apply", model, effort, memory, c) for c in cases]
    assert {c.max_tokens for c in calls} == {ml.MAX_TOKENS_SONNET_APPLY}
    apply_usd = ml.projected_usd(calls, batch=True)
    support = {lesson.lesson_id: Support(applies=0, agrees=0) for lesson in lessons}
    revisions = [ml._revise_call(lesson, support, cases, {}, TABLES) for lesson in lessons]
    total = 2 * apply_usd + ml.projected_usd(revisions, batch=False)
    assert total < 90.0
    at_old_limit = [dataclasses.replace(c, max_tokens=ml.MAX_TOKENS_SONNET) for c in calls]
    assert ml.projected_usd(at_old_limit, batch=True) > 90.0  # one apply alone, before the ruling


def test_propose_sends_no_steering_or_dev_400_case_by_the_default_exclusions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Final review T8, end to end: real sample ids among learning rows, the default exclusions.
    steer = samples.sample_ids("dev-steer-400")[0]
    dev400 = samples.sample_ids("dev-400")[0]
    raw = coded_record()

    def caused(marker: str) -> dict[str, object]:
        narratives = cast(list[dict[str, object]], raw["narratives"])
        return {**raw, "narratives": [{**narratives[0], "probableCause": f"{marker} cause."}]}

    h = Harness(tmp_path, lambda p: json.dumps({"new": [], "edits": [], "retire": []}), ())
    processed = h.settings.data_dir / "processed"
    shutil.rmtree(processed)
    write_cases(
        processed,
        [
            ("A000", "2009-05-01", "dev", "C", raw),
            (steer, "2009-05-02", "dev", "C", caused("steeringmarker")),
            (dev400, "2009-05-03", "dev", "C", caused("devfourmarker")),
        ],
    )
    sent: list[claude.Call] = []
    original = claude.LearningClient.send

    def spy(self: claude.LearningClient, call: claude.Call) -> claude.Reply:
        sent.append(call)
        return original(self, call)

    monkeypatch.setattr(claude.LearningClient, "send", spy)
    assert h.run("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a") == 0
    assert [call.case_ids for call in sent] == [("A000",)]
    users = " ".join(_user(params) for params in h.messages.created)
    assert len(h.messages.created) == 1
    for needle in (steer, dev400, "steeringmarker", "devfourmarker"):
        assert needle not in users


def test_a_truncated_record_line_is_skipped_and_its_count_printed(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Final review M2: a write cut short leaves a line that does not parse; it is not fatal.
    h = Harness(tmp_path, lambda p: json.dumps({"new": [], "edits": [], "retire": []}), ("2009",))
    (h.run_folder("run-x") / claude.CALLS_FILE).write_text('{"key": "cut sho')
    args = ("propose", "--period", "2009", "--from", "empty", "--to", "pilot-a")
    assert h.run(*args, "--resume", "run-x") == 0
    assert "1 unreadable record lines skipped in run run-x" in capsys.readouterr().out
