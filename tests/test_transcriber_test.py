"""scripts/transcriber_test.py: the measures and the rule, fixed before the test runs (0080)."""

import hashlib
import io
import json
from datetime import UTC, datetime
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
    TRANSCRIBE,
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


def test_resolution_200_only_for_more_than_five_points() -> None:
    assert tt.choose_resolution(0.80, 0.85) == 150
    assert tt.choose_resolution(0.80, 0.851) == 200


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
    cache.put(
        Transcription(
            key=tt._key(row, model, instruction=TRANSCRIBE.version, dpi=dpi),
            status="transcribed",
            text=text,
            cost_usd=cost_usd,
            prompt_tokens=prompt_tokens,
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
                {"kind": "image only"},
                {"kind": "image only"},
                {"kind": "text and image"},
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
    assert "stage total: $" in result
    assert "spent on S2.6 so far" in result
