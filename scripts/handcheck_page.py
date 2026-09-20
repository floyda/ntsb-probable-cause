"""A local, browser-based marking tool for the title hand-check (decision 0048 item 4).

Marking 60 rows in a spreadsheet by hand was reported unworkable twice. This writes one
self-contained HTML page the owner opens directly (``file://``, no server, no network) and
marks by clicking; a second, shorter page lists one case's whole docket for the owner's other
S2 task -- reading two or three documents and approving their text for commit (0037).

Usage:
    uv run python -m scripts.handcheck_page page [--out data/handcheck/index.html]
        Write the marking page and, alongside it, the case-reading page. Reads the docket
        cache and the processed corpus only; never fetches (``DocketClient`` at zero request
        gap, cache-only use).
    uv run python -m scripts.handcheck_page merge <marks.csv> [--sheet PATH]
        Fold an exported marks CSV (columns ``row,is_photo,could_hold_conclusions,author,
        notes``) into the committed hand-check sheet by row number. Titles, doc types and
        categories are left exactly as committed -- only the four mark columns change.

Why the page is never committed: decision 0049 keeps the committed sheet
(``tests/fixtures/docket/title_handcheck.csv``) redacted -- a document title can carry a real
surname, and that sheet is this project's own authored surface, not an NTSB page. This tool's
page is different in kind: it is a private working copy for the owner, the human gate decision
0037 already relies on, and showing him a ``[proper noun]`` marker in place of a real title
would make several rows unjudgeable. It is written under ``data/``, which is git-ignored, and
must never be committed -- it carries unredacted titles and links that name real cases.
"""

import argparse
import csv
import html
import sys
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.classify import document_category
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import Listing, parse_listing
from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from scripts.make_docket_fixture import (
    DOCUMENT_ALLOWED_CATEGORIES,
    FIXTURES,
    HANDCHECK_SAMPLE_SIZE,
    SEED,
    _cases,
    _stratified_sample,
)

DEFAULT_OUT = Path("data/handcheck/index.html")
CASE_DOCUMENTS_CASE_ID = "ERA19FA248"
SHEET_PATH = FIXTURES / "title_handcheck.csv"
MARK_COLUMNS = ("is_photo", "could_hold_conclusions", "author", "notes")
# The provenance header's own vocabulary (decision 0048 item 4, 0038): the question is *whose
# account is this*, not who holds formal party status. "recorded" was added 2026-09-19 for the
# case that exposed the gap -- an ATC transcript is nobody's account, a verbatim capture of what
# was said at the time.
AUTHOR_OPTIONS = ("investigation", "party", "independent", "recorded", "unclear")
# One-line gloss per option, in the owner's own terms, shown as each <option>'s tooltip.
AUTHOR_GLOSSES: Mapping[str, str] = {
    "investigation": "written by the NTSB or its investigators, e.g. an exam or factual report",
    "party": "an account from a party to the investigation, e.g. the pilot, operator or a "
    "manufacturer",
    "independent": "an account from someone with no stake in the case, e.g. a medical examiner "
    "or weather service",
    "recorded": "nobody's account -- a verbatim capture of what happened, e.g. an ATC transcript "
    "or a radar track",
    "unclear": "the listing does not say",
}
MARKS_CSV_HEADER = ("row", *MARK_COLUMNS)


@dataclass(frozen=True)
class HandcheckRow:
    """One document title as shown on a page: the real title, and where to see it."""

    row: int
    title: str
    doc_type: str
    category: str
    docket_url: str
    document_url: str | None


def rows_from_listing(listing: Listing) -> list[HandcheckRow]:
    """Every entry of one docket listing as page rows, titles unredacted, cache-only.

    ``row`` is the listing's own document index, not a position count -- so a number shown on
    the case-reading page can be typed straight into
    ``make_docket_fixture document <case_id> <index>`` without cross-referencing anything.
    """
    return [
        HandcheckRow(
            row=entry.index,
            title=entry.title,
            doc_type=entry.doc_type,
            category=document_category(entry.title),
            docket_url=sources.docket_url(listing.mkey),
            document_url=sources.docket_document_url(entry.href) if entry.href else None,
        )
        for entry in listing.entries
    ]


def _title_pools(
    settings: Settings,
) -> tuple[dict[str, list[tuple[str, str, str]]], dict[tuple[str, str, str], tuple[int, str]]]:
    """Every unique (title, doc_type, category) in the dev-400 cache, with one locator each.

    Mirrors ``make_docket_fixture._cmd_handcheck``'s own gathering loop exactly: the same
    cache, the same dev-400 filter, the same ``document_category`` call, over dockets in the
    same sorted order -- so the stratified sample drawn from this pool lands on the same 60
    rows, in the same order, as the committed (redacted) sheet. The only addition is a
    locator (mkey, href) per unique row, which the committed sheet has no use for but a real
    document link needs; ``setdefault`` keeps the first-seen locator, since the pool itself is
    a set of unique titles that may recur across cases.
    """
    cases = _cases(settings.data_dir / "processed", tuple(samples.sample_ids("dev-400")))
    allowed = {mkey for mkey, _event in cases.values()}
    pools: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    locators: dict[tuple[str, str, str], tuple[int, str]] = {}
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        for mkey_dir in sorted(settings.docket_dir.iterdir()):
            if not (mkey_dir / "listing.html").is_file():
                continue
            mkey = int(mkey_dir.name)
            if mkey not in allowed:
                continue
            listing = parse_listing(client.listing_html(mkey), mkey=mkey)
            for entry in listing.entries:
                category = document_category(entry.title)
                key = (entry.title, entry.doc_type, category)
                pools[category].add(key)
                locators.setdefault(key, (mkey, entry.href))
    return {category: sorted(rows) for category, rows in pools.items()}, locators


def sample_rows(settings: Settings) -> list[HandcheckRow]:
    """The same ~60-title stratified sample as the committed sheet, titles unredacted.

    Row numbers are the row's position in the sample (1-based), matching the committed
    sheet's own row order one for one -- ``merge`` depends on that alignment.
    """
    pools, locators = _title_pools(settings)
    sample = _stratified_sample(pools, total=HANDCHECK_SAMPLE_SIZE, seed=SEED)
    rows = []
    for position, (title, doc_type, category) in enumerate(sample, start=1):
        mkey, href = locators[(title, doc_type, category)]
        rows.append(
            HandcheckRow(
                row=position,
                title=title,
                doc_type=doc_type,
                category=category,
                docket_url=sources.docket_url(mkey),
                document_url=sources.docket_document_url(href) if href else None,
            )
        )
    return rows


def case_documents(settings: Settings, case_id: str) -> tuple[int, list[HandcheckRow]]:
    """One case's whole docket listing as page rows, from the cache only."""
    cases = _cases(settings.data_dir / "processed", (case_id,))
    if case_id not in cases:
        raise FixtureError(f"{case_id}: not found in cases.parquet")
    mkey, _event = cases[case_id]
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        listing = parse_listing(client.listing_html(mkey), mkey=mkey)
    return mkey, rows_from_listing(listing)


# --- HTML rendering. Inline everything; no CDN, no external stylesheet, no framework. ---


def _esc(text: str) -> str:
    """HTML-escape one piece of user-visible text (a title, a doc type, a URL)."""
    return html.escape(text, quote=True)


_STYLE = """
:root {
  color-scheme: light dark;
  --bg: #f6f6f4;
  --card-bg: #ffffff;
  --text: #1a1a1a;
  --muted: #5b5b5b;
  --border: #d8d8d4;
  --accent: #2b4b6f;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #17181a;
    --card-bg: #212225;
    --text: #e8e8e6;
    --muted: #a4a4a0;
    --border: #3a3b3e;
    --accent: #8fb3d9;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0;
  padding: 1.5rem 1.25rem 4rem;
  background: var(--bg);
  color: var(--text);
  font-family: -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  line-height: 1.4;
}
.page { max-width: 56rem; margin: 0 auto; }
h1 { font-size: 1.4rem; margin: 0 0 0.5rem; }
p.note { color: var(--muted); font-size: 0.92rem; max-width: 42rem; }
.banner {
  border: 1px solid var(--border);
  background: var(--card-bg);
  padding: 0.75rem 1rem;
  border-radius: 0.4rem;
  margin: 0.75rem 0;
  font-size: 0.9rem;
}
.banner.warning { border-color: #8a6d3b; }
.controls-bar {
  position: sticky;
  top: 0;
  background: var(--bg);
  padding: 0.75rem 0;
  border-bottom: 1px solid var(--border);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.75rem;
  z-index: 1;
}
#progress { font-weight: 600; }
button {
  font: inherit;
  padding: 0.45rem 0.9rem;
  border: 1px solid var(--border);
  border-radius: 0.35rem;
  background: var(--card-bg);
  color: var(--text);
  cursor: pointer;
}
button:hover { border-color: var(--accent); }
.row-card {
  border: 1px solid var(--border);
  background: var(--card-bg);
  border-radius: 0.5rem;
  padding: 1.1rem 1.25rem;
  margin: 1rem 0;
}
.row-card.marked { border-left: 3px solid var(--accent); }
.row-head {
  display: flex;
  align-items: baseline;
  gap: 0.6rem;
  flex-wrap: wrap;
}
.row-number {
  font-variant-numeric: tabular-nums;
  color: var(--muted);
  font-size: 0.9rem;
}
.row-title { font-size: 1.15rem; font-weight: 600; }
.row-meta { color: var(--muted); font-size: 0.88rem; margin: 0.2rem 0 0.6rem; }
.row-links { margin: 0.2rem 0 0.8rem; font-size: 0.9rem; }
.row-links a { color: var(--accent); margin-right: 1.2rem; }
fieldset {
  border: none;
  padding: 0;
  margin: 0 0 0.7rem;
}
legend {
  font-size: 0.85rem;
  color: var(--muted);
  padding: 0;
  margin-bottom: 0.25rem;
}
.options { display: flex; gap: 1.1rem; flex-wrap: wrap; }
.options label { font-size: 0.95rem; }
select, textarea {
  font: inherit;
  width: 100%;
  max-width: 32rem;
  padding: 0.4rem 0.5rem;
  border: 1px solid var(--border);
  border-radius: 0.3rem;
  background: var(--card-bg);
  color: var(--text);
}
textarea { min-height: 3rem; resize: vertical; }
#csv-preview { width: 100%; min-height: 8rem; font-family: ui-monospace, monospace; }
.export { margin-top: 1.5rem; }
"""


def _links_html(row: HandcheckRow) -> str:
    docket_link = (
        f'<a href="{_esc(row.docket_url)}" target="_blank" rel="noopener">Open the docket</a>'
    )
    links = [docket_link]
    if row.document_url is not None:
        document_link = (
            f'<a href="{_esc(row.document_url)}" target="_blank" rel="noopener">'
            "Open this document</a>"
        )
        links.append(document_link)
    return '<div class="row-links">' + "".join(links) + "</div>"


def _yes_no_fieldset(field: str, row_number: int, legend: str) -> str:
    name = f"{field}-{row_number}"
    options = "".join(
        f'<label><input type="radio" name="{name}" value="{value}"> {label}</label>'
        for value, label in (("y", "Yes"), ("n", "No"))
    )
    return (
        f'<fieldset data-field="{field}"><legend>{_esc(legend)}</legend>'
        f'<div class="options">{options}</div></fieldset>'
    )


def _author_fieldset(row_number: int) -> str:
    name = f"author-{row_number}"
    options = "".join(
        f'<option value="{value}" title="{_esc(AUTHOR_GLOSSES[value])}">{value}</option>'
        for value in AUTHOR_OPTIONS
    )
    return (
        '<fieldset data-field="author"><legend>Whose account is this?</legend>'
        f'<select name="{name}"><option value=""></option>{options}</select></fieldset>'
    )


def _row_card(row: HandcheckRow) -> str:
    conclusions_legend = "Could this document hold the investigators' own conclusions?"
    fieldsets = "".join(
        (
            _yes_no_fieldset("is_photo", row.row, "Is this a photograph?"),
            _yes_no_fieldset("could_hold_conclusions", row.row, conclusions_legend),
            _author_fieldset(row.row),
            '<fieldset data-field="notes"><legend>Notes (optional)</legend>'
            f'<textarea name="notes-{row.row}" rows="2"></textarea></fieldset>',
        )
    )
    return (
        f'<article class="row-card" data-row="{row.row}">'
        '<div class="row-head">'
        f'<span class="row-number">{row.row}</span>'
        f'<span class="row-title">{_esc(row.title)}</span>'
        "</div>"
        f'<p class="row-meta">doc type: {_esc(row.doc_type)} &middot; classifier category: '
        f"{_esc(row.category)}</p>"
        f"{_links_html(row)}"
        f"{fieldsets}"
        "</article>"
    )


_MARKING_JS = Template(
    """
(function () {
  "use strict";
  var STORAGE_KEY = "ntsb-handcheck-marks-v1";
  var TOTAL = $total;
  var storageOk = true;

  function loadMarks() {
    try {
      var raw = window.localStorage.getItem(STORAGE_KEY);
      return raw ? JSON.parse(raw) : {};
    } catch (e) {
      storageOk = false;
      return {};
    }
  }
  function saveMarks(marks) {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify(marks));
    } catch (e) {
      storageOk = false;
    }
  }

  var marks = loadMarks();
  if (!storageOk) {
    var warning = document.getElementById("storage-warning");
    if (warning) warning.hidden = false;
  }

  function markFor(row) {
    return marks[row] || { is_photo: "", could_hold_conclusions: "", author: "", notes: "" };
  }

  function isMarked(row) {
    var m = markFor(row);
    return Boolean(m.is_photo && m.could_hold_conclusions && m.author);
  }

  function applyMark(row) {
    var m = markFor(row);
    var card = document.querySelector('[data-row="' + row + '"]');
    if (!card) return;
    ["is_photo", "could_hold_conclusions"].forEach(function (field) {
      var input = card.querySelector(
        'input[name="' + field + "-" + row + '"][value="' + m[field] + '"]'
      );
      if (input) input.checked = true;
    });
    var authorSelect = card.querySelector('select[name="author-' + row + '"]');
    if (authorSelect) authorSelect.value = m.author || "";
    var notes = card.querySelector('textarea[name="notes-' + row + '"]');
    if (notes) notes.value = m.notes || "";
    card.classList.toggle("marked", isMarked(row));
  }

  function updateProgress() {
    var done = 0;
    for (var i = 1; i <= TOTAL; i++) {
      if (isMarked(i)) done++;
    }
    var el = document.getElementById("progress");
    if (el) el.textContent = done + " of " + TOTAL + " marked";
  }

  function firstUnmarked() {
    for (var i = 1; i <= TOTAL; i++) {
      if (!isMarked(i)) return i;
    }
    return null;
  }

  var jumpButton = document.getElementById("jump-unmarked");
  if (jumpButton) {
    jumpButton.addEventListener("click", function () {
      var row = firstUnmarked();
      if (row === null) return;
      var card = document.querySelector('[data-row="' + row + '"]');
      if (card) card.scrollIntoView({ block: "start", behavior: "smooth" });
    });
  }

  document.querySelectorAll(".row-card").forEach(function (card) {
    var row = card.getAttribute("data-row");
    card.addEventListener("change", function (evt) {
      var target = evt.target;
      var m = markFor(row);
      if (target.name === "is_photo-" + row) {
        m.is_photo = target.value;
      } else if (target.name === "could_hold_conclusions-" + row) {
        m.could_hold_conclusions = target.value;
      } else if (target.name === "author-" + row) {
        m.author = target.value;
      } else {
        return;
      }
      marks[row] = m;
      saveMarks(marks);
      card.classList.toggle("marked", isMarked(row));
      updateProgress();
    });
    card.addEventListener("input", function (evt) {
      var target = evt.target;
      if (target.name !== "notes-" + row) return;
      var m = markFor(row);
      m.notes = target.value;
      marks[row] = m;
      saveMarks(marks);
    });
  });

  for (var i = 1; i <= TOTAL; i++) applyMark(i);
  updateProgress();

  /* CSV EXPORT -- marks only, no titles. */
  function csvField(value) {
    var s = String(value === undefined || value === null ? "" : value);
    if (/[",\\n]/.test(s)) {
      s = '"' + s.replace(/"/g, '""') + '"';
    }
    return s;
  }
  function buildCsv() {
    var lines = ["row,is_photo,could_hold_conclusions,author,notes"];
    for (var i = 1; i <= TOTAL; i++) {
      var m = markFor(i);
      var fields = [
        i,
        csvField(m.is_photo),
        csvField(m.could_hold_conclusions),
        csvField(m.author),
        csvField(m.notes),
      ];
      lines.push(fields.join(","));
    }
    return lines.join("\\n") + "\\n";
  }
  function showPreview(csv) {
    var area = document.getElementById("csv-preview");
    if (!area) return;
    area.value = csv;
    area.hidden = false;
    area.focus();
    area.select();
  }
  var copyButton = document.getElementById("copy-csv");
  if (copyButton) {
    copyButton.addEventListener("click", function () {
      var csv = buildCsv();
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(csv).catch(function () {});
      }
      showPreview(csv);
    });
  }
  var downloadButton = document.getElementById("download-csv");
  if (downloadButton) {
    downloadButton.addEventListener("click", function () {
      var csv = buildCsv();
      var blob = new Blob([csv], { type: "text/csv" });
      var url = URL.createObjectURL(blob);
      var a = document.createElement("a");
      a.href = url;
      a.download = "handcheck-marks.csv";
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
      showPreview(csv);
    });
  }
  /* END CSV EXPORT */
})();
"""
)


_PAGE_TEMPLATE = Template(
    """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>$title</title>
<style>$style</style>
</head>
<body>
<div class="page">
<h1>$title</h1>
<p class="note">$intro</p>
<div id="storage-warning" class="banner warning" hidden>
This browser is not saving to local storage (a private window, or storage blocked). Marks made
here will not survive closing this tab -- export the CSV before you stop.
</div>
$extra_banner
<div class="controls-bar">
<span id="progress">0 of $total marked</span>
<button type="button" id="jump-unmarked">Jump to first unmarked</button>
<span style="flex: 1"></span>
<button type="button" id="copy-csv">Copy marks as CSV</button>
<button type="button" id="download-csv">Download marks as CSV</button>
</div>
<div class="export">
<textarea id="csv-preview" readonly hidden></textarea>
</div>
$rows_html
</div>
<script>$script</script>
</body>
</html>
"""
)


def render_marking_page(rows: Sequence[HandcheckRow]) -> str:
    """The self-contained marking page: one card per row, saved to ``localStorage`` as it goes."""
    intro = (
        "One row per document title from the dev-400 docket cache (decision 0048 item 4). "
        "Every mark is saved to this browser's local storage as you go -- closing the tab or "
        "reloading loses nothing. When you are done (or want to pause), copy or download the "
        "CSV below and hand it to `handcheck_page.py merge`. This page is local only and is "
        "never committed."
    )
    rows_html = "\n".join(_row_card(row) for row in rows)
    return _PAGE_TEMPLATE.substitute(
        title="NTSB docket title hand-check",
        style=_STYLE,
        intro=intro,
        extra_banner="",
        total=len(rows),
        rows_html=rows_html,
        script=_MARKING_JS.substitute(total=len(rows)),
    )


def _case_row_card(row: HandcheckRow) -> str:
    return (
        f'<article class="row-card" data-row="{row.row}">'
        '<div class="row-head">'
        f'<span class="row-number">#{row.row}</span>'
        f'<span class="row-title">{_esc(row.title)}</span>'
        "</div>"
        f'<p class="row-meta">doc type: {_esc(row.doc_type)} &middot; classifier category: '
        f"{_esc(row.category)}</p>"
        f"{_links_html(row)}"
        "</article>"
    )


def render_case_page(case_id: str, mkey: int, rows: Sequence[HandcheckRow]) -> str:
    """A short, read-only page listing one case's whole docket, for the reviewed-document read."""
    allowed = ", ".join(sorted(DOCUMENT_ALLOWED_CATEGORIES))
    intro = (
        f"Every document in {_esc(case_id)}'s docket (mkey {mkey}), for the second S2 task: "
        "reading two or three documents and approving their text for commit (decision 0037). "
        f"Only documents in the {_esc(allowed)} categories are ones "
        "`make_docket_fixture document` can commit as reviewed text -- the rest are shown for "
        "context. This page is local only and is never committed."
    )
    rows_html = "\n".join(_case_row_card(row) for row in rows)
    return _PAGE_TEMPLATE.substitute(
        title=f"{case_id} -- documents for review",
        style=_STYLE,
        intro=intro,
        extra_banner="",
        total=len(rows),
        rows_html=rows_html,
        script="",
    )


# --- Merge: fold an exported marks CSV into the committed sheet, by row number. ---


def merge_marks(sheet_path: Path, marks_path: Path) -> tuple[int, int]:
    """Fold ``marks_path`` into ``sheet_path`` by row number; return (rows updated, sheet rows).

    Only the four mark columns (``MARK_COLUMNS``) are ever written. Titles, doc types and
    categories are read back exactly as they were and rewritten unchanged, so the committed
    sheet's redaction (decision 0048 item 4) is never touched by this path.
    """
    with sheet_path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        if fieldnames is None:
            raise FixtureError(f"{sheet_path}: has no header row")
        sheet_rows = list(reader)

    with marks_path.open(newline="") as handle:
        marks_reader = csv.DictReader(handle)
        marks_fields = marks_reader.fieldnames or ()
        missing = {"row", *MARK_COLUMNS} - set(marks_fields)
        if missing:
            raise FixtureError(
                f"{marks_path}: missing column(s) {sorted(missing)}; expected "
                f"{','.join(MARKS_CSV_HEADER)}"
            )
        marks_by_row: dict[int, Mapping[str, str | None]] = {}
        for mark_row in marks_reader:
            raw_row = mark_row.get("row")
            try:
                row_number = int(str(raw_row))
            except ValueError as error:
                raise FixtureError(
                    f"{marks_path}: row number {raw_row!r} is not an integer"
                ) from error
            marks_by_row[row_number] = mark_row

    unknown = sorted(n for n in marks_by_row if not (1 <= n <= len(sheet_rows)))
    if unknown:
        raise FixtureError(
            f"{marks_path}: row number(s) outside the sheet (1-{len(sheet_rows)}): {unknown}"
        )

    updated = 0
    for position, row in enumerate(sheet_rows, start=1):
        mark = marks_by_row.get(position)
        if mark is None:
            continue
        for column in MARK_COLUMNS:
            row[column] = mark.get(column) or ""
        updated += 1

    with sheet_path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, lineterminator="\n")
        writer.writeheader()
        writer.writerows(sheet_rows)
    return updated, len(sheet_rows)


# --- CLI ---


def _cmd_page(args: argparse.Namespace, settings: Settings) -> int:
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    rows = sample_rows(settings)
    out.write_text(render_marking_page(rows))
    print(f"wrote {out}: {len(rows)} rows")

    case_out = Path(args.case_out) if args.case_out else out.with_name(f"{args.case.lower()}.html")
    mkey, case_rows = case_documents(settings, args.case)
    case_out.write_text(render_case_page(args.case, mkey, case_rows))
    print(f"wrote {case_out}: {len(case_rows)} documents for {args.case}")
    return 0


def _cmd_merge(args: argparse.Namespace) -> int:
    sheet_path = Path(args.sheet)
    marks_path = Path(args.marks)
    updated, total = merge_marks(sheet_path, marks_path)
    print(f"merged {updated} of {total} rows in {sheet_path} from {marks_path}")
    return 0


def main(argv: list[str]) -> int:
    """Dispatch the ``page`` and ``merge`` subcommands."""
    parser = argparse.ArgumentParser(prog="handcheck_page")
    commands = parser.add_subparsers(dest="command", required=True)

    page_p = commands.add_parser(
        "page", help="write the local marking page and the case-reading page"
    )
    page_p.add_argument(
        "--out",
        default=str(DEFAULT_OUT),
        help=f"where to write the marking page; git-ignored (default: {DEFAULT_OUT})",
    )
    page_p.add_argument(
        "--case",
        default=CASE_DOCUMENTS_CASE_ID,
        help="case id for the second, shorter reading page (default: %(default)s)",
    )
    page_p.add_argument(
        "--case-out",
        default=None,
        help="where to write the case-reading page (default: alongside --out)",
    )

    merge_p = commands.add_parser(
        "merge", help="fold an exported marks CSV into the committed hand-check sheet"
    )
    merge_p.add_argument("marks", help="the marks CSV exported from the marking page")
    merge_p.add_argument(
        "--sheet",
        default=str(SHEET_PATH),
        help="the committed sheet to update (default: %(default)s)",
    )

    args = parser.parse_args(argv)
    try:
        if args.command == "page":
            return _cmd_page(args, Settings())
        return _cmd_merge(args)
    except FixtureError as error:
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
