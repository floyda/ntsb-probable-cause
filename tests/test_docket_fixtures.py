"""Docket fixtures: development cases only, listing pages as received (decision 0037)."""

import argparse
import copy
import csv
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from datetime import date
from pathlib import Path

import httpx
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import respx
import scripts.make_docket_fixture as mdf
from scripts.make_docket_fixture import (  # noqa: F401 -- interface import, exercised by Step 4.
    CRITERIA,
    DOCUMENT_ALLOWED_CATEGORIES,
    _cmd_document,
    _cmd_handcheck,
    _fetch_listing,
    _stratified_sample,
    first_dev_400_case,
    outcome_only,
    redact_text,
    write_listing_fixture,
)
from tests.test_docket_manifest import _text_pdf

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.attach import OWNER_OPERATOR_LABEL
from ntsb_probable_cause.docket.classify import Kind
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord, Status
from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.fields import AMATEUR_BUILT_LABEL
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split, split_of

DOCKET_FIXTURES = Path("tests/fixtures/docket")


def docket_fixture_dirs() -> list[Path]:
    return sorted(p for p in DOCKET_FIXTURES.iterdir() if p.is_dir())


def test_at_least_one_listing_fixture_exists() -> None:
    assert docket_fixture_dirs(), "Task 6 commits the first listing fixture"


def test_every_docket_fixture_has_a_listing_and_a_manifest() -> None:
    for folder in docket_fixture_dirs():
        assert (folder / "listing.html").is_file(), folder
        manifest = json.loads((folder / "manifest.json").read_text())
        assert manifest["fixture"]["case_id"] == folder.name
        assert split_of(date.fromisoformat(manifest["fixture"]["event_date"])) is Split.DEV


def test_the_listing_fixture_is_byte_exact_as_received() -> None:
    """A normalised fixture would let the parser be written against a page the NTSB never sent.

    The listing pages this project fetches come back with CRLF line endings; committing a
    fixture that has been rewritten to LF-only (by an editor, or by a pre-commit hook that
    was not told to leave this tree alone) would let a parser regular expression pass every
    test here and still meet CRLF text on every real fetch. Reading as bytes, not text, is
    the point: a text-mode read can itself normalise line endings and hide the very thing
    this test exists to catch.
    """
    for folder in docket_fixture_dirs():
        data = (folder / "listing.html").read_bytes()
        assert b"\r\n" in data, folder
        manifest = json.loads((folder / "manifest.json").read_text())
        assert manifest["fixture"]["sha256"] == hashlib.sha256(data).hexdigest()


def test_fetching_a_held_out_case_makes_no_http_call(
    tmp_path: Path, respx_mock: respx.MockRouter
) -> None:
    """Decisions 0026, 0037: the thing to prevent is the look, not merely the commit.

    A refusal that happens only inside ``write_listing_fixture``, after the page has
    already been fetched and cached, would satisfy "never committed" while still
    violating "never looked at". The guard has to sit before ``DocketClient`` is even
    constructed, on every path that resolves a case -- so the route must never be called.
    """
    route = respx_mock.get(sources.docket_url(1)).mock(return_value=httpx.Response(200, text="x"))
    with pytest.raises(FixtureError, match="2021"):
        _fetch_listing("X", 1, "2021-05-01", Settings(docket_dir=tmp_path))
    assert route.call_count == 0


def test_write_listing_fixture_refuses_a_held_out_case(tmp_path: Path) -> None:
    with pytest.raises(FixtureError, match="2021"):
        write_listing_fixture(
            "X", 1, "2021-05-01", "<html/>", "2026-09-18T00:00:00+00:00", "test", root=tmp_path
        )


def test_write_listing_fixture_writes_the_page_as_received(tmp_path: Path) -> None:
    folder = write_listing_fixture(
        "X", 1, "2016-05-01", "<html>x</html>", "2026-09-18T00:00:00+00:00", "test", root=tmp_path
    )
    assert (folder / "listing.html").read_text() == "<html>x</html>"
    manifest = json.loads((folder / "manifest.json").read_text())
    assert manifest["fixture"]["mkey"] == 1
    assert manifest["documents"] == []


# --- Task 16: the fixture pool, the reviewed document, the title hand-check ---


def _row_html(row: tuple[int, str, int, int, str, str]) -> str:
    index, title, pages, photos, doc_type, href = row
    link = f'<a target="_blank" href="{href}">x</a>' if href else ""
    return (
        f"<tr><td><b>{index}</b></td><td>{title}</td><td><b>{pages}</b></td>"
        f"<td>{photos}</td><td>{doc_type}</td><td>{link}</td></tr>"
    )


def _cache_case(
    docket_dir: Path, mkey: int, rows: list[tuple[int, str, int, int, str, bytes | None]]
) -> None:
    """Seed a verified docket cache for ``mkey`` directly on disk -- no network, no respx.

    Each row is ``(index, title, pages, photos, doc_type, document_bytes)``; ``None`` bytes
    means no href (not a PDF, e.g. an HTML-only entry never used here) -- every row used by
    the tests below supplies bytes, since every criterion this file exercises cares about a
    real, cached, readable document. Mirrors the direct-to-cache construction
    ``tests/test_corpus_scan.py``'s ``docket_main`` tests already use, extended to more than
    one document per case.
    """
    case_dir = docket_dir / str(mkey)
    case_dir.mkdir(parents=True)
    row_html: list[str] = []
    fetch_documents: dict[str, dict[str, object]] = {}
    for index, title, pages, photos, doc_type, data in rows:
        href = ""
        if data is not None:
            href = f"/Docket/Document/docBLOB?ProjectID={mkey}&Index={index}&FileExtension=pdf"
            (case_dir / f"{index}.bin").write_bytes(data)
            fetch_documents[str(index)] = {
                "time": "2026-01-01T00:00:00+00:00",
                "sha256": hashlib.sha256(data).hexdigest(),
                "href": href,
            }
        row_html.append(_row_html((index, title, pages, photos, doc_type, href)))
    page = f"<html><body>Docket Items: {len(rows)}{''.join(row_html)}</body></html>"
    content = page.encode()
    (case_dir / "listing.html").write_bytes(content)
    fetch = {
        "listing": {
            "time": "2026-01-01T00:00:00+00:00",
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        "documents": fetch_documents,
    }
    (case_dir / "fetch.json").write_text(json.dumps(fetch))


def _dev_env(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cases: list[tuple[str, int, str, Mapping[str, object]]],
) -> Path:
    """A tmp dev-400 sample, ``cases.parquet`` and docket cache dir for the given cases.

    Each entry is ``(case_id, mkey, event_date, raw)``. Mirrors
    ``tests/test_corpus_scan.py``'s ``_docket_env``, extended to more than one case and to a
    caller-supplied raw record: Task 16's "two types" criterion reads ``highestInjuryLevel``,
    which a minimal synthetic record does not carry unless given.
    """
    ids_dir = tmp_path / "eval_ids"
    ids_dir.mkdir()
    with (ids_dir / "dev_ids.csv").open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["case_id", "event_date"])
        for case_id, _mkey, event_date, _raw in cases:
            writer.writerow([case_id, event_date])
    monkeypatch.setattr(samples, "EVAL_DIR", ids_dir)
    monkeypatch.setitem(samples._FILES, "dev-400", "dev_ids.csv")

    processed = tmp_path / "data" / "processed"
    processed.mkdir(parents=True)
    table = pa.table(
        {
            "ntsb_number": pa.array([c[0] for c in cases], type=pa.string()),
            "mkey": pa.array([c[1] for c in cases], type=pa.int64()),
            "event_date": pa.array([c[2] for c in cases], type=pa.string()),
            "raw_json": pa.array([json.dumps(c[3]) for c in cases], type=pa.string()),
        }
    )
    pq.write_table(table, processed / "cases.parquet")

    docket_dir = tmp_path / "docket"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("NTSB_DOCKET_DIR", str(docket_dir))
    return docket_dir


def _document_record(
    index: int,
    category: str,
    status: Status,
    *,
    kind: Kind = "born-digital",
    tokens: int = 100,
) -> DocumentRecord:
    entry = ListingEntry(
        index=index, title="x", pages=1, photos=0, doc_type="", extension="pdf", href="/x"
    )
    return DocumentRecord(
        entry=entry,
        category=category,
        status=status,
        pages=1,
        readable_pages=1 if status == "read" else 0,
        estimated_tokens=tokens,
        kind=kind if status == "read" else None,
    )


def _docket_of(records: list[DocumentRecord]) -> Docket:
    listing = Listing(mkey=1, declared_items=len(records), entries=tuple(r.entry for r in records))
    return Docket(mkey=1, listing=listing, documents=tuple(records), texts={})


def test_document_allowed_categories_is_narrowed_to_the_two_ntsb_authored_types() -> None:
    """Correction D: weather, medical_tox and atc_radar_data are not NTSB-authored by
    ``attach.py``'s own provenance labels, so ``document`` may not commit their text.
    """
    assert frozenset({"exam_site", "specialist_factual"}) == DOCUMENT_ALLOWED_CATEGORIES


def test_criteria_has_six_uniquely_named_entries() -> None:
    names = [name for name, _ in CRITERIA]
    assert len(names) == 6
    assert len(set(names)) == 6


def test_two_types_criterion_requires_both_allowed_categories_and_non_fatal() -> None:
    """Corrections B and D on the one criterion that picks the case Andy reads from."""
    _, criterion = next(c for c in CRITERIA if c[0] == "ntsb born-digital documents of two types")
    both_types = _docket_of(
        [
            _document_record(1, "exam_site", "read"),
            _document_record(2, "specialist_factual", "read"),
        ]
    )
    assert criterion(both_types, {"highestInjuryLevel": "Minor"}) is True
    # Correction B: Andy's ruling -- the case whose documents he reads must be non-fatal.
    assert criterion(both_types, {"highestInjuryLevel": "Fatal"}) is False
    one_type_only = _docket_of([_document_record(1, "exam_site", "read")])
    assert criterion(one_type_only, {"highestInjuryLevel": "Minor"}) is False
    # Correction D: a document outside the two NTSB-authored categories no longer counts,
    # even though the plan's original five-category list would have accepted "weather" here.
    wrong_category = _docket_of(
        [_document_record(1, "exam_site", "read"), _document_record(2, "weather", "read")]
    )
    assert criterion(wrong_category, {"highestInjuryLevel": "Minor"}) is False


def test_outcome_only_never_carries_text() -> None:
    row = outcome_only(_document_record(1, "exam_site", "read"))
    assert row["text_file"] is None
    assert row["pdf_file"] is None
    assert row["reviewed_by"] is None
    assert "text" not in row


def test_redact_text_calls_the_real_replacement_functions(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Correction C: no third, looser redaction implementation -- the real functions only."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "Invented Builder"
    aircrafts[0]["aircraftModel"] = "RV-7X"
    aircrafts[0]["ownerOperators"] = [{"registeredOwner": "Jordan Vale"}]
    text, count = redact_text(
        "The Invented Builder RV-7X, owned by Jordan Vale, was examined.", raw
    )
    assert "Invented Builder" not in text
    assert "RV-7X" not in text
    assert "Jordan Vale" not in text
    assert AMATEUR_BUILT_LABEL in text
    assert OWNER_OPERATOR_LABEL in text
    assert count == 3  # make, model, owner name


def test_stratified_sample_gives_every_present_category_an_equal_share() -> None:
    rows = {
        "a": [(f"t{i}", "d", "a") for i in range(5)],
        "b": [(f"t{i}", "d", "b") for i in range(5)],
    }
    sample = _stratified_sample(rows, total=4, seed=1)
    assert len(sample) == 4
    assert Counter(row[2] for row in sample) == {"a": 2, "b": 2}


def test_stratified_sample_tops_up_from_other_categories_when_one_is_short() -> None:
    """A rare category (party_submission's 11 unique titles, in the real cache) contributes
    everything it has; the rest of its share is drawn from a category with rows to spare, so
    the total still lands on the target instead of silently coming up short.
    """
    rows = {
        "party_submission": [("only", "d", "party_submission")],
        "other": [(f"t{i}", "d", "other") for i in range(10)],
    }
    sample = _stratified_sample(rows, total=6, seed=1)
    assert len(sample) == 6
    counts = Counter(row[2] for row in sample)
    assert counts["party_submission"] == 1
    assert counts["other"] == 5


def test_stratified_sample_is_reproducible_for_the_same_seed() -> None:
    rows = {"a": [(f"t{i}", "d", "a") for i in range(20)]}
    assert _stratified_sample(rows, total=5, seed=42) == _stratified_sample(rows, total=5, seed=42)


def test_handcheck_is_dev_400_only_by_construction_and_reports_the_skip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    docket_dir = _dev_env(
        tmp_path,
        monkeypatch,
        [
            ("DEV0001", 1, "2015-01-01", {"ntsbNumber": "DEV0001", "mKey": 1}),
            ("DEV0002", 2, "2016-01-01", {"ntsbNumber": "DEV0002", "mKey": 2}),
        ],
    )
    _cache_case(docket_dir, 1, [(1, "Weather Study", 1, 0, "Report", b"x")])
    _cache_case(docket_dir, 2, [(1, "Powerplant Examination", 1, 0, "Report", b"x")])
    # A cached mkey outside dev-400 (e.g. held-out or open) must be skipped, not sampled.
    outside = docket_dir / "999"
    outside.mkdir()
    (outside / "listing.html").write_bytes(b"<html>Docket Items: 0</html>")

    fixtures_root = tmp_path / "fixtures"
    fixtures_root.mkdir()
    monkeypatch.setattr(mdf, "FIXTURES", fixtures_root)
    assert _cmd_handcheck(argparse.Namespace(), Settings()) == 0

    with (fixtures_root / "title_handcheck.csv").open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert {row["title"] for row in rows} == {"Weather Study", "Powerplant Examination"}
    assert {row["category"] for row in rows} == {"weather", "exam_site"}
    for row in rows:
        assert row["is_photo"] == row["could_hold_conclusions"] == row["author"] == ""
    assert capsys.readouterr().err.strip() == "skipped 1 cached dockets outside dev-400"


def test_document_command_writes_pdf_and_redacted_text_and_updates_the_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    raw = copy.deepcopy(record_fixtures[0])
    raw["ntsbNumber"] = "DEV0001"
    raw["mKey"] = 1
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["ownerOperators"] = [{"registeredOwner": "Jordan Vale"}]
    docket_dir = _dev_env(tmp_path, monkeypatch, [("DEV0001", 1, "2015-01-01", raw)])
    page_texts = [(b"Examined by Jordan Vale. " * 20)]  # > 300 chars/page: born-digital
    pdf_bytes = _text_pdf(page_texts)
    _cache_case(docket_dir, 1, [(1, "Powerplant Examination", 1, 0, "Report", pdf_bytes)])

    fixtures_root = tmp_path / "fixtures"
    monkeypatch.setattr(mdf, "FIXTURES", fixtures_root)
    folder = write_listing_fixture(
        "DEV0001",
        1,
        "2015-01-01",
        (docket_dir / "1" / "listing.html").read_text(),
        "2026-01-01T00:00:00+00:00",
        "test",
        root=fixtures_root,
    )
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["documents"] = [{"index": 1, "text_file": None, "pdf_file": None, "reviewed_by": None}]
    (folder / "manifest.json").write_text(json.dumps(manifest))

    args = argparse.Namespace(case_id="DEV0001", index=1, reviewed_by="Andy, 2026-09-21")
    assert _cmd_document(args, Settings()) == 0

    assert (folder / "1.pdf").read_bytes() == pdf_bytes  # committed verbatim, never redacted
    written_text = (folder / "1.txt").read_text()
    assert "Jordan Vale" not in written_text
    assert OWNER_OPERATOR_LABEL in written_text
    updated = json.loads((folder / "manifest.json").read_text())
    row = updated["documents"][0]
    assert row["reviewed_by"] == "Andy, 2026-09-21"
    assert row["text_file"] == "1.txt"
    assert row["pdf_file"] == "1.pdf"
    assert row["redactions"] == 20  # "Jordan Vale" repeated 20 times in the invented text


def test_document_refuses_a_category_outside_the_ntsb_authored_allow_list(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures: list[dict[str, object]]
) -> None:
    """Correction D: weather is dropped from the allow-list, even though it is readable."""
    raw = copy.deepcopy(record_fixtures[0])
    raw["ntsbNumber"] = "DEV0002"
    raw["mKey"] = 2
    docket_dir = _dev_env(tmp_path, monkeypatch, [("DEV0002", 2, "2015-01-01", raw)])
    pdf_bytes = _text_pdf([b"Observed conditions were clear and ten. " * 10])
    _cache_case(docket_dir, 2, [(1, "Weather Study", 1, 0, "Report", pdf_bytes)])

    fixtures_root = tmp_path / "fixtures"
    monkeypatch.setattr(mdf, "FIXTURES", fixtures_root)
    folder = write_listing_fixture(
        "DEV0002",
        2,
        "2015-01-01",
        (docket_dir / "2" / "listing.html").read_text(),
        "2026-01-01T00:00:00+00:00",
        "test",
        root=fixtures_root,
    )
    manifest = json.loads((folder / "manifest.json").read_text())
    manifest["documents"] = [{"index": 1}]
    (folder / "manifest.json").write_text(json.dumps(manifest))

    args = argparse.Namespace(case_id="DEV0002", index=1, reviewed_by="Andy, 2026-09-21")
    with pytest.raises(FixtureError, match="not NTSB-authored"):
        _cmd_document(args, Settings())


def test_main_dispatches_draw_and_handcheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    docket_dir = _dev_env(
        tmp_path,
        monkeypatch,
        [("DEV0001", 1, "2015-01-01", {"ntsbNumber": "DEV0001", "mKey": 1})],
    )
    _cache_case(docket_dir, 1, [(1, "Weather Study", 1, 0, "Report", b"x")])
    fixtures_root = tmp_path / "fixtures"
    fixtures_root.mkdir()
    monkeypatch.setattr(mdf, "FIXTURES", fixtures_root)
    assert mdf.main(["handcheck"]) == 0
    assert (fixtures_root / "title_handcheck.csv").is_file()
    assert mdf.main(["draw"]) == 0  # no --write: prints candidates, commits nothing new
