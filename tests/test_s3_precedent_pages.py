"""scripts/exploratory/s3_precedent_pages.py: the probe's cases read beside their five nearest.

S3.1 Task 15, exploratory. Synthetic data only: a run folder built from ``CaseResult`` and
``RunRecord`` objects, a groups file as ``scripts/s3_case_groups.py`` writes it, and a processed
file of invented cases. Every case id, name and word in a text is invented; nothing looks like an
NTSB case number. Offline: no network, no model, no docket.
"""

import html
import itertools
import json
import random
import re
from collections.abc import Callable, Sequence
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from scripts.exploratory import s3_precedent_pages as pages
from scripts.exploratory import s3_precedent_probe as pp
from scripts.s3_trail_pages import Mark
from tests.test_occurrence_misses import _case
from tests.test_s3_precedent_probe import _processed, _write_run

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult

_RUN = "20261001T201506-fd6053f-dev-400-C"
_OTHER = "20261001T201648-fd6053f-dev-400-C"
_WHEN = datetime(2026, 10, 2, 18, 30, 15, tzinfo=UTC)
_STAMP = "20261002T183015"
_DAY = "2016-06-01"
_SEED = 20261002

# The judged cases. A: found (12, the odd ones fatal). B: not found (7, the last 4 fatal).
# C: always right, the nearest pointing away (3, the last fatal; C00's query shares a word with
# five earlier cases, C01's with four, C02's with one). D: always right, its nearest right: in no
# set. F: always wrong, failed. The fatal cases are not the lowest ids, so the page's order
# (fatal first, each kind sorted) is not the ids' order.
_A = tuple(f"ZQA{n:02d}" for n in range(12))
_B = tuple(f"ZQB{n:02d}" for n in range(7))
_C = ("ZQC00", "ZQC01", "ZQC02")
_D = "ZQD00"
_F = "ZQF00"
_JUDGED = (*_A, *_B, *_C, _D, _F)
_FATAL = frozenset((*_A[1::2], *_B[3:], _C[2]))
_SEALED = "ZQS001"
# Invented owner or operator names, and an invented amateur-built make.
_JUDGED_OWNER = "Zorvex Quillbright"
_EARLIER_OWNER = "Quorvane Hallet"
_MAKE = "Glimmerwing"

_A_CAUSE = f"The brambleton QUILLWORT exhaustion, said {_JUDGED_OWNER}"
_NTSB_CAUSE = f"{_JUDGED_OWNER} let the tank run dry."


def _result(
    case_id: str,
    ntsb: tuple[str, ...],
    answer: tuple[str, ...],
    *,
    cause: str = "",
    failed: bool = False,
) -> CaseResult:
    case = _case(case_id, ntsb, answer, scored=not failed).model_copy(
        update={"fatal": case_id in _FATAL}
    )
    if failed:
        return case
    step = case.steps[0]
    hypothesis = step.hypothesis.model_copy(update={"probable_cause": cause})
    return case.model_copy(update={"steps": (step.model_copy(update={"hypothesis": hypothesis}),)})


_A_NTSB = ("402192", "500241")
_A_ANSWER = ("402341", "500241", "402192")


def _cases() -> list[CaseResult]:
    return [
        *(_result(i, _A_NTSB, _A_ANSWER, cause=_A_CAUSE) for i in _A),
        *(_result(i, ("500230",), ("552230",), cause="Brambleton quillwort") for i in _B),
        _result(_C[0], ("552230",), ("552230",), cause="Brambleton"),
        _result(_C[1], ("552230",), ("552230",), cause="quillwort exhaustion ridge thistlecomb"),
        _result(_C[2], ("552230",), ("552230",), cause="Thistlecomb"),
        _result(_D, ("552230",), ("552230",), cause="Zephyrine marrowfat"),
        _result(_F, ("402192",), (), failed=True),
    ]


def _raw(  # noqa: PLR0913 -- a test-only builder, one keyword per varied field.
    case_id: str,
    day: str,
    cause: str,
    codes: Sequence[str],
    *,
    owner: str | None = None,
    make: str | None = None,
) -> dict[str, object]:
    aircraft: dict[str, object] = {
        "events": [
            {"eventCode": code, "isDefiningEvent": i == 0, "sequenceNumber": i + 1}
            for i, code in enumerate(codes)
        ],
        "findings": [],
    }
    if owner is not None:
        aircraft["ownerOperators"] = [{"operatorName": owner}]
    if make is not None:
        aircraft.update(aircraftAmateurBuilt=True, aircraftMake=make, aircraftModel="Zq-9")
    return {
        "ntsbNumber": case_id,
        "eventDate": f"{day}T00:00:00Z",
        "narratives": [{"probableCause": cause}],
        "aircrafts": [aircraft],
    }


_Row = tuple[str, str, str, str, dict[str, object]]


def _row(case_id: str, day: str, cause: str, codes: Sequence[str], **extra: str) -> _Row:
    return (case_id, day, "dev", "C", _raw(case_id, day, cause, codes, **extra))


_POOL: list[_Row] = [
    _row(
        "ZQP001",
        "2010-03-01",
        f"The Brambleton quillwort exhaustion, reported by {_EARLIER_OWNER}.",
        ("402192",),
        owner=_EARLIER_OWNER,
    ),
    _row(
        "ZQP002",
        "2011-03-01",
        f"Brambleton quillwort exhaustion in the {_MAKE}.",
        ("500192",),
        make=_MAKE,
    ),
    _row("ZQP003", "2012-03-01", "Brambleton quillwort ridge.", ("300230", "402192")),
    _row("ZQP004", "2013-03-01", "Brambleton thistlecomb.", ("552241",)),
    _row("ZQP005", "2014-03-01", 'Brambleton <script>x</script> & "co".', ("551092",)),
    _row("ZQP006", "2012-05-01", "Zephyrine marrowfat ground.", ("552230",)),
    _row("ZQP007", "2013-05-01", "Zephyrine marrowfat ground.", ("552230",)),
    _row("ZQP008", "2014-05-01", "Zephyrine marrowfat ground.", ("552230",)),
    _row("ZQP009", "2017-03-01", "Brambleton quillwort exhaustion.", ("402192",)),  # later
    _row(_SEALED, "2009-01-01", "Brambleton quillwort exhaustion.", ("402192",)),  # sealed
]


def _judged_rows(cases: Sequence[CaseResult]) -> list[_Row]:
    return [
        _row(c.case_id, _DAY, _NTSB_CAUSE, c.verdict_occurrence, owner=_JUDGED_OWNER) for c in cases
    ]


def _sample_ids(name: str) -> tuple[str, ...]:
    return {"dev-400": _JUDGED, "dev-seal-400": (), "dev-seal-s3-400": (_SEALED,)}.get(name, ())


def _groups(path: Path, *, runs: Sequence[str] = (_RUN,)) -> Path:
    data = {
        "sample": "dev-400",
        "runs": [{"run_id": r, "arm": "C"} for r in runs],
        "groups": {
            "arm C": {
                "always wrong": [*_A, *_B, _F],
                "always right": [*_C, _D],
                "flipping": [],
            }
        },
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1) + "\n")
    return path


@pytest.fixture
def runs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Run a under the runs folder, the processed file, and the sample lists."""
    folder = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(folder))
    monkeypatch.setattr(samples, "sample_ids", _sample_ids)
    cases = _cases()
    _processed(tmp_path, [*_POOL, *_judged_rows(cases)])
    _write_run(folder, _RUN, cases)
    return folder


@pytest.fixture
def groups(runs: Path) -> Path:
    return _groups(runs / "s3-case-groups" / "20261002T065520" / "groups.json")


def _main(groups: Path, *extra: str, now: Callable[[], datetime] = lambda: _WHEN) -> int:
    return pages.main(["--run", _RUN, "--groups", str(groups), *extra], now=now)


_TICKS = itertools.count()


def _write(groups: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> Path:
    """Write the page under the runs folder, each call a second later; return its folder."""
    when = _WHEN + timedelta(seconds=next(_TICKS))
    assert pages.main(["--run", _RUN, "--groups", str(groups), *extra], now=lambda: when) == 0
    printed = capsys.readouterr().out.strip()
    return groups.parents[2] / printed


def _page(groups: Path, capsys: pytest.CaptureFixture[str], *extra: str) -> str:
    return (_write(groups, capsys, *extra) / pages.PAGE_FILE).read_text(encoding="utf-8")


def _manifest(groups: Path, capsys: pytest.CaptureFixture[str]) -> dict[str, object]:
    folder = _write(groups, capsys)
    data = json.loads((folder / pages.MANIFEST_FILE).read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _section(page: str, case_id: str) -> str:
    """A case's section, by its case id or by its anchor (``A1``: the first case of set A)."""
    found = re.search(rf'<h2 id="{case_id}">|: {case_id}</h2>', page)
    assert found is not None, case_id
    end = page.find("<h2", found.end())
    return page[found.start() : end if end != -1 else len(page)]


def _chip(state: str, text: str) -> str:
    return f'<span class="mk mk-{state}">{html.escape(text)}</span> '


# --------------------------------------------------------------------------------------------
# The draw
# --------------------------------------------------------------------------------------------

_KINDS = {f"ZQF{n}": True for n in range(6)} | {f"ZQN{n}": False for n in range(6)}


def _kinds(ids: Sequence[str]) -> list[bool]:
    return [_KINDS[i] for i in ids]


class TestDraw:
    def test_counts_and_the_alternation_fatal_first(self) -> None:
        drawn = pages.draw(list(_KINDS), _KINDS, wanted=10, seed=_SEED, letter="A")
        assert len(drawn) == 10
        assert _kinds(drawn) == [True, False] * 5

    def test_an_odd_count_gives_the_extra_case_to_the_fatal_kind(self) -> None:
        drawn = pages.draw(list(_KINDS), _KINDS, wanted=5, seed=_SEED, letter="B")
        assert _kinds(drawn) == [True, False, True, False, True]

    def test_once_one_kind_runs_out_the_other_alone_fills_the_count(self) -> None:
        ids = ["ZQF0", "ZQF1", "ZQF2", "ZQF3", "ZQN0"]
        assert _kinds(pages.draw(ids, _KINDS, wanted=4, seed=_SEED, letter="A")) == [
            True,
            False,
            True,
            True,
        ]
        ids = ["ZQF0", "ZQN0", "ZQN1", "ZQN2"]
        assert _kinds(pages.draw(ids, _KINDS, wanted=4, seed=_SEED, letter="A")) == [
            True,
            False,
            False,
            False,
        ]

    def test_the_generator_is_seeded_by_seed_and_letter_and_shuffles_sorted_ids(self) -> None:
        rng = random.Random(f"{_SEED}:C")  # noqa: S311 -- the draw's own generator
        fatal = sorted(i for i in _KINDS if _KINDS[i])
        nonfatal = sorted(i for i in _KINDS if not _KINDS[i])
        rng.shuffle(fatal)
        rng.shuffle(nonfatal)
        expected = tuple(x for pair in zip(fatal[:3], nonfatal[:3], strict=True) for x in pair)
        shuffled = list(reversed(list(_KINDS)))  # the input's order does not matter
        assert pages.draw(shuffled, _KINDS, wanted=6, seed=_SEED, letter="C") == expected

    def test_the_same_seed_draws_the_same_cases_and_each_set_has_its_own_generator(self) -> None:
        def drawn(seed: int, letter: str) -> tuple[str, ...]:
            return pages.draw(list(_KINDS), _KINDS, wanted=4, seed=seed, letter=letter)

        assert drawn(_SEED, "A") == drawn(_SEED, "A")
        assert len({drawn(_SEED, letter) for letter in "ABC"} | {drawn(1, "A")}) > 1

    def test_fewer_than_asked_are_all_taken_and_none_gives_none(self) -> None:
        ids = ["ZQF0", "ZQN0", "ZQN1"]
        assert sorted(pages.draw(ids, _KINDS, wanted=5, seed=_SEED, letter="C")) == ids
        assert pages.draw([], _KINDS, wanted=5, seed=_SEED, letter="C") == ()

    def test_the_page_shows_a_set_fatal_first_each_kind_sorted(self) -> None:
        assert pages.page_order(["ZQN1", "ZQF2", "ZQN0", "ZQF0"], _KINDS) == (
            "ZQF0",
            "ZQF2",
            "ZQN0",
            "ZQN1",
        )


# --------------------------------------------------------------------------------------------
# The marks and the shared words
# --------------------------------------------------------------------------------------------


class TestPrecedentMark:
    @pytest.mark.parametrize(
        ("sequence", "mark"),
        [
            (("402192",), pages.SAME),
            (("402192", "500241"), pages.SAME),
            (("500192",), pages.SAME_EVENT),
            (("300230", "402192"), pages.IN_SEQUENCE),
            (("552241", "500241"), pages.DIFFERENT),
            (("402241",), pages.DIFFERENT),  # the same phase is not a near match
        ],
    )
    def test_each_mark(self, sequence: tuple[str, ...], mark: Mark) -> None:
        assert pages.precedent_mark(sequence, "402192") == mark

    def test_the_same_event_wins_over_in_its_sequence(self) -> None:
        assert pages.precedent_mark(("500192", "402192"), "402192") == pages.SAME_EVENT

    def test_the_words_and_colours(self) -> None:
        assert (pages.SAME.state, pages.SAME.text) == ("match", "✓ same first code")
        assert (pages.SAME_EVENT.state, pages.SAME_EVENT.text) == (
            "near",
            "≈ same event, other phase",
        )
        assert (pages.IN_SEQUENCE.state, pages.IN_SEQUENCE.text) == (
            "near",
            "↕ in its sequence, not first",
        )
        assert (pages.DIFFERENT.state, pages.DIFFERENT.text) == ("miss", "✗ different")


class TestSharedWords:
    def test_stop_words_are_never_bold_even_when_the_query_holds_them(self) -> None:
        query = ("the", "fuel", "and", "pump")  # not filtered: the text's side filters too
        assert pages.shared_pieces("The fuel and the pump.", query) == (
            "The ",
            pages.Bold("fuel"),
            " and the ",
            pages.Bold("pump"),
            ".",
        )

    def test_case_insensitive_and_the_text_keeps_its_own_case(self) -> None:
        assert pages.shared_pieces("FUEL Fuel fuel", pp.tokens("Fuel")) == (
            pages.Bold("FUEL"),
            " ",
            pages.Bold("Fuel"),
            " ",
            pages.Bold("fuel"),
        )

    def test_whole_words_only_as_the_tokeniser_cuts_them(self) -> None:
        pieces = pages.shared_pieces("fuels, the pilot's 100LL", pp.tokens("fuel pilot 100ll"))
        assert pieces == ("fuels, the ", pages.Bold("pilot"), "'s ", pages.Bold("100LL"))

    def test_the_pieces_join_back_to_the_text(self) -> None:
        text = "Brambleton, quillwort; (exhaustion) & more."
        pieces = pages.shared_pieces(text, pp.tokens("quillwort exhaustion more"))
        assert "".join(p.text if isinstance(p, pages.Bold) else p for p in pieces) == text

    def test_record_markup_is_escaped_first_and_never_bolded_into_a_tag_or_an_entity(self) -> None:
        text = '<b>fuel</b> & "x" &amp; amp'
        query = ("b", "fuel", "amp", "quot", "lt", "gt")
        rendered = pages.spans_html(pages.Spans(pages.shared_pieces(text, query), "Its cause"))
        assert rendered == (
            "<p><b>Its cause:</b> &lt;<b>b</b>&gt;<b>fuel</b>&lt;/<b>b</b>&gt; &amp; &quot;x&quot; "
            "&amp;<b>amp</b>; <b>amp</b></p>"
        )
        # Every tag on the page is one the page wrote, each bold piece letters and digits only.
        assert set(re.findall(r"</?[a-z]+", rendered)) == {"<p", "</p", "<b", "</b"}
        label, *bold = re.findall(r"<b>(.*?)</b>", rendered)
        assert label == "Its cause:"
        assert bold == ["b", "fuel", "b", "amp", "amp"]

    def test_a_spans_paragraph_renders_marks_as_the_trail_pages_chips(self) -> None:
        rendered = pages.spans_html(pages.Spans((pages.SAME, "402192: x <y>")))
        assert rendered == f"<p>{_chip('match', '✓ same first code')}402192: x &lt;y&gt;</p>"


# --------------------------------------------------------------------------------------------
# The search, as the page reads it
# --------------------------------------------------------------------------------------------


def _precedent(case_id: str, day: str, code: str, words: Sequence[str]) -> pp.Precedent:
    return pp.Precedent(case_id, date.fromisoformat(day), code, tuple(words))


class TestNearestAndEligible:
    POOL = (
        _precedent("ZQP001", "2010-01-01", "402192", ("fuel", "exhaustion")),
        _precedent("ZQP002", "2011-01-01", "552230", ("fuel",)),
        _precedent("ZQP003", "2012-01-01", "552230", ("ground", "loop")),
        _precedent("ZQP004", "2017-01-01", "402192", ("fuel", "exhaustion")),  # later
    )

    def test_nearest_is_the_probes_search_with_each_cases_score(self) -> None:
        index = pp.Index(self.POOL)
        day = date.fromisoformat(_DAY)
        found = pages.nearest(index, ("fuel", "exhaustion"), day)
        scores = index.scores(("fuel", "exhaustion"), day, "earlier")
        assert [p for p, _ in found] == list(index.search(("fuel", "exhaustion"), day, "earlier"))
        assert [p.case_id for p, _ in found] == ["ZQP001", "ZQP002"]  # not the later case
        assert all(score == scores[p.case_id] for p, score in found)

    def test_each_set_by_the_probes_measures(self) -> None:
        cases = {
            c.case_id: c
            for c in (
                _result("ZQW1", ("402192",), ("402341",), cause="fuel exhaustion"),  # found
                _result("ZQW2", ("500230",), ("552230",), cause="fuel"),  # not found
                _result("ZQW3", ("402192",), (), failed=True),  # no query: in no set
                _result("ZQR1", ("402192",), ("402192",), cause="fuel"),  # nearest 552230
                _result("ZQR2", ("552230",), ("552230",), cause="ground loop"),  # nearest right
            )
        }
        days = {i: date.fromisoformat(_DAY) for i in cases}
        groups: dict[pp.Group, Sequence[str]] = {
            "always wrong": ["ZQW1", "ZQW2", "ZQW3"],
            "always right": ["ZQR1", "ZQR2"],
        }
        sets = pages.eligible(cases, groups, pp.Index(self.POOL), days)
        assert sets == {"A": ("ZQW1",), "B": ("ZQW2",), "C": ("ZQR1",)}


# --------------------------------------------------------------------------------------------
# The whole page, on a synthetic run, groups and processed file
# --------------------------------------------------------------------------------------------


class TestSelectionOnThePage:
    def test_each_sets_counts_in_the_manifest(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sets = _manifest(groups, capsys)["sets"]
        assert isinstance(sets, dict)
        counts = {
            letter: (
                s["eligible"],
                s["eligible_fatal"],
                s["eligible_nonfatal"],
                s["shown"],
                s["shown_fatal"],
                s["shown_nonfatal"],
            )
            for letter, s in sets.items()
        }
        assert counts == {
            "A": (12, 6, 6, 10, 5, 5),
            "B": (7, 4, 3, 5, 3, 2),
            "C": (3, 1, 2, 3, 1, 2),
        }

    def test_the_cases_shown_are_the_draw_in_page_order_and_never_d_or_f(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        sets = _manifest(groups, capsys)["sets"]
        assert isinstance(sets, dict)
        fatal = {i: i in _FATAL for i in _JUDGED}
        for letter, ids, asked in (("A", _A, 10), ("B", _B, 5), ("C", _C, 5)):
            drawn = pages.draw(ids, fatal, wanted=asked, seed=_SEED, letter=letter)
            assert sets[letter]["cases"] == list(pages.page_order(drawn, fatal))
        shown = {i for s in sets.values() for i in s["cases"]}
        assert _D not in shown
        assert _F not in shown

    def test_the_page_order_matches_the_manifest_and_the_contents(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = _write(groups, capsys)
        page = (folder / pages.PAGE_FILE).read_text(encoding="utf-8")
        data = json.loads((folder / pages.MANIFEST_FILE).read_text(encoding="utf-8"))
        listed = [i for letter in "ABC" for i in data["sets"][letter]["cases"]]
        headed = re.findall(
            r"<h2 id=\"[ABC]\d+\">Set [ABC] \([^)]*\), case \d+ of \d+: (\w+)</h2>", page
        )
        assert headed == listed
        assert '<h2 id="A1">Set A (found), case 1 of 10: ' in page
        assert '<h2 id="C3">Set C (right but pointed away), case 3 of 3: ' in page
        assert '<li><a href="#B2">B2: ' in page

    def test_the_top_states_each_sets_counts_and_says_when_fewer_than_asked(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        page = _page(groups, capsys)
        top = page[: page.index("<h2")]
        assert "Eligible: 12 (6 fatal, 6 non-fatal); shown: 10 (5 fatal, 5 non-fatal)</li>" in top
        assert "Eligible: 7 (4 fatal, 3 non-fatal); shown: 5 (3 fatal, 2 non-fatal)</li>" in top
        assert (
            "Eligible: 3 (1 fatal, 2 non-fatal); shown: 3 (1 fatal, 2 non-fatal); fewer than the "
            "5 asked, so all are shown</li>"
        ) in top
        assert f"seeded &quot;{_SEED}:&lt;set letter&gt;&quot;" in top

    def test_the_same_arguments_write_the_same_page_and_another_seed_draws_again(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _page(groups, capsys) == _page(groups, capsys)  # two folders, the same page
        seeds = {
            json.dumps(pages.draw(_A, {i: i in _FATAL for i in _A}, wanted=10, seed=s, letter="A"))
            for s in (1, 2, 3)
        }
        assert len(seeds) > 1


class TestTheTop:
    def test_what_the_page_is_the_question_in_bold_and_the_search(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        page = _page(groups, capsys)
        top = page[: page.index("<h2")]
        assert "<title>S3.1 precedent reading page</title>" in page
        assert "A private reading aid" in top
        assert "commit 6dae045" in top
        assert "&quot;in between&quot;" in top
        assert "no number on it is cited" in top
        assert f"<b>{html.escape(pages.QUESTION)}</b>" in top
        assert pages.QUESTION.startswith("When the right code is among the five nearest")
        assert f"{_RUN} (arm C, dev-400)" in top
        assert "always wrong 20 (10 fatal, 10 non-fatal); always right 4 (1 fatal, 3 non" in top
        assert "BM25 (k1 = 1.2, b = 0.75)" in top

    def test_the_legend_shows_every_mark_with_its_words(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        page = _page(groups, capsys)
        top = page[: page.index("<h2")]
        for state, text in (
            ("match", "✓ match"),
            ("near", "↕ wrong place: the NTSB's rank k"),
            ("miss", "✗ not in the NTSB's"),
            ("match", "✓ same first code"),
            ("near", "≈ same event, other phase"),
            ("near", "↕ in its sequence, not first"),
            ("miss", "✗ different"),
        ):
            assert _chip(state, text) in top

    def test_one_self_contained_page_light_and_dark(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        page = _page(groups, capsys)
        assert "<script" not in page  # ZQP005's own <script> is escaped
        assert "&lt;script&gt;x&lt;/script&gt;" in page
        assert "http" not in page
        assert ":root{color-scheme:light dark;" in page
        assert '@media (prefers-color-scheme: dark){:root:not([data-theme="light"]){' in page
        assert ':root[data-theme="dark"]{' in page


class TestOneCase:
    """A1 and A10: found (every A case alike); B1: not found; C00, C01 and C02: five, four and
    one earlier cases."""

    def test_the_header(self, groups: Path, capsys: pytest.CaptureFixture[str]) -> None:
        case = _section(_page(groups, capsys), "A1")
        assert "<p><b>Event date:</b> 2016-06-01</p>" in case
        assert "<p><b>Injury:</b> fatal</p>" in case
        assert "<p><b>Injury:</b> non-fatal</p>" in _section(_page(groups, capsys), "A10")

    def test_the_ntsb_verdict_from_the_record_with_names_replaced(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        case = _section(_page(groups, capsys), "A1")
        verdict = case[case.index("The NTSB&#x27;s verdict") : case.index("The loop&#x27;s answer")]
        assert (
            "<ol><li>402192: Enroute-Cruise / Fuel exhaustion</li>"
            "<li>500241: Approach / Aerodynamic stall/spin</li></ol>"
        ) in verdict
        assert "<p><b>Probable cause:</b> Owner or operator let the tank run dry.</p>" in verdict
        assert _JUDGED_OWNER not in _page(groups, capsys)

    def test_the_loops_first_three_codes_marked_as_the_trail_pages_mark_them_and_the_query(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        case = _section(_page(groups, capsys), "A1")
        answer = case[case.index("The loop&#x27;s answer") : case.index("The five nearest")]
        not_in = _chip("miss", "✗ not in the NTSB's")
        wrong_place = _chip("near", "↕ wrong place: the NTSB's rank 1")
        match = _chip("match", "✓ match")
        assert (
            f"<ol><li>{not_in}402341: Enroute-Cruise / Loss of engine power (total) (p 0.30)</li>"
            f"<li>{match}500241: Approach / Aerodynamic stall/spin (p 0.30)</li>"
            f"<li>{wrong_place}402192: Enroute-Cruise / Fuel exhaustion (p 0.30)</li></ol>"
        ) in answer
        assert (
            "<p><b>The query (its probable cause):</b> The brambleton QUILLWORT exhaustion, said "
            "Owner or operator</p>"
        ) in answer

    def test_the_five_nearest_earlier_cases_in_rank_order(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        case = _section(_page(groups, capsys), "A1")
        ranks = re.findall(
            r"<h4>Rank (\d): BM25 (\d+\.\d\d), (ZQP\d+), (\d{4}-\d\d-\d\d)</h4>", case
        )
        assert [int(r[0]) for r in ranks] == [1, 2, 3, 4, 5]
        assert {r[2] for r in ranks} == {"ZQP001", "ZQP002", "ZQP003", "ZQP004", "ZQP005"}
        scores = [float(r[1]) for r in ranks]
        assert scores == sorted(scores, reverse=True)
        assert ("ZQP001", "2010-03-01") in {(r[2], r[3]) for r in ranks}
        # The later case and the sealed case, whose words are the query's, are never shown.
        assert "ZQP009" not in case
        assert _SEALED not in case

    def test_each_earlier_cases_first_code_is_marked_against_the_ntsb_first_code(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        case = _section(_page(groups, capsys), "A1")
        assert f"<li>{_chip('match', '✓ same first code')}402192: Enroute-Cruise / Fuel" in case
        assert f"<li>{_chip('near', '≈ same event, other phase')}500192: Approach / Fuel" in case
        assert (
            f"<ol><li>{_chip('near', '↕ in its sequence, not first')}300230: Takeoff / Loss of "
            "control on ground</li><li>402192: Enroute-Cruise / Fuel exhaustion</li></ol>"
        ) in case
        assert f"<li>{_chip('miss', '✗ different')}552241: " in case
        assert f"<li>{_chip('miss', '✗ different')}551092: " in case
        b_case = _section(_page(groups, capsys), "B1")
        assert f"<li>{_chip('near', '≈ same event, other phase')}300230: Takeoff" in b_case
        assert f"<li>{_chip('miss', '✗ different')}500192: " in b_case  # same phase only

    def test_shared_words_bold_names_replaced_with_the_earlier_cases_own_record(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        page = _page(groups, capsys)
        case = _section(page, "A1")
        assert (
            "<p><b>Its probable cause:</b> The <b>Brambleton</b> <b>quillwort</b> "
            "<b>exhaustion</b>, reported by Owner or operator.</p>"
        ) in case
        assert (
            "<p><b>Its probable cause:</b> <b>Brambleton</b> <b>quillwort</b> <b>exhaustion</b> "
            "in the Amateur-built.</p>"
        ) in case
        assert "<p><b>Its probable cause:</b> <b>Brambleton</b> <b>quillwort</b> ridge.</p>" in case
        assert _EARLIER_OWNER not in page
        assert _MAKE not in page

    def test_the_phase_aware_control_line(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        page = _page(groups, capsys)
        lead = (
            "<p><b>Phase-aware control: the five commonest first codes among earlier pool cases "
            "in phase {phase}, the phase of the loop&#x27;s first code:</b> "
        )
        assert (
            lead.format(phase="402 (Enroute-Cruise)")
            + f"{_chip('match', '✓ same first code')}402192: Enroute-Cruise / Fuel exhaustion</p>"
        ) in _section(page, "A1")
        assert (
            lead.format(phase="552 (Landing-Landing Roll)")
            + f"{_chip('near', '≈ same event, other phase')}552230: Landing-Landing Roll / Loss "
            f"of control on ground; {_chip('miss', '✗ different')}552241: Landing-Landing Roll / "
            "Aerodynamic stall/spin</p>"
        ) in _section(page, "B1")
        assert (
            lead.format(phase="552 (Landing-Landing Roll)")
            + f"{_chip('match', '✓ same first code')}552230: "
        ) in _section(page, "ZQC00")

    def test_fewer_than_five_earlier_cases_is_said(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        case = _section(_page(groups, capsys), "ZQC02")
        assert "<p>1 earlier case(s) share a word with the query; no more.</p>" in case
        assert len(re.findall(r"<h4>Rank ", case)) == 1
        assert "ZQP004" in case
        page = _page(groups, capsys)
        assert "<p>4 earlier case(s) share a word with the query; no more.</p>" in _section(
            page, "ZQC01"
        )
        assert "share a word with the query; no more" not in _section(page, "ZQC00")


# --------------------------------------------------------------------------------------------
# The output and the manifest
# --------------------------------------------------------------------------------------------


class TestOutput:
    def test_the_page_and_manifest_go_under_the_runs_folder_and_only_the_folder_is_printed(
        self, groups: Path, runs: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert pages.main(["--run", _RUN, "--groups", str(groups)], now=lambda: _WHEN) == 0
        assert capsys.readouterr().out == f"s3-precedent-pages/{_STAMP}\n"
        folder = runs / "s3-precedent-pages" / _STAMP
        assert sorted(p.name for p in folder.iterdir()) == ["cases.json", "precedents.html"]

    def test_an_out_dir_elsewhere_is_used_and_printed_relative_to_its_parent(
        self, groups: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        out = tmp_path / "elsewhere" / "pages"
        argv = ["--run", _RUN, "--groups", str(groups), "--out-dir", str(out)]
        assert pages.main(argv, now=lambda: _WHEN) == 0
        assert capsys.readouterr().out == f"pages/{_STAMP}\n"
        assert (out / _STAMP / pages.PAGE_FILE).is_file()

    def test_an_out_dir_inside_the_repository_is_refused_before_the_run_is_read(
        self, groups: Path
    ) -> None:
        inside = Path(__file__).resolve().parents[1] / "docs" / "zz-precedent-pages-test"
        argv = ["--run", "20260101T000000-abc1234-heldout-400-C", "--groups", str(groups)]
        with pytest.raises(SystemExit, match="inside the repository"):
            pages.main([*argv, "--out-dir", str(inside)], now=lambda: _WHEN)
        assert not inside.exists()

    def test_a_second_page_in_the_same_second_is_refused(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert _main(groups) == 0
        with pytest.raises(SystemExit, match="already exists"):
            _main(groups)

    def test_the_manifest(self, groups: Path, capsys: pytest.CaptureFixture[str]) -> None:
        data = _manifest(groups, capsys)
        assert {k: v for k, v in data.items() if k != "sets"} == {
            "manifest": "s3_precedent_pages",
            "sample": "dev-400",
            "run": _RUN,
            "groups": str(groups.resolve()),
            "seed": _SEED,
            "query": "probable cause",
            "pool": "earlier",
            "group_cases": {"always wrong": 20, "always right": 4},
        }
        sets = data["sets"]
        assert isinstance(sets, dict)
        assert {k: (v["name"], v["group"], v["asked"]) for k, v in sets.items()} == {
            "A": ("found", "always wrong", 10),
            "B": ("not found", "always wrong", 5),
            "C": ("right but pointed away", "always right", 5),
        }
        assert sets["C"]["cases"] == ["ZQC02", "ZQC00", "ZQC01"]  # fatal first, then sorted

    def test_the_seed_is_recorded_and_changes_nothing_else(
        self, groups: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        folder = _write(groups, capsys, "--seed", "7")
        data = json.loads((folder / pages.MANIFEST_FILE).read_text(encoding="utf-8"))
        assert data["seed"] == 7
        fatal = {i: i in _FATAL for i in _JUDGED}
        drawn = pages.draw(_A, fatal, wanted=10, seed=7, letter="A")
        assert data["sets"]["A"]["cases"] == list(pages.page_order(drawn, fatal))


# --------------------------------------------------------------------------------------------
# Refusals
# --------------------------------------------------------------------------------------------


class TestRefusals:
    def test_an_arm_b_run_is_refused_through_the_probes_loader(
        self, runs: Path, groups: Path
    ) -> None:
        _write_run(runs, _RUN, _cases(), arm="B")
        with pytest.raises(SystemExit, match="arm B; the precedent probe reads arm C runs only"):
            _main(groups)

    def test_a_held_out_run_id_is_refused(self, groups: Path) -> None:
        with pytest.raises(SystemExit, match="held-out"):
            pages.main(["--run", "20260101T000000-abc1234-heldout-400-C", "--groups", str(groups)])

    def test_an_unfinished_run_is_refused(self, runs: Path, groups: Path) -> None:
        _write_run(runs, _RUN, _cases(), finished=None)
        with pytest.raises(SystemExit, match="has not finished"):
            _main(groups)

    def test_a_groups_file_not_drawn_over_the_run_is_refused(
        self, runs: Path, tmp_path: Path
    ) -> None:
        other = _groups(tmp_path / "other" / "groups.json", runs=(_OTHER,))
        with pytest.raises(SystemExit, match=f"was not drawn over run {_RUN}"):
            _main(other)

    def test_a_group_case_the_run_does_not_hold_is_refused(self, groups: Path) -> None:
        data = json.loads(groups.read_text())
        data["groups"]["arm C"]["always wrong"].append("ZQX999")
        groups.write_text(json.dumps(data))
        with pytest.raises(SystemExit, match="do not hold 1 case"):
            _main(groups)

    def test_a_case_with_no_ntsb_occurrence_code_is_refused(self, runs: Path, groups: Path) -> None:
        cases = _cases()
        cases[-1] = cases[-1].model_copy(update={"verdict_occurrence": ()})
        _write_run(runs, _RUN, cases)
        with pytest.raises(SystemExit, match="no NTSB occurrence code"):
            _main(groups)

    def test_a_judged_record_of_another_case_is_refused(
        self, groups: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = samples.load_cases

        def swapped(processed: Path, ids: Sequence[str]) -> list[dict[str, object]]:
            raws = real(processed, ids)
            return [dict(r, ntsbNumber="ZQZ000") if r["ntsbNumber"] == "ZQC02" else r for r in raws]

        monkeypatch.setattr(samples, "load_cases", swapped)
        with pytest.raises(SystemExit, match="ZQC02: the record read for it is ZQZ000's"):
            _main(groups)

    def test_an_earlier_record_that_is_not_the_one_ranked_is_refused(
        self, groups: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = samples.load_cases

        def changed(processed: Path, ids: Sequence[str]) -> list[dict[str, object]]:
            raws = real(processed, ids)
            return [
                _raw("ZQP004", "2013-03-01", "Other words.", ("552241",))
                if r["ntsbNumber"] == "ZQP004"
                else r
                for r in raws
            ]

        monkeypatch.setattr(samples, "load_cases", changed)
        with pytest.raises(SystemExit, match="ZQP004: the record read for it is not the case"):
            _main(groups)

    def test_nothing_is_written_when_a_case_is_refused(
        self, groups: Path, runs: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def broken(processed: Path, ids: Sequence[str]) -> list[dict[str, object]]:
            return [_raw(i, "2021-01-01", "x", ("552230",)) for i in ids]  # held-out dates

        monkeypatch.setattr(samples, "load_cases", broken)
        with pytest.raises(SystemExit, match="outside the development split"):
            _main(groups)
        assert not (runs / "s3-precedent-pages").exists()


def test_the_phase_codes_are_the_probes_phase_aware_control() -> None:
    """The page's line and the probe's count read one function."""
    index = pp.Index(TestNearestAndEligible.POOL)
    day = date.fromisoformat(_DAY)
    answered = _result("ZQR1", ("402192",), ("552241",), cause="fuel")
    assert pp.phase_codes(index, answered, day, "earlier") == ("552230",)
    assert pp.phase_control(index, answered, day, "earlier") is False
    failed = _result("ZQW3", ("552230",), (), failed=True)
    assert pp.phase_codes(index, failed, day, "earlier") == ()
    assert pp.phase_control(index, failed, day, "earlier") is False
