"""Score the title hand-check: what the classifier's labels are actually used for (0048 item 4).

Status
    **Deprecated** (S2). Produced ``docs/results/s2-handcheck.txt`` (commit ``136d9f0``,
    2026-09-20). **All three uses it grades were removed after it ran, and this script is the
    evidence for removing them**: the photograph exclusion (decision 0052 -- it dropped 270
    documents to save about 6 tokens each and was wrong in both directions), the deny-list
    (0056 -- the hits could not be caught by any list of categories) and the provenance clause
    (0051 -- right on 32 of the 55 titles it made a claim about, 58%). None of the three exists
    in the code. Read this file as a record of a measurement, never as a description of the
    pipeline.

Grades three uses against Andy's marks, not the twelve category names. All three were
removed after this ran -- see Status above; the present tense below is the tense of the
measurement, not of the code:

1. the arm B photograph exclusion -- ``category == "photos"`` drops the whole document;
2. the deny-list -- a document that could hold the investigators' own conclusions;
3. the provenance header's *whose account is this* phrase, against the same five-word
   vocabulary the sheet asks for.

Titles only. No case is named and no document text is read.

Run: ``uv run python -m scripts.score_handcheck`` (``--out PATH`` to save the text).
"""

import argparse
import csv
from collections import Counter
from pathlib import Path

SHEET = Path("tests/fixtures/docket/title_handcheck.filled.csv")
PHOTO_CATEGORY = "photos"

# What each category's provenance phrase claims, in the sheet's five-word vocabulary. A
# category whose phrase hedges between two of the five accepts either: the hedge is the claim.
# ``other`` claims nothing ("not stated in the listing"), so it can never be wrong -- it is
# counted separately, as information lost rather than information falsified.
CLAIMED: dict[str, frozenset[str]] = {
    "party_submission": frozenset({"party"}),
    "pilot_form_6120": frozenset({"party"}),
    "photos": frozenset({"recorded"}),
    "weather": frozenset({"investigation", "independent"}),
    "maintenance_records": frozenset({"party", "independent"}),
    "medical_tox": frozenset({"independent"}),
    "specialist_factual": frozenset({"investigation"}),
    "exam_site": frozenset({"investigation"}),
    "conversation_statement": frozenset({"party", "independent"}),
    "atc_radar_data": frozenset({"recorded"}),
    "manuals_reference": frozenset({"independent"}),
}
NO_CLAIM = "other"


def load(sheet: Path) -> list[dict[str, str]]:
    """The marked sheet, refusing to score a partly marked one."""
    with sheet.open(newline="") as handle:
        rows = list(csv.DictReader(handle))
    blank = [i for i, r in enumerate(rows, start=1) if not r["author"].strip()]
    if blank:
        raise SystemExit(f"rows not marked: {blank}")
    return rows


def report(rows: list[dict[str, str]]) -> str:
    """The measurement, as the ledger and decision quote it. Counts only; no title is printed."""
    photo_hits = [r for r in rows if r["category"] == PHOTO_CATEGORY]
    marked_photo = [r for r in rows if r["is_photo"].strip().lower() == "y"]
    wrongly_dropped = [r for r in photo_hits if r["is_photo"].strip().lower() != "y"]
    wrongly_kept = [r for r in marked_photo if r["category"] != PHOTO_CATEGORY]

    conclusions = [r for r in rows if r["could_hold_conclusions"].strip().lower() == "y"]

    claiming = [r for r in rows if r["category"] in CLAIMED]
    agreed = [r for r in claiming if r["author"].strip().lower() in CLAIMED[r["category"]]]
    wrong = [r for r in claiming if r["author"].strip().lower() not in CLAIMED[r["category"]]]
    no_claim = [r for r in rows if r["category"] == NO_CLAIM]
    no_claim_decidable = [r for r in no_claim if r["author"].strip().lower() != "unclear"]
    unclear = [r for r in rows if r["author"].strip().lower() == "unclear"]

    def line(label: str, part: int, whole: int | None = None, tail: str = "") -> str:
        """One report line: a label, a count, and either a share of ``whole`` or a note."""
        share = f"({100 * part / whole:.0f}%)" if whole else ""
        return f"  {label:38s}{part:4d} {share}{tail}".rstrip()

    lines = [
        "title hand-check, scored (decision 0048 item 4)",
        f"sheet {SHEET}, {len(rows)} rows, every row marked",
        "",
        "1. the photograph exclusion -- arm B drops the whole document",
        line("marked a photograph by hand", len(marked_photo), len(rows)),
        line("classified photos", len(photo_hits), len(rows)),
        line("dropped but not a photograph", len(wrongly_dropped), tail="   evidence lost"),
        line("a photograph but kept", len(wrongly_kept), tail="   attached as text"),
        "",
        "2. the deny-list -- could hold the investigators' own conclusions",
        line("marked yes", len(conclusions), len(rows)),
        "",
        "3. the provenance header -- whose account is this",
        line("rows whose header makes a claim", len(claiming), len(rows)),
        line("  agrees with the hand mark", len(agreed), len(claiming)),
        line("  contradicts it", len(wrong), len(claiming)),
        line("rows whose header claims nothing", len(no_claim), len(rows)),
        line("  a person could still tell", len(no_claim_decidable), tail="   not falsified"),
        line("marked unclear by hand", len(unclear)),
        "",
        "where the header contradicts the mark, by category (claimed -> marked):",
    ]
    contradictions = Counter(
        (r["category"], "/".join(sorted(CLAIMED[r["category"]])), r["author"].strip().lower())
        for r in wrong
    )
    lines += [
        f"  {cat:24s} {claim:24s} -> {got:12s} {n}"
        for (cat, claim, got), n in sorted(contradictions.items())
    ] or ["  none"]
    lines += ["", "what the rows claiming nothing were marked as:"]
    lost = Counter(r["author"].strip().lower() for r in no_claim)
    lines += [f"  {word:24s} {n}" for word, n in sorted(lost.items())]
    notes = [(i, r["notes"]) for i, r in enumerate(rows, start=1) if r["notes"].strip()]
    lines += ["", f"rows carrying a note: {len(notes)}"]
    lines += [f"  row {i:2d}  {note}" for i, note in notes]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Print the measurement, optionally saving it."""
    parser = argparse.ArgumentParser(prog="score_handcheck")
    parser.add_argument("--sheet", type=Path, default=SHEET)
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    text = report(load(args.sheet))
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
