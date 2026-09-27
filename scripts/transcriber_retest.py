"""The transcriber re-test: new candidates on S2.6's answer keys, judged against Qwen (S2.7 §7.4).

Status
    One-shot (S2.7 track 2, Tasks 8-10). Built so far (Tasks 8 and 9):
      verify  -- re-score Qwen's cached readings on S2.6's keys and require its published
                 second-pass counts exactly (free; walkthrough W7)
      run     -- every candidate reads S2.6's four keys once at 150 dpi, synchronously at the
                 standard price (paid, up to about $2.50)
      pages   -- Andy's photograph and full-page-scan pages, for the candidates named (free;
                 walkthrough W3: those still in the running after Task 10's automatic measures)
    and decision 0100 item 3's choice rule (``choose_against_qwen``), fixed before any
    candidate is run. The score comes in Task 10.
    Reads S2.6's keys and marks under <data_dir>/s26/transcriber-test/ and never writes there;
    the pages and their sheets go under <data_dir>/s27/transcriber-retest/, and the readings
    into the transcription cache. Counts only.
"""

import argparse
import json
import os
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.render import RESOLUTION
from ntsb_probable_cause.docket.transcribe import TRANSCRIBE, TranscriptionCache
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts import transcriber_test as tt
from scripts.marking_page import Card, Choice, read_marks
from scripts.transcriber_shortlist import S27_CANDIDATES
from scripts.transcriber_test import (
    _GROUPED_LAYOUT,
    _MIXED_INTRO,
    _PHOTO_LABEL_RULE,
    _PHOTO_WORDS,
    _SCAN_WORDS,
    FOLDER,
    GATE_FORMAT_FAILED_SHARE,
    GATE_INVENTED_LINES_PER_100,
    GATE_INVENTED_MIXED_SHARE,
    GATE_INVENTED_PHOTO_SHARE,
    CandidateResult,
    Recheck,
    _apply_recheck,
    _fraction,
    _int,
    _key,
    _offline,
    _photo_body,
    _photo_group,
    _read,
    _reading_of,
    _result,
    _scan_body,
    _scan_group,
    _scan_layers,
    _version_cards,
)

RETEST_FOLDER = Path("s27") / "transcriber-retest"
# The reservation's price per page: twice Qwen's measured $0.00154; every candidate lists an
# input price at or below Qwen's (decision 0100 item 1).
EXPECTED_COST_PER_PAGE_USD = 0.003
# The re-test's own shuffles (S2.6's photographs used 100, its scans 200), so a page's version
# letters do not follow S2.6's order.
_PHOTO_SEED_BASE, _SCAN_SEED_BASE = 300, 400

QWEN = "qwen/qwen3.5-122b-a10b"
# docs/results/s26-transcriber-test-pass2.txt, Qwen's second-pass row (decision 0086).
QWEN_PASS2 = {
    "hw_lines": 1548,
    "hw_right": 1036,
    "hw_inventing": 54,
    "photo_pages": 50,
    "photo_invented": 2,
    "mixed_pages": 25,
    "mixed_invented": 0,
    "hw_pages": 25,
    "hw_format_failed": 2,
    "typed_chars": 164464,
    "typed_errors": 20219,
}
QWEN_COST_PER_PAGE = 0.00154


@dataclass(frozen=True)
class Limits:
    """Decision 0100 item 3: no worse than Qwen on invention, within 0080's margins on accuracy.

    Attributes:
        inventing_per_100: Most invented handwriting lines per 100 key lines.
        photo_invented: Most no-word photographs with an invented word (of 50).
        mixed_invented: Most full-page scans with invented added words (of 25).
        format_failed: Most handwriting pages failing the line format (of 25).
        hw_accuracy: Least share of handwriting key lines reproduced exactly.
        typed_errors_per_100: Most character errors per 100 characters of typed key.
        cost_per_page: The measured cost per test page a candidate must be below.
    """

    inventing_per_100: Fraction
    photo_invented: int
    mixed_invented: int
    format_failed: int
    hw_accuracy: Fraction
    typed_errors_per_100: Fraction
    cost_per_page: float


QWEN_LIMITS = Limits(
    inventing_per_100=Fraction(7, 2),
    photo_invented=2,
    mixed_invented=0,
    format_failed=2,
    hw_accuracy=Fraction(619, 1000),  # Qwen's 66.9% less 5 points
    typed_errors_per_100=Fraction(1329, 100),  # Qwen's 12.29 plus 1
    cost_per_page=QWEN_COST_PER_PAGE,
)


def _failures(r: CandidateResult, limits: Limits) -> list[str]:
    """Every one of the seven measures ``r`` misses, compared exactly from the raw counts."""
    out: list[str] = []
    if 100 * _fraction(r.hw_inventing, r.hw_lines) > limits.inventing_per_100:
        out.append(f"{r.hw_inventing} inventing lines in {r.hw_lines}")
    if r.photo_invented > limits.photo_invented:
        out.append(f"{r.photo_invented} of {r.photo_pages} photographs with invented words")
    if r.mixed_invented > limits.mixed_invented:
        out.append(f"{r.mixed_invented} of {r.mixed_pages} scans with invented added words")
    if r.hw_format_failed > limits.format_failed:
        out.append(f"{r.hw_format_failed} of {r.hw_pages} handwriting pages fail the format")
    if _fraction(r.hw_right, r.hw_lines) < limits.hw_accuracy:
        out.append(f"{r.hw_right} of {r.hw_lines} handwriting lines right")
    if 100 * _fraction(r.typed_errors, r.typed_chars) > limits.typed_errors_per_100:
        out.append(f"{r.typed_errors} typed errors in {r.typed_chars} characters")
    if not r.cost_per_page < limits.cost_per_page:
        out.append(f"${r.cost_per_page:.5f} a test page, not below Qwen's")
    return out


def choose_against_qwen(results: Sequence[CandidateResult]) -> tuple[str | None, list[str]]:
    """Decision 0100 item 3: the cheapest candidate meeting all seven, or None (Qwen stays).

    Args:
        results: Each candidate's counts on S2.6's four keys and its measured cost per page.

    Returns:
        The chosen model id, or None when no candidate meets all seven measures; and one note
        per candidate saying why it is out or that it meets all seven, then the outcome. A
        cost tie goes to the first model id in sort order.
    """
    notes: list[str] = []
    passing: list[CandidateResult] = []
    for r in results:
        failed = _failures(r, QWEN_LIMITS)
        if failed:
            notes.append(f"{r.model}: out -- " + "; ".join(failed))
        else:
            notes.append(f"{r.model}: meets all seven, ${r.cost_per_page:.5f} a test page")
            passing.append(r)
    if not passing:
        notes.append("no candidate meets all seven: Qwen stays (decision 0100 item 3)")
        return None, notes
    chosen = min(passing, key=lambda r: (r.cost_per_page, r.model))
    notes.append(f"chosen: {chosen.model}, the cheapest of {len(passing)} meeting all seven")
    return chosen.model, notes


def _exact(limit: float | Fraction) -> Fraction:
    """A gate constant as an exact fraction: S2.6's float ``1 / 20`` becomes exactly 1/20."""
    return Fraction(limit).limit_denominator()


def absolute_notes(r: CandidateResult) -> list[str]:
    """0080's absolute limits, printed beside a candidate; they decide nothing here.

    Args:
        r: One candidate's counts.

    Returns:
        One line per limit: the candidate's value, the limit, and "within" or "over".
    """
    checks = (
        (
            "inventing lines per 100",
            100 * _fraction(r.hw_inventing, r.hw_lines),
            GATE_INVENTED_LINES_PER_100,
        ),
        (
            "photographs with invented words",
            _fraction(r.photo_invented, r.photo_pages),
            GATE_INVENTED_PHOTO_SHARE,
        ),
        (
            "scans with invented added words",
            _fraction(r.mixed_invented, r.mixed_pages),
            GATE_INVENTED_MIXED_SHARE,
        ),
        (
            "format-failed handwriting pages",
            _fraction(r.hw_format_failed, r.hw_pages),
            GATE_FORMAT_FAILED_SHARE,
        ),
    )
    return [
        f"  0080's limit, {name}: {float(value):.3g} against {float(limit):.3g} "
        f"({'within' if value <= _exact(limit) else 'over'})"
        for name, value, limit in checks
    ]


def matches_qwen_pass2(r: CandidateResult) -> list[str]:
    """Every count of Qwen's re-scored row that differs from the published second pass.

    Args:
        r: Qwen's counts, re-scored from the transcription cache.

    Returns:
        One line per differing count; empty when every count matches.
    """
    return [
        f"{name} {getattr(r, name)}, published {value}"
        for name, value in QWEN_PASS2.items()
        if getattr(r, name) != value
    ]


@dataclass(frozen=True)
class KeyMaterial:
    """S2.6's four keys as its second pass scored them, and Qwen's photo and scan marks.

    Attributes:
        keys: The rows of ``keys.jsonl``: every key page, by set.
        key_texts: Andy's final handwriting key per page (decision 0086's recheck applied).
        typed_answers: The text layer of each typed key page, by key number.
        qwen_photo_invented: Qwen's photograph cards finally marked "some invented".
        qwen_mixed_invented: Qwen's full-page scan cards marked "some invented".
    """

    keys: list[dict[str, object]]
    key_texts: dict[int, str]
    typed_answers: dict[int, str]
    qwen_photo_invented: int
    qwen_mixed_invented: int


def key_material(settings: Settings, docs: CachedDocuments, recheck: Recheck) -> KeyMaterial:
    """The keys, Andy's final handwriting key (0086), the typed answers, Qwen's marks.

    Args:
        settings: Where S2.6's keys folder is (``<data_dir>/s26/transcriber-test``).
        docs: The docket cache, offline, for the typed pages' text layers.
        recheck: The second-pass CSV pair, applied over the ``pass1/`` CSVs.

    Returns:
        The key material every candidate, and Qwen, is scored against.
    """
    folder = settings.data_dir / FOLDER
    keys = _read(folder / "keys.jsonl")
    pages = json.loads((folder / "handwriting.json").read_text())
    photo_sheet = json.loads((folder / "photos.json").read_text())
    mixed_sheet = json.loads((folder / "mixed.json").read_text())
    hw_first = read_marks(folder / "pass1" / "handwriting-key.csv")
    photo_first = read_marks(folder / "pass1" / "photo-words.csv")
    hw_marks, photo_marks, _header = _apply_recheck(pages, hw_first, photo_first, recheck)
    mixed_marks = read_marks(folder / "pass1" / "mixed-words.csv")
    typed_answers = {
        _int(r, "k"): page_text(
            docs.document(_int(r, "mkey"), _int(r, "document")), _int(r, "page")
        )
        for r in keys
        if r["set"] == "typed"
    }
    return KeyMaterial(
        keys=keys,
        key_texts={k: fields["key"] for k, fields in hw_marks.items()},
        typed_answers=typed_answers,
        qwen_photo_invented=sum(
            1
            for n, fields in photo_marks.items()
            if photo_sheet.get(str(n), {}).get("model") == QWEN
            and fields.get("words") == "some invented"
        ),
        qwen_mixed_invented=sum(
            1
            for n, fields in mixed_marks.items()
            if mixed_sheet.get(str(n), {}).get("model") == QWEN
            and fields.get("added words") == "some invented"
        ),
    )


def cmd_verify(settings: Settings, docs: CachedDocuments, recheck: Recheck) -> str:
    """Walkthrough W7: Qwen re-scored from the cache must equal its published second pass.

    Args:
        settings: Where S2.6's keys and the transcription cache are.
        docs: The docket cache, offline.
        recheck: The second-pass CSV pair to try.

    Returns:
        A line naming the CSV pair that reproduced the published counts.

    Raises:
        SystemExit: Any count differs; the message names the pair and every difference.
    """
    material = key_material(settings, docs, recheck)
    qwen = _result(
        QWEN,
        material.keys,
        material.key_texts,
        material.qwen_photo_invented,
        material.typed_answers,
        TranscriptionCache(settings.transcription_dir),
        dpi=RESOLUTION,
        mixed_invented=material.qwen_mixed_invented,
        format_gate=True,
    )
    differences = matches_qwen_pass2(qwen)
    if differences:
        raise SystemExit(
            "Qwen's re-scored counts differ from docs/results/s26-transcriber-test-pass2.txt "
            f"with the recheck CSVs {recheck.handwriting_csv.name}, {recheck.photos_csv.name}: "
            + "; ".join(differences)
        )
    return (
        f"verified: Qwen's second pass reproduced exactly from the cache with "
        f"{recheck.handwriting_csv} and {recheck.photos_csv}"
    )


def cmd_run(
    settings: Settings, docs: CachedDocuments, *, models: Sequence[str], retry_failed: bool = False
) -> str:
    """Each candidate reads every key page once at 150 dpi, instruction t1 (as S2.6's run).

    S2.6's own run (``transcriber_test.cmd_run``, pre-flight 2.6) with one reservation price
    for every candidate: each model is one ``run_preparation`` job, which reserves within the
    month's budget and stops once its pages cost what it reserved. Every call is synchronous
    at the standard price (``transcribe.settings_for``; the batch service refuses images).

    Args:
        settings: Where S2.6's keys, the transcription cache and the spend records are.
        docs: The docket cache, offline.
        models: The candidates to run.
        retry_failed: Re-read each page whose cached reading failed, once.

    Returns:
        One line per candidate: pages read, pages failed, and their cost.
    """
    return tt.cmd_run(
        settings,
        docs,
        models=models,
        dpi=RESOLUTION,
        retry_failed=retry_failed,
        expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD,
    )


def word_cards(  # noqa: PLR0913 -- one keyword per fact a page's cards differ by.
    rows: Sequence[Mapping[str, object]],
    text_of: Callable[[int, str], str],
    *,
    models: Sequence[str],
    seed_base: int,
    choices: tuple[Choice, ...] = (_PHOTO_WORDS,),
    body: Callable[[int, str, str], str] = _photo_body,
) -> tuple[dict[int, dict[str, object]], list[Card]]:
    """One card per candidate reading holding a word; rows 10k+i, candidates shuffled per page.

    S2.6's own card loop (``transcriber_test._version_cards``), so a re-test card is numbered,
    lettered and judged as Qwen's were: a reading holds a word if it has two letters or digits
    in a row, which ``[illegible]`` does.

    Args:
        rows: The key pages, each with its number ``k``.
        text_of: A candidate's reading of page ``k``.
        models: The candidates, at most eight.
        seed_base: Added to S2.6's seed and ``k`` to shuffle the candidates on each page.
        choices: The card's choices; the photograph page's by default.
        body: The card's HTML from ``(k, version, text)``; a photograph card's by default.

    Returns:
        The sheet (row number to page and model) and the cards, in page order.
    """
    return _version_cards(
        rows, text_of, models=models, seed_base=seed_base, body=body, choices=choices
    )


def _missing(
    settings: Settings, rows: Sequence[Mapping[str, object]], models: Sequence[str]
) -> list[str]:
    """One line per candidate with key pages the cache holds no reading of (not yet run)."""
    cache = TranscriptionCache(settings.transcription_dir)
    out: list[str] = []
    for model in models:
        keys = (
            _key(row, model, instruction=TRANSCRIBE, dpi=RESOLUTION, mixed=row["set"] == "mixed")
            for row in rows
        )
        absent = sum(1 for key in keys if cache.get(key) is None)
        if absent:
            out.append(f"{absent} readings of {model}")
    return out


def cmd_pages(settings: Settings, docs: CachedDocuments, *, models: Sequence[str]) -> str:
    """Andy's two pages (walkthrough W3): the named candidates' words, in S2.6's layout.

    One page for the no-word photographs, one for the full-page scans. The candidates are
    put in sort order first, so the same candidates give the same card numbers whatever order
    they are named in, and marks already made reload on a rebuild. Each page shows S2.6's own
    page images through a path relative to it; none is copied.

    Args:
        settings: Where S2.6's keys and the transcription cache are.
        docs: The docket cache, offline, for the scans' text layers.
        models: The candidates still in the running (Task 10's automatic measures).

    Returns:
        The number of cards on each page, and where the pages are.

    Raises:
        ConfigurationError: A candidate has key pages with no cached reading; the pages
            would show those readings as holding no words.
    """
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    photos = [r for r in keys if r["set"] == "photo"]
    scans = [r for r in keys if r["set"] == "mixed"]
    ordered = tuple(sorted(set(models)))
    missing = _missing(settings, [*photos, *scans], ordered)
    if missing:
        raise ConfigurationError(
            "not in the transcription cache: " + "; ".join(missing) + " -- run the re-test first"
        )
    out = settings.data_dir / RETEST_FOLDER
    out.mkdir(parents=True, exist_ok=True)
    pages = os.path.relpath(FOLDER / "pages", RETEST_FOLDER)

    photo_sheet, photo_cards = word_cards(
        photos, _reading_of(settings, photos), models=ordered, seed_base=_PHOTO_SEED_BASE
    )
    (out / "photos.json").write_text(json.dumps(photo_sheet))
    photo_intro = (
        _GROUPED_LAYOUT + "<p>Each photograph is shown once on the left, held in view, with the "
        "words each candidate transcriber wrote for it as cards on the right, one per version. "
        "These photographs hold no words of their own apart from the docket's labels, so most "
        "versions are empty and are not shown. <b>Decision 0086's rule:</b> "
        + _PHOTO_LABEL_RULE
        + " Mark <b>some invented</b> if any other word is not on the page. Click a photograph "
        "to enlarge it.</p>"
    )
    (out / "photos.html").write_text(
        marking_page.render(
            title="Invented words on photographs (S2.7 re-test, spec §7.4)",
            intro_html=photo_intro,
            cards=photo_cards,
            storage_key="s27-photo-words",
            csv_name="s27-photo-words.csv",
            groups={str(_int(r, "k")): _photo_group(_int(r, "k"), pages) for r in photos},
        )
    )

    layers = _scan_layers(scans, docs)
    scan_sheet, scan_cards = word_cards(
        scans,
        _reading_of(settings, scans),
        models=ordered,
        seed_base=_SCAN_SEED_BASE,
        choices=(_SCAN_WORDS,),
        body=_scan_body(layers),
    )
    (out / "mixed.json").write_text(json.dumps(scan_sheet))
    (out / "mixed.html").write_text(
        marking_page.render(
            title="Words added to full-page scans (S2.7 re-test, spec §7.4)",
            intro_html=_GROUPED_LAYOUT + _MIXED_INTRO,
            cards=scan_cards,
            storage_key="s27-mixed-words",
            csv_name="s27-mixed-words.csv",
            groups={str(k): _scan_group(k, layer, pages) for k, layer in layers.items()},
        )
    )
    return (
        f"{len(photo_cards)} photograph outputs with words; page at {out / 'photos.html'}\n"
        f"{len(scan_cards)} full-page scan outputs with added words; page at {out / 'mixed.html'}"
    )


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="transcriber_retest")
    commands = parser.add_subparsers(dest="command", required=True)
    verify_p = commands.add_parser("verify")
    verify_p.add_argument("--handwriting-recheck", type=Path, required=True)
    verify_p.add_argument("--photos-recheck", type=Path, required=True)
    run_p = commands.add_parser("run")
    run_p.add_argument("--retry-failed", action="store_true")
    pages_p = commands.add_parser("pages")
    pages_p.add_argument("--models", nargs="+", required=True, choices=S27_CANDIDATES)
    args = parser.parse_args(argv)
    settings = Settings()
    # As transcriber_test.main: offline, one attempt -- a cache miss is a bug, not a fault.
    docs = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline(), max_attempts=1))
    if args.command == "run":
        text = cmd_run(settings, docs, models=S27_CANDIDATES, retry_failed=args.retry_failed)
    elif args.command == "pages":
        text = cmd_pages(settings, docs, models=args.models)
    else:
        recheck = Recheck(handwriting_csv=args.handwriting_recheck, photos_csv=args.photos_recheck)
        text = cmd_verify(settings, docs, recheck)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
