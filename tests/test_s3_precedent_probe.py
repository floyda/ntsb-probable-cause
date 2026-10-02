"""scripts/exploratory/s3_precedent_probe.py: earlier cases found from the loop's own words.

S3.1 Task 15, exploratory. Synthetic run folders built from ``CaseResult`` and ``RunRecord``
objects, a groups file as ``scripts/s3_case_groups.py`` writes it, and a processed file of
invented cases. Every case id and every word in a text is invented; nothing looks like an NTSB
case number. Offline: no network, no model.
"""

import json
import math
import shutil
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts import coding_stats as cs
from scripts.exploratory import s3_precedent_probe as pp
from tests.test_coding_stats import _CASE_NUMBER
from tests.test_occurrence_misses import _case
from tests.test_s3_case_groups import _record

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult, write_jsonl

_RUN_A = "20261001T201506-fd6053f-dev-400-C"
_RUN_B = "20261001T201648-fd6053f-dev-400-C"
_JUDGED_DAY = "2016-06-01"
_IDS = tuple(f"ZQX{n:03d}" for n in range(6))
_FATAL = frozenset(_IDS[:3])
_WRONG = ("ZQX000", "ZQX001", "ZQX002", "ZQX003", "ZQX005")
_RIGHT = ("ZQX004",)
_SEALED = "ZQS001"
# Invented words: none is in the code tables' labels, so "no text in the output" is testable.
_BQ = "Brambleton quillwort exhaustion"
_ZM = "Zephyrine marrowfat ground"
_WORDS = ("brambleton", "quillwort", "zephyrine", "marrowfat", "thistlecomb")


def _day(text: str) -> date:
    return date.fromisoformat(text)


def _precedent(case_id: str, day: str, code: str, words: Sequence[str]) -> pp.Precedent:
    return pp.Precedent(case_id, _day(day), code, tuple(words))


# --------------------------------------------------------------------------------------------
# The search
# --------------------------------------------------------------------------------------------


class TestTokens:
    def test_lower_cased_words_and_digits_less_the_stop_words(self) -> None:
        assert pp.tokens("The pilot's FAILURE to maintain 2 feet; and the 100LL fuel.") == (
            "pilot",
            "s",
            "failure",
            "maintain",
            "2",
            "feet",
            "100ll",
            "fuel",
        )

    def test_the_stop_word_list_is_a_fixed_set_of_function_words(self) -> None:
        assert {"the", "and", "of", "to", "a", "not"} <= pp.STOP_WORDS
        assert not {"pilot", "fuel", "engine", "stall", "failure"} & pp.STOP_WORDS


class TestBm25:
    """Three cases, all earlier than the judged case: N = 3, average length 7 / 3."""

    POOL = (
        _precedent("ZQPAAA", "2010-01-01", "402192", ("engine", "failure", "fuel")),
        _precedent("ZQPBBB", "2011-01-01", "402192", ("fuel", "exhaustion", "fuel")),
        _precedent("ZQPCCC", "2012-01-01", "552241", ("stall",)),
    )

    def test_one_word_by_hand(self) -> None:
        # df(fuel) = 2: IDF = ln(1 + (3 - 2 + 0.5) / (2 + 0.5)) = ln 1.6.
        idf = math.log(1.6)
        norm = 1.2 * (1 - 0.75 + 0.75 * 3 / (7 / 3))  # both fuel cases are 3 words long
        scores = pp.Index(self.POOL).scores(("fuel",), _day(_JUDGED_DAY), "earlier")
        assert set(scores) == {"ZQPAAA", "ZQPBBB"}  # the stall case shares no word: no score
        assert scores["ZQPAAA"] == pytest.approx(idf * 1 * 2.2 / (1 + norm))
        assert scores["ZQPAAA"] == pytest.approx(0.42081720292932145)
        assert scores["ZQPBBB"] == pytest.approx(idf * 2 * 2.2 / (2 + norm))
        assert scores["ZQPBBB"] == pytest.approx(0.5981864372218454)

    def test_two_words_add_and_a_repeated_query_word_counts_once(self) -> None:
        index = pp.Index(self.POOL)
        scores = index.scores(("fuel", "stall", "stall"), _day(_JUDGED_DAY), "earlier")
        # df(stall) = 1: IDF = ln(1 + 2.5 / 1.5); the stall case is 1 word long.
        idf = math.log(1 + 2.5 / 1.5)
        assert scores["ZQPCCC"] == pytest.approx(idf * 2.2 / (1 + 1.2 * (0.25 + 0.75 / (7 / 3))))
        assert scores["ZQPCCC"] == pytest.approx(1.2800652963034396)
        assert scores["ZQPBBB"] == pytest.approx(0.5981864372218454)
        ranked = index.search(("fuel", "stall"), _day(_JUDGED_DAY), "earlier")
        assert [p.case_id for p in ranked] == ["ZQPCCC", "ZQPBBB", "ZQPAAA"]

    def test_no_case_matches_an_empty_query_or_an_unknown_word(self) -> None:
        index = pp.Index(self.POOL)
        assert index.search((), _day(_JUDGED_DAY), "earlier") == ()
        assert index.search(("thistlecomb",), _day(_JUDGED_DAY), "earlier") == ()


class TestDateLimit:
    """Judged on 2016-06-01: two earlier cases, one the same day, one later."""

    POOL = (
        _precedent("ZQPE01", "2015-01-01", "402192", ("fuel",)),
        _precedent("ZQPE02", "2015-06-01", "402192", ("fuel", "engine")),
        _precedent("ZQPSAM", _JUDGED_DAY, "552230", ("fuel",)),
        _precedent("ZQPLAT", "2017-01-01", "300230", ("fuel", "fuel", "stall", "stall")),
    )

    def test_the_date_limited_pool_sees_strictly_earlier_cases_and_counts_over_them(self) -> None:
        # N = 2, df(fuel) = 2, average length (1 + 2) / 2 = 1.5.
        index = pp.Index(self.POOL)
        scores = index.scores(("fuel",), _day(_JUDGED_DAY), "earlier")
        assert set(scores) == {"ZQPE01", "ZQPE02"}
        idf = math.log(1 + 0.5 / 2.5)
        assert scores["ZQPE01"] == pytest.approx(idf * 2.2 / (1 + 1.2 * (0.25 + 0.75 * 1 / 1.5)))
        assert scores["ZQPE01"] == pytest.approx(0.21110917102457905)
        assert scores["ZQPE02"] == pytest.approx(0.16044296997868007)
        assert index.size(_day(_JUDGED_DAY), "earlier") == 2

    def test_the_whole_pool_leaves_out_only_the_same_day_and_counts_over_the_rest(self) -> None:
        # N = 3, df(fuel) = 3, average length (1 + 2 + 4) / 3.
        index = pp.Index(self.POOL)
        scores = index.scores(("fuel",), _day(_JUDGED_DAY), "whole")
        assert set(scores) == {"ZQPE01", "ZQPE02", "ZQPLAT"}
        idf = math.log(1 + 0.5 / 3.5)
        average = 7 / 3
        assert scores["ZQPE01"] == pytest.approx(idf * 2.2 / (1 + 1.2 * (0.25 + 0.75 / average)))
        assert scores["ZQPE01"] == pytest.approx(0.17426978359471593)
        assert scores["ZQPE02"] == pytest.approx(0.1418195480288033)
        assert scores["ZQPLAT"] == pytest.approx(0.15289096255893292)
        assert index.size(_day(_JUDGED_DAY), "whole") == 3

    def test_a_judged_case_before_the_pool_sees_nothing_earlier(self) -> None:
        index = pp.Index(self.POOL)
        assert index.search(("fuel",), _day("2014-01-01"), "earlier") == ()
        assert index.commonest(_day("2014-01-01"), "earlier") == ()
        assert index.size(_day("2014-01-01"), "whole") == 4


class TestRanking:
    def test_ties_go_to_the_lower_case_id_and_five_are_kept(self) -> None:
        # The same words score the same whatever the date; the dates run against the ids, so
        # date order (the index's own) would rank them otherwise.
        ids = ("ZQP009", "ZQP002", "ZQP007", "ZQP001", "ZQP005", "ZQP003")
        pool = [
            _precedent(case_id, f"{2010 + n}-01-01", "552230", ("fuel",))
            for n, case_id in enumerate(ids)
        ]
        ranked = pp.Index(pool).search(("fuel",), _day(_JUDGED_DAY), "earlier")
        assert [p.case_id for p in ranked] == ["ZQP001", "ZQP002", "ZQP003", "ZQP005", "ZQP007"]

    def test_a_higher_score_beats_a_lower_case_id(self) -> None:
        pool = [
            _precedent("ZQP001", "2012-01-01", "552230", ("fuel", "engine", "power")),
            _precedent("ZQP002", "2012-01-01", "402192", ("fuel",)),
        ]
        ranked = pp.Index(pool).search(("fuel",), _day(_JUDGED_DAY), "earlier")
        assert [p.case_id for p in ranked] == ["ZQP002", "ZQP001"]  # the shorter case


# --------------------------------------------------------------------------------------------
# The measures and the controls
# --------------------------------------------------------------------------------------------


def _five(*codes: str) -> tuple[pp.Precedent, ...]:
    return tuple(_precedent(f"ZQP{n:03d}", "2012-01-01", c, ()) for n, c in enumerate(codes))


class TestMeasures:
    def test_found_nearest_majority_and_event_only(self) -> None:
        five = _five("552230", "402192", "402192", "300230", "551092")
        assert pp.measure("402192", five) == pp.Hits(
            found=True, nearest=False, majority=True, event=True
        )
        assert pp.measure("552230", five) == pp.Hits(
            found=True, nearest=True, majority=False, event=True
        )
        # Same event, another phase: only event-only finds it.
        assert pp.measure("500192", five) == pp.Hits(
            found=False, nearest=False, majority=False, event=True
        )
        assert pp.measure("500241", five) == pp.MISSED

    def test_a_tied_majority_goes_to_the_code_ranked_first(self) -> None:
        # Not to the lower code: 300230 is lower, but 402192 is ranked first.
        five = _five("402192", "300230", "300230", "402192", "551092")
        assert pp.measure("402192", five).majority
        assert not pp.measure("300230", five).majority

    def test_a_failed_case_has_no_query_and_is_missed_whatever_the_pool_holds(self) -> None:
        failed = _one("ZQX002", ("552230",), (), failed=True)
        assert pp.query_text(failed, "probable cause") is None
        assert pp.query_text(failed, "evidence narrative") is None
        index = pp.Index([_precedent("ZQP001", "2012-01-01", "552230", ("fuel",))])
        for query in pp.QUERIES:
            assert pp.search_hits(index, failed, _day(_JUDGED_DAY), query, "earlier") == pp.MISSED
        answered = _one("ZQX001", ("552230",), ("552230",), cause="fuel", narrative="none")
        assert pp.query_text(answered, "probable cause") == "fuel"
        assert pp.query_text(answered, "evidence narrative") == "none"
        assert pp.search_hits(index, answered, _day(_JUDGED_DAY), "probable cause", "earlier") == (
            pp.Hits(found=True, nearest=True, majority=True, event=True)
        )

    def test_fewer_than_five_and_none(self) -> None:
        assert pp.measure("552230", _five("552230")) == pp.Hits(
            found=True, nearest=True, majority=True, event=True
        )
        assert pp.measure("552230", ()) == pp.MISSED


class TestControls:
    POOL = (
        _precedent("ZQP001", "2010-01-01", "552230", ()),
        _precedent("ZQP002", "2010-02-01", "552230", ()),
        _precedent("ZQP003", "2010-03-01", "402341", ()),
        _precedent("ZQP004", "2010-04-01", "402341", ()),
        _precedent("ZQP005", "2010-05-01", "552192", ()),
        _precedent("ZQP006", "2010-06-01", "300230", ()),
        _precedent("ZQP007", "2010-07-01", "551092", ()),
        _precedent("ZQP008", "2010-08-01", "500241", ()),
        _precedent("ZQP009", "2017-01-01", "500241", ()),
        _precedent("ZQP010", "2017-01-01", "500241", ()),
        _precedent("ZQP011", _JUDGED_DAY, "500241", ()),
        _precedent("ZQP012", _JUDGED_DAY, "500241", ()),
    )

    def test_the_five_commonest_earlier_first_codes_ties_by_code(self) -> None:
        index = pp.Index(self.POOL)
        # 552230 and 402341 twice; then four codes once each, of which the lowest three.
        assert index.commonest(_day(_JUDGED_DAY), "earlier") == (
            "402341",
            "552230",
            "300230",
            "500241",
            "551092",
        )

    def test_the_whole_pool_adds_later_cases_and_leaves_out_the_same_day(self) -> None:
        index = pp.Index(self.POOL)
        # 500241: once earlier, twice later; the two same-day cases do not count.
        assert index.commonest(_day(_JUDGED_DAY), "whole") == (
            "500241",
            "402341",
            "552230",
            "300230",
            "551092",
        )

    def test_the_phase_aware_control_keeps_the_answer_phase_only(self) -> None:
        index = pp.Index(self.POOL)
        assert index.commonest(_day(_JUDGED_DAY), "earlier", "552") == ("552230", "552192")
        assert index.commonest(_day(_JUDGED_DAY), "earlier", "999") == ()

    def test_control_and_phase_control_on_a_case(self) -> None:
        index = pp.Index(self.POOL)
        day = _day(_JUDGED_DAY)
        answered = _one("ZQX000", ("552192",), ("552241",))
        assert pp.control(index, answered, day, "earlier") is False  # 552192 is not top five
        assert pp.phase_control(index, answered, day, "earlier") is True  # but top in phase 552
        failed = _one("ZQX001", ("552230",), (), failed=True)
        assert pp.control(index, failed, day, "earlier") is True  # needs no answer
        assert pp.phase_control(index, failed, day, "earlier") is False  # no answer, no phase


class TestRule:
    @pytest.mark.parametrize(
        ("found", "control", "word"),
        [
            (67, 0, "promising"),
            (66, 0, "in between"),
            (27, 0, "in between"),
            (26, 0, "not promising"),
            (67, 66, "promising"),
            (67, 67, "not promising"),
            (40, 40, "not promising"),
            (40, 41, "not promising"),
            (0, 0, "not promising"),
        ],
    )
    def test_the_rule_at_its_edges(self, found: int, control: int, word: str) -> None:
        assert pp.outcome(found, control) == word

    @staticmethod
    def _results(pc: int, en: int, controlled: int, n: int = 266) -> pp.Results:
        ids = [f"ZQX{i:03d}" for i in range(n)]

        def hits(k: int) -> dict[str, pp.Hits]:
            hit = pp.Hits(found=True, nearest=False, majority=False, event=False)
            return {i: hit if j < k else pp.MISSED for j, i in enumerate(ids)}

        return pp.Results(
            hits={
                (1, "probable cause", "earlier"): hits(pc),
                (1, "evidence narrative", "earlier"): hits(en),
                (2, "probable cause", "earlier"): hits(0),
                (2, "evidence narrative", "earlier"): hits(n),
            },
            controls={"earlier": {i: j < controlled for j, i in enumerate(ids)}},
            phase_controls={},
            no_query={},
        )

    def _lines(self, pc: int, en: int, controlled: int) -> str:
        results = self._results(pc, en, controlled)
        ids = sorted(results.controls["earlier"])
        return "\n".join(pp.rule_lines(results, ids, (_RUN_A, _RUN_B)))

    def test_a_tie_goes_to_the_probable_cause(self) -> None:
        text = self._lines(70, 70, 10)
        assert "the better query (a tie goes to the probable cause): probable cause" in text
        assert text.endswith("Outcome: promising")

    def test_the_better_query_decides_and_run_b_does_not(self) -> None:
        text = self._lines(20, 70, 10)  # run b finds all 266 with its narrative: no matter
        assert "evidence narrative, found in 70 of 266, against the control's 10" in text
        assert "evidence-narrative query 266 of 266 (100.0%)" in text
        assert text.endswith("Outcome: promising")
        assert self._lines(70, 20, 70).endswith("Outcome: not promising")
        assert self._lines(30, 20, 10).endswith("Outcome: in between")

    def test_the_rule_prints_the_prediction_and_the_counts_with_intervals(self) -> None:
        text = self._lines(70, 20, 10)
        assert pp.PREDICTION in text
        assert "- found@5, probable-cause query: 70 of 266 (26.3%) [" in text
        assert "- control (the pool's five commonest first codes, no search): 10 of 266" in text
        assert "Note: the prediction names" not in text


# --------------------------------------------------------------------------------------------
# The whole script, on synthetic runs, groups and a processed file
# --------------------------------------------------------------------------------------------


def _one(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    ntsb: tuple[str, ...],
    answer: tuple[str, ...],
    *,
    cause: str = "",
    narrative: str = "",
    failed: bool = False,
) -> CaseResult:
    case = _case(case_id, ntsb, answer, scored=not failed).model_copy(
        update={"fatal": case_id in _FATAL}
    )
    if failed:
        return case
    step = case.steps[0]
    hypothesis = step.hypothesis.model_copy(
        update={"probable_cause": cause, "evidence_narrative": narrative}
    )
    return case.model_copy(update={"steps": (step.model_copy(update={"hypothesis": hypothesis}),)})


def _run_a() -> list[CaseResult]:
    """Run a. Cases 0-2 fatal. Every case is judged on 2016-06-01."""
    return [
        # found: the two earlier brambleton cases are 402192
        _one("ZQX000", ("402192",), ("402341",), cause=_BQ, narrative=_ZM),
        # the same words, but the NTSB's code is 552192: event-only finds 192; the sealed case
        # (552192, the same words) would find it if it reached the pool
        _one("ZQX001", ("552192",), ("552230",), cause=_BQ, narrative=_ZM),
        # failed: no query, not found; the control still counts it
        _one("ZQX002", ("552230",), (), failed=True),
        # only the later brambleton case is 300230: found in the whole pool only
        _one("ZQX003", ("300230",), ("300230",), cause=_BQ, narrative=_ZM),
        # found, and nearest: the zephyrine cases are 552230; its narrative ranks the two
        # quillwort cases (402192, the rarer word) above the three marrowfat ones: found, but
        # the nearest points away
        _one("ZQX004", ("552230",), ("552230",), cause=_ZM, narrative="quillwort marrowfat"),
        # only the same-day brambleton case is 551092: never found
        _one("ZQX005", ("551092",), ("551092",), cause="quillwort", narrative="quillwort"),
    ]


def _run_b() -> list[CaseResult]:
    """Run b: case 2 answered, and found with its probable cause."""
    cases = _run_a()
    cases[2] = _one("ZQX002", ("552230",), ("552230",), cause=_ZM, narrative=_ZM)
    return cases


def _write_run(
    runs: Path, run_id: str, cases: Sequence[CaseResult], *, arm: str = "C", **changes: object
) -> None:
    folder = runs / run_id
    shutil.rmtree(folder, ignore_errors=True)  # write_jsonl appends; a rewrite starts afresh
    write_jsonl(folder / "run.jsonl", [_record(run_id, arm=arm, **changes)])
    write_jsonl(folder / "cases.jsonl", cases)


def _raw(cause: str | None, codes: Sequence[str]) -> dict[str, object]:
    events = [
        {"eventCode": code, "isDefiningEvent": i == 0, "sequenceNumber": i + 1}
        for i, code in enumerate(codes)
    ]
    narratives = [{"probableCause": cause}] if cause is not None else []
    return {"narratives": narratives, "aircrafts": [{"events": events, "findings": []}]}


_ROWS: list[tuple[str, str, str, str, dict[str, object]]] = [
    ("ZQP001", "2010-03-01", "dev", "C", _raw(_BQ, ("402192",))),
    ("ZQP002", "2011-03-01", "dev", "F", _raw(_BQ, ("402192",))),
    ("ZQP003", "2012-03-01", "dev", "L", _raw(_ZM, ("552230",))),
    ("ZQP004", "2013-03-01", "dev", "C", _raw(_ZM, ("552230",))),
    ("ZQP005", "2014-03-01", "dev", "C", _raw(_ZM, ("552230",))),
    ("ZQP006", "2017-03-01", "dev", "C", _raw(_BQ, ("300230",))),  # later
    ("ZQP007", _JUDGED_DAY, "dev", "C", _raw(_BQ, ("551092",))),  # the same day
    ("ZQP008", "2012-05-01", "dev", "C", _raw(None, ("552230",))),  # no text
    ("ZQP009", "2012-06-01", "dev", "C", _raw("Thistlecomb", ())),  # no code
    (_SEALED, "2009-01-01", "dev", "C", _raw(_BQ, ("552192",))),  # a sealed sample's case
    ("ZQI001", "2009-01-01", "dev", "I", _raw(_BQ, ("552192",))),  # a class outside C/F/L
    ("ZQH001", "2021-01-01", "heldout", "C", _raw(_BQ, ("552192",))),
    *((case_id, _JUDGED_DAY, "dev", "C", _raw("Thistlecomb", ("552230",))) for case_id in _IDS),
]


def _processed(data: Path, rows: Sequence[tuple[str, str, str, str, dict[str, object]]]) -> None:
    processed = data / "processed"
    processed.mkdir(parents=True, exist_ok=True)
    table = pa.table(
        {
            "ntsb_number": pa.array([r[0] for r in rows], type=pa.string()),
            "event_date": pa.array([_day(r[1]) for r in rows], type=pa.date32()),
            "split": pa.array([r[2] for r in rows], type=pa.string()),
            "investigation_class": pa.array([r[3] for r in rows], type=pa.string()),
            "raw_json": pa.array([json.dumps(r[4]) for r in rows], type=pa.string()),
        }
    )
    pq.write_table(table, processed / "cases.parquet")


def _sample_ids(name: str) -> tuple[str, ...]:
    return {"dev-400": _IDS, "dev-seal-400": (), "dev-seal-s3-400": (_SEALED,)}.get(name, ())


def _groups(path: Path, *, runs: Sequence[str] = (_RUN_A, _RUN_B)) -> Path:
    data = {
        "sample": "dev-400",
        "runs": [{"run_id": r, "arm": "C"} for r in runs],
        "groups": {
            "arm C": {"always right": list(_RIGHT), "always wrong": list(_WRONG), "flipping": []}
        },
    }
    path.write_text(json.dumps(data, indent=1) + "\n")
    return path


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run a and run b under the runs folder, the processed file, and the sample lists."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", _sample_ids)
    _processed(tmp_path, _ROWS)
    _write_run(folder, _RUN_A, _run_a())
    _write_run(folder, _RUN_B, _run_b())
    return folder


@pytest.fixture
def groups(runs: Path) -> Path:
    """A groups file drawn over runs a and b, under the runs folder as the real one is."""
    path = runs / "s3-case-groups" / "20261002T065520" / "groups.json"
    path.parent.mkdir(parents=True)
    return _groups(path)


def _argv(groups: Path, *extra: str) -> list[str]:
    return ["--runs", _RUN_A, _RUN_B, "--groups", str(groups), *extra]


def _report(argv: Sequence[str], capsys: pytest.CaptureFixture[str]) -> str:
    assert pp.main(argv) == 0
    return capsys.readouterr().out


def _section(text: str, start: str, end: str | None = None) -> str:
    begin = text.index(start)
    stop = text.find(end, begin + 1) if end is not None else -1
    return text[begin : stop if stop != -1 else len(text)]


class TestReport:
    def test_the_head_names_the_runs_the_groups_and_their_source(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        assert text.startswith("S3.1 precedent probe on dev-400 (scripts/exploratory/")
        assert f"run a = {_RUN_A}\nrun b = {_RUN_B} (printed beside run a; decides nothing)" in text
        assert (
            "Groups: arm C, from s3-case-groups/20261002T065520/groups.json: always wrong 5 cases "
            "(3 fatal, 2 non-fatal); always right 1 cases (0 fatal, 1 non-fatal)"
        ) in text

    def test_the_rule_comes_first_with_its_outcome(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        rule = _section(text, "## The rule", "## Method")
        assert text.index("## The rule") < text.index("## Method") < text.index("## arm C")
        assert pp.PREDICTION in rule
        assert "Note: the prediction names 266 cases; this group holds 5." in rule
        assert "- found@5, probable-cause query: 1 of 5 (20.0%) [" in rule
        assert "- found@5, evidence-narrative query: 0 of 5 (0.0%) [" in rule
        assert "no search): 2 of 5 (40.0%) [" in rule
        assert "probable cause, found in 1 of 5, against the control's 2" in rule
        # Run b answers ZQX002 and finds it: printed, deciding nothing.
        assert "found@5 probable-cause query 2 of 5 (40.0%), evidence-narrative query" in rule
        assert rule.rstrip().endswith("Outcome: not promising")

    def test_the_pool_is_the_s3_statistics_pool_with_text_and_codes(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        method = _section(_report(_argv(groups), capsys), "## Method", "## arm C")
        # ZQP001-009 are in the pool; the sealed, class I, held-out and judged cases are not.
        assert f"the S3 statistics pool, {cs.STAGES['s3'].built_from}: 9 cases;" in method
        assert "occurrence code: 7 (event years 2010-2017); left out: 1 with no" in method
        assert "1 more with no occurrence code." in method
        assert "552230 Landing-Landing Roll / Loss of control on ground (3)" in method

    def test_each_measure_on_the_headline_group_by_pool_run_and_query(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        wrong = _section(text, "## arm C, always wrong", "## arm C, always right")
        assert "## arm C, always wrong: 5 cases (3 fatal, 2 non-fatal)" in wrong
        earlier = _section(wrong, "### date-limited pool", "### whole pool")
        assert "control (no search): 2 of 5 (40.0%) [" in earlier
        run_a = _section(earlier, f"run a ({_RUN_A})", f"run b ({_RUN_B})")
        assert "no query (failed or not scored): 1 of 5 (20.0%)" in run_a
        cause = _section(run_a, "probable cause query:", "evidence narrative query:")
        assert "- found@5: 1 of 5 (20.0%) [" in cause
        assert "; fatal 1 of 3 (33.3%) [" in cause
        assert "; non-fatal 0 of 2 (0.0%) [" in cause
        assert "- nearest@1: 1 of 5 (20.0%); fatal 1 of 3 (33.3%); non-fatal 0 of 2" in cause
        assert "- majority@5: 1 of 5 (20.0%)" in cause
        # ZQX000 (402192) and ZQX001 (552192, event 192 among the 402192 cases)
        assert "- event-only@5: 2 of 5 (40.0%); fatal 2 of 3 (66.7%); non-fatal 0 of 2" in cause
        # ZQX000 answered phase 402: the 402192 cases; ZQX001 phase 552: 552230 only; ZQX003
        # phase 300: none earlier; ZQX005 phase 551: the same-day case is left out.
        assert "phase-aware control: 1 of 5 (20.0%) [" in run_a
        run_b = _section(earlier, f"run b ({_RUN_B})")
        assert "no query (failed or not scored): 0 of 5 (0.0%)" in run_b
        assert "- found@5: 2 of 5 (40.0%) [" in run_b  # ZQX002 answered and found

    def test_the_whole_pool_adds_later_cases_but_never_the_same_day(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        wrong = _section(text, "## arm C, always wrong", "## arm C, always right")
        whole = _section(wrong, "### whole pool", f"run b ({_RUN_B})")
        # The later 300230 case finds ZQX003; the same-day 551092 case never finds ZQX005.
        assert "- found@5: 2 of 5 (40.0%) [" in whole
        # 300230 (ZQX003) is in the whole pool's five commonest; 402192 and 552230 still are.
        assert "control (no search): 3 of 5 (60.0%) [" in whole
        assert "phase-aware control: 2 of 5 (40.0%) [" in whole  # ZQX000; ZQX003, phase 300

    def test_the_always_right_group_says_how_often_the_precedents_point_away(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        right = _section(text, "## arm C, always right", "## all cases")
        earlier = _section(right, "### date-limited pool", "### whole pool")
        cause = _section(earlier, "probable cause query:", "evidence narrative query:")
        # ZQX004's probable cause finds the 552230 cases: nearest is right, found.
        assert "- the nearest case's first code differs from the NTSB's (= the loop's) " in cause
        assert "first code: 0 of 1 (0.0%)" in cause
        assert "- the NTSB's first code is not among the five: 0 of 1 (0.0%)" in cause
        narrative = _section(earlier, "evidence narrative query:", "phase-aware control")
        assert "- found@5: 1 of 1 (100.0%) [" in narrative
        assert "- nearest@1: 0 of 1 (0.0%)" in narrative
        assert "first code: 1 of 1 (100.0%)" in narrative
        assert "- the NTSB's first code is not among the five: 0 of 1 (0.0%)" in narrative
        wrong = _section(text, "## arm C, always wrong", "## arm C, always right")
        assert "differs from the NTSB's" not in wrong
        assert "not among the five" not in wrong

    def test_all_cases_count_a_failed_case_as_not_found_in_the_denominator(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        every = _section(text, "## all cases (failed cases counted as not found)")
        assert every.startswith(
            "## all cases (failed cases counted as not found): 6 cases (3 fatal, 3 non-fatal)"
        )
        run_a = _section(every, f"run a ({_RUN_A})", f"run b ({_RUN_B})")
        assert "no query (failed or not scored): 1 of 6 (16.7%)" in run_a
        assert "- found@5: 2 of 6 (33.3%) [" in run_a  # ZQX000 and ZQX004
        # The five earlier cases are just enough.
        assert "Cases whose date-limited pool holds fewer than 5 cases: 0 of 6 (0.0%)" in every

    def test_no_case_number_no_case_id_and_no_record_text_is_printed(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        text = _report(_argv(groups), capsys)
        assert not _CASE_NUMBER.search(text)
        assert "ZQ" not in text
        for word in _WORDS:
            assert word not in text.lower()

    def test_out_writes_the_same_text_and_the_text_does_not_depend_on_it(
        self, groups: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        plain = _report(_argv(groups), capsys)
        out = tmp_path / "results" / "s3-precedent-probe-dev.txt"
        written = _report(_argv(groups, "--out", str(out)), capsys)
        assert written == plain
        assert out.read_text() == plain


# --------------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------------


class TestRefusals:
    def test_an_arm_b_run_is_refused(self, runs: Path, groups: Path) -> None:
        _write_run(runs, _RUN_B, _run_b(), arm="B")
        with pytest.raises(SystemExit, match="arm B; the precedent probe reads arm C runs only"):
            pp.main(_argv(groups))

    def test_a_run_named_twice_is_refused(self, groups: Path) -> None:
        with pytest.raises(SystemExit, match="named twice"):
            pp.main(["--runs", _RUN_A, _RUN_A, "--groups", str(groups)])

    def test_one_run_is_a_usage_error(self, groups: Path) -> None:
        with pytest.raises(SystemExit) as raised:
            pp.main(["--runs", _RUN_A, "--groups", str(groups)])
        assert raised.value.code == 2

    def test_a_held_out_run_id_is_refused(self) -> None:
        with pytest.raises(SystemExit, match="held-out"):
            pp.main(["--runs", "20260101T000000-abc1234-heldout-400-C", _RUN_B, "--groups", "x"])

    def test_an_unfinished_run_is_refused(self, runs: Path, groups: Path) -> None:
        _write_run(runs, _RUN_A, _run_a(), finished=None)
        with pytest.raises(SystemExit, match="has not finished"):
            pp.main(_argv(groups))

    def test_a_groups_file_not_drawn_over_both_runs_is_refused(
        self, runs: Path, tmp_path: Path
    ) -> None:
        other = _groups(tmp_path / "other.json", runs=(_RUN_A,))
        with pytest.raises(SystemExit, match=f"was not drawn over run {_RUN_B}"):
            pp.main(_argv(other))

    def test_a_group_case_the_runs_do_not_hold_is_refused(self, groups: Path) -> None:
        data = json.loads(groups.read_text())
        data["groups"]["arm C"]["always wrong"].append("ZQX999")
        groups.write_text(json.dumps(data))
        with pytest.raises(SystemExit, match="do not hold 1 case"):
            pp.main(_argv(groups))

    def test_a_judged_case_with_no_ntsb_occurrence_code_is_refused(
        self, runs: Path, groups: Path
    ) -> None:
        cases = _run_b()
        cases[4] = cases[4].model_copy(update={"verdict_occurrence": ()})
        _write_run(runs, _RUN_B, cases)
        with pytest.raises(SystemExit, match="no NTSB occurrence code"):
            pp.main(_argv(groups))

    def test_a_judged_case_with_no_event_date_is_refused(
        self, runs: Path, groups: Path, tmp_path: Path
    ) -> None:
        _processed(tmp_path, [row for row in _ROWS if row[0] != "ZQX003"])
        with pytest.raises(SystemExit, match="1 judged case"):
            pp.main(_argv(groups))

    def test_a_pool_holding_a_sample_case_raises_through_check_pool(
        self, groups: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A pool built without the exclusions holds dev-400 and the sealed case: refused."""
        texts_read: list[str] = []
        real = fields.probable_cause

        def spy(raw: Mapping[str, object]) -> str | None:
            texts_read.append("read")
            return real(raw)

        monkeypatch.setattr(
            pp, "pool_cases", lambda rows, *, excluded: cs.pool_cases(rows, excluded=frozenset())
        )
        monkeypatch.setattr(fields, "probable_cause", spy)
        with pytest.raises(LeakageError, match=_SEALED):
            pp.main(_argv(groups))
        assert texts_read == []  # refused before any pool text was read

    def test_the_sealed_case_never_reaches_the_pool(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """Its words and its 552192 would find ZQX001 if it were in the pool."""
        text = _report(_argv(groups), capsys)
        cause = _section(
            _section(text, "## arm C, always wrong", "### whole pool"),
            "probable cause query:",
            "evidence narrative query:",
        )
        assert "- found@5: 1 of 5 (20.0%)" in cause  # ZQX000 only
