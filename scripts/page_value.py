"""What each page rule keeps of S2.6's transcriptions on dev-400 (S2.7 spec §7.3, T3).

Status
    Repeatable, free: reads the dev-400 docket cache and the transcription cache; makes no
    model call. Counts only (no case number, no page text). Decision 0100 item 4 fixes the
    choice before it runs: of the three rules, the one with the fewest pages whose transcribed
    characters are at least 90% of what S2.6's rule ("all") transcribed. Its effect on answers
    is measured at S2.7's meeting point, not here.

Why
    In the dev-400 transcription, text-and-image pages were about three fifths of the cost and
    most came back nearly empty, because their text layer already held the words (ad-hoc, S2.7
    spec §7.1). This script re-derives that with a committed script and picks a rule by a rule.

Usage
    uv run python -m scripts.page_value [--sample dev-400] [--out PATH]
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.pages import PageKind, document_facts
from ntsb_probable_cause.docket.render import image_area_shares
from ntsb_probable_cause.docket.transcribe import (
    PAGE_RULES,
    PageRule,
    ReadingLookup,
    Transcription,
    TranscriptionCache,
    page_choice,
)
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings
from scripts.transcriber_test import _offline

KEEP_SHARE = 0.9  # decision 0100 item 4
NEAR_EMPTY_CHARS = 20  # "returned under 20 characters" (S2.7 spec §7.1)
_LAYER_BANDS: tuple[tuple[float, float | None], ...] = ((50, 200), (200, 1000), (1000, None))
_SHARE_BANDS: tuple[tuple[float, float | None], ...] = ((0.0, 0.1), (0.1, 0.7), (0.7, None))


@dataclass(frozen=True)
class PageRow:
    """One image-bearing page: what the PDF holds, and what S2.6's reading of it returned."""

    fatal: bool
    kind: PageKind
    layer_chars: int
    image_share: float
    status: str | None  # "transcribed", "failed", or None when there is no reading
    chars: int
    cost_usd: float


@dataclass(frozen=True)
class RuleTally:
    """What one rule sends: pages, transcribed characters, cost, failed readings."""

    pages: int
    chars: int
    cost_usd: float
    failed: int


def rows_for_document(
    data: bytes, readings: Mapping[int, Transcription], *, fatal: bool
) -> list[PageRow]:
    """One row per image-bearing page of one PDF, joined to its S2.6 reading if any."""
    shares = image_area_shares(data)
    rows: list[PageRow] = []
    for number, page in enumerate(document_facts(data), start=1):
        if page.kind not in ("image only", "text and image"):
            continue
        reading = readings.get(number)
        text = reading.text if reading is not None and reading.status == "transcribed" else ""
        rows.append(
            PageRow(
                fatal=fatal,
                kind=page.kind,
                layer_chars=page.chars,
                image_share=shares[number - 1] if number <= len(shares) else 0.0,
                status=None if reading is None else reading.status,
                chars=len(text.strip()),
                cost_usd=0.0 if reading is None else reading.cost_usd,
            )
        )
    return rows


def _sent(row: PageRow, page_rule: PageRule) -> bool:
    choice = page_choice(row.kind, row.layer_chars, row.image_share, page_rule=page_rule)
    return choice is not None


def tally(rows: Sequence[PageRow], page_rule: PageRule) -> RuleTally:
    """Pages, characters, cost and failures of the pages ``page_rule`` sends."""
    sent = [r for r in rows if _sent(r, page_rule)]
    return RuleTally(
        pages=len(sent),
        chars=sum(r.chars for r in sent),
        cost_usd=sum(r.cost_usd for r in sent),
        failed=sum(1 for r in sent if r.status == "failed"),
    )


def choose_rule(rows: Sequence[PageRow]) -> tuple[PageRule, list[str]]:
    """Decision 0100 item 4: the fewest pages keeping at least 90% of "all"'s characters."""
    everything = tally(rows, "all")
    notes: list[str] = []
    kept: list[tuple[int, int, PageRule]] = []
    for order, rule in enumerate(PAGE_RULES):
        counted = tally(rows, rule)
        share = counted.chars / everything.chars if everything.chars else 1.0
        admissible = share >= KEEP_SHARE
        notes.append(
            f"{rule}: {counted.pages} pages, {share:.1%} of the characters "
            f"({'admissible' if admissible else 'under 90%'})"
        )
        if admissible:
            kept.append((counted.pages, order, rule))
    return min(kept)[2], notes


def _band(value: float, bands: Sequence[tuple[float, float | None]]) -> str:
    for low, high in bands:
        if value >= low and (high is None or value < high):
            return f"{low:g}+" if high is None else f"{low:g}-{high:g}"
    return "other"


def _band_lines(rows: Sequence[PageRow], title: str, key: str) -> list[str]:
    mixed = [r for r in rows if r.kind == "text and image"]
    bands = _LAYER_BANDS if key == "layer" else _SHARE_BANDS
    lines = [f"## text-and-image pages by {title}", "  band        pages  near-empty  chars  cost"]
    for low, _high in bands:
        label = _band(low, bands)
        members = [
            r
            for r in mixed
            if _band(r.layer_chars if key == "layer" else r.image_share, bands) == label
        ]
        empty = sum(1 for r in members if r.chars < NEAR_EMPTY_CHARS)
        lines.append(
            f"  {label:<10} {len(members):6d} {empty:11d} {sum(r.chars for r in members):6d} "
            f"${sum(r.cost_usd for r in members):.2f}"
        )
    return lines


def report(rows: Sequence[PageRow], *, sample: str, cases: int, pdfs: int) -> str:
    """The counts, each rule's tally by fatal and non-fatal, and the rule chosen."""
    chosen, notes = choose_rule(rows)
    lines = [
        "# page value: what each page rule keeps of S2.6's transcriptions (S2.7 spec §7.3, "
        "decision 0100 item 4) -- counts only",
        f"sample {sample}: {cases} cases, {pdfs} PDFs; {len(rows)} image-bearing pages; "
        "readings: S2.6's transcriber, instruction t1, 150 dpi",
        f"pages with no reading: {sum(1 for r in rows if r.status is None)}",
        "",
        "## by rule",
        "  rule                    pages   chars      cost  failed  fatal pages  non-fatal pages",
    ]
    for rule in PAGE_RULES:
        t = tally(rows, rule)
        fatal = tally([r for r in rows if r.fatal], rule).pages
        lines.append(
            f"  {rule:<22} {t.pages:6d} {t.chars:8d}  ${t.cost_usd:7.2f} {t.failed:7d} "
            f"{fatal:12d} {t.pages - fatal:16d}"
        )
    lines += ["", *_band_lines(rows, "text-layer characters", "layer")]
    lines += ["", *_band_lines(rows, "image cover", "share")]
    lines += ["", "## the choice (decision 0100 item 4, fixed before this ran)", *notes]
    lines.append(f"chosen: {chosen}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Count, choose, print, and with ``--out`` write the results file."""
    parser = argparse.ArgumentParser(prog="page_value")
    parser.add_argument("--sample", default="dev-400")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    if args.sample != "dev-400":
        raise SystemExit("page_value reads dev-400 only (S2.7 spec §7.3)")
    settings = Settings()
    raws = load_cases(settings.data_dir / "processed", sample_ids(args.sample))
    lookup = ReadingLookup(TranscriptionCache(settings.transcription_dir), page_rule="all")
    docs = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline(), max_attempts=1))
    rows: list[PageRow] = []
    pdfs = 0
    # Pre-flight risk 2: a case whose docket cannot be listed is skipped and counted, the same
    # boundary ``_page_jobs`` (apps/eval/__main__.py) draws around ``docs.listing``.
    skipped = 0
    for raw in raws:
        mkey = raw.get("mKey")
        if not isinstance(mkey, int):
            continue
        fatal = raw.get("highestInjuryLevel") == "Fatal"
        try:
            entries = docs.listing(mkey).entries
        except DocketError:
            skipped += 1
            continue
        for entry in entries:
            if not entry.is_pdf():
                continue
            try:
                data = docs.document(mkey, entry.index)
                rows += rows_for_document(data, lookup.for_document(data), fatal=fatal)
            except DocketError:
                continue
            pdfs += 1
    text = report(rows, sample=args.sample, cases=len(raws), pdfs=pdfs)
    print(text)
    print(f"cases skipped (docket could not be listed): {skipped}")
    if args.out is not None:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
