import hashlib
import json
import re
from collections import Counter
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts.corpus_scan import (
    THRESHOLD_LINE,
    _evidence_gap,
    choose_threshold,
    docket_hits,
    docket_main,
    docket_report,
    duplication_share,
    has_missed_break,
    has_nonempty_prelim_narrative,
    is_amateur_built,
    later_probable_cause_differs,
    leak_kinds,
    missed_break_sources,
    model_contains_make,
    multi_aircraft_with_codes,
    narratives_count,
    raw_aircraft_make,
    raw_aircraft_model,
)
from tests.test_attach import _docket as small_docket

from ntsb_probable_cause import fields
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.records import guard
from ntsb_probable_cause.scoring import samples

RESULTS = Path("docs/results/s0-corpus-scan.txt")


def test_choose_threshold_picks_smallest_length_with_zero_hits() -> None:
    assert choose_threshold({10: 4, 20: 0, 40: 0, 80: 0}) == 20
    assert choose_threshold({10: 0, 20: 0}) == 10
    assert choose_threshold({10: 3, 20: 1}) is None


def test_duplication_share_counts_long_analysis_sentences_found_in_factual() -> None:
    factual = (
        "The pilot reported a loss of engine power during cruise. The airplane landed in a field."
    )
    analysis = (
        "The pilot reported a loss of engine power during cruise. "
        "Examination revealed no anomalies at all."
    )
    assert duplication_share(analysis, factual) == pytest.approx(0.5)
    assert duplication_share(None, factual) == 0.0


def test_fixtures_have_no_leaks_at_any_candidate_length(
    record_fixtures: list[dict[str, object]],
) -> None:
    for raw in record_fixtures:
        for length in (10, 20, 40, 80):
            assert leak_kinds(raw, length) == {}, raw["ntsbNumber"]


def test_guard_threshold_is_the_value_the_scan_recorded() -> None:
    lines = [line for line in RESULTS.read_text().splitlines() if line.startswith(THRESHOLD_LINE)]
    assert len(lines) == 1
    assert int(re.sub(r"\D", "", lines[0])) == guard.MIN_SENTENCE_CHARS


# --- Item F: tripwire coverage limits, fixed in S2 (pure functions, no I/O) ---


def test_has_missed_break_after_a_closing_quote_then_space() -> None:
    assert has_missed_break('He said "stop." The pilot continued.') is True


def test_has_missed_break_after_bold_markers_then_space() -> None:
    assert has_missed_break("engine failure.** The pilot continued.") is True


def test_has_missed_break_after_a_closing_paren_then_space() -> None:
    assert has_missed_break("(see note).) The pilot continued.") is True


def test_has_missed_break_after_a_semicolon_with_no_space() -> None:
    assert has_missed_break("the powerplant;the pilot continued") is True


def test_has_missed_break_is_false_for_an_ordinary_sentence_boundary() -> None:
    assert has_missed_break("The engine lost power. The pilot continued.") is False


def test_missed_break_sources_names_only_the_texts_with_a_missed_break() -> None:
    raw = {
        "narratives": [
            {
                "concatenatedFactualNarrative": 'He said "stop." The pilot continued.',
                "analysisNarrative": "The engine lost power. The pilot continued.",
                "probableCause": "the powerplant;the pilot's inaction.",
            }
        ]
    }
    assert missed_break_sources(raw) == ["factual", "probable_cause"]


def test_narratives_count_reads_the_narratives_list_length() -> None:
    assert narratives_count({"narratives": [{}, {}]}) == 2
    assert narratives_count({"narratives": [{}]}) == 1
    assert narratives_count({}) == 0


def test_later_probable_cause_differs_only_when_a_later_entry_disagrees() -> None:
    same = {
        "narratives": [{"probableCause": "Engine failure."}, {"probableCause": "Engine failure."}]
    }
    different = {
        "narratives": [{"probableCause": "Engine failure."}, {"probableCause": "Pilot error."}]
    }
    assert later_probable_cause_differs(same) is False
    assert later_probable_cause_differs(different) is True
    assert (
        later_probable_cause_differs({"narratives": [{"probableCause": "Engine failure."}]})
        is False
    )


def test_multi_aircraft_with_codes_requires_more_than_one_aircraft_carrying_a_code() -> None:
    one_coded = {
        "aircrafts": [
            {"events": [{"eventCode": "500"}]},
            {"events": [], "findings": []},
        ]
    }
    two_coded = {
        "aircrafts": [
            {"events": [{"eventCode": "500"}]},
            {"findings": [{"findingCode": "22500"}]},
        ]
    }
    assert multi_aircraft_with_codes(one_coded) is False
    assert multi_aircraft_with_codes(two_coded) is True


def test_has_nonempty_prelim_narrative_reads_every_narratives_entry() -> None:
    assert has_nonempty_prelim_narrative({"narratives": [{"prelimNarrative": "  "}]}) is False
    assert (
        has_nonempty_prelim_narrative({"narratives": [{"prelimNarrative": "Some text."}]}) is True
    )
    assert (
        has_nonempty_prelim_narrative(
            {"narratives": [{}, {"prelimNarrative": "Later entry text."}]}
        )
        is True
    )


# --- amateur-built aircraft (decision 0020) — pure functions ---


def test_is_amateur_built_reads_the_flag() -> None:
    assert is_amateur_built({"aircrafts": [{"aircraftAmateurBuilt": True}]}) is True
    assert is_amateur_built({"aircrafts": [{"aircraftAmateurBuilt": False}]}) is False
    assert is_amateur_built({"aircrafts": [{}]}) is False
    assert is_amateur_built({}) is False


def test_is_amateur_built_fails_closed_for_a_non_boolean_flag() -> None:
    """Agrees with fields.py's fail-closed rule: only `False`/absent/`None` is not amateur-built."""
    assert is_amateur_built({"aircrafts": [{"aircraftAmateurBuilt": "true"}]}) is True
    assert is_amateur_built({"aircrafts": [{"aircraftAmateurBuilt": 1}]}) is True


def test_raw_aircraft_make_and_model_read_the_recorded_values() -> None:
    raw = {"aircrafts": [{"aircraftMake": "INVENTED BUILDER", "aircraftModel": "  "}]}
    assert raw_aircraft_make(raw) == "INVENTED BUILDER"
    assert raw_aircraft_model(raw) is None


def test_model_contains_make_is_case_insensitive() -> None:
    assert model_contains_make("Vans", "RV-8 Vans Kit") is True
    assert model_contains_make("Vans", "rv-8 vans kit") is True
    assert model_contains_make("Vans", "RV-8") is False
    assert model_contains_make(None, "RV-8") is False
    assert model_contains_make("Vans", None) is False


def test_all_fixtures_have_no_missed_break_prelim_or_multi_aircraft_codes(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Sanity check: the scan's new counters are all pure functions of the raw record."""
    for raw in record_fixtures:
        assert isinstance(missed_break_sources(raw), list)
        assert isinstance(narratives_count(raw), int)
        assert isinstance(later_probable_cause_differs(raw), bool)
        assert isinstance(multi_aircraft_with_codes(raw), bool)
        assert isinstance(has_nonempty_prelim_narrative(raw), bool)


# --- docket mode (spec §8.2, §8.3): the threshold on docket text, then the filter measurement ---


def test_docket_hits_finds_a_withheld_sentence_in_a_document(
    record_fixtures: list[dict[str, object]],
) -> None:
    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    narrative = fields.factual_narrative(raw) or ""
    docket = small_docket({1: f"[page 1 of 3]\n{narrative}\n"})
    hits = docket_hits(raw, docket, min_sentence_chars=20)
    assert hits["exam_site/text"] >= 1


def test_docket_report_names_the_threshold_and_the_filter_table() -> None:
    hits = {10: Counter({"exam_site/sentence": 2}), 20: Counter(), 40: Counter(), 80: Counter()}
    text = docket_report(hits, cases=3, documents=7)
    assert f"{THRESHOLD_LINE}20" in text
    assert "misses" in text
    assert "false denies" in text


# --- fix round 1 (spec-compliance review): findings 1, 2, 3, 5 ---


def _docket_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, mkey: int) -> Path:
    """One dev-400 case pointing at ``mkey``, no cached docket. Returns the docket cache dir.

    Mirrors ``tests/test_eval_app.py``'s ``_eval_env`` helper: ``samples.sample_ids("dev-400")``
    and ``samples.load_cases`` read from committed, non-overridable-by-env paths, so the sample
    and the processed file are pointed at a temporary fixture instead.
    """
    raw = {"ntsbNumber": "TEST0001", "mKey": mkey}
    ids_dir = tmp_path / "eval_ids"
    ids_dir.mkdir()
    (ids_dir / "dev_ids.csv").write_text("case_id,event_date\nTEST0001,2015-01-01\n")
    monkeypatch.setattr(samples, "EVAL_DIR", ids_dir)
    monkeypatch.setitem(samples._FILES, "dev-400", "dev_ids.csv")

    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    table = pa.table(
        {
            "ntsb_number": pa.array(["TEST0001"], type=pa.string()),
            "raw_json": pa.array([json.dumps(raw)], type=pa.string()),
        }
    )
    pq.write_table(table, processed / "cases.parquet")

    docket_dir = tmp_path / "docket"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NTSB_DOCKET_DIR", str(docket_dir))
    return docket_dir


def test_evidence_gap_flags_no_cases_no_documents_and_an_inconclusive_sweep() -> None:
    """Finding 2: zero cached dockets or zero readable documents must not state a threshold."""
    empty: dict[int, Counter[str]] = {length: Counter() for length in (10, 20, 40, 80)}
    assert _evidence_gap(empty, cases=0, documents=0) is not None
    assert _evidence_gap(empty, cases=1, documents=0) is not None
    inconclusive = {10: Counter({"a/text": 1}), 20: Counter({"a/text": 1})}
    assert _evidence_gap(inconclusive, cases=1, documents=1) is not None
    assert _evidence_gap(empty, cases=1, documents=1) is None


def test_docket_report_refuses_a_threshold_with_no_cached_dockets() -> None:
    """Finding 2, reproduced: 0 cases trivially gives zero hits at every length."""
    empty: dict[int, Counter[str]] = {length: Counter() for length in (10, 20, 40, 80)}
    text = docket_report(empty, cases=0, documents=0)
    assert f"{THRESHOLD_LINE}not measured" in text
    assert "no dev-400 case has a cached" in text


def test_docket_report_refuses_a_threshold_with_zero_readable_documents() -> None:
    """Finding 2, reproduced with the exact shape seen against the real, empty dev cache."""
    empty: dict[int, Counter[str]] = {length: Counter() for length in (10, 20, 40, 80)}
    text = docket_report(empty, cases=1, documents=0)
    assert f"{THRESHOLD_LINE}not measured" in text
    assert "no readable document" in text


def test_docket_report_shows_hits_at_every_length_not_only_the_chosen_one() -> None:
    """Finding 1, reproduced: hits at 10 and 20, none at 40 or 80. The old code computed the
    filter table at the chosen length (40, the smallest with zero hits) and so always printed
    an empty table there. The category that tripped must stay visible, under the guard's own
    operating threshold (20), which is marked as the table in force.
    """
    hits = {
        10: Counter({"exam_site/sentence": 2}),
        20: Counter({"exam_site/sentence": 1}),
        40: Counter(),
        80: Counter(),
    }
    text = docket_report(hits, cases=5, documents=9)
    assert f"{THRESHOLD_LINE}40" in text
    assert "20 *** table in force ***:" in text
    forced_start = text.index("20 *** table in force ***:")
    forced_end = text.index("\n40:", forced_start)
    assert "exam_site" in text[forced_start:forced_end]


def test_docket_hits_also_checks_the_listing_text(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Finding 3: attach_docket also renders docket.listing, and production split_record checks
    EvidenceRole.DOCKET_LISTING -- a hit there must be visible, under its own pseudo-category.
    """
    raw = next(r for r in record_fixtures if fields.probable_cause(r) and not is_amateur_built(r))
    cause = fields.probable_cause(raw) or ""
    entry = ListingEntry(
        index=1,
        title=f"Cover sheet: {cause}",
        pages=1,
        photos=0,
        doc_type="Report",
        extension="pdf",
        href="/x",
    )
    listing = Listing(mkey=1, declared_items=1, entries=(entry,))
    record = DocumentRecord(
        entry=entry,
        category="other",
        status="unreadable: scan",
        pages=1,
        readable_pages=0,
        estimated_tokens=0,
        kind="scan",
    )
    docket = Docket(mkey=1, listing=listing, documents=(record,), texts={})
    hits = docket_hits(raw, docket, min_sentence_chars=20)
    assert hits["listing/text"] >= 1


def test_docket_main_counts_a_missing_cache_entry_as_not_cached_with_no_refusal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Finding 5: a genuinely missing cache entry is caught by docket_main's own is_file()
    check before read_docket is ever called, so it never reaches the network-refusing
    transport -- counted as not cached, never as a refusal.
    """
    _docket_env(tmp_path, monkeypatch, mkey=424242)
    assert docket_main(None) == 1  # no evidence: refuses to state a threshold
    out = capsys.readouterr().out
    assert "not cached (skipped, never fetched): 1 of 1" in out
    assert "refused network requests (blocked by the transport, never sent): 0" in out


def test_docket_main_refuses_rather_than_fetches_an_unverifiable_cached_listing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Finding 5: a listing.html on disk with no matching, hash-verified fetch.json entry
    cannot be trusted as a real cache hit; DocketClient falls through to a live request, which
    the transport refuses -- counted separately from a genuinely missing entry.
    """
    docket_dir = _docket_env(tmp_path, monkeypatch, mkey=424242)
    case_dir = docket_dir / "424242"
    case_dir.mkdir(parents=True)
    (case_dir / "listing.html").write_text("<html>not really cached</html>")
    assert docket_main(None) == 1
    out = capsys.readouterr().out
    assert "not cached (skipped, never fetched): 0 of 1" in out
    assert "refused network requests (blocked by the transport, never sent): 1" in out


def test_docket_main_counts_a_refused_document_fetch_separately_from_a_cache_hit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Finding 5's observability gap: read_docket swallows a per-document DocketError as an
    ordinary 'fetch failed' status. A verified, cached listing (served with no request) plus
    zero cached documents proves every one of its readable-looking entries is counted as
    refused, not silently dropped from the measured population.
    """
    mkey = 424242
    docket_dir = _docket_env(tmp_path, monkeypatch, mkey=mkey)
    listing_bytes = Path("tests/fixtures/docket/ERA17LA217/listing.html").read_bytes()
    case_dir = docket_dir / str(mkey)
    case_dir.mkdir(parents=True)
    (case_dir / "listing.html").write_bytes(listing_bytes)
    digest = hashlib.sha256(listing_bytes).hexdigest()
    (case_dir / "fetch.json").write_text(
        json.dumps({"listing": {"time": "2026-01-01T00:00:00+00:00", "sha256": digest}})
    )
    assert docket_main(None) == 1  # zero readable documents: still no evidence
    out = capsys.readouterr().out
    assert "not cached (skipped, never fetched): 0 of 1" in out
    # Four non-photo PDF entries in the real fixture listing, none of them cached: every one is
    # refused rather than silently counted as an ordinary fetch failure.
    assert "refused network requests (blocked by the transport, never sent): 4" in out
