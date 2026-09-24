"""The analysis-sentence hand-check: Andy's marking page, and its scorer (S2.6 §4.2, 0077).

Status
    One-shot (S2.6). ``sheet`` writes a private marking page and sheet under
    ``data/handcheck/s26-analysis/`` for the ``dev-400`` docket sentences the tripwire
    matches to the analysis narrative (36 in 17 cases, ``docs/results/s2-docket-leak.txt``).
    ``score`` reads the marks Andy downloads from that page and writes
    ``docs/results/s26-analysis-handcheck.txt``, counts only. Decision 0077 takes effect only
    if 5 or fewer of the 36 are conclusions.

The sheet holds withheld text -- the matched analysis sentences -- so it lives under
``data/`` and is never committed (spec §4.2). Each sentence is shown inside the document
text around it, as the tripwire compares it (lower case, whitespace collapsed), with the
document's listing title, and one question: does this sentence quote evidence, or is it a
conclusion sitting in the docket?

Run:
    uv run python -m scripts.analysis_handcheck sheet [--sample dev-400]
    uv run python -m scripts.analysis_handcheck score <marks.csv> [--out PATH]
"""

import argparse
import csv
import html
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.attach import prepare_attachment
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.manifest import Docket
from ntsb_probable_cause.errors import DocketError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole, SynthesisRole, VerdictRole
from ntsb_probable_cause.records.guard import find_leaks, normalise_text
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.runner import CachedDocketReader
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts.marking_page import Card, Choice

ANALYSIS = SynthesisRole.ANALYSIS_NARRATIVE.value
CAUSE = VerdictRole.PROBABLE_CAUSE.value
DOCUMENTS = EvidenceRole.DOCKET_DOCUMENTS.value
CONTEXT_CHARS = 300
NO_SENTENCES = 10**9
# Spec §4.2 and decision 0077 item 4: "If 5 or fewer of the 36 are conclusions".
MAX_CONCLUSIONS = 5
EXPECTED_ROWS = 36
QUOTES, CONCLUSION = "quotes evidence", "conclusion in the docket"
MARKS = (QUOTES, CONCLUSION)
FOLDER = Path("handcheck") / "s26-analysis"
INTRO = (
    "<p>Each card shows one sentence (highlighted) that a docket document shares with the "
    "investigators' analysis narrative, inside the document text around it. The text is lower "
    "case because that is how the guard compares it. Mark each one: does the sentence "
    "<b>quote evidence</b> (a record of what was seen, measured or said), or is it a "
    "<b>conclusion in the docket</b> (a judgement about why the accident happened)? Marks save "
    "in this browser as you go. Download the CSV when you are done.</p>"
)


@dataclass(frozen=True)
class SheetRow:
    """One matched sentence, where it sits, and the text around it. Private."""

    case_id: str
    document: int
    title: str
    category: str
    sentence: str
    before: str
    after: str
    cause_in_case: bool


def _offline() -> httpx.BaseTransport:
    """A transport refusing every request, so a cache miss is loud and costs no fetch."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: this hand-check reads the cache only")

    return httpx.MockTransport(refuse)


def sheet_rows(raw: Mapping[str, object], docket: Docket) -> list[SheetRow]:
    """Every analysis sentence one of the case's readable documents shares, once per case.

    Mirrors ``scripts/docket_leak_scan.py``: every readable document is attached, the split
    runs with sentence checks off so the case is not refused, and each document is compared
    alone so the row can name it. A sentence found in two documents is one row, under the
    first, because the 36 of ``s2-docket-leak.txt`` count sentences, not places.
    """
    readable = [r.entry.index for r in docket.documents if r.status == "read"]
    attachment = prepare_attachment(raw, docket)
    _, synthesis, verdict = split_record(
        attachment.context_for(readable).context, min_sentence_chars=NO_SENTENCES
    )
    analysis = synthesis.analysis_narrative
    if not analysis:
        return []
    joined = "\n".join(attachment.document_texts[i] for i in readable)
    cause_in_case = bool(
        verdict.probable_cause
        and find_leaks(
            {DOCUMENTS: joined}, {CAUSE: verdict.probable_cause}, (), exemptions=frozenset()
        )
    )
    seen: set[str] = set()
    rows: list[SheetRow] = []
    for index in readable:
        text = attachment.document_texts[index]
        haystack = normalise_text(text)
        leaks = find_leaks({DOCUMENTS: text}, {ANALYSIS: analysis}, (), exemptions=frozenset())
        for leak in leaks:
            if leak.kind != "sentence" or leak.fragment in seen:
                continue
            seen.add(leak.fragment)
            start = haystack.find(leak.fragment)
            end = start + len(leak.fragment)
            record = docket.record(index)
            rows.append(
                SheetRow(
                    case_id=str(raw["ntsbNumber"]),
                    document=index,
                    title=record.entry.title,
                    category=record.category,
                    sentence=leak.fragment,
                    before=haystack[max(0, start - CONTEXT_CHARS) : start],
                    after=haystack[end : end + CONTEXT_CHARS],
                    cause_in_case=cause_in_case,
                )
            )
    return rows


def _body(number: int, row: SheetRow) -> str:
    esc = html.escape
    cause = " · this case also holds a probable-cause sentence" if row.cause_in_case else ""
    return (
        f'<p class="meta">Row {number} · case {esc(row.case_id)} · docket item {row.document}: '
        f"{esc(row.title)} ({esc(row.category)}){cause}</p>"
        f"<p>…{esc(row.before)}<mark>{esc(row.sentence)}</mark>{esc(row.after)}…</p>"
    )


def render_page(rows: Sequence[SheetRow]) -> str:
    """The marking page: one card per sentence, the two marks, optional notes."""
    cards = [
        Card(
            row=number,
            body_html=_body(number, row),
            choices=(Choice("mark", MARKS),),
            text_fields=(("notes", ""),),
        )
        for number, row in enumerate(rows, start=1)
    ]
    return marking_page.render(
        title="Analysis-sentence hand-check (decision 0077)",
        intro_html=INTRO,
        cards=cards,
        storage_key="s26-analysis-handcheck",
        csv_name="analysis-handcheck-marks.csv",
    )


def write_sheet(folder: Path, rows: Sequence[SheetRow]) -> None:
    """The page and the full private sheet (row numbers match the page's)."""
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "index.html").write_text(render_page(rows))
    names = ["row", *(field for field in SheetRow.__dataclass_fields__)]
    with (folder / "sheet.csv").open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=names)
        writer.writeheader()
        for number, row in enumerate(rows, start=1):
            writer.writerow({"row": number, **asdict(row)})


def score(rows: Sequence[Mapping[str, str]], marks: Mapping[int, str]) -> str:
    """Counts by mark and by document category, and the rule of 0077 item 4. No text."""
    numbers = [int(r["row"]) for r in rows]
    unmarked = [n for n in numbers if marks.get(n) not in MARKS]
    if unmarked:
        raise SystemExit(f"{len(unmarked)} rows are unmarked (e.g. row {unmarked[0]})")
    by_mark = Counter(marks[n] for n in numbers)
    by_category: Counter[tuple[str, str]] = Counter(
        (r["category"], marks[int(r["row"])]) for r in rows
    )
    conclusions = by_mark[CONCLUSION]
    total = len(numbers)
    low, high = wilson(conclusions, total)
    if total != EXPECTED_ROWS:
        outcome = (
            f"outcome: not applied -- the rule was written for {EXPECTED_ROWS} sentences and "
            f"this sheet holds {total}; returned to Andy"
        )
    elif conclusions <= MAX_CONCLUSIONS:
        outcome = "outcome: adopted -- decision 0077 takes effect"
    else:
        outcome = "outcome: not adopted -- returned to Andy, neutral-marker fallback (spec §4.2)"
    categories = sorted({c for c, _ in by_category})
    cases = len({r["case_id"] for r in rows})
    return "\n".join(
        [
            "# analysis-sentence hand-check (S2.6 spec §4.2, decision 0077 item 4) -- counts only",
            f"sample dev-400: {total} matched sentences in {cases} cases, each marked by Andy "
            "beside its document title",
            "the sentences themselves are withheld text and are not in this file",
            "",
            f"  {QUOTES:<28} {by_mark[QUOTES]:3d}",
            f"  {CONCLUSION:<28} {conclusions:3d}",
            "",
            "by document category (quotes evidence / conclusion in the docket):",
            *(
                f"  {c:<24} {by_category[(c, QUOTES)]:3d} / {by_category[(c, CONCLUSION)]:3d}"
                for c in categories
            ),
            "",
            f"the rule's measured error: {conclusions} of {total} sentences are conclusions "
            f"({conclusions / total:.1%} [{low:.1%}, {high:.1%}], Wilson 95%)",
            f"rule: adopt 0077 if {MAX_CONCLUSIONS} or fewer of {EXPECTED_ROWS} are conclusions",
            outcome,
        ]
    )


def _read_docket(reader: CachedDocketReader, mkey: object) -> Docket:
    """The docket for a case's ``mKey``, or raise ``DocketError`` if it has none."""
    if not isinstance(mkey, int):
        raise DocketError("no mKey")
    return reader.read(mkey)


def main(argv: list[str] | None = None) -> int:
    """``sheet`` writes the private page; ``score`` writes the counts."""
    parser = argparse.ArgumentParser(prog="analysis_handcheck")
    commands = parser.add_subparsers(dest="command", required=True)
    sheet_p = commands.add_parser("sheet")
    sheet_p.add_argument("--sample", default="dev-400")
    score_p = commands.add_parser("score")
    score_p.add_argument("marks", type=Path)
    score_p.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    folder = settings.data_dir / FOLDER
    if args.command == "sheet":
        if not args.sample.startswith("dev"):
            raise SystemExit("the hand-check reads development cases only")
        reader = CachedDocketReader(DocketClient(settings.docket_dir, transport=_offline()))
        rows: list[SheetRow] = []
        skipped = 0
        for raw in load_cases(settings.data_dir / "processed", sample_ids(args.sample)):
            mkey = raw.get("mKey")
            try:
                rows.extend(sheet_rows(raw, _read_docket(reader, mkey)))
            except DocketError, LeakageError:
                skipped += 1
        write_sheet(folder, rows)
        cases = len({r.case_id for r in rows})
        print(f"{len(rows)} sentences in {cases} cases; {skipped} cases skipped; page at {folder}")
        return 0
    with (folder / "sheet.csv").open(newline="") as handle:
        sheet = list(csv.DictReader(handle))
    marks = {
        row: fields.get("mark", "") for row, fields in marking_page.read_marks(args.marks).items()
    }
    text = score(sheet, marks)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
