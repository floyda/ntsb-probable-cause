"""The coding test (decisions 0204, 0205). A fake batch runner; offline; made-up cases."""

import json
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from scripts import memory_coding_test as ct

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import checks, prompts, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction, Support
from ntsb_probable_cause.model.batch import BatchRequest, BatchResult, BatchStatus
from ntsb_probable_cause.model.client import ModelReply, Payload, Usage, tool_reply
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.budget import SPEND_FILE, SpendRecord, open_reservations
from ntsb_probable_cause.scoring.records import read_jsonl
from ntsb_probable_cause.settings import Settings

NOW = datetime(2026, 10, 15, 9, tzinfo=UTC)
CAUSES: dict[str, str | None] = {
    "XXX09LA001": "The pilot's loss of directional control during the landing roll.",
    "XXX09LA002": "The pilot's failure to maintain airspeed, which resulted in a stall.",
}
FIRST, SECOND = CAUSES
HYPOTHESIS: dict[str, object] = {
    "evidence_narrative": "The airplane departed the runway during the landing roll.",
    "occurrence": [
        {"phase": "552", "event": "230", "probability": 0.6},
        {"phase": "551", "event": "230", "probability": 0.2},
    ],
    "findings": [{"category6": "020630", "modifier": "44", "probability": 0.7}],
    "probable_cause": "The pilot's loss of directional control during the landing roll.",
    "lay_explanation": "The plane swerved off the runway after touching down.",
    "confidence": 0.6,
    "abstain": False,
    "evidence_used": ["ntsb_probable_cause"],
}
REFINED = json.dumps({"items": [{"index": 0, "item8": "02063015"}]})
SOURCE = "20261015T090000Z-abc1234-dev-steer-400-mem-tables-a"

Answer = Callable[[BatchRequest], ModelReply | None]


def _text(content: str) -> ModelReply:
    return ModelReply(
        content=content,
        usage=Usage(prompt_tokens=1000, completion_tokens=200),
        model="fake",
        response_id="fake",
    )


class KilledError(Exception):
    """The process dying while it waits on a batch: not a model error, nothing catches it."""


@dataclass
class FakeBatch:
    """A scripted batch runner: every request answered by ``answer``; each round reports $0.001."""

    answer: Answer
    submitted: list[list[BatchRequest]] = field(default_factory=list)
    waited: list[str] = field(default_factory=list)
    die_at: str | None = None  # a batch id whose wait kills the process

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        self.submitted.append(list(requests))
        return f"b{len(self.submitted)}"

    def wait(
        self, batch_id: str, *, on_status: Callable[[BatchStatus], None] = lambda _s: None
    ) -> BatchStatus:
        self.waited.append(batch_id)
        if batch_id == self.die_at:
            raise KilledError
        requests = self.submitted[int(batch_id.removeprefix("b")) - 1]
        results = []
        for request in requests:
            reply = self.answer(request)
            error = None if reply is not None else "boom"
            results.append(BatchResult(custom_id=request.custom_id, reply=reply, error=error))
        status = BatchStatus(
            batch_id=batch_id, status="completed", results=tuple(results), reported_cost_usd=0.001
        )
        on_status(status)
        return status

    def requests(self) -> list[BatchRequest]:
        return [r for batch in self.submitted for r in batch]


def _case(request: BatchRequest) -> str:
    return request.custom_id.partition("#")[0]


@pytest.fixture
def settings(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Settings:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", False))
    monkeypatch.setattr(ct, "causes", lambda processed: dict(CAUSES))
    return Settings(data_dir=tmp_path / "data", monthly_budget_usd=40.0)


def _run(settings: Settings, fake: FakeBatch, argv: list[str]) -> int:
    return ct.main(argv, settings=settings, batch_factory=lambda _s: fake, now=lambda: NOW)


def _folder(settings: Settings, suffix: str) -> Path:
    (folder,) = settings.runs_dir.glob(f"*{suffix}")
    return folder


def _cases(folder: Path) -> dict[str, ct.CodingCase]:
    return {row.case_id: row for row in read_jsonl(folder / "cases.jsonl", ct.CodingCase)}


# --- the refusals ---------------------------------------------------------------------------


def test_only_the_steering_slice_is_accepted() -> None:
    ct.refuse_sample("dev-steer-400")
    for other in ("dev-400", "dev-seal-s3-400", "heldout-400", "live"):
        with pytest.raises(ConfigurationError):
            ct.refuse_sample(other)


def test_the_memory_condition_needs_the_registration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ct.gitinfo, "is_committed", lambda path: False)
    with pytest.raises(ConfigurationError):
        ct.refuse_memory_without_registration()
    monkeypatch.setattr(ct.gitinfo, "is_committed", lambda path: path == ct.REGISTRATION)
    ct.refuse_memory_without_registration()


def test_a_dirty_tree_is_refused_before_anything_is_read(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(gitinfo, "commit_state", lambda *a, **k: ("abc1234", True))

    def unread(_processed: Path) -> dict[str, str | None]:
        raise AssertionError("causes read on a dirty tree")

    monkeypatch.setattr(ct, "causes", unread)
    fake = FakeBatch(lambda _r: None)
    assert _run(settings, fake, ["answer", "--repeat", "a"]) == 1
    assert not fake.submitted
    assert not settings.runs_dir.exists()


# --- the tables condition -------------------------------------------------------------------


def _tables_answer(request: BatchRequest) -> ModelReply:
    if request.settings.schema_name == "refinement":
        return _text(REFINED)
    return _text(json.dumps(HYPOTHESIS))


def test_answer_codes_every_case_from_its_cause_alone(settings: Settings) -> None:
    fake = FakeBatch(_tables_answer)
    assert _run(settings, fake, ["answer", "--repeat", "a"]) == 0
    folder = _folder(settings, "-dev-steer-400-mem-tables-a")
    rows = _cases(folder)
    assert set(rows) == set(CAUSES)
    for row in rows.values():
        assert row.failure is None
        assert row.hypothesis is not None
        assert row.hypothesis.findings[0].item8 == "02063015"
        assert row.cost_usd > 0
    first = fake.submitted[0][0]
    assert first.payload == Payload.for_coding_test(str(CAUSES[FIRST]))
    assert first.system.startswith(prompts.CODING_PREFACE)
    assert first.settings.schema_name == "hypothesis"
    assert first.settings.model_id() == "openai/gpt-6-luna:batch"
    assert first.settings.reasoning_effort == "medium"
    assert first.settings.max_output_tokens == ct.MAX_OUTPUT_TOKENS
    refine = fake.submitted[1][0]
    assert refine.system.startswith(prompt.SYSTEM_REFINE)
    assert refine.history[0].content == json.dumps(HYPOTHESIS)
    spec = json.loads((folder / "spec.json").read_text())
    assert spec["condition"] == "tables"
    assert spec["sample"] == "dev-steer-400"
    assert spec["statistics"] == "mem"
    assert spec["guidance_sha256"] == prompt.guidance_sha256(ct.GUIDANCE)
    (spend,) = read_jsonl(folder / SPEND_FILE, SpendRecord)
    assert spend.kind == "coding-test"
    assert spend.cost_usd == pytest.approx(0.002)  # two rounds, each reporting $0.001
    assert spend.calls == 4
    assert open_reservations(settings.runs_dir) == {}


def test_a_rejected_answer_is_asked_again_once_then_recorded_as_failed(
    settings: Settings,
) -> None:
    def answer(request: BatchRequest) -> ModelReply:
        if _case(request) == FIRST and request.settings.schema_name == "hypothesis":
            return _text("not a hypothesis")
        return _tables_answer(request)

    fake = FakeBatch(answer)
    assert _run(settings, fake, ["answer", "--repeat", "b"]) == 0
    tries = [
        r for r in fake.requests() if _case(r) == FIRST and r.settings.schema_name == "hypothesis"
    ]
    assert len(tries) == 2
    assert prompt.REJECTED not in tries[0].system
    assert tries[1].system.startswith(prompts.CODING_PREFACE)
    assert f"\n\n{prompt.REJECTED}" in tries[1].system
    assert tries[1].payload == tries[0].payload
    rows = _cases(_folder(settings, "-mem-tables-b"))
    assert rows[FIRST].hypothesis is None
    assert rows[FIRST].failure == "failed: answer"
    assert rows[SECOND].hypothesis is not None


def test_a_case_with_no_cause_is_recorded_and_never_sent(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(ct, "causes", lambda processed: {**CAUSES, FIRST: None})
    fake = FakeBatch(_tables_answer)
    assert _run(settings, fake, ["answer", "--repeat", "a"]) == 0
    assert {_case(r) for r in fake.requests()} == {SECOND}
    rows = _cases(_folder(settings, "-mem-tables-a"))
    assert rows[FIRST].failure == ct.NO_CAUSE
    assert rows[FIRST].cost_usd == 0


# --- the counts and memory conditions -------------------------------------------------------


def _source(settings: Settings) -> None:
    folder = settings.runs_dir / SOURCE
    folder.mkdir(parents=True)
    spec = {"sample": "dev-steer-400", "condition": "tables", "repeat": "a"}
    (folder / "spec.json").write_text(json.dumps(spec))
    answered = {**HYPOTHESIS, "findings": [{**HYPOTHESIS["findings"][0], "item8": "02063015"}]}  # type: ignore[index]
    rows = [
        {"case_id": FIRST, "hypothesis": answered, "failure": None, "cost_usd": 0.001},
        {"case_id": SECOND, "hypothesis": None, "failure": "failed: answer", "cost_usd": 0.001},
    ]
    (folder / "cases.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))


def _tools_answer(request: BatchRequest) -> ModelReply:
    if request.settings.schema_name == "refinement":
        return _text(REFINED)
    return tool_reply("submit_answer", json.dumps(HYPOTHESIS))


def _snapshot(directory: Path, *, lessons: bool = True) -> None:
    lesson = Lesson(
        lesson_id="L001",
        kind="convention",
        statement="when the pilot stalls on approach, the NTSB codes loss of control first",
        scope="approach and landing",
        predicts=Prediction(first_occurrence=("550240",)),
        written_in=2009,
    )
    directory.mkdir()
    kept = (lesson,) if lessons else ()
    path = snapshots.save(Memory(name="t", periods=(2009,), lessons=kept), directory)
    stamp = checks.Stamp(
        snapshot="t",
        sha256=snapshots.sha256_of(path),
        withheld_texts_compared=1,
        causes_compared=1,
        checked_on=date(2026, 10, 15),
        commit="abc1234",
        dirty=False,
    )
    snapshots.stamp_path("t", directory).write_text(stamp.model_dump_json())


def test_counts_runs_the_fixed_tools_without_memory_and_skips_failed_sources(
    settings: Settings,
) -> None:
    _source(settings)
    fake = FakeBatch(_tools_answer)
    assert _run(settings, fake, ["tools", "--source", SOURCE, "--repeat", "a"]) == 0
    assert {_case(r) for r in fake.requests()} == {FIRST}
    answer = fake.submitted[0][0]
    assert answer.payload == Payload.for_coding_test(str(CAUSES[FIRST]))
    assert answer.system.startswith(prompts.CODING_PREFACE)
    assert prompts.MEMORY_HEADING not in answer.system
    called = [c.name for c in answer.history[0].tool_calls]
    assert called == ["describe_codes", "occurrence_usage", "past_findings"]
    folder = settings.runs_dir / f"{SOURCE}-counts-a"
    rows = _cases(folder)
    assert rows[FIRST].hypothesis is not None
    assert rows[FIRST].failure is None
    assert rows[SECOND].hypothesis is None
    assert rows[SECOND].failure == ct.SOURCE_FAILED
    assert rows[SECOND].cost_usd == 0
    spec = json.loads((folder / "spec.json").read_text())
    assert spec["condition"] == "counts"
    assert spec["source_run"] == SOURCE
    assert spec["snapshot"] is None
    assert spec["suggest_codes"] == "omitted: no phase-of-flight evidence"
    (spend,) = read_jsonl(folder / SPEND_FILE, SpendRecord)
    assert spend.kind == "coding-test"
    assert spend.calls == 2


def test_memory_appends_the_checked_snapshot_to_the_system_text(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(settings)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    _snapshot(tmp_path / "snapshots")
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: True)
    fake = FakeBatch(_tools_answer)
    argv = ["tools", "--source", SOURCE, "--snapshot", "t"]
    assert _run(settings, fake, argv) == 0
    answer = fake.submitted[0][0]
    assert answer.system.startswith(prompts.CODING_PREFACE)
    assert prompts.MEMORY_HEADING in answer.system
    folder = settings.runs_dir / f"{SOURCE}-memory-t"
    spec = json.loads((folder / "spec.json").read_text())
    assert spec["condition"] == "memory"
    assert spec["repeat"] is None  # the memory condition ignores --repeat
    assert spec["snapshot"] == "t"
    assert spec["snapshot_sha256"] == snapshots.sha256_of(tmp_path / "snapshots" / "t.json")
    assert "lookup_k" not in spec  # a memory spec is as it was before the lookup condition


def test_memory_is_refused_without_the_registration(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(settings)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    _snapshot(tmp_path / "snapshots")
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: False)
    fake = FakeBatch(_tools_answer)
    argv = ["tools", "--source", SOURCE, "--repeat", "a", "--snapshot", "t"]
    assert _run(settings, fake, argv) == 1
    assert not fake.submitted
    assert not (settings.runs_dir / f"{SOURCE}-memory-t").exists()


def test_tools_refuses_a_source_that_is_not_a_tables_run(settings: Settings) -> None:
    _source(settings)
    spec = settings.runs_dir / SOURCE / "spec.json"
    spec.write_text(json.dumps({"sample": "dev-steer-400", "condition": "counts"}))
    fake = FakeBatch(_tools_answer)
    assert _run(settings, fake, ["tools", "--source", SOURCE, "--repeat", "a"]) == 1
    spec.write_text(json.dumps({"sample": "dev-400", "condition": "tables"}))
    assert _run(settings, fake, ["tools", "--source", SOURCE, "--repeat", "a"]) == 1
    assert not fake.submitted


def test_a_run_folder_is_never_reused(settings: Settings) -> None:
    _source(settings)
    fake = FakeBatch(_tools_answer)
    assert _run(settings, fake, ["tools", "--source", SOURCE, "--repeat", "a"]) == 0
    sent = len(fake.requests())
    assert _run(settings, fake, ["tools", "--source", SOURCE, "--repeat", "a"]) == 1
    assert len(fake.requests()) == sent


def test_spend_falls_back_to_the_priced_cost_when_a_round_reports_none(
    settings: Settings,
) -> None:
    class Unreported(FakeBatch):
        def wait(
            self, batch_id: str, *, on_status: Callable[[BatchStatus], None] = lambda _s: None
        ) -> BatchStatus:
            status = super().wait(batch_id, on_status=on_status)
            return status.model_copy(update={"reported_cost_usd": None})

    fake = Unreported(_tables_answer)
    assert _run(settings, fake, ["answer", "--repeat", "a"]) == 0
    folder = _folder(settings, "-mem-tables-a")
    (spend,) = read_jsonl(folder / SPEND_FILE, SpendRecord)
    priced = sum(row.cost_usd for row in _cases(folder).values())
    assert spend.cost_usd == pytest.approx(priced)
    assert priced > 0
    assert Counter(r.settings.schema_name for r in fake.requests()) == {
        "hypothesis": 2,
        "refinement": 2,
    }


def test_a_cancelled_batch_still_writes_its_spend_and_settles(settings: Settings) -> None:
    class Cancelled(FakeBatch):
        def wait(
            self, batch_id: str, *, on_status: Callable[[BatchStatus], None] = lambda _s: None
        ) -> BatchStatus:
            if batch_id == "b1":
                return super().wait(batch_id, on_status=on_status)
            return BatchStatus(
                batch_id=batch_id, status="cancelled", results=(), reported_cost_usd=0.0005
            )

    fake = Cancelled(_tables_answer)
    assert _run(settings, fake, ["answer", "--repeat", "a"]) == 1
    folder = _folder(settings, "-mem-tables-a")
    assert not (folder / "cases.jsonl").exists()
    (spend,) = read_jsonl(folder / SPEND_FILE, SpendRecord)
    assert spend.cost_usd == pytest.approx(0.0015)
    assert spend.calls == 2
    assert open_reservations(settings.runs_dir) == {}


# --- fix round 1: resume, the spend row, empty snapshots, fairness --------------------------


def _first_try_rejected(request: BatchRequest) -> ModelReply:
    """The first case's first answer is rejected; everything else is answered."""
    if request.custom_id == f"{FIRST}#0":
        return _text("not a hypothesis")
    return _tables_answer(request)


def _on_disk(folder: Path) -> set[str]:
    return {
        f"{row['case_id']}#{row['call_index']}"
        for row in map(json.loads, (folder / "replies.jsonl").read_text().splitlines())
    }


def test_a_resume_after_a_death_mid_round_sends_no_answered_call_and_counts_spend_once(
    settings: Settings, capsys: pytest.CaptureFixture[str]
) -> None:
    dead = FakeBatch(_first_try_rejected, die_at="b2")
    with pytest.raises(KilledError):
        _run(settings, dead, ["answer", "--repeat", "a"])
    folder = _folder(settings, "-mem-tables-a")
    run_id = folder.name
    kept = capsys.readouterr().out  # final review M6: the message names both ways out
    assert f"--resume {run_id}" in kept
    assert f"uv run ntsb-eval release {run_id}" in kept
    (spend,) = read_jsonl(folder / SPEND_FILE, SpendRecord)
    assert spend.calls == 2  # round 1's replies; round 2 is open, so the priced cost is counted
    assert run_id in open_reservations(settings.runs_dir)  # an open round may still be billed
    answered = _on_disk(folder)
    assert answered == {f"{FIRST}#0", f"{SECOND}#0"}

    resumed = FakeBatch(_first_try_rejected, submitted=[list(b) for b in dead.submitted])
    argv = ["answer", "--repeat", "a", "--resume", run_id]
    assert _run(settings, resumed, argv) == 0
    assert resumed.waited == ["b2", "b3"]  # b2 waited on again, never sent again
    new = [r.custom_id for batch in resumed.submitted[len(dead.submitted) :] for r in batch]
    assert new == [f"{FIRST}#2"]  # only the first case's refinement is left
    assert not set(new) & answered
    (spend,) = read_jsonl(folder / SPEND_FILE, SpendRecord)  # one row, replaced
    assert spend.cost_usd == pytest.approx(0.003)  # three rounds, each reported once
    assert spend.calls == 5
    assert open_reservations(settings.runs_dir) == {}
    rows = _cases(folder)
    assert all(row.hypothesis is not None for row in rows.values())


def test_a_resume_is_refused_unless_its_spec_matches_and_it_is_unfinished(
    settings: Settings,
) -> None:
    dead = FakeBatch(_tables_answer, die_at="b2")
    with pytest.raises(KilledError):
        _run(settings, dead, ["answer", "--repeat", "a"])
    run_id = _folder(settings, "-mem-tables-a").name
    fake = FakeBatch(_tables_answer, submitted=[list(b) for b in dead.submitted])
    assert _run(settings, fake, ["answer", "--repeat", "b", "--resume", run_id]) == 1
    assert _run(settings, fake, ["answer", "--repeat", "a", "--resume", "no-such-run"]) == 1
    assert not fake.waited
    assert _run(settings, fake, ["answer", "--repeat", "a", "--resume", run_id]) == 0
    assert _run(settings, fake, ["answer", "--repeat", "a", "--resume", run_id]) == 1  # finished


def test_a_tools_resume_must_name_the_run_its_arguments_make(settings: Settings) -> None:
    _source(settings)
    fake = FakeBatch(_tools_answer)
    argv = ["tools", "--source", SOURCE, "--repeat", "a", "--resume", f"{SOURCE}-counts-b"]
    assert _run(settings, fake, argv) == 1
    assert _run(settings, fake, ["tools", "--source", SOURCE]) == 1  # counts needs --repeat
    assert not fake.submitted


def test_a_failed_spec_write_still_writes_spend_and_settles(
    settings: Settings, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(*_args: object, **_kwargs: object) -> str:
        raise OSError("disk full")

    monkeypatch.setattr(ct, "json", SimpleNamespace(dumps=broken, loads=json.loads))
    fake = FakeBatch(_tables_answer)
    with pytest.raises(OSError, match="disk full"):
        _run(settings, fake, ["answer", "--repeat", "a"])
    assert not fake.submitted
    folder = _folder(settings, "-mem-tables-a")
    (spend,) = read_jsonl(folder / SPEND_FILE, SpendRecord)
    assert (spend.calls, spend.cost_usd) == (0, 0.0)
    assert open_reservations(settings.runs_dir) == {}


def test_a_snapshot_with_no_lessons_is_refused(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(settings)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    _snapshot(tmp_path / "snapshots", lessons=False)
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: True)
    with pytest.raises(ConfigurationError, match="no lessons"):
        ct._checked_memory("t")
    fake = FakeBatch(_tools_answer)
    assert _run(settings, fake, ["tools", "--source", SOURCE, "--snapshot", "t"]) == 1
    assert not fake.submitted


def test_counts_and_memory_send_the_same_requests_but_for_the_memory_suffix(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(settings)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    _snapshot(tmp_path / "snapshots")
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: True)
    counts, memory = FakeBatch(_tools_answer), FakeBatch(_tools_answer)
    assert _run(settings, counts, ["tools", "--source", SOURCE, "--repeat", "a"]) == 0
    assert _run(settings, memory, ["tools", "--source", SOURCE, "--snapshot", "t"]) == 0
    pairs = list(zip(counts.requests(), memory.requests(), strict=True))
    assert pairs
    suffixed = 0
    for plain, with_memory in pairs:
        assert plain.custom_id == with_memory.custom_id
        assert plain.payload == with_memory.payload
        assert plain.settings == with_memory.settings
        assert plain.history == with_memory.history
        if plain.system != with_memory.system:
            assert with_memory.system.startswith(plain.system)
            assert with_memory.system[len(plain.system) :].startswith(prompts.MEMORY_HEADING)
            suffixed += 1
    assert suffixed == 1  # the answer call; the refinement's system text holds no memory


# --- the lookup condition (decision 0210) ---------------------------------------------------


WORDS = {"L001": "one", "L002": "two", "L003": "three", "L004": "four"}


def _lookup_snapshot(directory: Path) -> None:
    """One kept lesson that matches the source answer's 552230, one pushed out that matches its
    category 020630, one that matches nothing, and one that matches but has too little support."""

    def lesson(lid: str, first: tuple[str, ...], cats: tuple[str, ...], applies: int) -> Lesson:
        kind = "convention" if first else "evidence"
        return Lesson(
            lesson_id=lid,
            kind=kind,
            statement=f"lesson {WORDS[lid]} says how the NTSB codes it",
            scope="a scope",
            predicts=Prediction(first_occurrence=first, finding_categories=cats),
            written_in=2010,
            support=Support(applies=applies, agrees=applies // 2),
        )

    directory.mkdir()
    memory = Memory(
        name="t",
        periods=(2009, 2010),
        lessons=(lesson("L001", ("552230",), (), 30), lesson("L002", ("550240",), (), 30)),
        pushed_out=(lesson("L003", (), ("020630",), 20), lesson("L004", ("552230",), (), 9)),
    )
    path = snapshots.save(memory, directory)
    stamp = checks.Stamp(
        snapshot="t",
        sha256=snapshots.sha256_of(path),
        withheld_texts_compared=1,
        causes_compared=1,
        checked_on=date(2026, 10, 16),
        commit="abc1234",
        dirty=False,
    )
    snapshots.stamp_path("t", directory).write_text(stamp.model_dump_json())


def test_lookup_gives_the_case_the_lessons_that_match_its_first_answer(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(settings)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    _lookup_snapshot(tmp_path / "snapshots")
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: True)
    fake = FakeBatch(_tools_answer)
    argv = ["tools", "--source", SOURCE, "--snapshot", "t", "--lookup", "5"]
    assert _run(settings, fake, argv) == 0
    answer = fake.submitted[0][0]
    assert prompts.MEMORY_HEADING in answer.system
    assert "[L001]" in answer.system  # kept, matches the first code
    assert "[L003]" in answer.system  # pushed out, matches the finding category
    assert "[L002]" not in answer.system  # matches nothing
    assert "[L004]" not in answer.system  # below the support floor
    folder = settings.runs_dir / f"{SOURCE}-lookup5-t"
    spec = json.loads((folder / "spec.json").read_text())
    assert spec["condition"] == "lookup"
    assert spec["repeat"] is None
    assert spec["lookup_k"] == 5
    assert spec["lookup_min_applies"] == 10
    assert spec["lookup_lessons"] == {FIRST: ["L001", "L003"]}


def test_lookup_sends_the_counts_requests_with_only_the_lessons_added(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(settings)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    _lookup_snapshot(tmp_path / "snapshots")
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: True)
    counts, looked = FakeBatch(_tools_answer), FakeBatch(_tools_answer)
    assert _run(settings, counts, ["tools", "--source", SOURCE, "--repeat", "a"]) == 0
    argv = ["tools", "--source", SOURCE, "--snapshot", "t", "--lookup", "1"]
    assert _run(settings, looked, argv) == 0
    plain, with_lessons = counts.submitted[0][0], looked.submitted[0][0]
    assert plain.payload == with_lessons.payload
    assert plain.history == with_lessons.history
    suffix = with_lessons.system[len(plain.system) :]
    assert with_lessons.system.startswith(plain.system)
    assert suffix.startswith(prompts.MEMORY_HEADING)
    assert "[L001]" in suffix
    assert "[L003]" not in suffix  # K=1: only the best match


def test_lookup_is_refused_without_its_registration(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _source(settings)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    _lookup_snapshot(tmp_path / "snapshots")
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: path != ct.LOOKUP_REGISTRATION)
    fake = FakeBatch(_tools_answer)
    argv = ["tools", "--source", SOURCE, "--snapshot", "t", "--lookup", "5"]
    assert _run(settings, fake, argv) == 1
    assert not fake.submitted
    assert not (settings.runs_dir / f"{SOURCE}-lookup5-t").exists()


@pytest.mark.parametrize(
    "argv",
    [
        ["tools", "--source", SOURCE, "--repeat", "a", "--lookup", "5"],
        ["tools", "--source", SOURCE, "--snapshot", "t", "--lookup", "0"],
    ],
)
def test_lookup_needs_a_snapshot_and_a_positive_k(
    settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, argv: list[str]
) -> None:
    _source(settings)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snapshots")
    _lookup_snapshot(tmp_path / "snapshots")
    monkeypatch.setattr(gitinfo, "is_committed", lambda path: True)
    fake = FakeBatch(_tools_answer)
    assert _run(settings, fake, argv) == 1
    assert not fake.submitted
