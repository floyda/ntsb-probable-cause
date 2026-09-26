"""The kinds of page in a development sample's cached dockets: counts only (S2.6 §1, §5.2).

Status
    Live tool (S2.6, spec §6.2 step 1). ``make page-kinds`` (added in Task 6; until then run
    the command below) writes ``docs/results/s26-page-kinds.txt`` from the ``dev-400``
    docket cache, and the page frame the inventory and the transcriber test sample from,
    ``data/s26/pages-dev-400.jsonl``. The frame names cases, so it lives under ``data/``
    and is never committed. Every page-kind number in the S2.6 As-built record cites the
    results file; the design session's figures (spec §1, §5.2) were ad hoc, and where the
    two differ this one stands.

Reads the cache only -- a transport that refuses every request makes a cache miss loud and
free -- with one exception: ``--include-photo-only`` fetches the photo-only documents S2
never downloaded (decision W2, Andy, 2026-09-24), politely (the 2-second floor) into the
same cache, and counts and frames their pages apart from S2's, so the S2 figures above them
are unchanged. Development samples only: the frame would otherwise list held-out pages, and
no held-out page is inspected (spec §17).

Run: ``uv run python -m scripts.page_kinds [--sample dev-400] [--include-photo-only]
[--out PATH] [--frame PATH]``.
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.docket.pages import (
    TILED_MIN_IMAGES,
    PageFacts,
    PageKind,
    document_facts,
)
from ntsb_probable_cause.errors import DocketError
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings

KINDS: tuple[PageKind, ...] = ("text only", "image only", "text and image", "blank")
STRATA = ("fatal", "non-fatal")
ENCODING_ORDER = ("fax (CCITT)", "JPEG 2000", "JBIG2", "JPEG", "Flate", "other", "none")


def _offline() -> httpx.BaseTransport:
    """A transport refusing every request, so a cache miss is loud and costs no fetch."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: this measurement reads the cache only")

    return httpx.MockTransport(refuse)


@dataclass
class Tally:
    """Page and document counts, accumulated over the sample."""

    cases: Counter[str] = field(default_factory=Counter)
    pdfs: int = 0
    mixed_documents: int = 0
    pages: Counter[tuple[str, PageKind]] = field(default_factory=Counter)
    rotated: Counter[str] = field(default_factory=Counter)
    tiled: Counter[str] = field(default_factory=Counter)
    encodings: Counter[str] = field(default_factory=Counter)
    failed_pages: int = 0
    photo_only_entries: Counter[str] = field(default_factory=Counter)
    photo_only_pages: Counter[str] = field(default_factory=Counter)
    photo_pdfs: int = 0
    photo_pages: Counter[tuple[str, PageKind]] = field(default_factory=Counter)
    not_cached: int = 0
    fetch_failed: int = 0
    not_pdf: int = 0

    def add_photo_document(self, stratum: str, facts: Sequence[PageFacts]) -> None:
        """Count a fetched photo-only document's pages apart from S2's documents (W2)."""
        self.photo_pdfs += 1
        for page in facts:
            self.photo_pages[(stratum, page.kind)] += 1

    def add_document(self, stratum: str, facts: Sequence[PageFacts]) -> None:
        """Count one PDF's pages; image-only pages also by rotation, pieces and encoding."""
        self.pdfs += 1
        if len({f.kind for f in facts if f.kind != "blank"}) > 1:
            self.mixed_documents += 1
        for page in facts:
            self.pages[(stratum, page.kind)] += 1
            self.failed_pages += page.failed
            if page.kind != "image only":
                continue
            self.rotated[stratum] += page.rotation != 0
            self.tiled[stratum] += page.images >= TILED_MIN_IMAGES
            self.encodings.update(page.encodings)


def frame_rows(  # noqa: PLR0913 -- one keyword per fact a frame row records.
    *,
    case_id: str,
    mkey: int,
    fatal: bool,
    document: int,
    facts: Sequence[PageFacts],
    photo_only: bool = False,
) -> list[dict[str, object]]:
    """One private frame row per page: where it is, and its counts. Never its text."""
    return [
        {
            "case_id": case_id,
            "mkey": mkey,
            "fatal": fatal,
            "document": document,
            "page": n,
            "pages": len(facts),
            "kind": page.kind,
            "chars": page.chars,
            "images": page.images,
            "rotation": page.rotation,
            "encodings": list(page.encodings),
            "photo_only": photo_only,
        }
        for n, page in enumerate(facts, start=1)
    ]


def write_frame(path: Path, rows: Sequence[Mapping[str, object]]) -> None:
    """Write the frame as JSON lines, replacing any earlier one."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def sweep(
    records: Sequence[Mapping[str, object]],
    client: DocketClient,
    *,
    fetch_photo_only: DocketClient | None = None,
) -> tuple[Tally, list[dict[str, object]]]:
    """Every cached PDF of every case: counted, and listed page by page in the frame.

    With ``fetch_photo_only`` (a client allowed to fetch, politely), photo-only PDF entries
    are fetched too, and counted and framed apart (decision W2).
    """
    tally = Tally()
    rows: list[dict[str, object]] = []
    for raw in records:
        mkey = raw.get("mKey")
        fatal = raw.get("highestInjuryLevel") == "Fatal"
        stratum = STRATA[0] if fatal else STRATA[1]
        tally.cases[stratum] += 1
        if not isinstance(mkey, int):
            tally.not_cached += 1
            continue
        try:
            listing = parse_listing(client.listing_html(mkey), mkey=mkey)
        except DocketError:
            tally.not_cached += 1
            continue
        for entry in listing.entries:
            photo_only = entry.is_photo_only()
            if photo_only:
                tally.photo_only_entries[stratum] += 1
                tally.photo_only_pages[stratum] += entry.pages
                if fetch_photo_only is None:
                    continue
            if not entry.is_pdf():
                continue
            source = fetch_photo_only if photo_only and fetch_photo_only else client
            try:
                data = source.document(mkey, entry.index, entry.href)
            except DocketError:
                tally.fetch_failed += 1
                continue
            try:
                facts = document_facts(data)
            except DocketError:
                tally.not_pdf += 1
                continue
            if photo_only:
                tally.add_photo_document(stratum, facts)
            else:
                tally.add_document(stratum, facts)
            rows.extend(
                frame_rows(
                    case_id=str(raw["ntsbNumber"]),
                    mkey=mkey,
                    fatal=fatal,
                    document=entry.index,
                    facts=facts,
                    photo_only=photo_only,
                )
            )
    return tally, rows


def _row(label: str, counts: Mapping[str, int]) -> str:
    total = sum(counts.get(s, 0) for s in STRATA)
    fatal, non_fatal = counts.get("fatal", 0), counts.get("non-fatal", 0)
    return f"  {label:<16} {total:7d} {fatal:9d} {non_fatal:11d}"


def report(tally: Tally, sample: str) -> str:
    """The measurement, as docs/results/s26-page-kinds.txt holds it."""
    by_kind = {kind: {s: tally.pages[(s, kind)] for s in STRATA} for kind in KINDS}
    totals = {s: sum(by_kind[k][s] for k in KINDS) for s in STRATA}
    image_bearing = sum(sum(by_kind[k].values()) for k in ("image only", "text and image"))
    cases = sum(tally.cases.values())
    lines = [
        "# page kinds in the development dockets (S2.6 spec §1, §5.2) -- counts only",
        f"sample {sample}: {cases} cases (fatal {tally.cases['fatal']}, "
        f"non-fatal {tally.cases['non-fatal']}); PDFs read from the cache: {tally.pdfs}",
        f"no cached listing: {tally.not_cached}; document fetch failed: {tally.fetch_failed}; "
        f"not a PDF: {tally.not_pdf}; pages that failed to parse (counted blank): "
        f"{tally.failed_pages}",
        "a page with fewer than 50 characters of extractable text has no usable text layer",
        "(classify.SCAN_PAGE_MAX_CHARS); an image is any image the page's resources draw",
        "",
        "## pages by kind",
        f"  {'kind':<16} {'all':>7} {'fatal':>9} {'non-fatal':>11}",
        *(_row(kind, by_kind[kind]) for kind in KINDS),
        _row("total", totals),
        f"image-bearing pages (image only + text and image): {image_bearing}"
        f" (mean per case: {image_bearing / cases if cases else 0:.1f})",
        "",
        "## documents",
        f"  PDFs mixing more than one kind of non-blank page: {tally.mixed_documents}"
        f" of {tally.pdfs}",
        "",
        "## image-only pages: why pulling the image out would fail (spec §5.2)",
        _row("rotated", tally.rotated) + "   (90, 180 or 270 degrees)",
        _row(f"{TILED_MIN_IMAGES}+ images", tally.tiled),
        "  by encoding (a page counts once for each encoding it holds): "
        + ", ".join(f"{name} {tally.encodings[name]}" for name in ENCODING_ORDER),
        "",
        "## photo-only listing entries (S2's read_docket skips them; fetched for S2.6, W2)",
        _row("entries", tally.photo_only_entries),
        _row("declared pages", tally.photo_only_pages),
        f"  fetched and read: {tally.photo_pdfs} PDFs; their pages by kind:",
        *(_row(kind, {s: tally.photo_pages[(s, kind)] for s in STRATA}) for kind in KINDS),
        "",
        "## limits",
        "- an inline image (drawn in the content stream rather than as a resource) is not",
        "  counted, so a page built only from inline images reads as text only or blank;",
        "- text is pypdf's extract_text, as the docket tool reads it (decision 0047);",
        "- the counts above the photo-only section are S2's documents only, so they compare",
        "  with the design session's; photo-only pages are counted in their own section.",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Count page kinds over a development sample's cached dockets."""
    parser = argparse.ArgumentParser(prog="page_kinds")
    parser.add_argument("--sample", default="dev-400")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--frame", type=Path)
    parser.add_argument("--include-photo-only", action="store_true")
    args = parser.parse_args(argv)
    if not args.sample.startswith("dev"):
        raise SystemExit(f"{args.sample}: page kinds are counted on development samples only")
    settings = Settings()
    client = DocketClient(settings.docket_dir, transport=_offline())
    polite = (
        DocketClient(settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request)
        if args.include_photo_only
        else None
    )
    records = load_cases(settings.data_dir / "processed", sample_ids(args.sample))
    tally, rows = sweep(records, client, fetch_photo_only=polite)
    text = report(tally, args.sample)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    frame = args.frame or settings.data_dir / "s26" / f"pages-{args.sample}.jsonl"
    write_frame(frame, rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
