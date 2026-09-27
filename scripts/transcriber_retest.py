"""The transcriber re-test: new candidates on S2.6's answer keys, judged against Qwen (S2.7 §7.4).

Status
    One-shot (S2.7 track 2, Tasks 8-10). Built so far (Task 8):
      verify  -- re-score Qwen's cached readings on S2.6's keys and require its published
                 second-pass counts exactly (free; walkthrough W7)
    and decision 0100 item 3's choice rule (``choose_against_qwen``), fixed before any
    candidate is run. The candidates' run (paid) and the score come in Tasks 9 and 10.
    Reads S2.6's keys and marks under <data_dir>/s26/transcriber-test/ and never writes there.
    Counts only.
"""

import argparse
import json
from collections.abc import Sequence
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.render import RESOLUTION
from ntsb_probable_cause.docket.transcribe import TranscriptionCache
from ntsb_probable_cause.settings import Settings
from scripts.marking_page import read_marks
from scripts.transcriber_test import (
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
    _offline,
    _read,
    _result,
)

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


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="transcriber_retest")
    commands = parser.add_subparsers(dest="command", required=True)
    verify_p = commands.add_parser("verify")
    verify_p.add_argument("--handwriting-recheck", type=Path, required=True)
    verify_p.add_argument("--photos-recheck", type=Path, required=True)
    args = parser.parse_args(argv)
    settings = Settings()
    # As transcriber_test.main: offline, one attempt -- a cache miss is a bug, not a fault.
    docs = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline(), max_attempts=1))
    recheck = Recheck(handwriting_csv=args.handwriting_recheck, photos_csv=args.photos_recheck)
    print(cmd_verify(settings, docs, recheck))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
