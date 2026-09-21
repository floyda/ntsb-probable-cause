"""Create docket fixtures from development-split cases only (decision 0037).

Status
    Live tool (S2). Produced the committed docket fixture pool under ``tests/fixtures/docket/``
    -- listing pages, the reviewed document texts decision 0037 requires a human to attest to,
    and the title hand-check sheet. Rerun whenever a new fixture is needed; the ``document``
    subcommand still requires Andy to read the document and pass ``--reviewed-by``. The "Task
    16" references below are to the S2 implementation plan, which decision 0017 deleted at
    merge; the deviations it records are in the As-built part of
    ``docs/specs/2026-09-18-s2-docket-tool-design.md``.

Usage:
    uv run python -m scripts.make_docket_fixture listing [<case_id>]
        Fetch one dev-400 listing page (the seeded first case when no id is given) and
        commit it as received. Network; no key.
    uv run python -m scripts.make_docket_fixture draw [--write]
        For each of six criteria, the first cached dev-400 docket in seeded order that meets
        it and whose listing carries no title word the redaction name check cannot vouch for.
        Prints the candidates; ``--write`` also commits a listing fixture (an outcome-only
        manifest, never document text) per criterion. Reads the cache only.
    uv run python -m scripts.make_docket_fixture document <case_id> <index> --reviewed-by "..."
        Commit one already-drawn case's document (PDF and redacted text) after Andy has
        read it and is prepared to attest to it with ``--reviewed-by``. Reads the cache only.
    uv run python -m scripts.make_docket_fixture handcheck
        Write a stratified, ~60-title hand-check sheet for Andy's three-question review
        (decision 0048 item 4). Reads the cache only.

Task 16 brief, 2026-09-19: the commands below implement the plan's Task 16 with five
corrections over the plan text (A-E, cited at each site). Two are already folded into this
file's structure without their own callout: the criteria tuple below carries six entries, not
"about five", and the "over the cap at Sonnet 5 standard" criterion is replaced with the
largest readable docket in the sample -- both were already corrected in the plan text this
file is built from.
"""

import argparse
import csv
import hashlib
import json
import random
import sys
from collections import defaultdict
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause.docket.attach import amateur_built_replace, redact_known_names
from ntsb_probable_cause.docket.classify import document_category
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord, read_docket
from ntsb_probable_cause.docket.title_vocab import known_title_words, redact_title
from ntsb_probable_cause.errors import FixtureError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split, split_of

FIXTURES = Path("tests/fixtures/docket")
SEED = 20260918
# The "largest readable docket in the sample" criterion's own threshold -- named for what it
# picks, not for the S1 cost cap it used to be measured against (see the criterion's comment).
_LARGE_DOCKET_TOKENS = 15_000
# The "two types" criterion: both of DOCUMENT_ALLOWED_CATEGORIES must be present as read,
# born-digital documents.
_TWO_DOCUMENT_TYPES = 2


def _assert_dev_split(case_id: str, event_date: str) -> None:
    """Raise ``FixtureError`` unless the event date is in the development split.

    Called twice on the fetch path (fix round 2, Finding 1): once in ``_fetch_listing``,
    before ``DocketClient`` is even constructed, so a non-development case is never looked
    at, let alone cached (decisions 0026, 0037 treat the look as the thing to prevent, not
    merely the commit); and again inside ``write_listing_fixture``, which protects any
    future caller that skips the fetch helper.
    """
    if split_of(date.fromisoformat(event_date)) is not Split.DEV:
        raise FixtureError(f"{case_id}: event date {event_date} is not in the development split")


def _cases(processed: Path, ids: tuple[str, ...]) -> dict[str, tuple[int, str]]:
    """Case id to (mkey, event date) for the given ids, from cases.parquet."""
    wanted = set(ids)
    found: dict[str, tuple[int, str]] = {}
    with pq.ParquetFile(processed / "cases.parquet") as parquet_file:
        for batch in parquet_file.iter_batches(columns=["ntsb_number", "mkey", "event_date"]):
            for number, mkey, event in zip(
                batch.column("ntsb_number").to_pylist(),
                batch.column("mkey").to_pylist(),
                batch.column("event_date").to_pylist(),
                strict=True,
            ):
                if number in wanted:
                    found[str(number)] = (int(mkey), str(event))
    return found


def first_dev_400_case(processed: Path, *, seed: int = SEED) -> tuple[str, int, str]:
    """The first dev-400 case in seeded order: id, mkey, event date."""
    ids = list(samples.sample_ids("dev-400"))
    random.Random(seed).shuffle(ids)  # noqa: S311 -- reproducible draw, not security
    cases = _cases(processed, tuple(ids[:1]))
    if ids[0] not in cases:
        raise FixtureError(f"{ids[0]}: not found in cases.parquet; the corpus may be stale")
    mkey, event = cases[ids[0]]
    return ids[0], mkey, event


def write_listing_fixture(  # noqa: PLR0913, PLR0917 -- one argument per manifest field.
    case_id: str,
    mkey: int,
    event_date: str,
    html: str,
    fetched_at: str,
    criterion: str,
    *,
    root: Path = FIXTURES,
    seed: int | None = None,
) -> Path:
    """Write the listing page as received and a manifest; refuse anything outside development.

    Writes bytes, not text: ``Path.write_bytes`` never translates line endings, so the file
    on disk is exactly the encoded ``html`` string, byte for byte -- a docket fixture is a
    saved real response (decision 0037), and the ``sha256`` recorded below states what was
    actually received, not merely where it came from. ``seed`` is the RNG seed that drew
    this case, or ``None`` for a case named by hand (fix round 2, Finding 3): the manifest
    should evidence which happened by itself, without a reader having to trust ``criterion``
    or the filename.
    """
    _assert_dev_split(case_id, event_date)
    folder = root / case_id
    folder.mkdir(parents=True, exist_ok=True)
    content = html.encode("utf-8")
    (folder / "listing.html").write_bytes(content)
    manifest = {
        "fixture": {
            "source": f"https://data.ntsb.gov/Docket?ProjectID={mkey}",
            "fetched_at": fetched_at,
            "case_id": case_id,
            "mkey": mkey,
            "event_date": event_date,
            "criterion": criterion,
            "seed": seed,
            "sha256": hashlib.sha256(content).hexdigest(),
        },
        "documents": [],
    }
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    return folder


def _fetch_listing(case_id: str, mkey: int, event_date: str, settings: Settings) -> str:
    """Fetch one case's listing page, refusing before any request if it is not development.

    Fix round 2, Finding 1: the split is checked here, before ``DocketClient`` is
    constructed, so a held-out or open-split case is never looked at -- not merely never
    committed. Both ``_cmd_listing`` branches call this one function, so the guard runs on
    both the seeded draw and an explicit case id.
    """
    _assert_dev_split(case_id, event_date)
    with DocketClient(
        settings.docket_dir, seconds_per_request=settings.docket_seconds_per_request
    ) as client:
        return client.listing_html(mkey)


def _cmd_listing(args: argparse.Namespace, settings: Settings) -> int:
    processed = settings.data_dir / "processed"
    if args.case_id:
        cases = _cases(processed, (args.case_id,))
        if args.case_id not in samples.sample_ids("dev-400") or args.case_id not in cases:
            raise FixtureError(f"{args.case_id}: not a dev-400 case")
        case_id, (mkey, event) = args.case_id, cases[args.case_id]
        criterion = args.criterion or "named by hand"
        seed = None
    else:
        case_id, mkey, event = first_dev_400_case(processed)
        criterion = args.criterion or "first draw"
        seed = SEED
    html = _fetch_listing(case_id, mkey, event, settings)
    folder = write_listing_fixture(
        case_id, mkey, event, html, datetime.now(UTC).isoformat(), criterion, seed=seed
    )
    print(f"wrote {folder}")
    return 0


# --- Task 16: the fixture pool, the reviewed document, the title hand-check ---

# Task 16 brief, correction D: narrowed from the plan's original five categories (exam_site,
# specialist_factual, weather, medical_tox, atc_radar_data) to the two that attach.py's own
# provenance labels (_LABELS) actually attribute to the investigation itself (0048 item 4:
# "written by the investigation"). The three dropped are hedged or attributed elsewhere:
# weather -> the investigation's own study, or an independent weather service; medical_tox ->
# an independent medical examiner or laboratory; atc_radar_data -> recorded at the time, not an
# account. Decision 0037 permits committing text only from NTSB-authored documents; those three
# are not, by the project's own labels.
# Defined here, ahead of CRITERIA, so the "two types" criterion below names this set instead
# of a second, independently-typed literal that could drift from it.
DOCUMENT_ALLOWED_CATEGORIES: frozenset[str] = frozenset({"exam_site", "specialist_factual"})

CRITERIA: tuple[tuple[str, Callable[[Docket, Mapping[str, object]], bool]], ...] = (
    (
        "photo-only and non-pdf entries",
        lambda d, _raw: (
            any(e.is_photo_only() for e in d.listing.entries)
            and any(not e.is_pdf() for e in d.listing.entries)
        ),
    ),
    ("a scanned document", lambda d, _raw: any(r.kind == "scan" for r in d.documents)),
    ("a partial document", lambda d, _raw: any(r.kind == "partial" for r in d.documents)),
    # This said "over the cap at Sonnet 5 standard" with a hard-coded 15,000-token line. Since
    # the cap became honest (ANSWERING_TURNS, a case not a call), the Sonnet 5 standard output
    # reserve alone is $0.04 of the $0.05 cap, leaving about 2,500 prompt tokens across both
    # calls -- less than the non-docket prompt. EVERY case is "over the cap" there with no
    # docket attached, so the label measured nothing. Use the largest readable docket in the
    # sample, named for what it is.
    (
        "the largest readable docket in the sample",
        lambda d, _raw: (
            sum(r.estimated_tokens for r in d.documents if r.status == "read")
            > _LARGE_DOCKET_TOKENS
        ),
    ),
    # Task 16 brief, corrections B and D. Narrowed to DOCUMENT_ALLOWED_CATEGORIES (correction
    # D). And, from Andy's ruling this morning ("If the unredacted pdfs come from a non fatal
    # case then perhaps this can be ok"), the case whose documents he reads must be non-fatal
    # (correction B).
    (
        "ntsb born-digital documents of two types",
        lambda d, raw: (
            raw.get("highestInjuryLevel") != "Fatal"
            and len(
                {
                    r.category
                    for r in d.documents
                    if r.status == "read"
                    and r.kind == "born-digital"
                    and r.category in DOCUMENT_ALLOWED_CATEGORIES
                }
            )
            >= _TWO_DOCUMENT_TYPES
        ),
    ),
    (
        "a party submission",
        lambda d, _raw: any(r.category == "party_submission" for r in d.documents),
    ),
)


# A candidate-skip rule keyed on the title name-check used to sit here: a docket whose
# listing carried a word the vocabulary/dictionary check could not vouch for was passed over
# in favour of the next candidate. Measured across all 401 development dockets, only 34
# (8%) had a clean listing, and none of the 9 party-submission dockets did -- so the "a party
# submission" criterion could never be satisfied under that rule. Decision 0049 rules it out:
# a docket listing is an already-public NTSB page, and 0037's byte-exactness already commits
# it as received, names included. The line this project holds is its own public surfaces
# (0049 item 2), not a page the NTSB itself publishes. Do not reintroduce a listing-title skip
# here.


def outcome_only(record: DocumentRecord) -> dict[str, object]:
    """A manifest row: the classification and extraction outcome, never text (0037 item 3)."""
    return {
        "index": record.entry.index,
        "title": record.entry.title,
        "doc_type": record.entry.doc_type,
        "pages": record.pages,
        "photos": record.entry.photos,
        "extension": record.entry.extension,
        "category": record.category,
        "status": record.status,
        "kind": record.kind,
        "readable_pages": record.readable_pages,
        "estimated_tokens": record.estimated_tokens,
        "text_file": None,
        "pdf_file": None,
        "reviewed_by": None,
    }


def _cmd_draw(args: argparse.Namespace, settings: Settings) -> int:
    """For each criterion, the first cached dev-400 docket in seeded order that meets it.

    Correction B (Task 16 brief): a criterion may now need the case's own raw record, not
    only its docket -- ``highestInjuryLevel`` is not something a ``Docket`` carries. Raw
    records are loaded once, alongside the seeded id order ``_cases`` already keys by.

    No candidate is skipped for what its listing's titles name (decision 0049): a docket
    listing is committed as received, byte-exact (0037), and names in it are the NTSB's own
    public page, not this project's to withhold.
    """
    processed = settings.data_dir / "processed"
    ids = list(samples.sample_ids("dev-400"))
    random.Random(SEED).shuffle(ids)  # noqa: S311
    cases = _cases(processed, tuple(ids))
    raws = dict(zip(ids, samples.load_cases(processed, ids), strict=True))
    taken: dict[str, str] = {}
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        for name, criterion in CRITERIA:
            for case_id in ids:
                mkey, event = cases[case_id]
                if not (settings.docket_dir / str(mkey) / "listing.html").is_file():
                    continue
                docket = read_docket(client, mkey)
                if not criterion(docket, raws[case_id]):
                    continue
                taken[name] = case_id
                if args.write:
                    folder = write_listing_fixture(
                        case_id,
                        mkey,
                        event,
                        client.listing_html(mkey),
                        datetime.now(UTC).isoformat(),
                        name,
                        root=FIXTURES,
                    )
                    manifest = json.loads((folder / "manifest.json").read_text())
                    manifest["documents"] = [outcome_only(r) for r in docket.documents]
                    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
                break
    # Correction B: say plainly which case was drawn for Andy's read, and that it is non-fatal,
    # so the ruling's effect is visible in the draw's own output, not only in the code.
    for name, case_id in taken.items():
        injury = raws[case_id].get("highestInjuryLevel")
        note = (
            " -- non-fatal, as Andy's ruling requires"
            if name == "ntsb born-digital documents of two types"
            else ""
        )
        print(f"{name}: {case_id} (highestInjuryLevel={injury}){note}")
    missing = [name for name, _ in CRITERIA if name not in taken]
    if missing:
        print(f"no cached dev-400 docket satisfied: {missing}", file=sys.stderr)
    return 0


def redact_text(text: str, raw: Mapping[str, object]) -> tuple[str, int]:
    """The scripted redaction pass: exactly the two replacements the runtime performs.

    Correction C (Task 16 brief): an earlier version of this function re-derived the
    owner/operator replacement with its own ``re.subn``, a third implementation, looser than
    both real ones: no word-boundary anchoring (so a surname that is a substring of an
    ordinary word corrupts the committed text), no bare-digits rule (so a five-digit postcode
    replaces a matching serial number), and a different label. A committed fixture redacted by
    a different rule than the agent reads is a fixture whose "expected extraction" the
    pipeline never produces, and Andy's ``reviewed_by`` would attest to text no run will ever
    see. Call the real functions; never re-derive them.
    """
    text, count = amateur_built_replace(text, raw)
    text, n = redact_known_names(text, raw)
    return text, count + n


def _cmd_document(args: argparse.Namespace, settings: Settings) -> int:
    """Commit one NTSB-authored born-digital document's PDF and expected text, after Andy's read.

    The committed PDF is never redacted -- only the sibling ``.txt`` goes through
    ``redact_text``. The ``reviewed_by`` value is Andy's statement that he has read both the
    PDF and the ``.txt`` and found no personal name or non-NTSB text in either; the script
    cannot check that, which is why ``docket_fixture_problems`` (the fixture name-check hook)
    requires the field to be non-empty before either file is treated as reviewed.
    """
    folder = FIXTURES / args.case_id
    manifest = json.loads((folder / "manifest.json").read_text())
    mkey = int(manifest["fixture"]["mkey"])
    raws = samples.load_cases(settings.data_dir / "processed", [args.case_id])
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        docket = read_docket(client, mkey)
        record = docket.record(args.index)
        if record.status != "read" or record.kind != "born-digital":
            raise FixtureError(
                f"{args.case_id} #{args.index}: only a readable born-digital document may be "
                "committed as text"
            )
        if record.category not in DOCUMENT_ALLOWED_CATEGORIES:
            raise FixtureError(
                f"{args.case_id} #{args.index}: category {record.category} is not "
                "NTSB-authored (0037 item 3; correction D narrows this to exam_site and "
                "specialist_factual)"
            )
        data = client.document(mkey, record.entry.index, record.entry.href)
    text, redactions = redact_text(docket.texts[args.index], raws[0])
    (folder / f"{args.index}.pdf").write_bytes(data)
    (folder / f"{args.index}.txt").write_text(text)
    for row in manifest["documents"]:
        if row["index"] == args.index:
            row.update(
                {
                    "text_file": f"{args.index}.txt",
                    "pdf_file": f"{args.index}.pdf",
                    "reviewed_by": args.reviewed_by,
                    "redactions": redactions,
                }
            )
    (folder / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")
    print(
        f"wrote {folder / f'{args.index}.txt'} ({redactions} redactions); "
        f"reviewed by {args.reviewed_by}"
    )
    return 0


HANDCHECK_SAMPLE_SIZE = 60
HANDCHECK_QUESTIONS = (
    "is_photo",
    "could_hold_conclusions",
    "author",
)


def _stratified_sample(
    rows_by_category: Mapping[str, list[tuple[str, str, str]]], *, total: int, seed: int
) -> list[tuple[str, str, str]]:
    """An equal share of ``total`` from each category present, seeded (decision 0048 item 4).

    A flat random sample over twelve categories under-represents the rare ones: 60 of 2,655
    unique titles drawn flat would give about 5 per category on average but, by chance, could
    give none of the 11 unique ``party_submission`` titles. Every category present gets the
    same target share (the remainder, if any, going to the first categories in sorted order,
    so the total lands on ``total`` when every category has enough rows). A category with
    fewer rows than its share contributes all of it, and the shortfall is drawn from whatever
    categories still have rows spare, so the total stays close to ``total`` even then.
    """
    categories = sorted(rows_by_category)
    rng = random.Random(seed)  # noqa: S311 -- reproducible draw, not security
    share, extra = divmod(total, len(categories))
    target = {c: share + (1 if i < extra else 0) for i, c in enumerate(categories)}
    chosen: dict[str, list[tuple[str, str, str]]] = {}
    remaining: dict[str, list[tuple[str, str, str]]] = {}
    for category in categories:
        pool = sorted(rows_by_category[category])
        rng.shuffle(pool)
        take = min(target[category], len(pool))
        chosen[category] = pool[:take]
        remaining[category] = pool[take:]
    shortfall = total - sum(len(v) for v in chosen.values())
    for category in categories:
        if shortfall <= 0:
            break
        top_up = min(shortfall, len(remaining[category]))
        chosen[category].extend(remaining[category][:top_up])
        shortfall -= top_up
    return [row for category in categories for row in chosen[category]]


def _cmd_handcheck(args: argparse.Namespace, settings: Settings) -> int:
    """A stratified ~60-title sample, one row per title, for Andy's three-question hand-check.

    Decision 0048 item 4: each question grades exactly one of arm B's three uses of a
    document's category (the photograph exclusion, the deny-list, the provenance header), so
    the sheet asks those three questions rather than twelve-way agreement with the classifier.
    Stratified by category (correction A) so the rare and messy ones -- ``party_submission``
    at 11 unique titles, ``other`` at 408 -- are actually measured, not drowned out by a flat
    random draw. The dev-400 mkeys, via the same ``_cases`` helper ``_cmd_draw`` uses: a cached
    mkey outside this set is skipped rather than sampled, so the sheet is dev-400 by
    construction (never by relying on the cache holding nothing else).

    Every title is redacted before it is written (``title_vocab.redact_title``, the same
    membership test ``check_fixtures_redacted.title_looks_like_a_name`` applies): running that
    check over a real ~60-title draw flags genuine surnames of pilots, instructors and
    witnesses alongside harmless words, and the two cannot be told apart automatically, so the
    sheet has to redact everything the test flags rather than ship a sheet a human must clean
    up by hand before it can be committed. ``doc_type`` and ``category`` are left alone -- both
    are closed vocabularies, never free text a name could hide in.
    """
    cases = _cases(settings.data_dir / "processed", tuple(samples.sample_ids("dev-400")))
    allowed = {mkey for mkey, _event in cases.values()}
    rows_by_category: dict[str, set[tuple[str, str, str]]] = defaultdict(set)
    skipped = 0
    with DocketClient(settings.docket_dir, seconds_per_request=0.0) as client:
        for mkey_dir in sorted(settings.docket_dir.iterdir()):
            if not (mkey_dir / "listing.html").is_file():
                continue
            mkey = int(mkey_dir.name)
            if mkey not in allowed:
                skipped += 1
                continue
            listing = parse_listing(client.listing_html(mkey), mkey=mkey)
            for entry in listing.entries:
                category = document_category(entry.title)
                rows_by_category[category].add((entry.title, entry.doc_type, category))
    rows_by_category_sorted = {c: sorted(rows) for c, rows in rows_by_category.items()}
    sample = _stratified_sample(rows_by_category_sorted, total=HANDCHECK_SAMPLE_SIZE, seed=SEED)
    known, _dictionary_found = known_title_words()
    redacted_sample: list[tuple[str, str, str]] = []
    total_redactions = 0
    for title, doc_type, category in sample:
        redacted, count = redact_title(title, known)
        total_redactions += count
        redacted_sample.append((redacted, doc_type, category))
    with (FIXTURES / "title_handcheck.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["title", "doc_type", "category", *HANDCHECK_QUESTIONS, "notes"])
        writer.writerows((t, d, c, "", "", "", "") for t, d, c in redacted_sample)
    counts: dict[str, int] = defaultdict(int)
    for _title, _doc_type, category in sample:
        counts[category] += 1
    print(
        f"wrote {FIXTURES / 'title_handcheck.csv'}: {len(sample)} titles, "
        f"{total_redactions} words redacted"
    )
    for category in sorted(rows_by_category_sorted):
        available = len(rows_by_category_sorted[category])
        print(f"  {category}: {counts.get(category, 0)} (of {available} unique titles seen)")
    if skipped:
        print(f"skipped {skipped} cached dockets outside dev-400", file=sys.stderr)
    return 0


def main(argv: list[str]) -> int:
    """Dispatch one subcommand."""
    parser = argparse.ArgumentParser(prog="make_docket_fixture")
    commands = parser.add_subparsers(dest="command", required=True)
    listing_p = commands.add_parser("listing")
    listing_p.add_argument("case_id", nargs="?")
    listing_p.add_argument("--criterion", default=None)
    draw_p = commands.add_parser("draw", help="draw the fixture pool against the criteria")
    draw_p.add_argument(
        "--write", action="store_true", help="write the fixtures, not just the candidates"
    )
    document_p = commands.add_parser(
        "document", help="add one reviewed document to a drawn fixture"
    )
    document_p.add_argument("case_id")
    document_p.add_argument("index", type=int)
    document_p.add_argument("--reviewed-by", required=True, help='e.g. "Andy, 2026-09-21"')
    commands.add_parser("handcheck", help="write the ~60-title hand-check sheet")
    args = parser.parse_args(argv)
    settings = Settings()
    try:
        if args.command == "listing":
            return _cmd_listing(args, settings)
        if args.command == "draw":
            return _cmd_draw(args, settings)
        if args.command == "document":
            return _cmd_document(args, settings)
        if args.command == "handcheck":
            return _cmd_handcheck(args, settings)
    except FixtureError as error:
        print(f"{args.command}: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
