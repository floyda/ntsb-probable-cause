"""scripts/s3_trail_pages.py: a few arm C trails as one private page for Andy (S3.1 Task 15).

Synthetic run folders (``run.jsonl``, ``cases.jsonl``, ``trail.jsonl``), a groups file as
``scripts/s3_case_groups.py`` writes it, the record fixtures (real development records,
redacted) and a synthetic docket. Offline: the docket is passed in, or read from an empty
cache, which must refuse rather than fetch.
"""

import copy
import dataclasses
import html
import json
import random
import re
import shutil
from collections.abc import Callable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from scripts import s3_trail_pages as tp
from scripts.miss_kinds import PATTERNS
from tests.conftest import FIXTURES

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.agent.schemas import CodingToolName, parse_call
from ntsb_probable_cause.agent.tools import run_coding_tool
from ntsb_probable_cause.agent.trail import AgentCall, StepKind
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord, Status
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.coding_stats import load_stats
from ntsb_probable_cause.scoring.hypothesis import FindingGuess, Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import CaseScores
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, StepRecord, write_jsonl

_TABLES = load_tables()
_STATS = load_stats("s3")
_WHEN = datetime(2026, 10, 2, 12, 30, 15, tzinfo=UTC)
_STAMP = "20261002T123015"
_RUN_A = "20261001T201506-fd6053f-dev-400-C"
_RUN_B = "20261001T201648-fd6053f-dev-400-C"
_FATAL = ("ANC10MA068", "ANC13FA004", "ANC15FA071")
_NONFATAL = ("ANC09CA020", "ANC09CA024", "ANC09CA027", "ANC09LA022", "ANC10LA044", "CEN11CA664")
_IDS = tuple(sorted(_FATAL + _NONFATAL))
# Two cases with their own story: one failed at the coding step, one stopped by the guard before
# any call. Every other case carries the full trail below.
_FAILED = "ANC15FA071"
_NO_CALL = "ANC09CA027"
# An invented owner or operator name, put back into every record (the fixtures are redacted of
# it, as an unredacted record is not) and into a document title and the agent's own words.
_OWNER = "Zorvex Quillbright"
_NAMED = "ANC13FA004"

# --------------------------------------------------------------------------------------------
# The records, the docket, the trails
# --------------------------------------------------------------------------------------------


def _raws() -> dict[str, dict[str, object]]:
    raws: dict[str, dict[str, object]] = {}
    for path in sorted((FIXTURES / "records").glob("*.json")):
        raw = json.loads(path.read_text())["record"]
        assert isinstance(raw, dict)
        aircraft = cast(list[dict[str, object]], raw["aircrafts"])[0]
        aircraft["ownerOperators"] = [{"operatorName": _OWNER}]
        raws[path.stem] = raw
    return raws


_RAWS = _raws()


def _load(ids: Sequence[str]) -> list[dict[str, object]]:
    return [copy.deepcopy(_RAWS[i]) for i in ids]


_LONG = "[page 1 of 3]\n" + "The engine examination found the crankshaft intact. " * 10
_SHORT = "[page 1 of 2]\nA short statement.\n"
_DOCUMENTS: tuple[tuple[int, str, int, Status], ...] = (
    (1, "Powerplant Examination Report", 3, "read"),
    (2, f"Statement of {_OWNER}", 2, "read"),
    (3, "Pilot Operator Report 6120", 4, "unreadable: scan"),
)


def _docket(mkey: int) -> Docket:
    """Three documents: [2] is offered first (smaller), then [1]; [3] cannot be read."""
    texts = {1: _LONG, 2: _SHORT}
    records = tuple(
        DocumentRecord(
            entry=ListingEntry(
                index=index,
                title=title,
                pages=pages,
                photos=0,
                doc_type="Report",
                extension="pdf",
                href=f"/d{index}",
            ),
            category="other",
            status=status,
            pages=pages,
            readable_pages=pages if status == "read" else 0,
            estimated_tokens=len(texts.get(index, "")) // 4,
            kind="born-digital" if status == "read" else "scan",
        )
        for index, title, pages, status in _DOCUMENTS
    )
    listing = Listing(mkey=mkey, declared_items=3, entries=tuple(r.entry for r in records))
    return Docket(mkey=mkey, listing=listing, documents=records, texts=texts)


def _hypothesis(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    tag: str,
    first: str = "500240",
    *,
    findings: bool = False,
    item: str | None = None,
    abstain: bool = False,
    confidence: float = 0.45,
) -> Hypothesis:
    return Hypothesis(
        evidence_narrative=f"NARRATIVE-{tag}",
        occurrence=(
            OccurrenceGuess(phase=first[:3], event=first[3:], probability=0.55),
            OccurrenceGuess(phase="552", event="241", probability=0.25),
        ),
        findings=(
            (FindingGuess(category6="010100", modifier="01", probability=0.4, item8=item),)
            if findings
            else ()
        ),
        probable_cause=f"CAUSE-{tag}",
        lay_explanation="lay",
        confidence=confidence,
        abstain=abstain,
        evidence_used=(),
    )


_H0 = _hypothesis("H0").model_copy(update={"evidence_narrative": f"NARRATIVE-H0 names {_OWNER}"})
_H1 = _hypothesis("H1")
_H2 = _hypothesis("H2")
_ANSWER = _hypothesis("ANSWER", findings=True)
_REFINED = _hypothesis("ANSWER", findings=True, item="01010000")
_OTHER = _hypothesis("OTHER", "552241", findings=True, item="01010000")


def _call(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    index: int,
    step: StepKind,
    tool: str | None,
    *,
    arguments: Mapping[str, object] | None = None,
    offered: tuple[int, ...] = (),
    error: str | None = None,
    retry: bool = False,
    hypothesis: Hypothesis | None = None,
    result_chars: int = 0,
    argument_errors: int = 0,
    run_id: str = _RUN_A,
) -> AgentCall:
    if hypothesis is not None and arguments is None:
        arguments = hypothesis.model_dump(mode="json")
    return AgentCall(
        run_id=run_id,
        case_id=case_id,
        trigger=1,
        docket_state="all",
        call_index=index,
        step=step,
        retry=retry,
        tool=tool,
        arguments=dict(arguments or {}),
        offered=offered,
        protocol_error=error,
        result_chars=result_chars,
        argument_errors=argument_errors,
        hypothesis=hypothesis,
        prompt_tokens=100,
        cached_tokens=None,
        completion_tokens=10,
        reasoning_tokens=None,
        finish_reason="tool_calls",
        cost_usd=0.001,
        estimated_usd=0.002,
        sent_at=_WHEN,
        returned_at=_WHEN,
        batch_id="b1",
        commit_sha="fd6053f",
        dirty=False,
    )


def _why(tag: str, **arguments: object) -> dict[str, object]:
    return {**arguments, "reason": f"REASON-{tag}", "expected_effect": f"EFFECT-{tag}"}


# The coding calls of the full trail: every tool, one unknown code among them.
_CODING: tuple[tuple[str, dict[str, object], int], ...] = (
    ("describe_codes", _why("DESCRIBE", kind="occurrence", codes=["500240", "999999"]), 1),
    ("describe_codes", _why("CATEGORY", kind="finding_category", codes=["010100"]), 0),
    ("describe_codes", _why("ITEM", kind="item", codes=["01010000"]), 0),
    ("occurrence_usage", _why("USAGE", codes=["500240", "552241"]), 0),
    ("past_findings", _why("PAST", occurrence="500240"), 0),
    ("suggest_codes", _why("SUGGEST", phase_group="Approach"), 0),
)


def _rebuilt(tool: str, arguments: Mapping[str, object]) -> str:
    """What ``run_coding_tool`` returns for the recorded arguments, parsed as the loop parses."""
    parsed = parse_call(tool, json.dumps(arguments), _TABLES)
    return run_coding_tool(cast(CodingToolName, tool), parsed, tables=_TABLES, stats=_STATS).text


def _full_trail(case_id: str, run_id: str = _RUN_A) -> list[AgentCall]:
    choice1 = {
        "decisions": [
            {"document": 2, "read": True, "expected_effect": "EXPECT-READ-2"},
            {"document": 1, "read": False, "expected_effect": "EXPECT-SKIP-1"},
            {"document": 3, "read": True, "expected_effect": "EXPECT-EXTRA-3"},
            {"document": 9, "read": False, "expected_effect": "EXPECT-EXTRA-9"},
        ],
        "reason": "REASON-CHOICE-1",
    }
    choice2 = {
        "decisions": [
            {"document": 1, "read": True, "expected_effect": "EXPECT-READ-1"},
            {"document": 2, "read": True, "expected_effect": "EXPECT-AGAIN-2"},
        ],
        "reason": "REASON-CHOICE-2",
    }
    calls = [
        _call(case_id, 0, "h0", "record_hypothesis", hypothesis=_H0, run_id=run_id),
        _call(
            case_id,
            1,
            "choice1",
            "choose_documents",
            arguments=choice1,
            offered=(2, 1),
            argument_errors=2,
            run_id=run_id,
        ),
        _call(
            case_id,
            2,
            "h1",
            "record_hypothesis",
            error="occurrence probabilities sum to more than 1",
            run_id=run_id,
        ),
        _call(case_id, 3, "h1", "record_hypothesis", retry=True, hypothesis=_H1, run_id=run_id),
        _call(
            case_id,
            4,
            "choice2",
            "choose_documents",
            arguments=choice2,
            offered=(1,),
            argument_errors=1,
            run_id=run_id,
        ),
        _call(case_id, 5, "h2", "record_hypothesis", hypothesis=_H2, run_id=run_id),
    ]
    for n, (tool, arguments, errors) in enumerate(_CODING, start=6):
        text = _rebuilt(tool, arguments)
        calls.append(
            _call(
                case_id,
                n,
                "coding",
                tool,
                arguments=arguments,
                result_chars=len(text),
                argument_errors=errors,
                run_id=run_id,
            )
        )
    n = len(calls)
    return [
        *calls,
        _call(
            case_id,
            n,
            "coding",
            "record_hypothesis",
            error="this step takes describe_codes, "
            "occurrence_usage, past_findings, suggest_codes or submit_answer, not "
            "record_hypothesis",
            run_id=run_id,
        ),
        _call(
            case_id, n + 1, "coding", "submit_answer", retry=True, hypothesis=_ANSWER, run_id=run_id
        ),
        _call(case_id, n + 2, "refine", None, hypothesis=_REFINED, run_id=run_id),
    ]


def _failed_trail(case_id: str, run_id: str = _RUN_A) -> list[AgentCall]:
    """H0, then two coding calls not accepted: the case failed at the coding step."""
    return [
        _call(case_id, 0, "h0", "record_hypothesis", hypothesis=_H0, run_id=run_id),
        _call(
            case_id,
            1,
            "coding",
            "describe_codes",
            error="arguments of describe_codes are not valid: kind: Input should be 'occurrence'",
            run_id=run_id,
        ),
        _call(
            case_id,
            2,
            "coding",
            "describe_codes",
            retry=True,
            error="arguments of describe_codes are not valid: kind: Input should be 'occurrence'",
            run_id=run_id,
        ),
    ]


_SCORES = CaseScores(
    occurrence_top1=False,
    occurrence_top3=True,
    event_match=False,
    pair_unseen=False,
    finding_precision_10=0.0,
    finding_recall_10=0.0,
    finding_precision_8=None,
    finding_recall_8=None,
    finding_precision_6=None,
    finding_recall_6=None,
    finding_precision_all_10=None,
    finding_recall_all_10=None,
    abstained=False,
    confidence=0.45,
)


def _step(case_id: str, hypothesis: Hypothesis, kind: str = "refine") -> StepRecord:
    return StepRecord(
        case_id=case_id,
        step=0,
        arm="C",
        condition="full",
        day=None,
        tool=f"checkpoint:{kind}",
        arguments={},
        reason="",
        expected_effect="",
        returned_roles=(),
        not_available=(),
        payload_fingerprint="x",
        hypothesis=hypothesis,
        observed_effect="",
        stop_reason="answered",
        model="m",
        price_variant="batch",
        prompt_tokens=0,
        completion_tokens=0,
        cost_usd=0.0,
        cumulative_cost_usd=0.0,
        commit_sha="fd6053f",
        dirty=False,
    )


def _checkpoints(case_id: str, final: Hypothesis) -> tuple[StepRecord, ...]:
    """The full trail's checkpoints, as the loop records them: H0, H1, H2, answer, refinement."""
    kinds = (("h0", _H0), ("h1", _H1), ("h2", _H2), ("answer", final), ("refine", final))
    return tuple(_step(case_id, hypothesis, kind) for kind, hypothesis in kinds)


def _result(case_id: str, *, final: Hypothesis | None, failure: str | None) -> CaseResult:
    _, _, verdict = split_record(_RAWS[case_id])
    return CaseResult(
        case_id=case_id,
        split="dev",
        fatal=case_id in _FATAL,
        investigation_class=case_id[5],
        report_flavour=None,
        verdict_occurrence=verdict.occurrence_codes,
        verdict_findings=verdict.finding_codes,
        verdict_findings_in_cause=verdict.finding_codes_in_cause,
        steps=() if final is None else _checkpoints(case_id, final),
        scores=None if final is None or failure is not None else _SCORES,
        cost_usd=0.0123,
        failure=failure,
    )


def _record(run_id: str, **changes: object) -> RunRecord:
    record = RunRecord(
        run_id=run_id,
        sample="dev-400",
        arm="C",
        evidence_version="v1",
        exclusions=(),
        includes=(),
        prompt_version="s3-v1",
        model="openai/gpt-6-luna",
        price_variant="batch",
        cap_usd=0.15,
        budget_usd=40.0,
        commit_sha="fd6053f",
        dirty=False,
        started=_WHEN,
        finished=_WHEN,
        cases=len(_IDS),
        cost_usd=0.5,
    )
    return record.model_copy(update=changes)


def _write_run(
    runs: Path,
    run_id: str,
    *,
    record: RunRecord | None = None,
    final: Hypothesis = _REFINED,
    cases: Sequence[CaseResult] | None = None,
) -> None:
    folder = runs / run_id
    shutil.rmtree(folder, ignore_errors=True)  # write_jsonl appends; a rewrite starts afresh
    write_jsonl(folder / "run.jsonl", [record or _record(run_id)])
    results, calls = [], []
    for case_id in _IDS:
        if case_id == _FAILED:
            results.append(_result(case_id, final=None, failure="failed: coding"))
            calls += _failed_trail(case_id, run_id)
        elif case_id == _NO_CALL:
            results.append(_result(case_id, final=None, failure="leak: docket_documents sentence"))
        else:
            results.append(_result(case_id, final=final, failure=None))
            calls += _full_trail(case_id, run_id)
    write_jsonl(folder / "cases.jsonl", results if cases is None else cases)
    write_jsonl(folder / "trail.jsonl", calls)


def _write_groups(
    path: Path,
    *,
    runs: Sequence[str] = (_RUN_A, _RUN_B),
    sample: str = "dev-400",
    split: str = "arm C",
    ids: Sequence[str] = _IDS,
) -> Path:
    data = {
        "sample": sample,
        "runs": [{"run_id": r, "arm": "C"} for r in runs],
        "groups": {split: {"always right": [], "always wrong": list(ids), "flipping": []}},
        "fatal": sorted(_FATAL),
    }
    path.write_text(json.dumps(data, indent=1) + "\n")
    return path


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run a and run b under ``<data>/runs``; the docket cache is ``<data>/docket``, empty."""
    data = tmp_path / "data"
    folder = data / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(data))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setenv("NTSB_DOCKET_DIR", str(data / "docket"))
    _write_run(folder, _RUN_A)
    _write_run(folder, _RUN_B, final=_OTHER)
    return folder


def _argv(groups: Path, *extra: str, fatal: int = 2, nonfatal: int = 2) -> list[str]:
    return [
        "--run",
        _RUN_A,
        "--groups",
        str(groups),
        "--group",
        "always_wrong",
        "--arm",
        "C",
        "--fatal",
        str(fatal),
        "--nonfatal",
        str(nonfatal),
        "--seed",
        "20261002",
        *extra,
    ]


def _main(
    argv: Sequence[str],
    *,
    when: datetime = _WHEN,
    docket: Callable[[int], Docket] | None = _docket,
    load: Callable[[Sequence[str]], list[dict[str, object]]] = _load,
) -> int:
    return tp.main(argv, now=lambda: when, load_raws=load, read_docket=docket)


def _page(runs: Path, groups: Path, *extra: str, fatal: int = 3, nonfatal: int = 6) -> str:
    """Every case of the group (3 fatal, 6 non-fatal), compared with run b; the HTML text."""
    assert _main(_argv(groups, "--compare", _RUN_B, *extra, fatal=fatal, nonfatal=nonfatal)) == 0
    return (runs / "s3-trail-pages" / _STAMP / "trails.html").read_text()


def _markdown(runs: Path) -> str:
    return (runs / "s3-trail-pages" / _STAMP / "trails.md").read_text()


def _case_section(page: str, case_id: str) -> str:
    """The page from a case's heading to the next case's heading (or the end)."""
    start = page.index(f": {case_id}</h2>")
    end = page.find("<h2", start)
    return page[start : end if end != -1 else len(page)]


def _chip(state: str, text: str) -> str:
    """A mark as the HTML page writes it (unescaped), before the text it marks."""
    return f'<span class="mk mk-{state}">{text}</span> '


_MATCH = _chip("match", "✓ match")
_NOT_NTSB = _chip("miss", "✗ not in the NTSB's")
_NOT_LOOP = _chip("miss", "✗ not in the loop's")


def _near(whose: str, rank: int) -> str:
    return _chip("near", f"↕ wrong place: the {whose}'s rank {rank}")


def _manifest(runs: Path, stamp: str = _STAMP) -> dict[str, object]:
    data = json.loads((runs / "s3-trail-pages" / stamp / "cases.json").read_text())
    assert isinstance(data, dict)
    return data


def _shown(page: str) -> list[str]:
    """The case ids the page shows, in page order."""
    return [
        i for _, i in sorted((page.index(f": {i}</h2>"), i) for i in _IDS if f": {i}</h2>" in page)
    ]


# --------------------------------------------------------------------------------------------
# The draw
# --------------------------------------------------------------------------------------------


class TestDraw:
    _FATALITY: Mapping[str, bool] = {i: i in _FATAL for i in _IDS}

    def test_the_same_seed_draws_the_same_cases_whatever_the_order_given(self) -> None:
        drawn = tp.draw(_IDS, self._FATALITY, per_fatal=2, per_nonfatal=3, seed=7)
        again = tp.draw(tuple(reversed(_IDS)), self._FATALITY, per_fatal=2, per_nonfatal=3, seed=7)
        assert drawn == again
        fatal, nonfatal = drawn
        assert len(fatal) == 2
        assert set(fatal) <= set(_FATAL)
        assert len(nonfatal) == 3
        assert set(nonfatal) <= set(_NONFATAL)
        assert list(fatal) == sorted(fatal)
        assert list(nonfatal) == sorted(nonfatal)

    def test_a_pool_smaller_than_asked_is_taken_whole(self) -> None:
        fatal, nonfatal = tp.draw(_IDS, self._FATALITY, per_fatal=10, per_nonfatal=0, seed=7)
        assert fatal == tuple(sorted(_FATAL))
        assert nonfatal == ()


# --------------------------------------------------------------------------------------------
# The page
# --------------------------------------------------------------------------------------------


class TestThePage:
    def test_writes_html_and_markdown_under_the_runs_folder_and_prints_the_relative_path(
        self, runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        before = {p for p in tmp_path.rglob("*") if p.is_file()}
        assert _main(_argv(groups)) == 0
        assert capsys.readouterr().out == f"s3-trail-pages/{_STAMP}\n"
        written = {p for p in tmp_path.rglob("*") if p.is_file()} - before
        folder = runs / "s3-trail-pages" / _STAMP
        assert written == {folder / "trails.html", folder / "trails.md", folder / "cases.json"}
        assert not folder.resolve().is_relative_to(tp.REPOSITORY)

    def test_nothing_is_written_inside_the_repository(
        self, runs: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        assert _main(_argv(groups)) == 0
        printed = capsys.readouterr().out.strip()
        assert not Path(printed).is_absolute()
        assert not (Path.cwd() / printed).exists()
        assert not tp.REPOSITORY.joinpath("s3-trail-pages").exists()

    def test_the_same_arguments_write_the_same_page(self, runs: Path, tmp_path: Path) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        assert _main(_argv(groups, "--compare", _RUN_B)) == 0
        later = datetime(2026, 10, 2, 13, 0, 0, tzinfo=UTC)
        assert _main(_argv(groups, "--compare", _RUN_B), when=later) == 0
        first, second = (
            runs / "s3-trail-pages" / _STAMP,
            runs / "s3-trail-pages" / "20261002T130000",
        )
        for name in ("trails.html", "trails.md", "cases.json"):
            assert (first / name).read_text() == (second / name).read_text()

    def test_the_page_is_self_contained_and_readable_light_or_dark(
        self, runs: Path, tmp_path: Path
    ) -> None:
        page = _page(runs, _write_groups(tmp_path / "groups.json"))
        assert page.startswith("<!doctype html>")
        assert "prefers-color-scheme: dark" in page
        for external in ("http://", "https://", "<script", "<link", "src="):
            assert external not in page

    def test_the_draw_picks_the_asked_number_of_fatal_and_non_fatal_cases(
        self, runs: Path, tmp_path: Path
    ) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        assert _main(_argv(groups, fatal=1, nonfatal=2)) == 0
        page = (runs / "s3-trail-pages" / _STAMP / "trails.html").read_text()
        shown = sorted((page.index(f": {i}</h2>"), i) for i in _IDS if f": {i}</h2>" in page)
        fatal, nonfatal = tp.draw(
            _IDS, {i: i in _FATAL for i in _IDS}, per_fatal=1, per_nonfatal=2, seed=20261002
        )
        assert [i for _, i in shown] == [*fatal, *nonfatal]  # fatal first, each slice sorted
        assert "1 fatal and 2 non-fatal" in page

    def test_the_case_header(self, runs: Path, tmp_path: Path) -> None:
        page = _page(runs, _write_groups(tmp_path / "groups.json"))
        section = _case_section(page, "ANC13FA004")
        assert "<b>Event date:</b> 2012-10-15" in section
        assert "<b>Injury:</b> fatal" in section
        assert "<b>Docket:</b> 3 listed; 2 offered (readable); 2 read" in section
        assert "[3] Pilot Operator Report 6120 (unreadable: scan)" in section
        nonfatal = _case_section(page, "ANC09CA024")
        assert "<b>Injury:</b> non-fatal" in nonfatal
        assert "occurrence top-1 wrong, top-3 right" in nonfatal

    def test_each_checkpoint_shows_its_codes_with_labels_and_the_agents_own_words(
        self, runs: Path, tmp_path: Path
    ) -> None:
        section = _case_section(_page(runs, _write_groups(tmp_path / "groups.json")), "ANC10LA044")
        assert "500240: Approach / Loss of control in flight (p 0.55)" in section
        assert "552241: Landing-Landing Roll / Aerodynamic stall/spin (p 0.25)" in section
        for tag in ("H1", "H2", "ANSWER"):
            assert f"NARRATIVE-{tag}" in section
            assert f"CAUSE-{tag}" in section
        assert "<b>Confidence:</b> 0.45; abstain: no" in section
        category = _TABLES.categories["010100"]
        assert html.escape(f"010100/01: {category} [Failure] (p 0.40)") in section

    def test_a_read_choice_names_each_document_its_decision_and_the_extras_answers(
        self, runs: Path, tmp_path: Path
    ) -> None:
        section = _case_section(_page(runs, _write_groups(tmp_path / "groups.json")), "ANC10LA044")
        assert "<b>Reason for the choice:</b> REASON-CHOICE-1" in section
        first = section.index("[2] Statement of")
        assert first < section.index("[1] Powerplant Examination Report (3 pages): skip")
        assert "(2 pages): read. Expected: EXPECT-READ-2" in section
        assert "Expected: EXPECT-SKIP-1" in section
        assert (
            "[3] asked to read; expected: EXPECT-EXTRA-3. "
            "Answered: Document [3] cannot be read; skipped."
        ) in section
        assert (
            "[9] asked to skip; expected: EXPECT-EXTRA-9. "
            "Answered: There is no document [9]; skipped."
        ) in section
        assert "Answered: Document [2] was already read; skipped." in section

    def test_each_coding_call_shows_its_labelled_arguments_and_the_rebuilt_tool_text(
        self, runs: Path, tmp_path: Path
    ) -> None:
        page = _page(runs, _write_groups(tmp_path / "groups.json"))
        section = _case_section(page, "ANC10LA044")
        markdown = _markdown(runs)
        for tool, arguments, _errors in _CODING:
            text = _rebuilt(tool, arguments)
            assert f"<pre>{html.escape(text)}</pre>" in section
            assert text in markdown
        assert "500240: Approach / Loss of control in flight" in section
        assert "999999: not in the code tables" in section
        assert html.escape(f"010100: {_TABLES.categories['010100']}") in section
        assert "phase group: Approach" in section
        assert "<b>Reason:</b> REASON-USAGE" in section
        assert "<b>Expected effect:</b> EFFECT-USAGE" in section
        assert "<b>Argument errors the tool counted:</b> 1" in section
        assert "rebuilt by re-running describe_codes on the recorded arguments" in section
        text = _rebuilt("past_findings", _CODING[4][1])
        assert f"({len(text)} characters; the trail recorded {len(text)} sent back" in section

    def test_protocol_errors_and_retries_are_shown_where_they_happened(
        self, runs: Path, tmp_path: Path
    ) -> None:
        section = _case_section(_page(runs, _write_groups(tmp_path / "groups.json")), "ANC10LA044")
        refused = section.index("<b>Not accepted:</b> occurrence probabilities sum to more than 1")
        retried = section.index("Call 4: hypothesis after the first read (H1), retry")
        assert refused < retried
        assert "not record_hypothesis" in section

    def test_the_final_answer_the_verdict_and_run_b(self, runs: Path, tmp_path: Path) -> None:
        section = _case_section(_page(runs, _write_groups(tmp_path / "groups.json")), "ANC10LA044")
        item = _TABLES.items["01010000"]
        answer = section[section.index("Final answer</h3>") :]
        assert html.escape(f"item 01010000 {item}") in answer
        _, _, verdict = split_record(_RAWS["ANC10LA044"])
        assert verdict.probable_cause
        assert html.escape(verdict.probable_cause) in section
        for code in verdict.occurrence_codes:
            label = f"{_TABLES.phases[code[:3]]} / {_TABLES.events[code[3:]]}"
            assert html.escape(f"{code}: {label}") in section
        for code in verdict.finding_codes:
            assert code in section
        cause = verdict.finding_codes_in_cause[0]
        assert html.escape(f"{cause}: {_TABLES.items[cause[:8]]}") in section
        assert "flagged as cause" in section
        assert f"<b>Run b ({_RUN_B}), final answer:</b> 552241" in section

    def test_a_case_that_failed_has_no_final_answer_and_run_b_says_so(
        self, runs: Path, tmp_path: Path
    ) -> None:
        section = _case_section(_page(runs, _write_groups(tmp_path / "groups.json")), _FAILED)
        assert "did not answer (failed: coding)" in section
        assert "None: the case did not answer in this run (failed: coding)." in section
        assert f"<b>Run b ({_RUN_B}), final answer:</b> none (failed: coding)" in section

    def test_a_case_with_no_model_call(self, runs: Path, tmp_path: Path) -> None:
        section = _case_section(_page(runs, _write_groups(tmp_path / "groups.json")), _NO_CALL)
        assert "No model call was made for this case in this run." in section
        assert "<b>Docket:</b> 3 listed; 2 offered (readable); 0 read" in section

    def test_owner_and_operator_names_the_record_holds_are_replaced(
        self, runs: Path, tmp_path: Path
    ) -> None:
        page = _page(runs, _write_groups(tmp_path / "groups.json"))
        section = _case_section(page, _NAMED)
        assert _OWNER not in page
        assert _OWNER not in _markdown(runs)
        assert "[2] Statement of Owner or operator (2 pages)" in section
        assert "NARRATIVE-H0 names Owner or operator" in section

    def test_the_markdown_copy_holds_the_same_trail(self, runs: Path, tmp_path: Path) -> None:
        _page(runs, _write_groups(tmp_path / "groups.json"))
        markdown = _markdown(runs)
        assert markdown.startswith("# ")
        assert "## Case 1 of 9: " in markdown
        assert "**Reason for the choice:** REASON-CHOICE-1" in markdown
        assert "**Not accepted:** occurrence probabilities sum to more than 1" in markdown
        assert (
            "1. [✗ not in the NTSB's] 500240: Approach / Loss of control in flight (p 0.55)"
            in markdown
        )
        assert f"**Run b ({_RUN_B}), final answer:** 552241" in markdown


# --------------------------------------------------------------------------------------------
# Differences at a glance
# --------------------------------------------------------------------------------------------


def _guesses(
    *codes: tuple[str, float], findings: Sequence[FindingGuess] = (), abstain: bool = False
) -> Hypothesis:
    return Hypothesis(
        evidence_narrative="n",
        occurrence=tuple(
            OccurrenceGuess(phase=code[:3], event=code[3:], probability=p) for code, p in codes
        ),
        findings=tuple(findings),
        probable_cause="p",
        lay_explanation="l",
        confidence=0.5,
        abstain=abstain,
        evidence_used=(),
    )


_GLANCE = "ZQX001"


def _glance_case(
    ntsb: tuple[str, ...],
    checkpoints: Mapping[str, Hypothesis],
    *,
    failure: str | None = None,
    flagged: tuple[str, ...] = (),
    others: tuple[str, ...] = (),
) -> CaseResult:
    """A case with the checkpoints given (``h0`` .. ``answer``, ``refine``), in that order."""
    steps = tuple(_step(_GLANCE, hypothesis, kind) for kind, hypothesis in checkpoints.items())
    scored = failure is None and bool(steps)
    return CaseResult(
        case_id=_GLANCE,
        split="dev",
        fatal=False,
        investigation_class="C",
        report_flavour=None,
        verdict_occurrence=ntsb,
        verdict_findings=(*flagged, *others),
        verdict_findings_in_cause=flagged,
        steps=steps,
        scores=_SCORES if scored else None,
        cost_usd=0.0,
        failure=failure,
    )


def _answered(
    ntsb: tuple[str, ...],
    answer: Hypothesis,
    *,
    flagged: tuple[str, ...] = (),
    others: tuple[str, ...] = (),
) -> CaseResult:
    """A case that answered: the answer is its H0, its answer and its refinement."""
    checkpoints = {"h0": answer, "answer": answer, "refine": answer}
    return _glance_case(ntsb, checkpoints, flagged=flagged, others=others)


def _glance(
    result: CaseResult,
    calls: Sequence[AgentCall] = (),
    *,
    tables: CodeTables = _TABLES,
    other: tp.Run | None = None,
) -> str:
    """The block as HTML, unescaped back to text so lines can be compared as written."""
    blocks = tp.glance_blocks(result, calls, tables=tables, stats=_STATS, other=other)
    return html.unescape(tp.render_html("glance", blocks))


def _label(code: str) -> str:
    return tp.occurrence_label(_TABLES, code)


def _coding(index: int, tool: str, *, error: str | None = None, **arguments: object) -> AgentCall:
    return _call(_GLANCE, index, "coding", tool, arguments=_why(tool, **arguments), error=error)


class TestGlanceDefiningEvent:
    @pytest.mark.parametrize(
        ("answer", "kind"),
        [
            (("552240", "552241"), "first code right"),
            (("552241", "552240"), "order"),
            (("552241",), "same phase, different event"),
            (("500240",), "same event, different phase"),
            (("500120",), "different phase and event"),
        ],
    )
    def test_each_kind_with_both_first_codes(self, answer: tuple[str, ...], kind: str) -> None:
        hypothesis = _guesses(*((code, 0.4) for code in answer))
        text = _glance(_answered(("552240",), hypothesis))
        assert "<h3>Differences at a glance</h3>" in text
        assert f"The NTSB's first code: 552240: {_label('552240')}" in text
        assert f"The loop's first code: {answer[0]}: {_label(answer[0])} (p 0.40)" in text
        assert f"Kind: {kind}<" in text

    def test_the_patterns_or_none(self) -> None:
        text = _glance(_answered(("552241",), _guesses(("500240", 0.6))))
        assert (
            "Patterns: NTSB stall/spin first, loop loss of control first; generic consequence"
            in text
        )
        assert "Patterns: none" in _glance(_answered(("552241",), _guesses(("500120", 0.6))))

    def test_an_abstained_answer_with_the_right_first_code(self) -> None:
        text = _glance(_answered(("552240",), _guesses(("552240", 0.6), abstain=True)))
        assert "Kind: first code right" in text
        assert "Patterns: abstained" in text

    def test_a_failed_case(self) -> None:
        result = _glance_case(("552240",), {"h0": _guesses(("500120", 0.5))}, failure="failed: h2")
        text = _glance(result)
        assert "The loop's first code: none; the case did not answer (failed: h2)" in text
        assert "Kind: failed or not scored" in text
        assert "Patterns: none" in text


class TestGlanceHowClose:
    _CODE = "552240"

    def _rows(self, text: str) -> str:
        start = text.index("How close the loop came")
        return text[start : text.index("The NTSB's occurrence codes", start)]

    def test_never_in_any_hypothesis(self) -> None:
        result = _glance_case(
            (self._CODE,),
            {
                "h0": _guesses(("500120", 0.5)),
                "h1": _guesses(("500241", 0.5)),
                "answer": _guesses(("500241", 0.5)),
                "refine": _guesses(("500241", 0.5)),
            },
        )
        rows = self._rows(_glance(result))
        assert f"How close the loop came to the NTSB's first code, {self._CODE}:" in rows
        assert f"<li>{_NOT_LOOP}H0: not among its codes</li>" in rows
        assert f"<li>{_NOT_LOOP}H1: not among its codes</li>" in rows
        assert "<li>H2: no such checkpoint in this case</li>" in rows  # no mark: nothing to mark
        assert f"<li>{_NOT_LOOP}Answer: not among its codes</li>" in rows
        assert "In short:</b> never in any hypothesis" in rows

    def test_held_then_dropped(self) -> None:
        held = _guesses(("500120", 0.5), (self._CODE, 0.3))
        result = _glance_case(
            (self._CODE,),
            {
                "h0": held,
                "h1": _guesses((self._CODE, 0.6)),
                "h2": _guesses(("500120", 0.7)),
                "answer": _guesses(("500120", 0.7)),
                "refine": _guesses(("500120", 0.7)),
            },
        )
        rows = self._rows(_glance(result))
        # The NTSB's first code appears at rank 2, moves to rank 1, then disappears.
        assert f"<li>{_near('loop', 2)}H0: rank 2 (p 0.30)</li>" in rows
        assert f"<li>{_MATCH}H1: rank 1 (p 0.60)</li>" in rows
        assert f"<li>{_NOT_LOOP}H2: not among its codes</li>" in rows
        assert "In short:</b> held at H0 and H1, then dropped" in rows

    def test_in_the_answer_at_its_rank(self) -> None:
        answer = _guesses(("500120", 0.5), ("500241", 0.2), (self._CODE, 0.1))
        rows = self._rows(_glance(_answered((self._CODE,), answer)))
        assert f"<li>{_near('loop', 3)}Answer: rank 3 (p 0.10)</li>" in rows
        assert "In short:</b> in the answer at rank 3" in rows

    def test_held_at_three_checkpoints_and_in_the_answer(self) -> None:
        answer = _guesses((self._CODE, 0.5))
        result = _glance_case(
            (self._CODE,),
            {"h0": answer, "h1": _guesses(("500120", 0.5)), "h2": answer, "answer": answer},
        )
        assert "In short:</b> in the answer at rank 1" in self._rows(_glance(result))

    def test_three_held_checkpoints_are_named_in_a_list(self) -> None:
        held = _guesses((self._CODE, 0.5))
        result = _glance_case(
            (self._CODE,),
            {"h0": held, "h1": held, "h2": held, "answer": _guesses(("500120", 0.5))},
        )
        assert "In short:</b> held at H0, H1 and H2, then dropped" in self._rows(_glance(result))

    def test_a_case_that_failed_after_holding_it(self) -> None:
        result = _glance_case(
            (self._CODE,), {"h0": _guesses((self._CODE, 0.5))}, failure="failed: h1"
        )
        rows = self._rows(_glance(result))
        assert "<li>Answer: no such checkpoint in this case</li>" in rows
        assert (
            "In short:</b> held at H0; the case reached no later checkpoint; the case failed, "
            "so nothing was scored"
        ) in rows

    def test_a_case_that_failed_after_its_answer(self) -> None:
        answer = _guesses((self._CODE, 0.5))
        result = _glance_case(
            (self._CODE,), {"h0": answer, "answer": answer}, failure="failed: coding"
        )
        assert (
            "In short:</b> in the answer at rank 1; the case failed, so nothing was scored"
        ) in self._rows(_glance(result))

    def test_a_case_with_no_checkpoint(self) -> None:
        result = _glance_case((self._CODE,), {}, failure="leak: docket_documents sentence")
        rows = self._rows(_glance(result))
        assert "In short:</b> no checkpoint: the case made no hypothesis" in rows

    def test_the_coding_calls_naming_it_and_the_tool_results_listing_it(self) -> None:
        # 509240 (Approach-VFR Go-Around / Loss of control in flight) is the first code
        # suggest_codes lists for the Approach phase group.
        code = "509240"
        calls = [
            _coding(7, "describe_codes", kind="occurrence", codes=[code]),
            _coding(8, "describe_codes", kind="finding_category", codes=["010100"]),
            _coding(9, "past_findings", occurrence=code),
            _coding(10, "suggest_codes", phase_group="Approach"),
            # Not accepted: the loop answered it with an error, so it is not counted.
            _coding(11, "occurrence_usage", error="not accepted", codes=[code]),
        ]
        text = _glance(_answered((code,), _guesses(("500120", 0.5))), calls)
        assert (
            "Coding calls naming it:</b> describe_codes (call 8); past_findings (call 10)" in text
        )
        assert (
            "Coding tool results listing it (rebuilt):</b> describe_codes (call 8); "
            "suggest_codes (call 11)"
        ) in text

    def test_no_coding_call_naming_it(self) -> None:
        text = _glance(_answered(("552240",), _guesses(("500120", 0.5))))
        assert "Coding calls naming it:</b> none" in text
        assert "Coding tool results listing it (rebuilt):</b> none" in text


class TestGlanceSequenceAndFindings:
    def test_the_ntsbs_sequence_marked_against_the_answer(self) -> None:
        answer = _guesses(("552241", 0.5), ("552240", 0.3))
        text = _glance(_answered(("552240", "552241", "500120"), answer))
        assert "The NTSB's occurrence codes, in its order, against the loop's answer:" in text
        assert (
            f"<li>{_near('loop', 2)}552240: {_label('552240')}: in the answer at rank 2</li>"
            in text
        )
        assert (
            f"<li>{_near('loop', 1)}552241: {_label('552241')}: in the answer at rank 1</li>"
            in text
        )
        assert f"<li>{_NOT_LOOP}500120: {_label('500120')}: not in the answer</li>" in text

    def test_an_ntsb_code_at_the_answers_same_rank_is_a_match(self) -> None:
        answer = _guesses(("552240", 0.5), ("500120", 0.3))
        text = _glance(_answered(("552240", "552241"), answer))
        assert f"<li>{_MATCH}552240: {_label('552240')}: in the answer at rank 1</li>" in text
        assert f"<li>{_NOT_LOOP}552241: {_label('552241')}: not in the answer</li>" in text
        assert f"<li>{_MATCH}The loop's first code: 552240: {_label('552240')} (p 0.50)" in text

    def test_the_sequence_of_a_case_with_no_answer(self) -> None:
        text = _glance(_glance_case(("552240",), {}, failure="failed: h0"))
        assert f"<li>552240: {_label('552240')}: no answer to compare</li>" in text

    def test_each_flagged_finding_at_its_level_and_the_loops_unmatched_findings(self) -> None:
        exact, item, category, missed = "0106201220", "0206304044", "0204152044", "0202202544"
        findings = (
            FindingGuess(category6="010620", modifier="20", probability=0.5, item8="01062012"),
            FindingGuess(category6="020630", modifier="45", probability=0.4, item8="02063040"),
            FindingGuess(category6="020415", modifier="44", probability=0.3, item8="02041510"),
            FindingGuess(category6="010100", modifier="01", probability=0.2, item8="01010000"),
            # Matches only a finding the NTSB lists without flagging it: not unmatched.
            FindingGuess(category6="030340", modifier="91", probability=0.1),
        )
        result = _answered(
            ("552240",),
            _guesses(("500120", 0.5), findings=findings),
            flagged=(exact, item, category, missed),
            others=("0303404091",),
        )
        text = _glance(result)
        verdict = {
            c: f"{c}: {_TABLES.items[c[:8]]} [{_TABLES.modifiers[c[8:]]}]"
            for c in (exact, item, category, missed)
        }
        assert f"<li>{_chip('match', '✓ exact')}{verdict[exact]}: exact (item and modifier)" in text
        assert (
            f"<li>{_chip('near', '≈ partial: item only')}{verdict[item]}: item only; the loop's "
            "modifier 45 [Pilot of other aircraft]"
        ) in text
        item_label = _TABLES.items["02041510"]
        assert (
            f"<li>{_chip('near', '≈ partial: category only')}{verdict[category]}: category only; "
            f"the loop's item 02041510 {item_label}"
        ) in text
        assert f"<li>{_chip('miss', '✗ missed')}{verdict[missed]}: missed</li>" in text
        unmatched = text[text.index("The loop's findings that match no NTSB finding") :]
        assert f"<li>{_chip('miss', '✗ matches no NTSB finding')}010100/01" in unmatched
        assert "030340" not in unmatched
        assert "010620" not in unmatched

    def test_a_category_match_with_no_item(self) -> None:
        findings = (FindingGuess(category6="020415", modifier="44", probability=0.3),)
        result = _answered(
            ("552240",), _guesses(("500120", 0.5), findings=findings), flagged=("0204152044",)
        )
        assert "category only; the loop named no item" in _glance(result)

    def test_no_flagged_finding_and_no_unmatched_finding(self) -> None:
        text = _glance(_answered(("552240",), _guesses(("500120", 0.5))))
        flagged = text[text.index("Findings flagged as cause") :]
        assert "<li>none flagged</li>" in flagged
        unmatched = text[text.index("The loop's findings that match no NTSB finding") :]
        assert "<li>none</li>" in unmatched

    def test_the_findings_of_a_case_with_no_answer(self) -> None:
        result = _glance_case(("552240",), {}, failure="failed: h0", flagged=("0204152044",))
        text = _glance(result)
        assert "<li>not compared: the case did not answer</li>" in text


class TestGlanceRunB:
    def _other(self, result: CaseResult | None) -> tp.Run:
        return tp.Run(_RUN_B, {} if result is None else {_GLANCE: result}, {})

    def test_its_first_code_and_kind(self) -> None:
        other = self._other(_answered(("552240",), _guesses(("552241", 0.55))))
        text = _glance(_answered(("552240",), _guesses(("500120", 0.5))), other=other)
        assert (
            f"Run b ({_RUN_B}), defining event:</b> {_NOT_NTSB}first code 552241: "
            f"{_label('552241')} (p 0.55); kind: same phase, different event"
        ) in text

    def test_its_first_code_is_marked_against_run_as_ntsb_sequence(self) -> None:
        other = self._other(_answered(("552240", "552241"), _guesses(("552241", 0.55))))
        result = _answered(("552240", "552241"), _guesses(("500120", 0.5)))
        assert f"defining event:</b> {_near('NTSB', 2)}first code 552241" in _glance(
            result, other=other
        )

    def test_a_failed_case_in_run_b(self) -> None:
        other = self._other(_glance_case(("552240",), {}, failure="failed: coding"))
        text = _glance(_answered(("552240",), _guesses(("500120", 0.5))), other=other)
        assert "defining event:</b> no answer (failed: coding); kind: failed or not scored" in text

    def test_run_b_without_the_case(self) -> None:
        text = _glance(_answered(("552240",), _guesses(("500120", 0.5))), other=self._other(None))
        assert "defining event:</b> the run holds no such case" in text

    def test_no_run_b_line_without_compare(self) -> None:
        assert "Run b" not in _glance(_answered(("552240",), _guesses(("500120", 0.5))))


class TestGlanceEscaping:
    def test_every_label_is_escaped(self) -> None:
        events = {**_TABLES.events, "240": "Loss <of> control & more"}
        tables = dataclasses.replace(_TABLES, events=events)
        blocks = tp.glance_blocks(
            _answered(("552240",), _guesses(("500240", 0.5))),
            (),
            tables=tables,
            stats=_STATS,
            other=None,
        )
        page = tp.render_html("glance", blocks)
        assert "Loss &lt;of&gt; control &amp; more" in page
        assert "<of>" not in page
        assert "Loss <of> control & more" in tp.render_markdown(blocks)


class TestSummary:
    def test_counts_each_kind_and_pattern_among_the_cases_shown(self) -> None:
        results = [
            _answered(("552240",), _guesses(("552241", 0.5))),
            _answered(("552241",), _guesses(("552240", 0.5))),
            _answered(("552240",), _guesses(("552240", 0.5), abstain=True)),
            _glance_case(("552240",), {}, failure="failed: h0"),
        ]
        blocks = tp.summary_blocks(results)
        text = html.unescape(tp.render_html("summary", blocks))
        assert "Kinds among the 4 cases shown, run a (counts only):" in text
        assert "<li>same phase, different event: 2</li>" in text
        assert "<li>first code right: 1</li>" in text
        assert "<li>failed or not scored: 1</li>" in text
        assert "<li>order: 0</li>" in text
        assert "<li>NTSB stall/spin first, loop loss of control first: 1</li>" in text
        assert "<li>NTSB loss of control first, loop stall/spin first: 1</li>" in text
        assert "<li>generic consequence: 1</li>" in text
        assert "<li>abstained: 1</li>" in text
        assert "<li>NTSB cause undetermined: 0</li>" in text


class TestGlanceOnThePage:
    def test_the_block_opens_each_case_after_its_header_and_before_its_trail(
        self, runs: Path, tmp_path: Path
    ) -> None:
        page = html.unescape(_page(runs, _write_groups(tmp_path / "groups.json")))
        section = _case_section(page, "ANC10LA044")
        header = section.index("<b>This run:</b>")
        glance = section.index("<h3>Differences at a glance</h3>")
        trail = section.index("<h3>Trail, in call order</h3>")
        assert header < glance < trail
        block = section[glance:trail]
        assert f"The NTSB's first code: 551230: {_label('551230')}" in block
        assert f"The loop's first code: 500240: {_label('500240')} (p 0.55)" in block
        assert "Kind: different phase and event" in block
        assert "Patterns: generic consequence" in block
        assert "In short:</b> never in any hypothesis" in block
        # The trail's describe_codes call names 500240, not the NTSB's code.
        assert "Coding calls naming it:</b> none" in block
        assert (
            f"Run b ({_RUN_B}), defining event:</b> {_NOT_NTSB}first code 552241: "
            f"{_label('552241')} (p 0.55); kind: different phase and event"
        ) in block

    def test_the_page_opens_with_the_counts_of_the_cases_shown(
        self, runs: Path, tmp_path: Path
    ) -> None:
        page = html.unescape(_page(runs, _write_groups(tmp_path / "groups.json")))
        top = page[: page.index("<h2")]
        assert "Kinds among the 9 cases shown, run a (counts only):" in top
        assert "<li>different phase and event: 7</li>" in top
        assert "<li>failed or not scored: 2</li>" in top
        assert "<li>generic consequence: 7</li>" in top
        assert "<li>NTSB cause undetermined: 2</li>" in top

    def test_the_markdown_copy_holds_the_block(self, runs: Path, tmp_path: Path) -> None:
        _page(runs, _write_groups(tmp_path / "groups.json"))
        markdown = _markdown(runs)
        assert "### Differences at a glance" in markdown
        assert "**In short:** never in any hypothesis" in markdown


# --------------------------------------------------------------------------------------------
# Marks: a colour and words for each code's match state
# --------------------------------------------------------------------------------------------


class TestOccurrenceMark:
    _NTSB = ("552240", "552241", "500120")

    @pytest.mark.parametrize(
        ("code", "rank", "state", "text"),
        [
            ("552240", 1, "match", "✓ match"),
            ("552241", 2, "match", "✓ match"),
            ("500120", 3, "match", "✓ match"),
            ("552241", 1, "near", "↕ wrong place: the NTSB's rank 2"),
            ("552240", 3, "near", "↕ wrong place: the NTSB's rank 1"),
            ("500120", 5, "near", "↕ wrong place: the NTSB's rank 3"),  # beyond the NTSB's list
            ("500240", 1, "miss", "✗ not in the NTSB's"),
            ("500240", 4, "miss", "✗ not in the NTSB's"),
        ],
    )
    def test_the_state_at_each_rank(self, code: str, rank: int, state: str, text: str) -> None:
        assert tp.occurrence_mark(code, rank, self._NTSB, whose="the NTSB's") == tp.Mark(
            cast(tp.State, state), text
        )

    def test_the_other_way_round_names_the_loops_rank(self) -> None:
        mark = tp.occurrence_mark("552240", 1, ("500120", "552240"), whose="the loop's")
        assert mark == tp.Mark("near", "↕ wrong place: the loop's rank 2")
        assert tp.occurrence_mark("552241", 2, ("500120",), whose="the loop's") == tp.Mark(
            "miss", "✗ not in the loop's"
        )


class TestFindingMark:
    _FLAGGED = "0106201220"
    _LISTED = ("0106201220", "0206304044", "0206301099")
    _IN_CAUSE = frozenset({"0106201220", "0206301099"})

    @pytest.mark.parametrize(
        ("guess", "state", "text"),
        [
            (("010620", "20", "01062012"), "match", "✓ exact (cause)"),
            (("020630", "44", "02063040"), "match", "✓ exact"),
            (("010620", "45", "01062012"), "near", "≈ partial: item only (cause)"),
            (("010620", "20", None), "near", "≈ partial: category only (cause)"),
            # The deepest level wins: item only (not flagged) over category only (flagged).
            (("020630", "01", "02063040"), "near", "≈ partial: item only"),
            (("030340", "91", "03034040"), "miss", "✗ matches no NTSB finding"),
        ],
    )
    def test_the_deepest_level_against_any_ntsb_finding(
        self, guess: tuple[str, str, str | None], state: str, text: str
    ) -> None:
        category, modifier, item = guess
        finding = FindingGuess(category6=category, modifier=modifier, probability=0.3, item8=item)
        assert tp.finding_mark(finding, self._LISTED, self._IN_CAUSE) == tp.Mark(
            cast(tp.State, state), text
        )


def _marked_case() -> list[CaseResult]:
    """Run a's cases; ANC10LA044's NTSB sequence holds the loop's 500240 at rank 1 and its
    552241 at rank 3, and its one finding, flagged, is the refined answer's exactly."""
    cases = [_result(i, final=_REFINED, failure=None) for i in _IDS]
    at = _IDS.index("ANC10LA044")
    cases[at] = cases[at].model_copy(
        update={
            "verdict_occurrence": ("500240", "500120", "552241"),
            "verdict_findings": ("0101000001",),
            "verdict_findings_in_cause": ("0101000001",),
        }
    )
    return cases


class TestMarksOnThePage:
    @pytest.fixture
    def section(self, runs: Path, tmp_path: Path) -> str:
        _write_run(runs, _RUN_A, cases=_marked_case())
        page = html.unescape(_page(runs, _write_groups(tmp_path / "groups.json")))
        return _case_section(page, "ANC10LA044")

    @staticmethod
    def _between(section: str, start: str, end: str) -> str:
        at = section.index(start)
        return section[at : section.index(end, at)]

    _CODES = (
        f"{_MATCH}500240: Approach / Loss of control in flight (p 0.55)",
        f"{_near('NTSB', 3)}552241: Landing-Landing Roll / Aerodynamic stall/spin (p 0.25)",
    )

    @pytest.mark.parametrize(
        ("start", "end"),
        [
            ("Call 1: first hypothesis (H0)", "Call 2:"),
            ("Call 4: hypothesis after the first read (H1), retry", "Call 5:"),
            ("Call 6: hypothesis after the second look (H2)", "Call 7:"),
            ("Call 14: coding step, retry — submit_answer", "Call 15:"),
            ("Final answer</h3>", "The NTSB's verdict"),
        ],
    )
    def test_every_checkpoint_marks_each_occurrence_code(
        self, section: str, start: str, end: str
    ) -> None:
        part = self._between(section, start, end)
        for line in self._CODES:
            assert line in part

    def test_the_loops_findings_are_marked_at_each_checkpoint(self, section: str) -> None:
        answer = self._between(section, "Call 14:", "Call 15:")
        assert f"{_chip('near', '≈ partial: category only (cause)')}010100/01: " in answer
        refine = self._between(section, "Call 15:", "Final answer</h3>")
        assert f"{_chip('match', '✓ exact (cause)')}010100/01: " in refine
        final = self._between(section, "Final answer</h3>", "The NTSB's verdict")
        assert f"{_chip('match', '✓ exact (cause)')}010100/01: " in final

    def test_the_glance_marks_the_loops_code_at_every_checkpoint(self, section: str) -> None:
        glance = self._between(section, "Differences at a glance", "Trail, in call order")
        assert f"<li>{_MATCH}The loop's first code: 500240" in glance
        for name in ("H0", "H1", "H2", "Answer"):
            assert f"<li>{_MATCH}{name}: rank 1 (p 0.55)</li>" in glance
        assert f"<li>{_MATCH}500240: {_label('500240')}: in the answer at rank 1</li>" in glance
        assert f"<li>{_NOT_LOOP}500120: {_label('500120')}: not in the answer</li>" in glance
        assert (
            f"<li>{_near('loop', 2)}552241: {_label('552241')}: in the answer at rank 2</li>"
            in glance
        )
        assert f"<li>{_chip('match', '✓ exact')}0101000001: " in glance
        # Run b's first code, 552241, against run a's NTSB sequence.
        assert f"defining event:</b> {_near('NTSB', 3)}first code 552241" in glance

    def test_the_ntsbs_verdict_and_the_coding_arguments_carry_no_mark(self, section: str) -> None:
        verdict = section[section.index("The NTSB's verdict") :]
        assert 'class="mk' not in verdict.split("Run b (")[0]
        arguments = self._between(section, "Call 10:", "Call 11:")  # occurrence_usage
        assert 'class="mk' not in arguments

    def test_the_markdown_copy_carries_the_words_only(self, runs: Path, tmp_path: Path) -> None:
        _write_run(runs, _RUN_A, cases=_marked_case())
        _page(runs, _write_groups(tmp_path / "groups.json"))
        markdown = _markdown(runs)
        assert "1. [✓ match] 500240: Approach / Loss of control in flight (p 0.55)" in markdown
        assert "2. [↕ wrong place: the NTSB's rank 3] 552241: " in markdown
        assert "- [✓ exact (cause)] 010100/01: " in markdown
        assert "<span" not in markdown
        assert "mk-" not in markdown


def _style(page: str) -> str:
    return page[page.index("<style>") + len("<style>") : page.index("</style>")]


def _tokens(block: str) -> dict[str, str]:
    return dict(re.findall(r"--([a-z-]+):([^;}]+)", block))


class TestLegendAndTheme:
    _CHIPS = ("match", "near", "miss")

    def test_a_legend_at_the_top_names_each_state_in_words(
        self, runs: Path, tmp_path: Path
    ) -> None:
        page = html.unescape(_page(runs, _write_groups(tmp_path / "groups.json")))
        top = page[: page.index("<h2")]
        assert "Marks: green, amber and red, each with words that read without colour:" in top
        assert _chip("match", "✓ match") in top
        assert _chip("near", "↕ wrong place / ≈ partial") in top
        assert _chip("miss", "✗ no match") in top
        assert "(cause) after a finding's mark" in top
        assert "a green mark below rank 1 means the same code at the same rank" in top
        markdown = _markdown(runs)
        top_md = markdown[: markdown.index("\n## ")]
        for words in ("[✓ match] ", "[↕ wrong place / ≈ partial] ", "[✗ no match] "):
            assert words in top_md

    def test_every_colour_is_a_token_on_bare_root_and_redefined_for_dark_twice(
        self, runs: Path, tmp_path: Path
    ) -> None:
        style = _style(_page(runs, _write_groups(tmp_path / "groups.json")))
        bare = re.search(r"(?m)^:root\{([^}]*)\}", style)
        media = re.search(
            r'@media \(prefers-color-scheme: dark\)\{:root:not\(\[data-theme="light"\]\)'
            r"\{([^}]*)\}\}",
            style,
        )
        theme = re.search(r':root\[data-theme="dark"\]\{([^}]*)\}', style)
        assert bare is not None
        assert media is not None
        assert theme is not None
        light, dark, dark_again = (_tokens(m.group(1)) for m in (bare, media, theme))
        assert dark == dark_again
        assert set(dark) == set(light)  # every token on bare :root, every one redefined for dark
        for state in self._CHIPS:
            assert {f"{state}-bg", f"{state}-fg"} <= set(light)
            assert light[f"{state}-bg"] != dark[f"{state}-bg"]
            assert f".mk-{state}{{background:var(--{state}-bg);color:var(--{state}-fg)}}" in style
        assert set(re.findall(r"var\(--([a-z-]+)\)", style)) <= set(light)
        # No token is defined anywhere but in those three blocks.
        assert len(re.findall(r"--[a-z-]+:", style)) == 3 * len(light)
        # Every rule outside them takes its colours from the tokens: no colour written in place.
        rest = style
        for block in (bare, media, theme):
            rest = rest.replace(block.group(0), "")
        assert re.search(r"#[0-9a-fA-F]{3,8}\b", rest) is None


# --------------------------------------------------------------------------------------------
# The selection: a pattern, a spread, exclusions, and the manifest
# --------------------------------------------------------------------------------------------


class TestSpread:
    # Event 100 is the largest group (two fatal, one not), then 200 (two non-fatal), then the
    # single cases of 300 (fatal) and 400 (non-fatal).
    _EVENTS: Mapping[str, str] = {
        "F1": "100",
        "F2": "100",
        "N1": "100",
        "N2": "200",
        "N3": "200",
        "F3": "300",
        "N4": "400",
    }
    _FATALITY: Mapping[str, bool] = {i: i.startswith("F") for i in _EVENTS}

    def _spread(
        self, ids: Sequence[str], fatal: int, nonfatal: int, seed: int = 7
    ) -> tuple[tuple[str, ...], tuple[str, ...]]:
        return tp.spread(
            ids, self._FATALITY, self._EVENTS, per_fatal=fatal, per_nonfatal=nonfatal, seed=seed
        )

    def test_one_case_per_event_largest_first_fatal_and_non_fatal_in_turn(self) -> None:
        fatal, nonfatal = self._spread(tuple(self._EVENTS), 2, 2)
        # 100 gives a fatal case, 200 a non-fatal one, 300 its fatal one, 400 its non-fatal one;
        # each group's first case is the front of its list as the group's own generator shuffled
        # it ("<seed>:<event>"), fatal list first.
        first = random.Random("7:100")  # noqa: S311 -- the documented sampling, not security
        queue = ["F1", "F2"]
        first.shuffle(queue)
        second = random.Random("7:200")  # noqa: S311 -- likewise
        empty: list[str] = []
        second.shuffle(empty)  # 200 holds no fatal case: its generator shuffles an empty list
        other = ["N2", "N3"]
        second.shuffle(other)
        assert fatal == tuple(sorted((queue[0], "F3")))
        assert nonfatal == tuple(sorted((other[0], "N4")))
        assert len({self._EVENTS[i] for i in (*fatal, *nonfatal)}) == 4

    def test_the_same_seed_gives_the_same_cases_whatever_the_order_given(self) -> None:
        ids = tuple(self._EVENTS)
        assert self._spread(ids, 2, 3) == self._spread(tuple(reversed(ids)), 2, 3)
        picks = {self._spread(ids, 1, 1, seed=s) for s in range(40)}
        assert len(picks) > 1  # the seed decides within a group

    def test_the_turn_passes_between_fatal_and_non_fatal(self) -> None:
        # Three events of one fatal and one non-fatal case each. In turn: 100 fatal, 200
        # non-fatal, 300 fatal; then a second round, 100 non-fatal. Always fatal first would
        # take the fatal cases of 100 and 200 instead.
        events = {"FA": "100", "NA": "100", "FB": "200", "NB": "200", "FC": "300", "NC": "300"}
        fatality = {i: i.startswith("F") for i in events}
        assert tp.spread(tuple(events), fatality, events, per_fatal=2, per_nonfatal=2, seed=7) == (
            ("FA", "FC"),
            ("NA", "NB"),
        )

    def test_the_largest_group_first_then_by_event_code(self) -> None:
        events = {"N1": "900", "N2": "900", "N3": "900", "N4": "300", "N5": "200"}
        fatality = dict.fromkeys(events, False)
        _, one = tp.spread(tuple(events), fatality, events, per_fatal=0, per_nonfatal=1, seed=7)
        assert set(one) <= {"N1", "N2", "N3"}  # 900 holds the most, though its code is last
        _, three = tp.spread(tuple(events), fatality, events, per_fatal=0, per_nonfatal=2, seed=7)
        assert "N5" in three  # 200 before 300: equal groups go by event code
        assert "N4" not in three

    def test_a_group_without_the_kind_wanted_gives_the_other(self) -> None:
        # 200 is the largest group here and holds no fatal case: it gives a non-fatal one, and
        # the fatal turn passes to 100.
        fatal, nonfatal = self._spread(("N2", "N3", "F1"), 1, 1)
        assert fatal == ("F1",)
        assert len(nonfatal) == 1
        assert set(nonfatal) <= {"N2", "N3"}

    def test_a_second_round_when_the_events_run_out(self) -> None:
        fatal, nonfatal = self._spread(("F1", "F2", "N1", "F3"), 3, 1)
        assert fatal == ("F1", "F2", "F3")
        assert nonfatal == ("N1",)

    def test_a_kind_not_asked_for_is_never_taken(self) -> None:
        fatal, nonfatal = self._spread(tuple(self._EVENTS), 0, 2)
        assert fatal == ()
        assert {self._EVENTS[i] for i in nonfatal} == {"100", "200"}

    def test_a_pool_smaller_than_asked_is_taken_whole(self) -> None:
        fatal, nonfatal = self._spread(tuple(self._EVENTS), 10, 10)
        assert fatal == ("F1", "F2", "F3")
        assert nonfatal == ("N1", "N2", "N3", "N4")


class TestSelection:
    def test_every_pattern_of_the_classifier_has_its_option(self) -> None:
        assert sorted(tp.PATTERN_OPTIONS.values()) == sorted(PATTERNS)
        assert tp.PATTERN_OPTIONS["generic_consequence"] == "generic consequence"
        assert tp.PATTERN_OPTIONS["ntsb_cause_undetermined"] == "NTSB cause undetermined"

    def test_the_default_selection_is_stated(self, runs: Path, tmp_path: Path) -> None:
        page = html.unescape(_page(runs, _write_groups(tmp_path / "groups.json")))
        top = page[: page.index("<h2")]
        assert "arm C, always wrong, from groups.json: 9 cases (3 fatal, 6 non-fatal)." in top
        assert "<li>Excluded: none</li>" in top
        assert "<li>Pattern: none asked</li>" in top
        assert "<li>Eligible: 9 cases (3 fatal, 6 non-fatal)</li>" in top
        assert (
            "<li>Shown: 3 fatal and 6 non-fatal, drawn with seed 20261002 from the sorted "
            "eligible ids</li>"
        ) in top

    def test_a_pattern_keeps_only_the_cases_run_a_shows_it_in(
        self, runs: Path, tmp_path: Path
    ) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        page = html.unescape(_page(runs, groups, "--pattern", "ntsb_cause_undetermined"))
        # 0500000000 is flagged as cause in these two records, and the loop did not abstain.
        assert _shown(page) == ["ANC10MA068", "ANC13FA004"]
        top = page[: page.index("<h2")]
        assert (
            "<li>Pattern: NTSB cause undetermined (--pattern ntsb_cause_undetermined), in run a: "
            "0500000000 is flagged as cause"
        ) in top
        assert "<li>Eligible: 2 cases (2 fatal, 0 non-fatal)</li>" in top
        assert _manifest(runs)["pattern"] == "ntsb_cause_undetermined"

    def test_a_spread_by_the_ntsbs_first_event(self, runs: Path, tmp_path: Path) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        extra = ("--pattern", "generic_consequence", "--spread-by", "ntsb_first_event")
        page = html.unescape(_page(runs, groups, *extra, fatal=2, nonfatal=2))
        # Seven cases show the pattern; their first events: 230 twice (both non-fatal), then 000
        # and 120 (fatal), 200, 402 and 490 (non-fatal) once each. Visited largest first:
        # 230 gives a non-fatal case, 000 a fatal one, 120 the other fatal one, 200 a non-fatal.
        shown = _shown(page)
        assert shown[:2] == ["ANC10MA068", "ANC13FA004"]
        assert "CEN11CA664" in shown[2:]
        assert len(set(shown[2:]) & {"ANC09CA024", "ANC10LA044"}) == 1
        assert len(shown) == 4
        top = page[: page.index("<h2")]
        assert "<li>Eligible: 7 cases (2 fatal, 5 non-fatal)</li>" in top
        assert "<li>Shown: 2 fatal and 2 non-fatal, spread by the NTSB's first event" in top
        events = top[top.index("The NTSB's first events among the eligible cases") :]
        label = _TABLES.events["230"]
        assert f"<li>230: {label}: 2 eligible (0 fatal, 2 non-fatal), 1 shown</li>" in events
        assert events.index("230: ") < events.index("000: ") < events.index("120: ")
        assert f"<li>402: {_TABLES.events['402']}: 1 eligible (0 fatal, 1 non-fatal), 0 shown" in (
            events
        )
        data = _manifest(runs)
        assert data["spread_by"] == "ntsb_first_event"
        assert data["eligible"] == 7

    def test_cases_shown_on_an_earlier_page_are_left_out(self, runs: Path, tmp_path: Path) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        assert _main(_argv(groups, fatal=1, nonfatal=2)) == 0
        first = runs / "s3-trail-pages" / _STAMP
        earlier = set(cast(list[str], _manifest(runs)["cases"]))
        later = datetime(2026, 10, 2, 13, 0, 0, tzinfo=UTC)
        argv = _argv(groups, "--exclude-from", str(first), fatal=3, nonfatal=6)
        assert _main(argv, when=later) == 0
        page = html.unescape(
            (runs / "s3-trail-pages" / "20261002T130000" / "trails.html").read_text()
        )
        shown = set(_shown(page))
        assert len(earlier) == 3
        assert not shown & earlier
        assert shown == set(_IDS) - earlier
        top = page[: page.index("<h2")]
        assert (
            f"<li>Excluded: 3 of the group's cases, shown on earlier pages ({_STAMP}/cases.json)"
            "</li>"
        ) in top
        assert "<li>Eligible: 6 cases (2 fatal, 4 non-fatal)</li>" in top
        data = _manifest(runs, "20261002T130000")
        assert data["exclude_from"] == [str((first / "cases.json").resolve())]
        assert data["excluded"] == 3

    def test_exclusions_repeat_and_take_a_manifest_file(self, runs: Path, tmp_path: Path) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        manifests = []
        for n, ids in enumerate((("ANC10MA068",), ("ANC09CA020", "ZQX999"))):
            path = tmp_path / f"m{n}.json"
            path.write_text(json.dumps({"manifest": "s3_trail_pages", "cases": list(ids)}))
            manifests += ["--exclude-from", str(path)]
        page = html.unescape(_page(runs, groups, *manifests))
        assert set(_shown(page)) == set(_IDS) - {"ANC10MA068", "ANC09CA020"}
        assert "<li>Excluded: 2 of the group's cases" in page

    def test_the_manifest_names_the_cases_and_how_they_were_chosen(
        self, runs: Path, tmp_path: Path
    ) -> None:
        groups = _write_groups(tmp_path / "groups.json")
        page = html.unescape(_page(runs, groups))
        assert _manifest(runs) == {
            "manifest": "s3_trail_pages",
            "sample": "dev-400",
            "run": _RUN_A,
            "compare": _RUN_B,
            "groups": str(groups.resolve()),
            "split": "arm C",
            "group": "always wrong",
            "seed": 20261002,
            "fatal_asked": 3,
            "nonfatal_asked": 6,
            "exclude_from": [],
            "excluded": 0,
            "pattern": None,
            "spread_by": None,
            "group_cases": 9,
            "eligible": 9,
            "cases": _shown(page),
        }


class TestSelectionRefusals:
    @pytest.fixture
    def groups(self, runs: Path, tmp_path: Path) -> Path:
        return _write_groups(tmp_path / "groups.json")

    def test_an_unknown_pattern_or_spread_is_a_usage_error(self, groups: Path) -> None:
        for extra in (("--pattern", "generic consequence"), ("--spread-by", "phase")):
            with pytest.raises(SystemExit) as raised:
                _main(_argv(groups, *extra))
            assert raised.value.code == 2

    def test_no_eligible_case_is_refused(self, groups: Path) -> None:
        with pytest.raises(SystemExit, match="no case of the group is eligible"):
            _main(_argv(groups, "--pattern", "abstained"))

    def test_a_folder_with_no_manifest_is_refused(self, groups: Path, tmp_path: Path) -> None:
        with pytest.raises(SystemExit, match="no page manifest"):
            _main(_argv(groups, "--exclude-from", str(tmp_path)))

    @pytest.mark.parametrize(
        ("text", "match"),
        [
            ("{not json", "is not JSON"),
            ('{"cases": ["ANC10MA068"]}', "not a trail page manifest"),
            ('{"manifest": "s3_trail_pages", "cases": [1]}', "not a trail page manifest"),
            ('["ANC10MA068"]', "not a trail page manifest"),
        ],
    )
    def test_a_file_that_is_not_a_page_manifest_is_refused(
        self, groups: Path, tmp_path: Path, text: str, match: str
    ) -> None:
        path = tmp_path / "other.json"
        path.write_text(text)
        with pytest.raises(SystemExit, match=match):
            _main(_argv(groups, "--exclude-from", str(path)))

    @pytest.mark.parametrize(
        "extra", [("--pattern", "generic_consequence"), ("--spread-by", "ntsb_first_event")]
    )
    def test_a_case_with_no_ntsb_code_is_refused_when_selecting_by_it(
        self, runs: Path, groups: Path, extra: tuple[str, str]
    ) -> None:
        cases = [_result(i, final=_REFINED, failure=None) for i in _IDS]
        cases[0] = cases[0].model_copy(update={"verdict_occurrence": ()})
        _write_run(runs, _RUN_A, cases=cases)
        with pytest.raises(SystemExit, match="no pattern or first event to select by"):
            _main(_argv(groups, *extra))


class TestRebuiltToolText:
    @pytest.mark.parametrize(("tool", "arguments", "errors"), _CODING)
    def test_equals_what_the_tool_returns_for_the_recorded_arguments(
        self, tool: str, arguments: dict[str, object], errors: int
    ) -> None:
        call = _call("C1", 6, "coding", tool, arguments=arguments, argument_errors=errors)
        assert tp.rebuilt_tool_text(call, _TABLES, _STATS) == _rebuilt(tool, arguments)


# --------------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------------


class TestRefusals:
    @pytest.fixture
    def groups(self, runs: Path, tmp_path: Path) -> Path:
        return _write_groups(tmp_path / "groups.json")

    def _refused(
        self,
        argv: Sequence[str],
        match: str,
        *,
        docket: Callable[[int], Docket] | None = _docket,
        load: Callable[[Sequence[str]], list[dict[str, object]]] = _load,
    ) -> None:
        with pytest.raises(SystemExit, match=match):
            _main(argv, docket=docket, load=load)

    def test_a_held_out_run_id_is_refused_before_its_folder_is_read(self, groups: Path) -> None:
        argv = _argv(groups)
        argv[1] = "20260101T000000-abc1234-heldout-400-C"
        self._refused(argv, "held-out")

    @pytest.mark.parametrize(
        ("sample", "match"),
        [("heldout-400", "held-out"), ("open-400", "not a development sample")],
    )
    def test_a_run_recorded_on_a_held_out_or_open_sample_is_refused(
        self, runs: Path, groups: Path, sample: str, match: str
    ) -> None:
        _write_run(runs, "renamed", record=_record("renamed", sample=sample))
        argv = _argv(groups)
        argv[1] = "renamed"
        self._refused(argv, match)

    def test_a_sealed_sample_is_refused_even_once_opened(
        self, runs: Path, groups: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): True)
        _write_run(runs, "sealed", record=_record("sealed", sample="dev-seal-s3-400"))
        argv = _argv(groups)
        argv[1] = "sealed"
        self._refused(argv, "dev-400 runs only")

    def test_a_sealed_sample_not_yet_opened_is_refused_as_sealed(
        self, runs: Path, groups: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
        _write_run(runs, "sealed", record=_record("sealed", sample="dev-seal-s3-400"))
        argv = _argv(groups)
        argv[1] = "sealed"
        self._refused(argv, "sealed")

    def test_an_arm_b_run_is_refused(self, runs: Path, groups: Path) -> None:
        _write_run(runs, "arm-b", record=_record("arm-b", arm="B"))
        argv = _argv(groups)
        argv[1] = "arm-b"
        self._refused(argv, "arm B; trail pages read arm C runs only")

    def test_an_unfinished_run_is_refused(self, runs: Path, groups: Path) -> None:
        _write_run(runs, "dead", record=_record("dead", finished=None))
        argv = _argv(groups)
        argv[1] = "dead"
        self._refused(argv, "has not finished")

    def test_a_folder_with_no_run_record_is_refused(self, groups: Path) -> None:
        argv = _argv(groups)
        argv[1] = "missing"
        self._refused(argv, r"no run\.jsonl")

    def test_a_copied_folder_is_refused(self, runs: Path, groups: Path) -> None:
        _write_run(runs, "copy", record=_record(_RUN_B))
        argv = _argv(groups)
        argv[1] = "copy"
        self._refused(argv, "copied or renamed")

    def test_a_run_with_no_trail_is_refused(self, runs: Path, groups: Path) -> None:
        (runs / _RUN_A / "trail.jsonl").unlink()
        self._refused(_argv(groups), r"no trail\.jsonl")

    def test_a_trail_holding_another_runs_calls_is_refused(self, runs: Path, groups: Path) -> None:
        (runs / _RUN_A / "trail.jsonl").unlink()
        write_jsonl(runs / _RUN_A / "trail.jsonl", _full_trail("ANC10LA044", _RUN_B))
        self._refused(_argv(groups), "holds a call of run")

    def test_a_case_outside_the_development_split_is_refused(
        self, runs: Path, groups: Path
    ) -> None:
        cases = [_result(i, final=_REFINED, failure=None) for i in _IDS]
        cases[0] = cases[0].model_copy(update={"split": "open"})
        _write_run(runs, _RUN_A, cases=cases)
        self._refused(_argv(groups), "outside the dev split")

    def test_a_record_outside_the_development_split_is_refused(self, groups: Path) -> None:
        def later(ids: Sequence[str]) -> list[dict[str, object]]:
            return [{**raw, "eventDate": "2024-05-01T00:00:00Z"} for raw in _load(ids)]

        self._refused(_argv(groups), "outside the development split", load=later)

    def test_a_record_for_another_case_is_refused(self, groups: Path) -> None:
        def wrong(ids: Sequence[str]) -> list[dict[str, object]]:
            return _load(["CEN11CA664"] * len(ids))

        self._refused(_argv(groups, fatal=1, nonfatal=0), "not its own", load=wrong)

    def test_comparing_a_run_with_itself_is_refused(self, groups: Path) -> None:
        self._refused(_argv(groups, "--compare", _RUN_A), "the run itself")

    def test_a_compare_run_that_is_not_arm_c_is_refused(self, runs: Path, groups: Path) -> None:
        _write_run(runs, "arm-b", record=_record("arm-b", arm="B"))
        self._refused(_argv(groups, "--compare", "arm-b"), "arm C runs only")

    def test_a_groups_file_drawn_over_other_runs_is_refused(
        self, runs: Path, tmp_path: Path
    ) -> None:
        groups = _write_groups(tmp_path / "other.json", runs=(_RUN_B,))
        self._refused(_argv(groups), "was not drawn over run")

    def test_a_groups_file_on_another_sample_is_refused(self, runs: Path, tmp_path: Path) -> None:
        groups = _write_groups(tmp_path / "other.json", sample="dev-seal-400")
        self._refused(_argv(groups), "is not a dev-400 groups file")

    def test_a_missing_groups_file_is_refused(self, runs: Path, tmp_path: Path) -> None:
        self._refused(_argv(tmp_path / "absent.json"), "no groups file")

    def test_a_split_the_groups_file_does_not_hold_is_refused(
        self, runs: Path, tmp_path: Path
    ) -> None:
        groups = _write_groups(tmp_path / "other.json", split="arm B")
        self._refused(_argv(groups), "holds no arm C groups")

    def test_a_group_case_the_run_does_not_hold_is_refused(
        self, runs: Path, tmp_path: Path
    ) -> None:
        groups = _write_groups(tmp_path / "other.json", ids=(*_IDS, "ZQX999"))
        self._refused(_argv(groups), "does not hold 1 case")

    def test_nothing_to_draw_is_a_usage_error(self, groups: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            _main(_argv(groups, fatal=0, nonfatal=0))
        assert raised.value.code == 2

    def test_a_drawn_case_with_no_ntsb_occurrence_code_is_refused(
        self, runs: Path, groups: Path
    ) -> None:
        cases = [_result(i, final=_REFINED, failure=None) for i in _IDS]
        cases[0] = cases[0].model_copy(update={"verdict_occurrence": ()})
        _write_run(runs, _RUN_A, cases=cases)
        self._refused(_argv(groups, fatal=3, nonfatal=6), "no NTSB occurrence code")

    def test_a_second_page_in_the_same_second_is_refused(self, groups: Path) -> None:
        assert _main(_argv(groups)) == 0
        self._refused(_argv(groups), "already exists")

    @pytest.mark.parametrize("inside", ["docs/results", "s3-trail-pages-test"])
    def test_an_out_dir_inside_the_repository_is_refused_before_anything_is_read(
        self, groups: Path, inside: str
    ) -> None:
        target = tp.REPOSITORY / inside
        existed = target.exists()
        self._refused(_argv(groups, "--out-dir", str(target)), "inside the repository")
        assert target.exists() == existed

    def test_an_out_dir_under_the_ignored_data_folder_is_allowed(self) -> None:
        tp.refuse_inside_repository(tp.REPOSITORY / "data" / "runs" / "s3-trail-pages")

    def test_an_out_dir_elsewhere_is_used(
        self, groups: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _main(_argv(groups, "--out-dir", str(tmp_path / "pages"))) == 0
        assert capsys.readouterr().out == f"pages/{_STAMP}\n"
        assert (tmp_path / "pages" / _STAMP / "trails.html").is_file()

    def test_a_docket_not_in_the_cache_is_refused_not_fetched(self, groups: Path) -> None:
        # No reader passed in: the real one reads the empty cache, and a miss must not fetch.
        self._refused(_argv(groups), "not all in the docket cache", docket=None)

    def test_a_docket_for_another_case_is_refused(self, groups: Path) -> None:
        self._refused(_argv(groups), "not its own", docket=lambda _mkey: _docket(1))

    def test_a_choice_the_cached_docket_could_not_have_offered_is_refused(
        self, runs: Path, groups: Path
    ) -> None:
        def fewer(mkey: int) -> Docket:
            docket = _docket(mkey)
            records = tuple(
                r.model_copy(update={"status": "unreadable: scan"}) if r.entry.index == 1 else r
                for r in docket.documents
            )
            return docket.model_copy(update={"documents": records})

        self._refused(_argv(groups), "the docket cache no longer matches", docket=fewer)
