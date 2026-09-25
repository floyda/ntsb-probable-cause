"""scripts/transcriber_test.py: the measures and the rule, fixed before the test runs (0080)."""

import hashlib
import io
import json
import random
import re
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

import pytest
from PIL import Image
from scripts import transcriber_test as tt
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.render import RESOLUTION
from ntsb_probable_cause.docket.transcribe import (
    LABEL,
    TRANSCRIBE,
    PageJob,
    Transcription,
    TranscriptionCache,
    parse_reply,
)
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring.budget import SpendRecord, write_spend
from ntsb_probable_cause.scoring.records import RunRecord, write_jsonl
from ntsb_probable_cause.settings import Settings


def _result(model: str, **overrides: float) -> tt.CandidateResult:
    values: dict[str, float] = {
        "cost_per_page": 0.001,
        "hw_lines": 375,
        "hw_right": 300,
        "hw_inventing": 3,
        "photo_pages": 50,
        "photo_invented": 1,
        "typed_chars": 100_000,
        "typed_errors": 500,
        "mixed_pages": 25,
        "mixed_invented": 0,
    }
    values.update(overrides)
    return tt.CandidateResult(model=model, **dict(values))  # type: ignore[arg-type]


def test_lines_collapse_whitespace_and_drop_blanks() -> None:
    assert tt.lines_of("  Fuel   BOTH \n\n Mixture RICH") == ["Fuel BOTH", "Mixture RICH"]


def test_line_hits_use_each_line_once() -> None:
    assert tt.line_hits(["a b", "a b", "c"], ["a b", "c", "d"]) == 2


def test_illegible_is_right_where_the_key_has_it() -> None:
    key = tt.lines_of("Switched to [illegible] tank")
    assert tt.line_hits(key, tt.lines_of("Switched to [illegible] tank")) == 1
    assert tt.line_hits(key, tt.lines_of("Switched to left tank")) == 0


def test_a_guess_where_the_key_is_illegible_is_invented() -> None:
    key = "Switched to [illegible] tank\nno change"
    assert tt.inventing_lines(key, tt.lines_of("Switched to left tank\nno change")) == 1
    assert tt.inventing_lines(key, tt.lines_of("Switched to [illegible] tank")) == 0


def test_typed_errors_count_one_wrong_character() -> None:
    errors, chars = tt.typed_errors(
        "left magneto replaced 12/03/17", "left magneto replaced 12/08/17"
    )
    assert (errors, chars) == (1, 30)


def test_the_draft_is_the_version_that_agrees_most() -> None:
    versions = {"A": ["x", "y", "z"], "B": ["x", "y", "q"], "C": ["x", "p", "q"], "D": ["r"]}
    assert tt.draft_letter(versions) == "B"
    assert tt.agreed_lines({"A": ["x", "y"], "B": ["y", "x"]}, order=["x", "y"]) == ["x", "y"]


def test_the_gate_removes_an_inventing_model() -> None:
    results = [
        _result("cheap", cost_per_page=0.0005, hw_inventing=9),  # 2.4 per 100 lines
        _result("dear", cost_per_page=0.003),
    ]
    chosen, notes = tt.choose(results)
    assert chosen == "dear"
    assert any("cheap: out" in note for note in notes)


def test_the_photo_gate_is_one_in_twenty() -> None:
    chosen, _ = tt.choose([_result("a", photo_invented=3), _result("b", photo_invented=2)])
    assert chosen == "b"


def test_the_full_page_scan_gate_is_one_in_twenty() -> None:
    """Decision W7: 2 of 25 scans with invented added words is over 1 in 20; 1 is not."""
    chosen, notes = tt.choose(
        [_result("a", cost_per_page=0.0005, mixed_invented=2), _result("b", mixed_invented=1)]
    )
    assert chosen == "b"
    assert any("a: out" in note and "full-page scans" in note for note in notes)


def test_the_cheapest_within_the_margins_wins() -> None:
    results = [
        _result("best", cost_per_page=0.004, hw_right=320),
        _result("close", cost_per_page=0.001, hw_right=303),  # 80.8% against 85.3%: within 5
        _result("far", cost_per_page=0.0005, hw_right=290),  # 77.3%: not within 5
    ]
    assert tt.choose(results)[0] == "close"


def test_typed_errors_must_be_within_one_per_hundred() -> None:
    results = [
        _result("best", cost_per_page=0.004, typed_errors=300),
        _result("sloppy", cost_per_page=0.001, typed_errors=1_400),
    ]
    assert tt.choose(results)[0] == "best"


def test_no_model_passing_means_no_transcriber() -> None:
    assert tt.choose([_result("a", hw_inventing=20)])[0] is None


def test_choose_picks_handwriting_first_when_no_candidate_is_within_both_margins() -> None:
    """Fix round 2, C1 (Andy, "handwriting first"): the review's own example -- A's
    handwriting is best but its typed errors are too far behind B's; B's typed errors are
    best but its handwriting is too far behind A's. No candidate is within both margins, so
    handwriting comes first."""
    results = [
        _result(
            "A",
            cost_per_page=0.01,
            hw_lines=1000,
            hw_right=901,
            hw_inventing=0,
            typed_chars=100,
            typed_errors=5,
        ),
        _result(
            "B",
            cost_per_page=0.001,
            hw_lines=1000,
            hw_right=800,
            hw_inventing=0,
            typed_chars=100,
            typed_errors=1,
        ),
    ]
    chosen, notes = tt.choose(results)
    assert chosen == "A"
    assert any("handwriting first" in note for note in notes)


def test_choose_handwriting_first_tie_on_cost_broken_by_typed_errors() -> None:
    """Fix round 2, C1: within the handwriting-first branch, a cost tie is broken by typed
    errors per 100 characters, lower winning."""
    results = [
        _result(
            "far",  # excluded from the handwriting-first pool: too far from the best hw
            cost_per_page=0.0001,
            hw_lines=1000,
            hw_right=500,
            hw_inventing=0,
            typed_chars=100,
            typed_errors=0,
        ),
        _result(
            "A",
            cost_per_page=0.001,
            hw_lines=1000,
            hw_right=900,
            hw_inventing=0,
            typed_chars=100,
            typed_errors=10,
        ),
        _result(
            "B",
            cost_per_page=0.001,
            hw_lines=1000,
            hw_right=900,
            hw_inventing=0,
            typed_chars=100,
            typed_errors=5,
        ),
    ]
    chosen, notes = tt.choose(results)
    assert chosen == "B"
    assert any("handwriting first" in note for note in notes)


def test_choose_all_out_still_gives_no_transcriber() -> None:
    """Fix round 2, C1: when every candidate fails the gate, the outcome is unchanged --
    handwriting-first only applies once at least one candidate has passed."""
    results = [_result("a", hw_inventing=20), _result("b", hw_inventing=30)]
    chosen, notes = tt.choose(results)
    assert chosen is None
    assert any("no candidate passed the gate" in note for note in notes)


def test_resolution_200_only_for_more_than_five_points() -> None:
    """Fix round 3, R6: ``choose_resolution`` takes exact ``Fraction``s, not floats -- updated
    from the brief's literal ``choose_resolution(0.80, 0.85)`` / ``(0.80, 0.851)``, which the
    review's own sweep found misfires on the float path (0.85 - 0.80 is not exactly 0.05)."""
    assert tt.choose_resolution(Fraction(4, 5), Fraction(17, 20)) == 150  # 0.80, 0.85: exact 5
    assert tt.choose_resolution(Fraction(4, 5), Fraction(9, 10)) == 200  # 0.80, 0.90: 10 points


def test_choose_resolution_refuses_a_float() -> None:
    """Fix round 3, R6: a runtime check, not just the type hint."""
    with pytest.raises(TypeError):
        tt.choose_resolution(0.80, 0.85)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "path", sorted(Path("tests/fixtures/openrouter/transcription").glob("*.json"))
)
def test_every_recorded_candidate_reply_parses(path: Path) -> None:
    """Each candidate's real reply to the invented probe page (Step 7) parses as a reading."""
    reply = json.loads(path.read_text())
    text, kind = parse_reply(reply["content"], TRANSCRIBE)
    assert "Engine sputtered at 800 ft." in text
    assert kind in {"typed text", "mixed", "filled form"}


# ---------------------------------------------------------------------------------------
# The subcommands, each over a tmp_path data directory (no network: --disable-socket).
# ---------------------------------------------------------------------------------------


def _offline_docs(settings: Settings) -> CachedDocuments:
    return CachedDocuments(DocketClient(settings.docket_dir, transport=tt._offline()))


def _seed(cache_dir: Path, mkey: int, document: bytes, *, index: int = 1) -> None:
    """Put one document straight into the docket cache: no fetch, no network, ever."""
    folder = cache_dir / str(mkey)
    folder.mkdir(parents=True, exist_ok=True)
    href = f"/Docket/Document/docBLOB?ProjectID={mkey}&Index={index}&FileExtension=pdf"
    listing_html = (
        "<html><body><table>"
        f"<tr><td><b>{index}</b></td><td>Report</td><td><b>1</b></td><td>0</td><td>Other</td>"
        f'<td>\n<a target="_blank" href="{href}">Download</a></td></tr>'
        "</table></body></html>"
    ).encode()
    (folder / "listing.html").write_bytes(listing_html)
    (folder / f"{index}.bin").write_bytes(document)
    stamp = "2026-01-01T00:00:00+00:00"
    fetch = {
        "listing": {"time": stamp, "sha256": hashlib.sha256(listing_html).hexdigest()},
        "documents": {
            str(index): {
                "time": stamp,
                "sha256": hashlib.sha256(document).hexdigest(),
                "href": href,
            }
        },
    }
    (folder / "fetch.json").write_text(json.dumps(fetch))


def _text_pdf(text: str = "hello") -> bytes:
    return build_pdf([PageSpec(text=text)])


def _full_page_pdf() -> bytes:
    """A page that is almost entirely one image: a decision W7 "full-page scan"."""
    image = Image.new("L", (200, 300), 0)
    out = io.BytesIO()
    image.save(out, format="PDF", resolution=72)
    return out.getvalue()


def test_cmd_keys_draws_the_four_keys_with_no_top_up(tmp_path: Path) -> None:
    """The inventory already reaches 25 handwriting and 50 photo pages: no labeller call."""
    settings = Settings(data_dir=tmp_path)
    docs = _offline_docs(settings)
    doc = _text_pdf()
    scan = _full_page_pdf()
    s26 = settings.data_dir / "s26"
    (s26 / "inventory").mkdir(parents=True)

    frame: list[dict[str, object]] = []
    mkey = 0
    for fatal in (True, False):
        for _i in range(60):  # more than enough for the 50 needed per fatal state
            mkey += 1
            _seed(settings.docket_dir, mkey, doc)
            frame.append(
                {
                    "case_id": f"T{mkey}",
                    "mkey": mkey,
                    "document": 1,
                    "page": 1,
                    "fatal": fatal,
                    "kind": "text only",
                    "chars": 500,
                }
            )
    for i in range(tt.MIXED_PAGES):
        mkey += 1
        _seed(settings.docket_dir, mkey, scan)
        frame.append(
            {
                "case_id": f"M{mkey}",
                "mkey": mkey,
                "document": 1,
                "page": 1,
                "fatal": i % 2 == 0,
                "kind": "text and image",
                "photo_only": False,
            }
        )
    (s26 / "pages-dev-400.jsonl").write_text("".join(json.dumps(r) + "\n" for r in frame))

    # A real sample.jsonl row (Task 12's inventory) already carries its own document_sha256,
    # filled when the inventory drew the page (page_inventory.py:_draw_pages).
    doc_sha = hashlib.sha256(doc).hexdigest()
    sample_rows: list[dict[str, object]] = []
    labels: dict[str, str] = {}
    n = 0
    for _ in range(tt.HANDWRITING_PAGES):
        n += 1
        mkey += 1
        _seed(settings.docket_dir, mkey, doc)
        sample_rows.append(
            {
                "n": n,
                "stratum": "image only/fatal",
                "case_id": f"H{n}",
                "mkey": mkey,
                "document": 1,
                "page": 1,
                "document_sha256": doc_sha,
            }
        )
        labels[str(n)] = "handwriting"
    for _ in range(tt.PHOTO_PAGES):
        n += 1
        mkey += 1
        _seed(settings.docket_dir, mkey, doc)
        sample_rows.append(
            {
                "n": n,
                "stratum": "image only/fatal",
                "case_id": f"P{n}",
                "mkey": mkey,
                "document": 1,
                "page": 1,
                "document_sha256": doc_sha,
            }
        )
        labels[str(n)] = "photograph"
    (s26 / "inventory" / "sample.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in sample_rows)
    )
    (s26 / "inventory" / "labels.json").write_text(json.dumps(labels))

    result = tt.cmd_keys(settings, docs)
    assert result == ("keys: typed 100, handwriting 25, photo 50, full-page scans 25")
    rows = tt._read(settings.data_dir / tt.FOLDER / "keys.jsonl")
    assert len(rows) == 200
    counts = {
        name: sum(1 for r in rows if r["set"] == name)
        for name in ("typed", "handwriting", "photo", "mixed")
    }
    assert counts == {"typed": 100, "handwriting": 25, "photo": 50, "mixed": 25}
    assert all("document_sha256" in r for r in rows)
    assert len(list((settings.data_dir / tt.FOLDER / "pages").glob("*.jpg"))) == 200


def _put(  # noqa: PLR0913 -- one keyword per fact a test needs to set.
    cache: TranscriptionCache,
    row: dict[str, object],
    model: str,
    text: str,
    *,
    dpi: int = RESOLUTION,
    cost_usd: float = 0.001,
    prompt_tokens: int = 0,
) -> None:
    mixed = row.get("set") == "mixed"
    cache.put(
        Transcription(
            key=tt._key(row, model, instruction=TRANSCRIBE, dpi=dpi, mixed=mixed),
            status="transcribed",
            text=text,
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
            mixed=mixed,
            created=datetime.now(UTC),
        )
    )


def test_cmd_handwriting_agrees_on_shared_lines_and_drafts_the_majority(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    row = {"set": "handwriting", "k": 1, "document_sha256": "a" * 64, "page": 1}
    (folder / "keys.jsonl").write_text(json.dumps(row) + "\n")
    cache = TranscriptionCache(settings.transcription_dir)
    texts = {
        "google/gemini-3.1-flash-lite": "Fuel BOTH\nMixture RICH",
        "google/gemini-3.6-flash": "Fuel BOTH\nMixture LEAN",
        "qwen/qwen3.5-122b-a10b": "Fuel BOTH\nMixture RICH",
        "openai/gpt-6-luna": "Fuel BOTH\nMixture RICH",
    }
    for model, text in texts.items():
        _put(cache, row, model, text)

    result = tt.cmd_handwriting(settings)
    assert str(folder / "handwriting.html") in result
    assert (folder / "handwriting.html").exists()
    pages = json.loads((folder / "handwriting.json").read_text())
    assert pages["1"]["agreed"] == ["Fuel BOTH"]
    draft_letter = pages["1"]["draft"]
    assert pages["1"]["versions"][draft_letter] == ["Fuel BOTH", "Mixture RICH"]


def test_cmd_photos_lists_only_outputs_that_hold_words(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    row = {"set": "photo", "k": 1, "document_sha256": "b" * 64, "page": 1}
    (folder / "keys.jsonl").write_text(json.dumps(row) + "\n")
    cache = TranscriptionCache(settings.transcription_dir)
    _put(cache, row, "openai/gpt-6-luna", "N12345")
    # The other three candidates read no words on this page: no card for them.

    result = tt.cmd_photos(settings)
    sheet = json.loads((folder / "photos.json").read_text())
    assert len(sheet) == 1
    assert next(iter(sheet.values()))["model"] == "openai/gpt-6-luna"
    assert "1 outputs with words" in result
    assert (folder / "photos.html").exists()


def test_cmd_mixed_lists_only_outputs_that_added_words(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    doc = _text_pdf("the page's own text layer")
    _seed(settings.docket_dir, 1, doc)
    row = {
        "set": "mixed",
        "k": 1,
        "document_sha256": "c" * 64,
        "page": 1,
        "mkey": 1,
        "document": 1,
    }
    (folder / "keys.jsonl").write_text(json.dumps(row) + "\n")
    cache = TranscriptionCache(settings.transcription_dir)
    _put(cache, row, "openai/gpt-6-luna", "a handwritten margin note")

    result = tt.cmd_mixed(settings, _offline_docs(settings))
    sheet = json.loads((folder / "mixed.json").read_text())
    assert len(sheet) == 1
    assert "1 outputs with added words" in result
    assert (folder / "mixed.html").exists()


def _write_csv(path: Path, header: list[str], rows: list[list[str]]) -> None:
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(f'"{cell}"' for cell in row))
    path.write_text("\n".join(lines) + "\n")


def test_cmd_score_applies_the_rule_and_reports_the_choice(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    typed_text = "FUEL SELECTOR BOTH. MIXTURE RICH."
    typed_doc = _text_pdf(typed_text)
    _seed(settings.docket_dir, 1, typed_doc)
    docs = _offline_docs(settings)
    key_text = page_text(typed_doc, 1)

    typed_row = {
        "set": "typed",
        "k": 1,
        "mkey": 1,
        "document": 1,
        "page": 1,
        "document_sha256": hashlib.sha256(typed_doc).hexdigest(),
    }
    hw_row = {"set": "handwriting", "k": 1, "document_sha256": "a" * 64, "page": 1}
    photo_row = {"set": "photo", "k": 1, "document_sha256": "b" * 64, "page": 1}
    mixed_row = {"set": "mixed", "k": 1, "document_sha256": "c" * 64, "page": 1}
    keys = [typed_row, hw_row, photo_row, mixed_row]
    (folder / "keys.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keys))

    cache = TranscriptionCache(settings.transcription_dir)
    _put(cache, typed_row, "openai/gpt-6-luna", key_text)
    _put(cache, hw_row, "openai/gpt-6-luna", "Fuel BOTH")
    _put(cache, photo_row, "openai/gpt-6-luna", "")
    _put(cache, mixed_row, "openai/gpt-6-luna", "")
    # Fix round 1, I2: `score` refuses to choose while any candidate lacks a transcribed
    # reading of any key page, so every other candidate needs one too (blank is fine: it is
    # not a *failed* reading, just an empty one, and scores as before).
    for model in tt.CANDIDATES:
        if model == "openai/gpt-6-luna":
            continue
        for row in keys:
            _put(cache, row, model, "")

    (folder / "handwriting.json").write_text(
        json.dumps({"1": {"versions": {"A": ["Fuel BOTH"]}, "draft": "A", "agreed": ["Fuel BOTH"]}})
    )
    (folder / "photos.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    (folder / "mixed.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))

    hw_csv = tmp_path / "handwriting-key.csv"
    _write_csv(hw_csv, ["row", "key"], [["1", "Fuel BOTH"]])
    photos_csv = tmp_path / "photo-words.csv"
    _write_csv(photos_csv, ["row", "words"], [["11", "all on the page"]])
    mixed_csv = tmp_path / "mixed-words.csv"
    _write_csv(mixed_csv, ["row", "added words"], [["11", "all on the page and new"]])

    text = tt.cmd_score(settings, docs, hw_csv, photos_csv, mixed_csv)
    assert "openai/gpt-6-luna: chosen -- the cheapest within both margins" in text
    assert "the transcriber test" in text


def test_cmd_score_resolution_not_decided_while_a_200dpi_reading_is_missing(
    tmp_path: Path,
) -> None:
    """Fix round 3, R2: the resolution comparison refuses to decide while any 200 dpi reading
    on the handwriting or typed key is missing, the same way `score` refuses at 150 dpi --
    an interrupted resolution run must not silently score its unread pages as empty, which
    would push the choice towards 150 dpi with no sign anything was missing."""
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    typed_text = "FUEL SELECTOR BOTH. MIXTURE RICH."
    typed_doc = _text_pdf(typed_text)
    _seed(settings.docket_dir, 1, typed_doc)
    docs = _offline_docs(settings)
    key_text = page_text(typed_doc, 1)

    typed_row = {
        "set": "typed",
        "k": 1,
        "mkey": 1,
        "document": 1,
        "page": 1,
        "document_sha256": hashlib.sha256(typed_doc).hexdigest(),
    }
    hw_row = {"set": "handwriting", "k": 1, "document_sha256": "a" * 64, "page": 1}
    photo_row = {"set": "photo", "k": 1, "document_sha256": "b" * 64, "page": 1}
    mixed_row = {"set": "mixed", "k": 1, "document_sha256": "c" * 64, "page": 1}
    keys = [typed_row, hw_row, photo_row, mixed_row]
    (folder / "keys.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keys))

    cache = TranscriptionCache(settings.transcription_dir)
    _put(cache, typed_row, "openai/gpt-6-luna", key_text)
    _put(cache, hw_row, "openai/gpt-6-luna", "Fuel BOTH")
    _put(cache, photo_row, "openai/gpt-6-luna", "")
    _put(cache, mixed_row, "openai/gpt-6-luna", "")
    for model in tt.CANDIDATES:
        if model == "openai/gpt-6-luna":
            continue
        for row in keys:
            _put(cache, row, model, "")
    # The resolution run only got to the handwriting key before being interrupted.
    _put(cache, hw_row, "openai/gpt-6-luna", "Fuel BOTH", dpi=200)

    (folder / "handwriting.json").write_text(
        json.dumps({"1": {"versions": {"A": ["Fuel BOTH"]}, "draft": "A", "agreed": ["Fuel BOTH"]}})
    )
    (folder / "photos.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    (folder / "mixed.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    hw_csv = tmp_path / "handwriting-key.csv"
    _write_csv(hw_csv, ["row", "key"], [["1", "Fuel BOTH"]])
    photos_csv = tmp_path / "photo-words.csv"
    _write_csv(photos_csv, ["row", "words"], [["11", "all on the page"]])
    mixed_csv = tmp_path / "mixed-words.csv"
    _write_csv(mixed_csv, ["row", "added words"], [["11", "all on the page and new"]])

    text = tt.cmd_score(settings, docs, hw_csv, photos_csv, mixed_csv)
    assert "openai/gpt-6-luna: chosen" in text
    assert "resolution: not decided -- 1 pages have no reading at 200 dpi" in text
    assert "chosen: 150 dpi" not in text
    assert "chosen: 200 dpi" not in text


def test_cmd_score_does_not_choose_while_a_reading_is_missing(tmp_path: Path) -> None:
    """Fix round 1, I2/M9 (narrowed by fix round 2's "count it as wrong"): one candidate
    missing a reading of one key page -- never attempted, no record at all -- holds off
    `choose` entirely, naming the count, rather than silently scoring the gap as empty."""
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    typed_doc = _text_pdf("FUEL SELECTOR BOTH.")
    _seed(settings.docket_dir, 1, typed_doc)
    docs = _offline_docs(settings)
    key_text = page_text(typed_doc, 1)
    typed_row = {
        "set": "typed",
        "k": 1,
        "mkey": 1,
        "document": 1,
        "page": 1,
        "document_sha256": hashlib.sha256(typed_doc).hexdigest(),
    }
    hw_row = {"set": "handwriting", "k": 1, "document_sha256": "a" * 64, "page": 1}
    photo_row = {"set": "photo", "k": 1, "document_sha256": "b" * 64, "page": 1}
    mixed_row = {"set": "mixed", "k": 1, "document_sha256": "c" * 64, "page": 1}
    keys = [typed_row, hw_row, photo_row, mixed_row]
    (folder / "keys.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keys))

    cache = TranscriptionCache(settings.transcription_dir)
    for model in tt.CANDIDATES:
        _put(cache, typed_row, model, key_text)
        _put(cache, hw_row, model, "Fuel BOTH")
        _put(cache, mixed_row, model, "")
        if model != "openai/gpt-6-luna":
            _put(cache, photo_row, model, "")
        # openai/gpt-6-luna's photo reading is never cached: it is missing.

    (folder / "handwriting.json").write_text(
        json.dumps({"1": {"versions": {"A": ["Fuel BOTH"]}, "draft": "A", "agreed": ["Fuel BOTH"]}})
    )
    (folder / "photos.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    (folder / "mixed.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    hw_csv = tmp_path / "handwriting-key.csv"
    _write_csv(hw_csv, ["row", "key"], [["1", "Fuel BOTH"]])
    photos_csv = tmp_path / "photo-words.csv"
    _write_csv(photos_csv, ["row", "words"], [["11", "all on the page"]])
    mixed_csv = tmp_path / "mixed-words.csv"
    _write_csv(mixed_csv, ["row", "added words"], [["11", "all on the page and new"]])

    text = tt.cmd_score(settings, docs, hw_csv, photos_csv, mixed_csv)
    assert "not chosen:" in text
    assert "run `transcriber_test run`" in text
    assert "chosen -- the cheapest" not in text
    assert "photo 1 missing/0 failed" in text


def test_cmd_score_scores_a_failed_reading_as_wrong_and_still_chooses(tmp_path: Path) -> None:
    """Fix round 2 (Andy, "count it as wrong"): a page a candidate still failed to read after
    a retry does not block `choose` -- it counts as wrong for that candidate (0 handwriting
    lines right, no invented lines, every typed character an error), its cost still counts,
    and the failure is counted and printed."""
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    typed_doc = _text_pdf("FUEL SELECTOR BOTH.")
    _seed(settings.docket_dir, 1, typed_doc)
    docs = _offline_docs(settings)
    key_text = page_text(typed_doc, 1)
    typed_row = {
        "set": "typed",
        "k": 1,
        "mkey": 1,
        "document": 1,
        "page": 1,
        "document_sha256": hashlib.sha256(typed_doc).hexdigest(),
    }
    hw_row = {"set": "handwriting", "k": 1, "document_sha256": "a" * 64, "page": 1}
    photo_row = {"set": "photo", "k": 1, "document_sha256": "b" * 64, "page": 1}
    mixed_row = {"set": "mixed", "k": 1, "document_sha256": "c" * 64, "page": 1}
    keys = [typed_row, hw_row, photo_row, mixed_row]
    (folder / "keys.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keys))

    cache = TranscriptionCache(settings.transcription_dir)
    for model in tt.CANDIDATES:
        if model == "openai/gpt-6-luna":
            # This candidate's handwriting reading failed (tried, cost real money, no text).
            cache.put(
                Transcription(
                    key=tt._key(hw_row, model, instruction=TRANSCRIBE, dpi=RESOLUTION),
                    status="failed",
                    error="boom",
                    cost_usd=0.002,
                    created=datetime.now(UTC),
                )
            )
        else:
            _put(cache, hw_row, model, "Fuel BOTH")
        _put(cache, typed_row, model, key_text)
        _put(cache, photo_row, model, "")
        _put(cache, mixed_row, model, "")

    (folder / "handwriting.json").write_text(
        json.dumps({"1": {"versions": {"A": ["Fuel BOTH"]}, "draft": "A", "agreed": ["Fuel BOTH"]}})
    )
    (folder / "photos.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    (folder / "mixed.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    hw_csv = tmp_path / "handwriting-key.csv"
    _write_csv(hw_csv, ["row", "key"], [["1", "Fuel BOTH"]])
    photos_csv = tmp_path / "photo-words.csv"
    _write_csv(photos_csv, ["row", "words"], [["11", "all on the page"]])
    mixed_csv = tmp_path / "mixed-words.csv"
    _write_csv(mixed_csv, ["row", "added words"], [["11", "all on the page and new"]])

    text = tt.cmd_score(settings, docs, hw_csv, photos_csv, mixed_csv)
    assert "not chosen:" not in text
    assert "chosen --" in text
    assert "handwriting 0 missing/1 failed" in text


def test_cmd_score_refuses_unmarked_photograph_outputs(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    (folder / "keys.jsonl").write_text("")
    (folder / "handwriting.json").write_text(json.dumps({}))
    (folder / "photos.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    (folder / "mixed.json").write_text(json.dumps({}))
    hw_csv = tmp_path / "handwriting-key.csv"
    _write_csv(hw_csv, ["row", "key"], [])
    photos_csv = tmp_path / "photo-words.csv"
    _write_csv(photos_csv, ["row", "words"], [["11", ""]])
    mixed_csv = tmp_path / "mixed-words.csv"
    _write_csv(mixed_csv, ["row", "added words"], [])
    with pytest.raises(SystemExit, match="unmarked"):
        tt.cmd_score(settings, _offline_docs(settings), hw_csv, photos_csv, mixed_csv)


def test_cmd_estimate_reports_the_stage_total(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    s26 = settings.data_dir / "s26"
    (s26 / "inventory").mkdir(parents=True)
    (s26 / "pages-dev-400.jsonl").write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in (
                {"kind": "image only", "case_id": "C1"},
                {"kind": "image only", "case_id": "C2"},
                {"kind": "text and image", "case_id": "C3"},
            )
        )
    )
    (s26 / "inventory" / "sample.jsonl").write_text(
        json.dumps(
            {
                "n": 1,
                "stratum": "text and image/fatal",
                "kind": "text and image",
                "image_area_share": 0.9,
            }
        )
        + "\n"
    )
    (s26 / "inventory" / "labels.json").write_text(json.dumps({"1": "mixed"}))
    (s26 / "inventory" / "population.json").write_text(json.dumps({"text and image/fatal": 5}))

    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    photo_row = {"set": "photo", "k": 1, "document_sha256": "f" * 64, "page": 1}
    (folder / "keys.jsonl").write_text(json.dumps(photo_row) + "\n")
    cache = TranscriptionCache(settings.transcription_dir)
    _put(cache, photo_row, "openai/gpt-6-luna", "N12345", cost_usd=0.002, prompt_tokens=1000)

    write_spend(
        settings.runs_dir,
        SpendRecord(
            job_id="20260101T000000-abc1234-transcriber-test",
            kind="transcriber-test",
            model="openai/gpt-6-luna",
            started=datetime(2026, 1, 1, tzinfo=UTC),
            calls=1,
            cost_usd=1.23,
            commit_sha="abc1234",
            dirty=False,
        ),
    )
    write_jsonl(
        settings.runs_dir / "20260101T000000-abc1234-heldout-400-B" / "run.jsonl",
        [
            RunRecord(
                run_id="20260101T000000-abc1234-heldout-400-B",
                sample="heldout-400",
                arm="B",
                exclusions=(),
                includes=(),
                prompt_version="p1",
                model="openai/gpt-6-luna",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=40.0,
                commit_sha="abc1234",
                dirty=False,
                started=datetime(2026, 1, 1, tzinfo=UTC),
                finished=datetime(2026, 1, 1, 1, tzinfo=UTC),
                cases=10,
                cost_usd=5.0,
            )
        ],
    )

    result = tt.cmd_estimate(
        settings, "openai/gpt-6-luna", RESOLUTION, stage_commits=_STAGE_COMMITS
    )
    assert "stage rest to spend: $" in result
    assert "spent on S2.6 so far" in result
    assert "month spent so far: $0.00; open reservations: $0.00; headroom" in result


def test_cmd_estimate_pauses_on_the_stage_total_even_with_headroom_to_spare(
    tmp_path: Path,
) -> None:
    """Fix round 3, R3: decision 0083 item 2's own test (the stage total against its $40
    line) is applied even when the remaining spend alone would fit the month's headroom -- a
    large preparation spend from earlier in the stage, dated outside the current month,
    inflates the stage total without touching `month_spent`'s headroom at all."""
    settings = Settings(data_dir=tmp_path)
    s26 = settings.data_dir / "s26"
    (s26 / "inventory").mkdir(parents=True)
    (s26 / "pages-dev-400.jsonl").write_text(
        "".join(
            json.dumps(r) + "\n"
            for r in (
                {"kind": "image only", "case_id": "C1"},
                {"kind": "image only", "case_id": "C2"},
                {"kind": "text and image", "case_id": "C3"},
            )
        )
    )
    (s26 / "inventory" / "sample.jsonl").write_text(
        json.dumps(
            {
                "n": 1,
                "stratum": "text and image/fatal",
                "kind": "text and image",
                "image_area_share": 0.9,
            }
        )
        + "\n"
    )
    (s26 / "inventory" / "labels.json").write_text(json.dumps({"1": "mixed"}))
    (s26 / "inventory" / "population.json").write_text(json.dumps({"text and image/fatal": 5}))

    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    photo_row = {"set": "photo", "k": 1, "document_sha256": "f" * 64, "page": 1}
    (folder / "keys.jsonl").write_text(json.dumps(photo_row) + "\n")
    cache = TranscriptionCache(settings.transcription_dir)
    _put(cache, photo_row, "openai/gpt-6-luna", "N12345", cost_usd=0.002, prompt_tokens=1000)

    # A large spend row from earlier in the stage, dated in a month before "now" (2026-09-25
    # in this repo's fixed calendar): counted in the stage total (its commit is one of the
    # stage's) but not in `month_spent` (filtered to the current month), so headroom stays
    # close to $40.
    write_spend(
        settings.runs_dir,
        SpendRecord(
            job_id="20260801T000000-abc1234-transcriber-test",
            kind="transcriber-test",
            model="openai/gpt-6-luna",
            started=datetime(2026, 8, 1, tzinfo=UTC),
            calls=1,
            cost_usd=50.0,
            commit_sha="abc1234",
            dirty=False,
        ),
    )
    write_jsonl(
        settings.runs_dir / "20260101T000000-abc1234-heldout-400-B" / "run.jsonl",
        [
            RunRecord(
                run_id="20260101T000000-abc1234-heldout-400-B",
                sample="heldout-400",
                arm="B",
                exclusions=(),
                includes=(),
                prompt_version="p1",
                model="openai/gpt-6-luna",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=40.0,
                commit_sha="abc1234",
                dirty=False,
                started=datetime(2026, 1, 1, tzinfo=UTC),
                finished=datetime(2026, 1, 1, 1, tzinfo=UTC),
                cases=10,
                cost_usd=0.1,  # a small per-case cost, so the projected rest fits the headroom
            )
        ],
    )

    result = tt.cmd_estimate(
        settings, "openai/gpt-6-luna", RESOLUTION, stage_commits=_STAGE_COMMITS
    )
    assert "pause: ask Andy" in result
    assert "passes the $40 stage line (decision 0083 item 2)" in result
    assert "does not fit the month's" not in result


# ---------------------------------------------------------------------------------------
# Fix round 4, T1: S2.6's spend is counted by commit, not by date. The commit lists below are
# invented full SHAs; the tests never read the real repository's history.
# ---------------------------------------------------------------------------------------

_S26_RUN = "40c6ec6" + "1" * 33  # an S2.6 evaluation-run commit (Task 9B)
_S26_PREP = "31af9fb" + "2" * 33  # an S2.6 preparation commit (the inventory)
_S24_RUN = "7071800" + "3" * 33  # an S2.4 commit: reachable from the S2.4 merge, so not listed
_STAGE_COMMITS = frozenset({_S26_RUN, _S26_PREP, "abc1234" + "4" * 33})


def _estimate_inputs(settings: Settings) -> None:
    """The frame, inventory and one cached photo reading `cmd_estimate` needs, minimal."""
    s26 = settings.data_dir / "s26"
    (s26 / "inventory").mkdir(parents=True)
    (s26 / "pages-dev-400.jsonl").write_text(
        json.dumps({"kind": "image only", "case_id": "C1"}) + "\n"
    )
    (s26 / "inventory" / "sample.jsonl").write_text(
        json.dumps(
            {
                "n": 1,
                "stratum": "text and image/fatal",
                "kind": "text and image",
                "image_area_share": 0.9,
            }
        )
        + "\n"
    )
    (s26 / "inventory" / "labels.json").write_text(json.dumps({"1": "mixed"}))
    (s26 / "inventory" / "population.json").write_text(json.dumps({"text and image/fatal": 5}))
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    photo_row = {"set": "photo", "k": 1, "document_sha256": "f" * 64, "page": 1}
    (folder / "keys.jsonl").write_text(json.dumps(photo_row) + "\n")
    cache = TranscriptionCache(settings.transcription_dir)
    _put(cache, photo_row, "openai/gpt-6-luna", "N12345", cost_usd=0.002, prompt_tokens=1000)


def _run_record(settings: Settings, run_id: str, sha: str, cost_usd: float) -> None:
    started = datetime.strptime(run_id[:15], "%Y%m%dT%H%M%S").replace(tzinfo=UTC)
    write_jsonl(
        settings.runs_dir / run_id / "run.jsonl",
        [
            RunRecord(
                run_id=run_id,
                sample=run_id.split("-", 2)[2].rsplit("-", 1)[0],
                arm="B",
                exclusions=(),
                includes=(),
                prompt_version="p1",
                model="openai/gpt-6-luna",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=40.0,
                commit_sha=sha,
                dirty=False,
                started=started,
                finished=started,
                cases=400,
                cost_usd=cost_usd,
            )
        ],
    )


def _spend_row(settings: Settings, job_id: str, sha: str, cost_usd: float) -> None:
    write_spend(
        settings.runs_dir,
        SpendRecord(
            job_id=job_id,
            kind="inventory",
            model="google/gemini-3.1-flash-lite",
            started=datetime(2026, 9, 24, 12, tzinfo=UTC),
            calls=1,
            cost_usd=cost_usd,
            commit_sha=sha,
            dirty=False,
        ),
    )


def test_cmd_estimate_counts_the_stage_by_commit_not_by_date(tmp_path: Path) -> None:
    """An S2.4 run from the stage's first day, an S2.4 spend row and a run at an unknown commit
    are not S2.6 spend; an S2.6 run and an S2.6 spend row are, matched by their abbreviated
    shas against the stage's full ones."""
    settings = Settings(data_dir=tmp_path)
    _estimate_inputs(settings)
    # S2.4's held-out B bar, run on 2026-09-24 -- the day a date filter took as S2.6's start.
    _run_record(settings, "20260924T185800-7071800-heldout-400-B", _S24_RUN[:7], 1.129)
    _run_record(settings, "20260925T100148-40c6ec6-dev-400-B", _S26_RUN[:7], 1.181)
    _run_record(settings, "20260925T110000-deadbee-dev-400-B", "deadbee", 7.0)
    _spend_row(settings, "20260924T120000-31af9fb-inventory", _S26_PREP[:7], 0.11)
    _spend_row(settings, "20260924T120000-ce8a55e-inventory", "ce8a55e", 0.5)

    result = tt.cmd_estimate(
        settings, "openai/gpt-6-luna", RESOLUTION, stage_commits=_STAGE_COMMITS
    )
    assert (
        "spent on S2.6 so far: $1.29 ($0.11 preparation spend rows, $1.18 evaluation runs; "
        "counted by commit, the 3 commits since the S2.4 merge 90ceab9)"
    ) in result


def test_in_stage_matches_an_abbreviated_sha_by_prefix_only() -> None:
    assert tt._in_stage(_S26_RUN[:7], _STAGE_COMMITS)
    assert tt._in_stage(_S26_RUN, _STAGE_COMMITS)
    assert not tt._in_stage(_S24_RUN[:7], _STAGE_COMMITS)
    assert not tt._in_stage("deadbee", _STAGE_COMMITS)
    assert not tt._in_stage("", _STAGE_COMMITS)  # would prefix-match every commit
    assert not tt._in_stage(_S26_RUN[:3], _STAGE_COMMITS)  # shorter than git's shortest


def test_cmd_estimate_refuses_when_git_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def no_git(base: str, repo: Path = Path()) -> tuple[str, ...]:
        raise FileNotFoundError(2, "No such file or directory", "git")

    monkeypatch.setattr(tt, "commits_since", no_git)
    settings = Settings(data_dir=tmp_path)
    _estimate_inputs(settings)
    with pytest.raises(ConfigurationError, match=r"needs git to list S2\.6's commits"):
        tt.cmd_estimate(settings, "openai/gpt-6-luna", RESOLUTION)


def test_stage_commits_refuses_outside_a_repository(tmp_path: Path) -> None:
    with pytest.raises(ConfigurationError, match=r"git rev-list 90ceab9\.\.HEAD"):
        tt._stage_commits(tmp_path)


# ---------------------------------------------------------------------------------------
# Fix round 1: the missing tests the review lists (M9), plus I7's boundary tests.
# ---------------------------------------------------------------------------------------


def test_choose_margin_boundaries_use_exact_fractions_not_floats() -> None:
    """Fix round 1, I7: an exact 5-point handwriting gap and an exact 1-per-100 typed gap are
    both within margin -- not misjudged by 0.05's own floating-point rounding."""
    results = [
        _result(
            "best",
            cost_per_page=0.004,
            hw_lines=20,
            hw_right=20,
            hw_inventing=0,
            typed_chars=2000,
            typed_errors=20,
        ),
        _result(
            "edge",
            cost_per_page=0.001,
            hw_lines=20,
            hw_right=19,
            hw_inventing=0,
            typed_chars=2000,
            typed_errors=40,
        ),
    ]
    assert tt.choose(results)[0] == "edge"


def test_choose_resolution_keeps_150_at_an_exact_five_point_gap() -> None:
    """3/20 handwriting accuracy against 4/20 is exactly 5 points; the rule needs MORE than
    5, so 150 dpi is kept. 3/20 against 5/20 (10 points) does cross it."""
    assert tt.choose_resolution(Fraction(3, 20), Fraction(4, 20)) == 150
    assert tt.choose_resolution(Fraction(3, 20), Fraction(5, 20)) == 200


def test_fraction_of_zero_lines_is_zero() -> None:
    assert tt._fraction(0, 0) == Fraction(0)
    assert tt._fraction(3, 4) == Fraction(3, 4)


def test_reading_counts_reports_missing_and_failed(tmp_path: Path) -> None:
    """Fix round 1, M9 (the review's own list): a failed or never-attempted reading is
    counted, not silently scored as if it read no words."""
    settings = Settings(data_dir=tmp_path)
    cache = TranscriptionCache(settings.transcription_dir)
    row_ok = {"set": "typed", "k": 1, "document_sha256": "a" * 64, "page": 1}
    row_failed = {"set": "typed", "k": 2, "document_sha256": "b" * 64, "page": 1}
    row_missing = {"set": "typed", "k": 3, "document_sha256": "c" * 64, "page": 1}
    _put(cache, row_ok, "openai/gpt-6-luna", "text")
    cache.put(
        Transcription(
            key=tt._key(row_failed, "openai/gpt-6-luna", instruction=TRANSCRIBE, dpi=RESOLUTION),
            status="failed",
            error="boom",
            created=datetime.now(UTC),
        )
    )
    counts = tt._reading_counts(
        cache, [row_ok, row_failed, row_missing], "openai/gpt-6-luna", dpi=RESOLUTION
    )
    assert counts["typed"] == tt.ReadingCounts(missing=1, failed=1)
    # Fix round 2: only a missing reading blocks scoring; a failed one counts as wrong.
    assert counts["typed"].incomplete == 1
    assert counts["handwriting"] == tt.ReadingCounts(missing=0, failed=0)


def test_top_up_labels_the_pool_until_want_is_reached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 1, M9: the top-up actually calls the labeller and keeps what it labels,
    stopping once ``want`` pages are found rather than labelling the whole pool."""
    settings = Settings(data_dir=tmp_path)
    docs = _offline_docs(settings)
    doc = _text_pdf()
    pool: list[dict[str, object]] = []
    for i in range(3):
        mkey = 100 + i
        _seed(settings.docket_dir, mkey, doc)
        pool.append({"case_id": f"F{i}", "mkey": mkey, "document": 1, "page": 1})
    cache = TranscriptionCache(settings.transcription_dir)

    def fake_run_preparation(  # noqa: PLR0913 -- mirrors run_preparation's own signature.
        *,
        kind: str,
        jobs: list[PageJob],
        instruction: object,
        settings: Settings,
        commit: tuple[str, bool],
        expected_cost_per_page_usd: float,
        workers: int = 4,
        retry_failed: bool = False,
    ) -> list[Transcription]:
        for job in jobs:
            cache.put(
                Transcription(
                    key=job.key,
                    status="transcribed",
                    text="",
                    page_kind="handwriting",
                    created=datetime.now(UTC),
                )
            )
        return []

    monkeypatch.setattr(tt, "run_preparation", fake_run_preparation)
    have = tt._top_up([], pool, 2, ("handwriting",), docs, settings)
    assert len(have) == 2
    assert {row["mkey"] for row in have} <= {100, 101, 102}
    assert all(row["source"] == "top-up" and row["page_kind"] == "handwriting" for row in have)


def test_top_up_accepts_either_of_two_labels(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 2, C2 (Andy, "hand-filled pilot forms"): the handwriting top-up keeps a page
    the labeller calls either ``handwriting`` or ``filled form``."""
    settings = Settings(data_dir=tmp_path)
    docs = _offline_docs(settings)
    pool: list[dict[str, object]] = []
    for i in range(3):
        mkey = 200 + i
        # Distinct content per page (fix round 1's own I3 note applies here too): identical
        # bytes would give every page the same document_sha256, so they would share one cache
        # key and only the last-written label would be readable back.
        _seed(settings.docket_dir, mkey, _text_pdf(f"page {i}"))
        pool.append({"case_id": f"G{i}", "mkey": mkey, "document": 1, "page": 1})
    cache = TranscriptionCache(settings.transcription_dir)
    kinds = ["filled form", "typed text", "handwriting"]  # only the first and third qualify

    def fake_run_preparation(  # noqa: PLR0913 -- mirrors run_preparation's own signature.
        *,
        kind: str,
        jobs: list[PageJob],
        instruction: object,
        settings: Settings,
        commit: tuple[str, bool],
        expected_cost_per_page_usd: float,
        workers: int = 4,
        retry_failed: bool = False,
    ) -> list[Transcription]:
        for job, page_kind in zip(jobs, kinds, strict=True):
            cache.put(
                Transcription(
                    key=job.key,
                    status="transcribed",
                    text="",
                    page_kind=page_kind,
                    created=datetime.now(UTC),
                )
            )
        return []

    monkeypatch.setattr(tt, "run_preparation", fake_run_preparation)
    have = tt._top_up([], pool, 5, ("handwriting", "filled form"), docs, settings)
    assert len(have) == 2
    assert {row["page_kind"] for row in have} == {"handwriting", "filled form"}


def test_top_up_skips_run_preparation_when_the_batch_is_already_cached(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 3, R5: a `keys` re-run whose pool pages are already labelled from an earlier
    run must not call `run_preparation` at all -- two top-ups of the same kind and model
    (handwriting's and the photograph's) landing in the same clock second would otherwise both
    try to claim one job folder."""
    settings = Settings(data_dir=tmp_path)
    docs = _offline_docs(settings)
    pool: list[dict[str, object]] = []
    cache = TranscriptionCache(settings.transcription_dir)
    for i in range(2):
        mkey = 300 + i
        doc = _text_pdf(f"cached page {i}")
        _seed(settings.docket_dir, mkey, doc)
        row = {"case_id": f"H{i}", "mkey": mkey, "document": 1, "page": 1}
        hashed = tt._hashed([row], docs)[0]
        cache.put(
            Transcription(
                key=tt._key(hashed, tt.LABELLER, instruction=LABEL, dpi=RESOLUTION),
                status="transcribed",
                text="",
                page_kind="handwriting",
                created=datetime.now(UTC),
            )
        )
        pool.append(row)

    def boom(**_kwargs: object) -> list[Transcription]:
        raise AssertionError("run_preparation must not be called: the batch is already cached")

    monkeypatch.setattr(tt, "run_preparation", boom)
    have = tt._top_up([], pool, 2, ("handwriting", "filled form"), docs, settings)
    assert len(have) == 2


def test_full_scans_excludes_sampled_photo_only_and_low_image_share(tmp_path: Path) -> None:
    """Fix round 1, M9: the full-page-scan draw excludes a sampled page, a photo-only
    document's page, and a page whose images cover too little of it -- even when each is
    otherwise a valid text-and-image page."""
    settings = Settings(data_dir=tmp_path)
    docs = _offline_docs(settings)
    full_page = _full_page_pdf()
    text_page = _text_pdf()
    frame: list[dict[str, object]] = [
        {
            "case_id": "S",
            "mkey": 1,
            "document": 1,
            "page": 1,
            "kind": "text and image",
            "photo_only": False,
        },
        {
            "case_id": "P",
            "mkey": 2,
            "document": 1,
            "page": 1,
            "kind": "text and image",
            "photo_only": True,
        },
        {
            "case_id": "L",
            "mkey": 3,
            "document": 1,
            "page": 1,
            "kind": "text and image",
            "photo_only": False,
        },
        {
            "case_id": "G",
            "mkey": 4,
            "document": 1,
            "page": 1,
            "kind": "text and image",
            "photo_only": False,
        },
    ]
    _seed(settings.docket_dir, 1, full_page)
    _seed(settings.docket_dir, 2, full_page)
    _seed(settings.docket_dir, 3, text_page)  # mostly text: image_area_share well under 70%
    _seed(settings.docket_dir, 4, full_page)
    sampled = {("S", 1, 1)}  # the sampled page is excluded even though it would qualify

    scans = tt._full_scans(frame, sampled, docs, random.Random(1))  # noqa: S311
    assert [r["case_id"] for r in scans] == ["G"]


def test_typed_rows_are_reproducible_from_the_seed() -> None:
    """Fix round 1, M9: the seeded draw gives the same pages on a second call."""
    frame = [
        {
            "case_id": f"T{i}",
            "mkey": i,
            "document": 1,
            "page": 1,
            "fatal": i % 2 == 0,
            "kind": "text only",
            "chars": 500,
        }
        for i in range(20)
    ]
    first = tt._typed_rows(frame, random.Random(tt.SEED))  # noqa: S311
    second = tt._typed_rows(frame, random.Random(tt.SEED))  # noqa: S311
    assert first == second
    assert len(first) == 20  # 10 fatal + 10 non-fatal, all that is available


def test_highlighting_colours_words_by_how_many_versions_hold_them() -> None:
    """A display aid for Andy (2026-09-25): plain in every version, some, or only this one."""
    versions = {
        "A": ["Fuel BOTH, <mixture> rich"],
        "B": ["fuel both"],
        "C": ["Fuel both rich"],
        "D": [],
    }
    shown = tt._highlighted(versions["A"], versions)
    assert shown.startswith("Fuel BOTH, ")
    assert '<span class="only">&lt;mixture&gt;</span>' in shown
    assert '<span class="some">rich</span>' in tt._highlighted(versions["C"], versions)
    assert tt._highlighted(["x y"], {"A": ["x y"]}) == "x y"


def test_a_grouped_image_is_shown_once_and_repeats_are_named() -> None:
    """Andy (2026-09-25): one image per group; identical versions say so."""
    seen: dict[str, str] = {}
    assert tt._same_as(seen, "N123AB", "A") == ""
    assert tt._same_as(seen, "N123AB", "C") == " -- same words as version A"
    assert tt._same_as(seen, "N12", "D") == ""
    assert '<img src="pages/photo-1.jpg"' in tt._image_head("Photograph 1", "pages/photo-1.jpg")


def test_added_words_are_coloured_against_the_text_layer() -> None:
    """Andy (2026-09-25): a display aid for 'repeats the text layer'."""
    shown = tt._against_layer("FUEL: Both\nN123AB <x>", "Fuel selector both")
    assert shown.startswith('<span class="inlayer">FUEL:</span> <span class="inlayer">Both</span>')
    assert '<span class="new">N123AB</span>' in shown
    assert '<span class="new">&lt;x&gt;</span>' in shown


# ---------------------------------------------------------------------------------------
# Decision 0086: the second pass -- the two recheck pages and the corrected scoring.
# ---------------------------------------------------------------------------------------

_ROWS = re.compile(r'data-row="(\d+)"')


def test_photos_recheck_lists_only_the_cards_first_marked_invented(tmp_path: Path) -> None:
    """Item 1: the recheck page holds exactly the "some invented" cards, with their rows."""
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    rows: list[dict[str, object]] = [
        {"set": "photo", "k": k, "document_sha256": f"{k}" * 64, "page": 1} for k in (1, 2)
    ]
    (folder / "keys.jsonl").write_text("".join(json.dumps(r) + "\n" for r in rows))
    cache = TranscriptionCache(settings.transcription_dir)
    for row in rows:
        for model in tt.CANDIDATES:
            _put(cache, row, model, "Photo N12345")
    tt.cmd_photos(settings)
    sheet = json.loads((folder / "photos.json").read_text())
    numbers = sorted(int(n) for n in sheet)
    assert len(numbers) == 2 * len(tt.CANDIDATES)
    invented = [numbers[1], numbers[4], numbers[6]]
    (folder / tt.PASS1).mkdir()
    _write_csv(
        folder / tt.PASS1 / "photo-words.csv",
        ["row", "words"],
        [[str(n), "some invented" if n in invented else "all on the page"] for n in numbers],
    )

    result = tt.cmd_photos_recheck(settings)
    page = (folder / "photos-recheck.html").read_text()
    assert [int(n) for n in _ROWS.findall(page)] == invented
    assert "3 outputs to re-mark" in result
    assert '"s26-photo-words-pass2"' in page
    assert '"photo-words-pass2.csv"' in page
    assert 'value="all on the page"' in page
    assert 'value="some invented"' in page
    assert "photo label counts as on the page" in page
    assert "a misread registration is still invented" in page
    # The first pass's sheet is untouched.
    assert json.loads((folder / "photos.json").read_text()) == sheet


def test_photos_recheck_refuses_rows_that_no_longer_match_the_sheet(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    row = {"set": "photo", "k": 1, "document_sha256": "d" * 64, "page": 1}
    (folder / "keys.jsonl").write_text(json.dumps(row) + "\n")
    cache = TranscriptionCache(settings.transcription_dir)
    _put(cache, row, "openai/gpt-6-luna", "Photo")
    tt.cmd_photos(settings)
    (number,) = json.loads((folder / "photos.json").read_text())
    (folder / "photos.json").write_text(
        json.dumps({number: {"k": 1, "model": "google/gemini-3.6-flash"}})
    )
    (folder / tt.PASS1).mkdir()
    _write_csv(folder / tt.PASS1 / "photo-words.csv", ["row", "words"], [[number, "some invented"]])
    with pytest.raises(ConfigurationError, match=r"no longer match photos\.json"):
        tt.cmd_photos_recheck(settings)


def _handwriting_pages() -> dict[str, dict[str, object]]:
    """Two pages as the first pass stored them: page 1's draft is A, page 2's is B."""
    return {
        "1": {
            "letters": {"A": "openai/gpt-6-luna", "B": "google/gemini-3.6-flash"},
            "versions": {"A": ["Fuel BOTH", "Mixture RICH"], "B": ["Fuel BOTH", "Mixture LEAN"]},
            "draft": "A",
            "agreed": ["Fuel BOTH"],
            "spot": ["Fuel BOTH"],
        },
        "2": {
            "letters": {"A": "openai/gpt-6-luna", "B": "google/gemini-3.6-flash"},
            "versions": {"A": ["Engine quit"], "B": ["Engine quit", "at 800 ft"]},
            "draft": "B",
            "agreed": ["Engine quit"],
            "spot": [],
        },
    }


def test_draft_anchored_compares_lines_not_raw_text() -> None:
    pages = _handwriting_pages()
    edited_2 = {
        1: {"key": "Fuel  BOTH\n\nMixture RICH\n"},  # the draft, whitespace aside
        2: {"key": "Engine quit\nat 900 ft"},  # edited
    }
    assert tt.draft_anchored(pages, edited_2) == [1]
    edited_1 = {1: {"key": "Fuel BOTH"}, 2: {"key": "Engine quit\nat 800 ft"}}
    assert tt.draft_anchored(pages, edited_1) == [2]


def test_handwriting_recheck_lists_only_draft_anchored_pages_prefilled(tmp_path: Path) -> None:
    """Item 3: only the pages whose first-pass key is the draft; the box holds that key; the
    spot checks are not repeated."""
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    (folder / "handwriting.json").write_text(json.dumps(_handwriting_pages()))
    (folder / tt.PASS1).mkdir()
    _write_csv(
        folder / tt.PASS1 / "handwriting-key.csv",
        ["row", "spot check", "key"],
        [["1", "all correct", "Fuel BOTH\nMixture RICH"], ["2", "", "Engine quit\nat 900 ft"]],
    )

    result = tt.cmd_handwriting_recheck(settings)
    page = (folder / "handwriting-recheck.html").read_text()
    assert [int(n) for n in _ROWS.findall(page)] == [1]
    assert "1 draft-anchored pages" in result
    assert "Fuel BOTH\nMixture RICH</textarea>" in page
    assert "spot check" not in page
    assert "check this line" not in page
    assert '"s26-handwriting-key-pass2"' in page
    assert '"handwriting-key-pass2.csv"' in page
    assert "Check this page's key against the image and correct it" in page
    assert "left as the prefilled draft in the first pass" in page
    assert 'src="pages/handwriting-1.jpg"' in page
    assert '<span class="only">RICH</span>' in page


def test_overridden_replaces_rechecked_rows_field_by_field() -> None:
    first = {
        1: {"spot check": "all correct", "key": "old"},
        2: {"spot check": "", "key": "kept"},
    }
    again = {1: {"checked": "key corrected in the box", "key": "new"}}
    assert tt.overridden(first, again) == {
        1: {"spot check": "all correct", "key": "new", "checked": "key corrected in the box"},
        2: {"spot check": "", "key": "kept"},
    }
    photos = {11: {"words": "some invented"}, 12: {"words": "all on the page"}}
    assert tt.overridden(photos, {11: {"words": "all on the page"}}) == {
        11: {"words": "all on the page"},
        12: {"words": "all on the page"},
    }


def test_a_reply_under_half_the_key_lines_is_a_format_failure() -> None:
    """Item 2's boundary: against a 10-line key, 5 lines pass and 4 fail."""
    key = [f"line {i}" for i in range(10)]
    assert not tt.format_failed(key, key[:5])
    assert tt.format_failed(key, key[:4])
    assert not tt.format_failed(["a", "b", "c"], ["a", "b"])  # 2 of 3: not under half
    assert tt.format_failed(["a", "b", "c"], ["a"])  # 1 of 3: under half


def test_the_format_gate_is_one_in_twenty() -> None:
    """Item 2's gate, exactly as the photo gate: 1 of 20 passes, 2 of 20 is out."""
    chosen, _ = tt.choose(
        [
            _result("a", cost_per_page=0.0005, hw_pages=20, hw_format_failed=2),
            _result("b", hw_pages=20, hw_format_failed=1),
        ]
    )
    assert chosen == "b"
    _, notes = tt.choose([_result("a", hw_pages=25, hw_format_failed=2)])
    assert any("a: out -- fewer than half the key's lines on 2 of 25" in n for n in notes)
    assert tt.choose([_result("a", hw_pages=25, hw_format_failed=1)])[0] == "a"
    # The first pass never counts format failures, so the gate cannot fire there.
    assert tt.choose([_result("a", hw_pages=25)])[0] == "a"


def test_result_scores_a_format_failed_page_as_wrong_only_in_the_second_pass(
    tmp_path: Path,
) -> None:
    settings = Settings(data_dir=tmp_path)
    cache = TranscriptionCache(settings.transcription_dir)
    row = {"set": "handwriting", "k": 1, "document_sha256": "e" * 64, "page": 1}
    key = "\n".join(f"line {i}" for i in range(10))
    _put(cache, row, "openai/gpt-6-luna", "line 0\nline 1\nline 2\ninvented words")

    def result(*, format_gate: bool) -> tt.CandidateResult:
        return tt._result(
            "openai/gpt-6-luna",
            [row],
            {1: key},
            0,
            {},
            cache,
            dpi=RESOLUTION,
            format_gate=format_gate,
        )

    first, second = result(format_gate=False), result(format_gate=True)
    assert (first.hw_right, first.hw_format_failed, first.hw_pages) == (3, 0, 1)
    assert (second.hw_right, second.hw_format_failed, second.hw_pages) == (0, 1, 1)
    assert first.hw_inventing == second.hw_inventing == 1  # still counts as invented
    assert first.hw_lines == second.hw_lines == 10


def _score_fixture(tmp_path: Path) -> tuple[Settings, CachedDocuments, dict[str, Path]]:
    """One page per key set; GPT-6 Luna reads the handwriting page as one line of three.

    The first-pass key equals the draft (so the page is draft-anchored) and the one photograph
    output was first marked "some invented".
    """
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / tt.FOLDER
    folder.mkdir(parents=True)
    typed_doc = _text_pdf("FUEL SELECTOR BOTH. MIXTURE RICH.")
    _seed(settings.docket_dir, 1, typed_doc)
    docs = _offline_docs(settings)
    typed_row = {
        "set": "typed",
        "k": 1,
        "mkey": 1,
        "document": 1,
        "page": 1,
        "document_sha256": hashlib.sha256(typed_doc).hexdigest(),
    }
    hw_row = {"set": "handwriting", "k": 1, "document_sha256": "a" * 64, "page": 1}
    photo_row = {"set": "photo", "k": 1, "document_sha256": "b" * 64, "page": 1}
    mixed_row = {"set": "mixed", "k": 1, "document_sha256": "c" * 64, "page": 1}
    keys = [typed_row, hw_row, photo_row, mixed_row]
    (folder / "keys.jsonl").write_text("".join(json.dumps(r) + "\n" for r in keys))
    cache = TranscriptionCache(settings.transcription_dir)
    for model in tt.CANDIDATES:
        _put(cache, typed_row, model, page_text(typed_doc, 1))
        _put(cache, photo_row, model, "")
        _put(cache, mixed_row, model, "")
        luna = model == "openai/gpt-6-luna"
        _put(cache, hw_row, model, "Fuel BOTH" if luna else "Fuel BOTH\nMixture RICH\nEngine OK")
    draft = ["Fuel BOTH", "Mixture RICH", "Engine OK"]
    (folder / "handwriting.json").write_text(
        json.dumps({"1": {"versions": {"A": draft}, "draft": "A", "agreed": draft}})
    )
    (folder / "photos.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    (folder / "mixed.json").write_text(json.dumps({"11": {"k": 1, "model": "openai/gpt-6-luna"}}))
    csvs = {name: tmp_path / f"{name}.csv" for name in ("hw", "photos", "mixed", "hw2", "photos2")}
    _write_csv(csvs["hw"], ["row", "spot check", "key"], [["1", "", "\n".join(draft)]])
    _write_csv(csvs["photos"], ["row", "words"], [["11", "some invented"]])
    _write_csv(csvs["mixed"], ["row", "added words"], [["11", "all on the page and new"]])
    _write_csv(
        csvs["hw2"],
        ["row", "checked", "key"],
        [["1", "key corrected in the box", "Fuel BOTH\nMixture RICH\nEngine ROUGH"]],
    )
    _write_csv(csvs["photos2"], ["row", "words"], [["11", "all on the page"]])
    return settings, docs, csvs


def test_score_second_pass_applies_the_three_corrections(tmp_path: Path) -> None:
    settings, docs, csvs = _score_fixture(tmp_path)
    text = tt.cmd_score(
        settings,
        docs,
        csvs["hw"],
        csvs["photos"],
        csvs["mixed"],
        recheck=tt.Recheck(handwriting_csv=csvs["hw2"], photos_csv=csvs["photos2"]),
    )
    lines = text.splitlines()
    assert lines[0] == "# the transcriber test -- SECOND PASS (post-hoc, decision 0086)"
    assert lines[1].startswith("corrections (decision 0086, fixed before re-marking): 1.")
    assert lines[2] == (
        "re-marked: 1 photograph cards (1 marks changed); 1 handwriting pages (1 keys changed; "
        "0 pages where Andy's own answer disagrees)"
    )
    assert "the first pass stands unchanged in docs/results/s26-transcriber-test.txt" in text
    assert "# the transcriber test (S2.6 spec §7, decision 0080) -- counts only" in text
    # The re-marked photograph is no longer invented; the corrected key is the one scored.
    luna = text.split("## openai/gpt-6-luna")[1]
    assert "0 of 1 photographs" in luna
    # One line of a three-line key: under half, so wrong; 1 page in 1 is over 1 in 20 -- out.
    assert "handwriting lines right: 0 of 3" in luna
    assert "scored as wrong): 1 of 1" in luna
    assert "openai/gpt-6-luna: out -- fewer than half the key's lines on 1 of 1" in text
    flash = text.split("## google/gemini-3.6-flash")[1].split("##")[0]
    assert "handwriting lines right: 2 of 3" in flash  # "Engine OK" was corrected
    assert "scored as wrong): 0 of 1" in flash


def test_score_first_pass_is_unchanged_without_the_second(tmp_path: Path) -> None:
    """The same sheets without ``recheck``: no header, no format rule, the first-pass marks."""
    settings, docs, csvs = _score_fixture(tmp_path)
    text = tt.cmd_score(settings, docs, csvs["hw"], csvs["photos"], csvs["mixed"])
    assert text.splitlines()[0] == (
        "# the transcriber test (S2.6 spec §7, decision 0080) -- counts only"
    )
    assert "SECOND PASS" not in text
    assert "format-failed" not in text
    assert "decision 0086" not in text
    luna = text.split("## openai/gpt-6-luna")[1]
    assert "1 of 1 photographs" in luna
    assert "handwriting lines right: 1 of 3" in luna


def test_score_second_pass_refuses_a_recheck_with_the_wrong_rows(tmp_path: Path) -> None:
    settings, docs, csvs = _score_fixture(tmp_path)
    _write_csv(csvs["photos2"], ["row", "words"], [["12", "all on the page"]])
    recheck = tt.Recheck(handwriting_csv=csvs["hw2"], photos_csv=csvs["photos2"])
    with pytest.raises(SystemExit, match="the photograph recheck holds 1 row"):
        tt.cmd_score(settings, docs, csvs["hw"], csvs["photos"], csvs["mixed"], recheck=recheck)
    _write_csv(csvs["photos2"], ["row", "words"], [["11", "all on the page"]])
    _write_csv(csvs["hw2"], ["row", "checked", "key"], [["1", "", "Fuel BOTH"]])
    with pytest.raises(SystemExit, match=r"unmarked or empty for page\(s\): \[1\]"):
        tt.cmd_score(settings, docs, csvs["hw"], csvs["photos"], csvs["mixed"], recheck=recheck)


@pytest.mark.parametrize(
    "extra",
    [
        ["--pass2"],
        ["--pass2", "--handwriting-recheck", "h.csv"],
        ["--photos-recheck", "p.csv"],
        [
            "--pass2",
            "--handwriting-recheck",
            "h.csv",
            "--photos-recheck",
            "p.csv",
            "--out",
            "docs/results/s26-transcriber-test.txt",
        ],
    ],
)
def test_score_second_pass_arguments_are_refused_unless_complete(extra: list[str]) -> None:
    argv = ["score", "--handwriting", "a", "--photos", "b", "--mixed", "c", *extra]
    with pytest.raises(SystemExit) as raised:
        tt.main(argv)
    assert raised.value.code == 2  # argparse's usage error, before anything is read
