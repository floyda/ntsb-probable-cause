"""The transcriber re-test: new candidates on S2.6's answer keys, judged against Qwen (S2.7 §7.4).

Status
    One-shot (S2.7 track 2, Tasks 8-10). Built (Tasks 8 to 10):
      verify    -- re-score Qwen's cached readings on S2.6's keys and require its published
                   second-pass counts exactly (free; walkthrough W7)
      run       -- every candidate reads S2.6's four keys once at 150 dpi, synchronously at
                   the standard price (paid, up to about $2.50); ``--models`` names a subset,
                   as when the retry was finished for the five candidates a stopped one missed
      automatic -- the candidates still in the running on every measure that needs no marks,
                   and cost; Andy marks only those (free; walkthrough W3)
      pages     -- Andy's photograph and full-page-scan pages, for the candidates named (free;
                   walkthrough W3: those ``automatic`` leaves in the running)
      score     -- decision 0100 item 3's choice rule (``choose_against_qwen``, fixed before
                   any candidate was run) over every candidate, with Andy's marks (free)
      routing-pages, routing-tally
                -- exploratory, outside that rule (Andy, 2026-09-27): a full-page-scan page
                   for the named candidates in its own folder, and the tally of Andy's marks,
                   for routing text-and-image pages to a cheaper model (free)
    ``automatic`` and ``score`` first re-verify Qwen's row from the cache (as ``verify``) and
    refuse a candidate with a key page never read.
    Reads S2.6's keys and marks under <data_dir>/s26/transcriber-test/ and never writes there;
    the pages and their sheets go under <data_dir>/s27/transcriber-retest/, and the readings
    into the transcription cache. Counts only.
"""

import argparse
import json
import os
from collections import Counter
from collections.abc import Callable, Collection, Mapping, Sequence
from dataclasses import dataclass, replace
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
    _reading_counts,
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
        out.append(
            f"${r.cost_per_page:.7f} a test page, not below the rule's ${limits.cost_per_page:.5f}"
        )
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


def _scored(
    model: str,
    material: KeyMaterial,
    cache: TranscriptionCache,
    *,
    photo_invented: int = 0,
    mixed_invented: int = 0,
) -> CandidateResult:
    """One model's counts on the four keys, scored exactly as S2.6's second pass scored Qwen."""
    return _result(
        model,
        material.keys,
        material.key_texts,
        photo_invented,
        material.typed_answers,
        cache,
        dpi=RESOLUTION,
        mixed_invented=mixed_invented,
        format_gate=True,
    )


def _verified(
    settings: Settings, docs: CachedDocuments, recheck: Recheck
) -> tuple[KeyMaterial, CandidateResult]:
    """The key material, and Qwen's row re-scored from the cache, which must be its published one.

    Raises:
        SystemExit: Any count differs; the message names the pair and every difference.
    """
    material = key_material(settings, docs, recheck)
    qwen = _scored(
        QWEN,
        material,
        TranscriptionCache(settings.transcription_dir),
        photo_invented=material.qwen_photo_invented,
        mixed_invented=material.qwen_mixed_invented,
    )
    differences = matches_qwen_pass2(qwen)
    if differences:
        raise SystemExit(
            "Qwen's re-scored counts differ from docs/results/s26-transcriber-test-pass2.txt "
            f"with the recheck CSVs {recheck.handwriting_csv.name}, {recheck.photos_csv.name}: "
            + "; ".join(differences)
        )
    return material, qwen


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
    _verified(settings, docs, recheck)
    return (
        f"verified: Qwen's second pass reproduced exactly from the cache with "
        f"{recheck.handwriting_csv} and {recheck.photos_csv}"
    )


# The re-test's retries, as run (the S2.7 track 2 plan's Deviations, Task 9 Step 6): stated in
# the results file because a page still failed after them is scored as wrong.
RETRY_NOTE = (
    "retries: each candidate had one retry of failed pages (run --retry-failed), except "
    "deepseek/deepseek-v4.1-flash, whose retry stopped at its reservation with 31 pages "
    "unread (the S2.7 track 2 plan's Deviations, Task 9 Step 6); its counts include those "
    "pages as failed, and a failed page is scored as wrong for its reader"
)


def automatic_pass(r: CandidateResult) -> bool:
    """Walkthrough W3 (Andy, 2026-09-27): every measure that needs no marks, and cost.

    Args:
        r: One candidate's counts; its photograph and scan counts are ignored.

    Returns:
        True when ``r`` meets decision 0100 item 3 on every measure but the two marked ones.
    """
    return not _failures(replace(r, photo_invented=0, mixed_invented=0), QWEN_LIMITS)


def _refuse_unread(
    settings: Settings, rows: Sequence[Mapping[str, object]], models: Sequence[str]
) -> None:
    """Refuse a candidate with a key page never read: it would be scored as wrong, unseen.

    Raises:
        SystemExit: The cache holds no reading of some key page for some candidate.
    """
    missing = _missing(settings, rows, models)
    if missing:
        raise SystemExit(
            "not in the transcription cache: " + "; ".join(missing) + " -- run the re-test first"
        )


def _failed_line(cache: TranscriptionCache, material: KeyMaterial, r: CandidateResult) -> str:
    """The candidate's measured cost to 7 places, and its key pages still failed after retry."""
    counts = _reading_counts(cache, material.keys, r.model, dpi=RESOLUTION)
    failed = sum(c.failed for c in counts.values())
    return (
        f"  measured ${r.cost_per_page:.7f} a test page; {failed} of {len(material.keys)} key "
        "pages failed to read"
    )


def _pair(recheck: Recheck) -> str:
    """The recheck CSV pair, each named with its folder (``pass2/...``)."""
    return " and ".join(
        f"{p.parent.name}/{p.name}" for p in (recheck.handwriting_csv, recheck.photos_csv)
    )


def _bar_lines(qwen: CandidateResult, recheck: Recheck) -> list[str]:
    """The rule's published bar, and Qwen's row as the cache gives it, unrounded cost included.

    The rule's cost bar is S2.6's rounded $0.00154; Qwen's measured cost is printed beside it
    to 10 places so a candidate between the two can be seen (Task 8 review).
    """
    return [
        "the bar: decision 0100 item 3's limits, from Qwen3.5 122B's published second pass "
        "(docs/results/s26-transcriber-test-pass2.txt); its cost bar is S2.6's rounded "
        f"${QWEN_LIMITS.cost_per_page:.5f} a test page",
        f"Qwen re-scored from the cache as the candidates are, with {_pair(recheck)}: "
        f"{qwen.hw_right} of {qwen.hw_lines} handwriting lines right ({qwen.hw_accuracy:.1%}), "
        f"{qwen.hw_inventing} inventing lines, {qwen.photo_invented} of {qwen.photo_pages} "
        f"photographs and {qwen.mixed_invented} of {qwen.mixed_pages} scans with invented "
        f"words, {qwen.hw_format_failed} of {qwen.hw_pages} format-failed handwriting pages, "
        f"{qwen.typed_errors_per_100:.2f} typed errors per 100 characters; measured "
        f"${qwen.cost_per_page:.10f} a test page against the rule's "
        f"${QWEN_LIMITS.cost_per_page:.5f}",
    ]


def _for_andy(results: Sequence[CandidateResult], qwen: CandidateResult) -> list[str]:
    """Candidates dearer than Qwen's measured cost yet below the rule's rounded bar.

    The rule is not changed (decision 0100 item 3 was fixed before the run); the line only
    makes the gap between S2.6's rounded $0.00154 and Qwen's measured cost visible to Andy.
    """
    bar = QWEN_LIMITS.cost_per_page
    return [
        f"FOR ANDY: {r.model} costs ${r.cost_per_page:.7f}, below the rule's ${bar:.5f} but "
        f"above Qwen's measured ${qwen.cost_per_page:.7f}; the rule as written admits it"
        for r in results
        if qwen.cost_per_page <= r.cost_per_page < bar
    ]


def cmd_automatic(
    settings: Settings, docs: CachedDocuments, recheck: Recheck, *, models: Sequence[str]
) -> tuple[str, tuple[str, ...]]:
    """The candidates still in the running before any marking (walkthrough W3), and why not.

    A candidate out on an automatic measure cannot be chosen whatever its marks (decision
    0100 item 3), so Andy marks only the ones still in.

    Args:
        settings: Where S2.6's keys and the transcription cache are.
        docs: The docket cache, offline.
        recheck: The second-pass CSV pair; Qwen's row must reproduce with it.
        models: The candidates.

    Returns:
        The text (Qwen's bar, one entry per candidate, any line for Andy, and "to mark"), and
        the candidates still in the running.
    """
    material, qwen = _verified(settings, docs, recheck)
    _refuse_unread(settings, material.keys, models)
    cache = TranscriptionCache(settings.transcription_dir)
    results = [_scored(m, material, cache) for m in models]
    still_in = tuple(r.model for r in results if automatic_pass(r))
    lines = [*_bar_lines(qwen, recheck), ""]
    for r in results:
        lines.append(
            f"{r.model}: still in the running"
            if r.model in still_in
            else f"{r.model}: out on an automatic measure -- "
            + "; ".join(_failures(replace(r, photo_invented=0, mixed_invented=0), QWEN_LIMITS))
        )
        lines.append(_failed_line(cache, material, r))
    lines += _for_andy(results, qwen)
    lines.append(f"to mark: {' '.join(still_in) or 'none (Qwen stays; no marking needed)'}")
    return "\n".join(lines), still_in


def invented_by_model(
    sheet: Mapping[str, Mapping[str, object]],
    marks: Mapping[int, Mapping[str, str]],
    *,
    field: str,
    invented: str,
) -> Counter[str]:
    """Cards marked ``invented``, by model; every card on the sheet must be marked.

    Args:
        sheet: Card row number (as a string) to its page ``k`` and ``model``.
        marks: Andy's downloaded CSV, by row number.
        field: The mark's column.
        invented: The choice that counts.

    Returns:
        The number of cards marked ``invented``, by model.

    Raises:
        SystemExit: A card on the sheet is unmarked, or missing from the CSV.
    """
    if any(marks.get(int(n), {}).get(field, "") == "" for n in sheet):
        raise SystemExit(f"some cards are unmarked ({field})")
    return Counter(
        str(sheet[str(n)]["model"])
        for n, fields in marks.items()
        if str(n) in sheet and fields.get(field) == invented
    )


def _marked_counts(
    folder: Path, photos_csv: Path, mixed_csv: Path, marked: Collection[str]
) -> tuple[Counter[str], Counter[str]]:
    """The marked candidates' photographs and scans with invented words, from Andy's CSVs.

    Raises:
        SystemExit: A card is unmarked, or a sheet holds cards of a model not in ``marked``.
    """
    counts: list[Counter[str]] = []
    for sheet_name, csv, field in (
        ("photos.json", photos_csv, "words"),
        ("mixed.json", mixed_csv, "added words"),
    ):
        sheet = json.loads((folder / sheet_name).read_text())
        others = sorted({str(v["model"]) for v in sheet.values()} - set(marked))
        if others:
            raise SystemExit(
                f"score: {sheet_name} holds cards of models not named in --marked: "
                + " ".join(others)
            )
        counts.append(
            invented_by_model(sheet, read_marks(csv), field=field, invented="some invented")
        )
    return counts[0], counts[1]


def cmd_score(  # noqa: PLR0913 -- the key material's recheck pair and the two new CSVs.
    settings: Settings,
    docs: CachedDocuments,
    recheck: Recheck,
    photos_csv: Path | None,
    mixed_csv: Path | None,
    *,
    models: Sequence[str],
    marked: Collection[str],
) -> str:
    """Decision 0100 item 3 over the candidates; Qwen's row printed as the bar.

    Only ``marked`` candidates (those still in the running after :func:`cmd_automatic`) have
    photograph and scan marks (walkthrough W3); the rest print "not marked (already out)". With
    none marked there are no CSVs, and ``photos_csv``/``mixed_csv`` are None.

    Args:
        settings: Where S2.6's keys, the re-test's sheets and the transcription cache are.
        docs: The docket cache, offline.
        recheck: The second-pass CSV pair; Qwen's row must reproduce with it.
        photos_csv: Andy's marks on the re-test's photograph page, or None if none marked.
        mixed_csv: Andy's marks on the re-test's full-page scan page, or None if none marked.
        models: The candidates.
        marked: The candidates Andy marked: exactly those still in the running.

    Returns:
        The results file's text.

    Raises:
        SystemExit: A candidate still in the running was not marked (the rule would score
            its marked measures as 0), a CSV is missing or has an unmarked card, or a
            candidate has a key page never read.
    """
    material, qwen = _verified(settings, docs, recheck)
    _refuse_unread(settings, material.keys, models)
    cache = TranscriptionCache(settings.transcription_dir)
    automatic = [_scored(m, material, cache) for m in models]
    unmarked = [r.model for r in automatic if automatic_pass(r) and r.model not in marked]
    if unmarked:
        raise SystemExit(
            "score: still in the running but not marked: "
            + " ".join(unmarked)
            + " -- build their pages (s27-retest-pages) and mark them first"
        )
    photos: Counter[str] = Counter()
    mixed: Counter[str] = Counter()
    if marked:
        if photos_csv is None or mixed_csv is None:
            raise SystemExit("score: candidates are marked, so both marks CSVs are required")
        photos, mixed = _marked_counts(
            settings.data_dir / RETEST_FOLDER, photos_csv, mixed_csv, marked
        )
    results = [
        replace(r, photo_invented=photos[r.model], mixed_invented=mixed[r.model]) for r in automatic
    ]
    _chosen, notes = choose_against_qwen(results)  # the notes' last line names the outcome
    recollection = (
        "the pass2/ pair Andy recalled as final"
        if recheck.handwriting_csv.parent.name == "pass2"
        else "not the pass2/ pair Andy recalled as final"
    )
    lines = [
        "# the transcriber re-test (S2.7 spec §7.4, decision 0100) -- counts only",
        "keys: S2.6's four (docs/results/s26-transcriber-test-pass2.txt); 150 dpi; instruction "
        f"t1; decision 0086's corrections; the second-pass recheck CSVs {_pair(recheck)}, "
        f"which reproduce Qwen's published counts exactly (walkthrough W7; {recollection})",
        RETRY_NOTE,
        *_bar_lines(qwen, recheck),
        "",
    ]
    out_note = "not marked (already out on an automatic measure, walkthrough W3)"
    for r in results:
        is_marked = r.model in marked
        photo_line = (
            f"{r.photo_invented} of {r.photo_pages} photographs"
            if is_marked
            else f"photographs {out_note}"
        )
        scan_line = (
            f"  full-page scans: invented added words on {r.mixed_invented} of {r.mixed_pages}"
            if is_marked
            else f"  full-page scans: {out_note}"
        )
        lines += [
            f"## {r.model} (measured ${r.cost_per_page:.7f} per test page)",
            f"  invented: {r.hw_inventing} lines ({r.invented_per_100_lines:.1f} per 100 "
            f"handwriting lines); {photo_line}",
            f"  handwriting lines right: {r.hw_right} of {r.hw_lines} ({r.hw_accuracy:.1%})",
            f"  typed errors: {r.typed_errors_per_100:.2f} per 100 characters",
            scan_line,
            f"  format-failed handwriting pages: {r.hw_format_failed} of {r.hw_pages}",
            _failed_line(cache, material, r),
            *(absolute_notes(r) if is_marked else ()),
        ]
    lines += _for_andy(results, qwen)
    lines += ["", "## the rule (decision 0100 item 3, fixed before the run)", *notes]
    return "\n".join(lines)


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


def _refuse_moved_marks(out: Path, sheets: Mapping[str, dict[int, dict[str, object]]]) -> None:
    """Refuse a rebuild whose sheet would renumber cards already written (as S2.6's recheck).

    A marking page keeps Andy's marks in the browser by row number, under a fixed storage key.
    The shuffle depends on the set of candidates, so a rebuild with another set can give row
    ``10k + i`` to another model: an earlier mark would show on, and be scored against, a
    reading Andy never marked. A rebuild with the same candidates writes the same sheet.

    Raises:
        ConfigurationError: An existing sheet in ``out`` differs from the one to be written.
    """
    changed: list[str] = []
    for name, sheet in sheets.items():
        path = out / name
        if not path.exists():
            continue
        old = json.loads(path.read_text())
        new = json.loads(json.dumps(sheet))
        rows = sorted(int(n) for n in old.keys() | new.keys() if old.get(n) != new.get(n))
        if rows:
            changed.append(f"{name} rows {rows}")
    if changed:
        raise ConfigurationError(
            "these candidates would renumber cards already on Andy's pages, so marks saved in "
            "the browser would sit on other models' readings: "
            + "; ".join(changed)
            + f". Rebuild with the same candidates, or to start over deliberately, move {out} "
            "aside and clear the pages' saved marks in the browser"
        )


def _scan_cards(
    settings: Settings,
    docs: CachedDocuments,
    scans: Sequence[Mapping[str, object]],
    models: Sequence[str],
    choice: Choice = _SCAN_WORDS,
) -> tuple[dict[int, str], dict[int, dict[str, object]], list[Card]]:
    """The full-page scans' text layers, sheet and cards, shuffled with the re-test's scan seed.

    Shared by the re-test's scan page and the routing page, so the same candidates give the
    same card numbers on both. ``choice`` changes only the cards' options, never the sheet.
    """
    layers = _scan_layers(scans, docs)
    sheet, cards = word_cards(
        scans,
        _reading_of(settings, scans),
        models=models,
        seed_base=_SCAN_SEED_BASE,
        choices=(choice,),
        body=_scan_body(layers),
    )
    return layers, sheet, cards


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
    photo_sheet, photo_cards = word_cards(
        photos, _reading_of(settings, photos), models=ordered, seed_base=_PHOTO_SEED_BASE
    )
    layers, scan_sheet, scan_cards = _scan_cards(settings, docs, scans, ordered)
    out = settings.data_dir / RETEST_FOLDER
    _refuse_moved_marks(out, {"photos.json": photo_sheet, "mixed.json": scan_sheet})
    out.mkdir(parents=True, exist_ok=True)
    pages = os.path.relpath(FOLDER / "pages", RETEST_FOLDER)

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


# Andy, 2026-09-27 ("now"): whether cheaper candidates invent added words on text-and-image
# pages, for decision 120's open idea of routing those pages to a cheaper model. Exploratory:
# outside decision 0100 item 3's rule, and it changes neither the rule nor the re-test's outcome.
ROUTING_FOLDER = RETEST_FOLDER / "routing"
_ROUTING_INTRO = (
    "<p>This page marks, for each candidate's reading of S2.6's full-page scans, whether its "
    "added words are on the page, repeat the text layer, or are invented. It serves a question "
    "outside the re-test's rule: whether text-and-image pages could be routed to a cheaper "
    "model. Qwen's readings are not shown: S2.6 already marked them (0 of 25 invented). "
    "Pick <b>can't judge</b> when the part of the page the added words would come from cannot "
    "be read; those cards are counted apart and not as invented.</p>"
)
# Andy, 2026-09-28 (A): a fourth choice on the routing page alone, for added words from a
# part of the page he cannot read. S2.6's ``_SCAN_WORDS`` and the re-test's page keep three.
_CANT_JUDGE = "can't judge — I can't read this part of the page"
_ROUTING_SCAN_WORDS = Choice(_SCAN_WORDS.name, (*_SCAN_WORDS.options, _CANT_JUDGE))
# The page's model list, beside its sheet: a candidate with no card was still on the page.
_ROUTING_MODELS = "models.json"
# docs/results/s26-transcriber-test-pass2.txt, Qwen's "full-page scans (decision W7)" line.
_QWEN_S26_SCANS = "invented added words on 0 of 25; repeated the text layer on 0"


def cmd_routing_pages(settings: Settings, docs: CachedDocuments, *, models: Sequence[str]) -> str:
    """Andy's full-page-scan page for the named candidates, in its own folder (routing).

    The re-test's scan page (:func:`cmd_pages`) with its own folder, storage key and CSV name,
    so marks made here never mix with the re-test's. The candidates are sorted first, and a
    rebuild that would renumber cards already written is refused.

    Args:
        settings: Where S2.6's keys and the transcription cache are.
        docs: The docket cache, offline, for the scans' text layers.
        models: The candidates to show.

    Returns:
        One line per candidate with its number of cards, and where the page is.

    Raises:
        ConfigurationError: A candidate has a scan with no cached reading, or the sheet would
            change under marks already made.
    """
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    scans = [r for r in keys if r["set"] == "mixed"]
    ordered = tuple(sorted(set(models)))
    missing = _missing(settings, scans, ordered)
    if missing:
        raise ConfigurationError(
            "not in the transcription cache: " + "; ".join(missing) + " -- run the re-test first"
        )
    layers, sheet, cards = _scan_cards(settings, docs, scans, ordered, _ROUTING_SCAN_WORDS)
    out = settings.data_dir / ROUTING_FOLDER
    _refuse_moved_marks(out, {"mixed.json": sheet})
    out.mkdir(parents=True, exist_ok=True)
    pages = os.path.relpath(FOLDER / "pages", ROUTING_FOLDER)
    (out / "mixed.json").write_text(json.dumps(sheet))
    (out / _ROUTING_MODELS).write_text(json.dumps(list(ordered)))
    page = out / "scans.html"
    page.write_text(
        marking_page.render(
            title="Words added to full-page scans, for routing (S2.7, exploratory)",
            intro_html=_GROUPED_LAYOUT + _ROUTING_INTRO + _MIXED_INTRO,
            cards=cards,
            storage_key="s27-routing-scan-words",
            csv_name="s27-routing-scan-words.csv",
            groups={str(k): _scan_group(k, layer, pages) for k, layer in layers.items()},
        )
    )
    per_model = Counter(str(v["model"]) for v in sheet.values())
    lines = [f"{m}: {per_model[m]} card{'' if per_model[m] == 1 else 's'}" for m in ordered]
    return "\n".join([*lines, f"page at {page}"])


def cmd_routing_tally(settings: Settings, *, models: Sequence[str], mixed_csv: Path) -> str:
    """Each candidate's marks on the routing page, with its failed readings (exploratory).

    Args:
        settings: Where S2.6's keys, the routing sheet and the transcription cache are.
        models: The candidates the page was built for.
        mixed_csv: Andy's marks, downloaded from the routing page.

    Returns:
        The text: the key, Qwen's S2.6 figure, and one line per candidate.

    Raises:
        SystemExit: A card is unmarked, missing from the CSV or marked with an unknown choice;
            the sheet holds cards of a model not in ``models``; or a model in ``models`` was
            not on the page when it was built (or the page has no model list).
    """
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    scans = [r for r in keys if r["set"] == "mixed"]
    folder = settings.data_dir / ROUTING_FOLDER
    sheet = json.loads((folder / "mixed.json").read_text())
    others = sorted({str(v["model"]) for v in sheet.values()} - set(models))
    if others:
        raise SystemExit(
            "routing-tally: cards of models not named in --models: " + " ".join(others)
        )
    if not (folder / _ROUTING_MODELS).exists():
        raise SystemExit(
            f"routing-tally: {folder / _ROUTING_MODELS} is missing, so a model with no card "
            "cannot be told from one never shown -- rebuild the page (s27-routing-pages) with "
            "the same models"
        )
    built = set(json.loads((folder / _ROUTING_MODELS).read_text()))
    never_built = [m for m in models if m not in built]
    if never_built:
        raise SystemExit(
            "routing-tally: the routing page was not built for: " + " ".join(never_built)
        )
    marks = read_marks(mixed_csv)
    field = _ROUTING_SCAN_WORDS.name
    unknown = sorted(
        n
        for n in sheet
        if marks.get(int(n), {}).get(field, "") not in {"", *_ROUTING_SCAN_WORDS.options}
    )
    if unknown:
        raise SystemExit(f"routing-tally: cards marked with an unknown choice: {unknown}")
    invented = invented_by_model(sheet, marks, field=field, invented="some invented")
    repeated = invented_by_model(sheet, marks, field=field, invented="repeats the text layer")
    new = invented_by_model(sheet, marks, field=field, invented="all on the page and new")
    cant_judge = invented_by_model(sheet, marks, field=field, invented=_CANT_JUDGE)
    cards = Counter(str(v["model"]) for v in sheet.values())
    cache = TranscriptionCache(settings.transcription_dir)
    lines = [
        "# routing text-and-image pages: words added to S2.6's full-page scans -- counts only",
        "exploratory (Andy, 2026-09-27): evidence for decision 120's open idea of routing "
        "text-and-image pages to a cheaper model; outside decision 0100 item 3's rule, and it "
        "changes neither that rule nor the re-test's outcome "
        "(docs/results/s27-transcriber-retest.txt)",
        f"key: S2.6's {len(scans)} full-page scans (docs/results/s26-transcriber-test-pass2.txt); "
        "150 dpi; instruction t1; each reading's added words marked by Andy on the routing page",
        f"for comparison, {QWEN} in S2.6 (docs/results/s26-transcriber-test-pass2.txt): "
        + _QWEN_S26_SCANS,
        "",
    ]
    for m in models:
        failed = _reading_counts(cache, scans, m, dpi=RESOLUTION)["mixed"].failed
        lines.append(
            f"{m}: invented added words on {invented[m]} of {len(scans)} scans; repeated the "
            f"text layer on {repeated[m]}; all on the page and new on {new[m]}; could not be "
            f"judged on {cant_judge[m]}; no words added / no card on "
            f"{len(scans) - cards[m] - failed}; failed to read {failed}"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="transcriber_retest")
    commands = parser.add_subparsers(dest="command", required=True)
    verify_p = commands.add_parser("verify")
    automatic_p = commands.add_parser("automatic")
    score_p = commands.add_parser("score")
    for p in (verify_p, automatic_p, score_p):
        p.add_argument("--handwriting-recheck", type=Path, required=True)
        p.add_argument("--photos-recheck", type=Path, required=True)
    score_p.add_argument("--photos", type=Path, default=None)
    score_p.add_argument("--mixed", type=Path, default=None)
    # The candidates Andy marked (``automatic``'s "to mark" line); none when none are still in.
    score_p.add_argument("--marked", nargs="*", choices=S27_CANDIDATES, default=[])
    score_p.add_argument("--out", type=Path, default=None)
    run_p = commands.add_parser("run")
    run_p.add_argument("--retry-failed", action="store_true")
    # Task 9 Step 6 (Andy, option A): to finish a retry for the candidates a stopped one missed.
    run_p.add_argument("--models", nargs="+", choices=S27_CANDIDATES, default=S27_CANDIDATES)
    pages_p = commands.add_parser("pages")
    pages_p.add_argument("--models", nargs="+", required=True, choices=S27_CANDIDATES)
    routing_p = commands.add_parser("routing-pages")
    routing_p.add_argument("--models", nargs="+", required=True, choices=S27_CANDIDATES)
    tally_p = commands.add_parser("routing-tally")
    tally_p.add_argument("--models", nargs="+", required=True, choices=S27_CANDIDATES)
    tally_p.add_argument("--mixed", type=Path, required=True)
    tally_p.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    # As transcriber_test.main: offline, one attempt -- a cache miss is a bug, not a fault.
    docs = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline(), max_attempts=1))
    if args.command == "run":
        text = cmd_run(settings, docs, models=args.models, retry_failed=args.retry_failed)
    elif args.command == "pages":
        text = cmd_pages(settings, docs, models=args.models)
    elif args.command == "routing-pages":
        text = cmd_routing_pages(settings, docs, models=args.models)
    elif args.command == "routing-tally":
        text = cmd_routing_tally(settings, models=args.models, mixed_csv=args.mixed)
        if args.out is not None:
            args.out.write_text(text + "\n")
    else:
        recheck = Recheck(handwriting_csv=args.handwriting_recheck, photos_csv=args.photos_recheck)
        if args.command == "automatic":
            text, _still_in = cmd_automatic(settings, docs, recheck, models=S27_CANDIDATES)
        elif args.command == "score":
            text = cmd_score(
                settings,
                docs,
                recheck,
                args.photos,
                args.mixed,
                models=S27_CANDIDATES,
                marked=tuple(args.marked),
            )
            if args.out is not None:
                args.out.write_text(text + "\n")
        else:
            text = cmd_verify(settings, docs, recheck)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
