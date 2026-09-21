"""The narrative-coverage scan measures the gap decision 0050's sentence exemption leaves."""

from scripts.narrative_coverage import BANDS, Coverage, _matched, _sentence_needles, report

NARRATIVE = (
    "The airplane departed the runway during the takeoff roll. "
    "The pilot reported that the engine lost power shortly after rotation. "
    "A postaccident examination found the fuel selector in the off position."
)


def test_an_exact_copy_of_the_narrative_matches_every_sentence() -> None:
    """A document reproducing the narrative verbatim covers all of its sentences."""
    needles = _sentence_needles(NARRATIVE)
    assert len(needles) == 3
    assert _matched(NARRATIVE, NARRATIVE) == needles


def test_dropping_one_sentence_still_leaves_the_rest_matched() -> None:
    """The shape of the gap: a near-complete copy, which no whole-text needle catches."""
    without_last = NARRATIVE.rsplit(" A postaccident", maxsplit=1)[0]
    matched = _matched(without_last, NARRATIVE)
    assert len(matched) == 2
    assert len(matched) < len(_sentence_needles(NARRATIVE))


def test_an_unrelated_document_matches_nothing() -> None:
    """A document sharing no sentence with the narrative covers none of it."""
    assert _matched("Weather at the time was clear with light winds.", NARRATIVE) == set()


def test_report_states_its_denominator_and_every_band() -> None:
    """A reader must be able to tell a complete scan from a partial one."""
    result = Coverage(cases=2, skipped=3, no_narrative=1)
    result.shares = [0.1, 0.95]
    result.best_document_shares = [0.1, 0.95]
    for band in BANDS:
        if band <= 0.95:
            result.band_cases[band] += 1
            result.band_documents[band] += 1
    text = report(result, "dev-400")
    assert "2 cases measured" in text
    assert "3 skipped" in text
    assert "1 with no factual narrative" in text
    for band in BANDS:
        assert f"  {band:.0%}  whole docket" in text


def test_report_on_an_empty_sweep_states_the_counts_and_no_quantiles() -> None:
    """Zero measured cases must not raise, and must not print an empty distribution."""
    text = report(Coverage(), "dev-400")
    assert "0 cases measured" in text
    assert "median" not in text
