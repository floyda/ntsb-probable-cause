"""scripts/transcriber_test.py: the measures and the rule, fixed before the test runs (0080)."""

import hashlib
import io
import json
import random
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

    result = tt.cmd_estimate(settings, "openai/gpt-6-luna", RESOLUTION)
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
    # in this repo's fixed calendar): counted in the stage total (unfiltered by date) but not
    # in `month_spent` (filtered to the current month), so headroom stays close to $40.
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

    result = tt.cmd_estimate(settings, "openai/gpt-6-luna", RESOLUTION)
    assert "pause: ask Andy" in result
    assert "passes the $40 stage line (decision 0083 item 2)" in result
    assert "does not fit the month's" not in result


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
