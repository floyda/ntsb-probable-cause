"""What the listing's ``doc_type`` column does to the category, over the whole dev-400 cache.

Written to measure a finding from the title hand-check (task 16): "WITNESS STATEMENTS" is
classified ``photos`` and dropped by arm B, because ``document_category`` matches its patterns
against the title and the ``doc_type`` column joined into one string, and the NTSB's
``Text/Image`` doc_type contains the word *image*.

Counts and titles only; no document text is printed. Titles are read from the cached listing
pages, the same source the committed hand-check sheet was drawn from.

The fix (task 16b) removed ``doc_type`` from ``document_category`` itself, so the old, joined
behaviour is reproduced here instead, in ``_joined_category``, a frozen copy of the pre-fix
match -- this script's job is to keep comparing the two, not to exercise the fixed function
twice.

Run: ``uv run python -m scripts.doctype_scan`` (``--out PATH`` to save the text).
"""

import argparse
import re
from collections import Counter
from pathlib import Path

from ntsb_probable_cause.docket.classify import (
    CATEGORIES,
    document_category,
    estimated_tokens,
    readable_pages,
)
from ntsb_probable_cause.docket.extract import extract_pdf
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.settings import Settings

LISTING_FILE = "listing.html"
EXAMPLES = 12

# A frozen copy of the pre-fix roster check and category patterns (see the module docstring):
# this script measures the fix, so it keeps its own snapshot of the behaviour being replaced
# rather than reach back into the library for logic the library no longer has.
_ROSTER = re.compile(r"statement of party representatives")
_COMPILED = tuple((name, re.compile(pattern)) for name, pattern in CATEGORIES)


def _joined_category(title: str, doc_type: str) -> str:
    """The pre-fix match: the title and the listing's file-type column joined into one string."""
    text = f"{title} {doc_type}".lower()
    if _ROSTER.search(text):
        return "other"
    for name, pattern in _COMPILED:
        if pattern.search(text):
            return name
    return "other"


def scan(root: Path) -> str:
    """The measurement, as docs/results/s2-doctype.txt holds it."""
    dockets = [d for d in sorted(root.iterdir()) if d.is_dir() and (d / LISTING_FILE).is_file()]
    if not dockets:
        raise SystemExit(f"no cached dockets under {root}; nothing to measure")

    documents = 0
    doc_types: Counter[str] = Counter()
    changed: Counter[tuple[str, str]] = Counter()
    extensions: Counter[tuple[str, str]] = Counter()
    affected: set[str] = set()
    examples: list[tuple[str, str]] = []
    readable = not_pdf = not_cached = failed = dropped = 0
    tokens = 0
    by_category: Counter[str] = Counter()
    readable_by_category: Counter[str] = Counter()

    for docket in dockets:
        page = (docket / LISTING_FILE).read_bytes().decode("utf-8", "replace")
        for entry in parse_listing(page, mkey=int(docket.name)).entries:
            documents += 1
            doc_types[entry.doc_type] += 1
            joined = _joined_category(entry.title, entry.doc_type)
            alone = document_category(entry.title)
            if joined == alone:
                continue
            extensions[(entry.doc_type, entry.extension)] += 1
            if joined != "photos":
                changed[(entry.doc_type, alone)] += 1
                continue
            dropped += 1
            affected.add(docket.name)
            by_category[alone] += 1
            if len(examples) < EXAMPLES:
                examples.append((alone, entry.title))
            if not entry.is_pdf():
                not_pdf += 1
                continue
            cached = docket / f"{entry.index}.bin"
            if not cached.is_file():
                not_cached += 1
                continue
            try:
                extracted = extract_pdf(cached.read_bytes())
            except Exception:  # a broken PDF is a count here, not a failure
                failed += 1
                continue
            if readable_pages(extracted.chars_by_page):
                readable += 1
                readable_by_category[alone] += 1
                tokens += estimated_tokens(sum(extracted.chars_by_page))

    others = [
        f"  {t:28s} -> {alone:24s} {n}"
        for (t, alone), n in sorted(changed.items(), key=lambda kv: -kv[1])
    ] or ["  none"]
    lines = [
        "the doc_type column and the photograph exclusion",
        f"cache {root}, {len(dockets)} dockets, {documents} documents",
        "",
        "listing doc_type values:",
        *(f"  {t:28s} {n}" for t, n in doc_types.most_common()),
        "",
        "documents classified photos only because doc_type was matched, not the title:",
        f"  documents                             {dropped:5d}"
        f" ({100 * dropped / documents:.1f}% of documents)",
        f"  dockets holding at least one          {len(affected):5d}"
        f" ({100 * len(affected) / len(dockets):.0f}% of dockets)",
        "",
        "  what the title alone says they are, and how many hold readable text:",
        *(
            f"    {c:24s} {readable_by_category[c]:3d} readable / {n:3d}"
            for c, n in by_category.most_common()
        ),
        "",
        f"  with at least one readable page       {readable:5d}"
        f" ({100 * readable / dropped:.0f}% of the {dropped})",
        f"  estimated tokens in those             {tokens:7,d}",
        f"  not a downloadable PDF                {not_pdf:5d}",
        f"  PDF absent from the cache             {not_cached:5d}",
        f"  extraction raised                     {failed:5d}",
        "",
        "  examples (title, and the category the title alone gives):",
        *(f"    [{c:22s}] {t}" for c, t in examples),
        "",
        "other category changes from dropping doc_type (not into photos):",
        *others,
        "",
        "every category change from dropping doc_type, by file extension --",
        "a non-PDF is never attached anyway (filter.arm_b_documents takes status 'read' only),",
        "so only the .pdf rows are documents the exclusion actually loses:",
        *(
            f"  {t:28s} .{e or '(none)':10s} {n}"
            for (t, e), n in sorted(extensions.items(), key=lambda kv: -kv[1])
        ),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Print the measurement, optionally saving it."""
    parser = argparse.ArgumentParser(prog="doctype_scan")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    text = scan(Settings().data_dir / "docket")
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
