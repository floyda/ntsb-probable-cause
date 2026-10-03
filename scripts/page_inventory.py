"""The inventory: what the image-bearing pages show, in measured proportions (S2.6 §6).

Status
    One-shot (S2.6, Task 12). Five subcommands, run in order:
      sample -- draw the 330 pages from the page frame (seeded) and draw each to a private image
      probe  -- label one page, to confirm the model accepts the request (paid, under a cent)
      label  -- label all 330 with Gemini 3.1 Flash Lite at minimal reasoning (paid, ~$0.20)
      check  -- write Andy's page for a seeded 60 of the 330
      score  -- write docs/results/s26-inventory.txt: counts, Andy's check, the mixed-page
                cut-off and the stop rule (spec §6.4)
    Everything but the results file lives under data/s26/inventory/ and is never committed.
    The labeller writes categories only, never words or descriptions (spec §6.2 item 3).
"""

import argparse
import hashlib
import html
import json
import random
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

import httpx

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.render import RESOLUTION, render_pages
from ntsb_probable_cause.docket.transcribe import (
    LABEL,
    PAGE_LABELS,
    PageJob,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
)
from ntsb_probable_cause.errors import ConfigurationError, DocketError
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.preparation import run_preparation
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts.marking_page import Card, Choice

SEED = 20260924
CHECK_SEED = 20260925
CHECK_SIZE = 60
MODEL = "google/gemini-3.1-flash-lite"
# Conservative: the reservation is sized from this, the spend rows record the real cost.
EXPECTED_COST_PER_PAGE_USD = 0.002
ALLOCATION: dict[tuple[str, bool], int] = {
    ("image only", True): 68,
    ("image only", False): 67,
    ("text and image", True): 68,
    ("text and image", False): 67,
    ("text only", True): 15,
    ("text only", False): 15,
    # Decision W2 (Andy, 2026-09-24): the photo-only documents S2 never fetched, as their own
    # stratum, so an ordinary scan and a wreckage photograph are never drawn from one pool.
    ("photo-only", True): 15,
    ("photo-only", False): 15,
}
IMAGE_BEARING = ("image only", "text and image", "photo-only")
# Whether a page's images hold words (decision W6): on an image-only page typed text counts,
# because nothing else holds it; on a text-and-image page it does not, because the text
# layer already holds it. Looked up by a page's own kind (never by its stratum): a photo-only
# page is judged exactly like an ordinary page of the same kind (decision A, fix round 2).
_IMAGE_ONLY_WORDS = frozenset({"typed text", "handwriting", "filled form", "mixed"})
WORDS = {
    "image only": _IMAGE_ONLY_WORDS,
    "text and image": frozenset({"handwriting", "filled form", "mixed"}),
}
# The frame kinds a photo-only page must have to enter the photo-only stratum at all (decision
# A, fix round 2): S2's page-kinds scan read every photo-only page's own kind, and 508 of 831
# have a text layer (docs/results/s26-page-kinds.txt) -- a photo-only page that is text-only
# or blank is neither image-bearing nor an ordinary page of that kind (S2's own scan never
# reads a photo-only document), so it takes no part in either pool or population.
_PHOTO_ONLY_IMAGE_BEARING_KINDS = ("image only", "text and image")
STOP_SHARE = 0.10
CUTS = (0.02, 0.05, 0.10, 0.20)
MAX_WORDS_BELOW_CUT = 1 / 20
FOLDER = Path("s26") / "inventory"


def sample_kind(row: Mapping[str, object]) -> str | None:
    """The page's kind for sampling (decision W2, amended by decision A, fix round 2).

    A photo-only page is its own stratum only when its own kind is image-bearing; a
    text-only or blank photo-only page takes no part in either pool, so it maps to no kind
    at all (``None`` never equals an allocation's kind string).
    """
    if row.get("photo_only"):
        kind = str(row["kind"])
        return "photo-only" if kind in _PHOTO_ONLY_IMAGE_BEARING_KINDS else None
    return str(row["kind"])


def _stratum(kind: object, fatal: object) -> str:
    return f"{kind}/{'fatal' if fatal else 'non-fatal'}"


def draw_sample(
    frame: Sequence[Mapping[str, object]],
    *,
    allocation: Mapping[tuple[str, bool], int] = ALLOCATION,
    seed: int = SEED,
) -> list[dict[str, object]]:
    """The seeded, stratified sample, numbered 1..n in stratum order."""
    rng = random.Random(seed)  # noqa: S311 -- sampling, not security
    sample: list[dict[str, object]] = []
    for (kind, fatal), size in allocation.items():
        pool = sorted(
            (r for r in frame if sample_kind(r) == kind and r["fatal"] == fatal),
            key=lambda r: (str(r["case_id"]), int(str(r["document"])), int(str(r["page"]))),
        )
        for row in rng.sample(pool, min(size, len(pool))):
            sample.append({**row, "stratum": _stratum(kind, fatal)})
    for number, row in enumerate(sample, start=1):
        row["n"] = number
    return sample


def weighted_word_share(
    labels: Mapping[str, Sequence[tuple[str, str]]],
    population: Mapping[str, int],
    *,
    counted: Mapping[str, frozenset[str]] = WORDS,
) -> float:
    """Of all image-bearing pages, the share whose label is ``counted`` for its OWN kind.

    Each entry pairs a page's own frame kind with its final label -- not the stratum it was
    drawn into (decision A, fix round 2): the photo-only stratum can mix image-only and
    text-and-image pages, and each is judged by its own kind's word set, exactly like an
    ordinary page of that kind. A stratum with no entry of a counted kind (a text-only
    control stratum) takes no part in the weighted estimate, as before. Weighted by each
    stratum's population in the frame. By default it counts pages whose images hold words
    (decision W6); the transcriber test's estimate passes the picture labels instead, to
    size the v3 probe.
    """
    total = 0.0
    hits = 0.0
    for stratum, entries in labels.items():
        countable = [(kind, label) for kind, label in entries if kind in counted]
        if not countable:
            continue
        share = sum(1 for kind, label in countable if label in counted[kind]) / len(countable)
        hits += population[stratum] * share
        total += population[stratum]
    return hits / total if total else 0.0


def cut_evidence(rows: Sequence[tuple[float, str]]) -> list[tuple[float, int, int, bool]]:
    """For each candidate cut: pages below it, how many of those hold words, admissible or not.

    Decision W3, made measurable (fix round 1, I4): a reader can check the chosen cut from
    this table rather than trust the committed constant alone. A cut with no sampled pages
    below it carries no evidence for it (fix round 1, M2), so it is inadmissible rather than
    vacuously true -- a correction to the plan's rule that can only make the chosen cut
    smaller, never larger, so it cannot admit a page W3 would otherwise have excluded.
    """
    evidence: list[tuple[float, int, int, bool]] = []
    for cut in CUTS:
        below = [label for share, label in rows if share < cut]
        held = sum(1 for label in below if label in WORDS["text and image"])
        admissible = bool(below) and held / len(below) <= MAX_WORDS_BELOW_CUT
        evidence.append((cut, held, len(below), admissible))
    return evidence


def mixed_cut(rows: Sequence[tuple[float, str]]) -> float:
    """The largest run of admissible cuts of image-area share (decision W3)."""
    chosen = 0.0
    for cut, _held, _total, admissible in cut_evidence(rows):
        if not admissible:
            break
        chosen = cut
    return chosen


def stop_outcome(share: float) -> str:
    """Spec §6.4 with decision W6's number.

    Printed to three decimal places (fix round 3, N2, correcting fix round 1's M4): two
    decimals could still round a share just under the threshold up to "10.00%" while the
    text beside it says "under 10%" (0.09999 does exactly that at two decimals). The
    decision itself always compares the unrounded value, never the printed one.
    """
    if share < STOP_SHARE:
        return (
            f"stop: {share:.3%} of image-bearing pages hold words in their images, under "
            f"{STOP_SHARE:.0%}; transcription is not worth its cost (spec §6.4)"
        )
    return f"go on: {share:.3%} of image-bearing pages hold words in their images"


# --- the subcommands (plumbing; the rules above are what the tests pin) ---


def _offline() -> httpx.BaseTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: the inventory reads the docket cache only")

    return httpx.MockTransport(refuse)


def _documents(settings: Settings) -> CachedDocuments:
    """The cache-only reader every subcommand shares.

    ``max_attempts=1`` (fix round 1, M1): the default client retries a failed request five
    times with growing backoff, so a cache miss against this offline transport used to sleep
    about 30 seconds before raising -- with the ``CachedDocuments`` lock held the whole time
    for a listing miss. One attempt makes a miss loud and free, as it is meant to be.
    """
    client = DocketClient(settings.docket_dir, transport=_offline(), max_attempts=1)
    return CachedDocuments(client)


def _read_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _key(row: Mapping[str, object]) -> TranscriptionKey:
    return TranscriptionKey(
        document_sha256=str(row["document_sha256"]),
        page=int(str(row["page"])),
        model=MODEL,
        instruction=LABEL.version,
        dpi=RESOLUTION,
    )


class _Loader(Protocol):
    """What ``_jobs``/``cmd_probe`` need: just the page loader, so a test can fake it."""

    def loader(self, mkey: int, index: int) -> Callable[[], bytes]: ...


class _DocumentSource(Protocol):
    """What ``_draw_pages`` needs: just the one document call, so a test can fake it."""

    def document(self, mkey: int, index: int) -> bytes: ...


def _jobs(rows: Sequence[Mapping[str, object]], documents: _Loader) -> list[PageJob]:
    return [
        PageJob(_key(r), documents.loader(int(str(r["mkey"])), int(str(r["document"]))), False)
        for r in rows
    ]


def _draw_pages(
    sample: Sequence[dict[str, object]], documents: _DocumentSource, folder: Path
) -> int:
    """Render each sampled page to a private JPEG; return how many failed to render.

    A page that fails -- fetching its document or rendering it -- is recorded failed (no
    ``document_sha256`` or ``image_area_share``, and its ``render_error``) rather than
    aborting the whole draw (fix round 1, M7): render.py notes that a real dev-400 page can
    fail to load in PDFium, and with a fixed seed there would otherwise be no way past it.
    """
    failed = 0
    for row in sample:
        try:
            data = documents.document(int(str(row["mkey"])), int(str(row["document"])))
            (page,) = render_pages(data, [int(str(row["page"]))])
        except DocketError as error:
            row["document_sha256"] = None
            row["image_area_share"] = None
            row["render_error"] = str(error)
            failed += 1
            continue
        (folder / "pages" / f"{row['n']}.jpg").write_bytes(page.data)
        row["document_sha256"] = hashlib.sha256(data).hexdigest()
        row["image_area_share"] = page.image_area_share
    return failed


def cmd_sample(settings: Settings, documents: _DocumentSource) -> str:
    """Draw the sample; draw each page to a private JPEG; record hashes and image share."""
    folder = settings.data_dir / FOLDER
    (folder / "pages").mkdir(parents=True, exist_ok=True)
    frame = _read_jsonl(settings.data_dir / "s26" / "pages-dev-400.jsonl")
    sample = draw_sample(frame)
    failed = _draw_pages(sample, documents, folder)
    (folder / "sample.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sample))
    population = Counter(
        _stratum(kind, r["fatal"]) for r in frame if (kind := sample_kind(r)) is not None
    )
    (folder / "population.json").write_text(json.dumps(population))
    note = f", {failed} failed to render" if failed else ""
    return f"{len(sample)} pages drawn to {folder}{note}"


def cmd_probe(
    settings: Settings,
    documents: _Loader,
    sample: Sequence[Mapping[str, object]],
    *,
    client_factory: Callable[[ExitStack], Callable[[], ModelClient]] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> tuple[str, bool]:
    """Label one page through ``run_preparation`` (fix round 1, I3).

    So its reservation and spend row are real and the page's cache entry is real: ``label``
    then reuses it rather than paying for it a second time. If the page is already cached
    (a re-run of the probe), no call is made and that reading is reported instead. ``now``
    exists so a test can run the probe twice without the second call refusing to share the
    first's job folder (fix round 3, M9): two real probes are never a second apart.
    """
    job = _jobs(sample[:1], documents)[0]
    done = run_preparation(
        kind="inventory",
        jobs=[job],
        instruction=LABEL,
        settings=settings,
        commit=commit_state(),
        expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD,
        workers=1,
        client_factory=client_factory,
        now=now,
    )
    note = ""
    record: Transcription | None
    if done:
        record = done[0]
    else:
        note = "already cached: "
        record = TranscriptionCache(settings.transcription_dir).get(job.key)
    if record is None:
        return "probe: no record (unexpected)", False
    text = (
        f"probe: {note}{record.status}, kind {record.page_kind}, error {record.error}, "
        f"{record.prompt_tokens}+{record.completion_tokens} tokens, ${record.cost_usd:.5f}"
    )
    return text, record.status == "transcribed"


def cmd_check(settings: Settings) -> str:
    """Andy's page: a seeded 60, each image beside its label."""
    folder = settings.data_dir / FOLDER
    sample = _read_jsonl(folder / "sample.jsonl")
    cache = TranscriptionCache(settings.transcription_dir)
    rng = random.Random(CHECK_SEED)  # noqa: S311 -- sampling, not security
    chosen = sorted(rng.sample(sample, CHECK_SIZE), key=lambda r: int(str(r["n"])))
    cards = []
    for row in chosen:
        record = cache.get(_key(row))
        label = record.page_kind if record is not None else "(no label)"
        cards.append(
            Card(
                row=int(str(row["n"])),
                body_html=(
                    f'<p class="meta">Page {row["n"]} · the model says: '
                    f"<b>{html.escape(str(label))}</b></p>"
                    f'<img src="pages/{row["n"]}.jpg" alt="page {row["n"]}">'
                ),
                choices=(
                    Choice("label", ("right", "wrong")),
                    Choice("correct label", PAGE_LABELS, required=False),
                ),
            )
        )
    intro = (
        "<p>Each card shows one docket page and the kind of page the model says it is. Mark the "
        "label right or wrong; when wrong, pick the right kind. The kinds: "
        + ", ".join(PAGE_LABELS)
        + ".</p>"
    )
    (folder / "check.html").write_text(
        marking_page.render(
            title="Inventory check (S2.6 spec §6.2)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-inventory-check",
            csv_name="inventory-check-marks.csv",
        )
    )
    return f"page at {folder / 'check.html'}"


def _undrawable(row: Mapping[str, object]) -> bool:
    """Whether a sampled page failed to render (fix round 1, M7; fix round 3, N1).

    Such a row has no ``document_sha256`` and no ``image_area_share`` -- it was never sent
    to the labeller and never drawn to an image, so it takes no part in a job, a cut-off row
    or a stratum's word share, however it may have been marked.
    """
    return row.get("document_sha256") is None


def final_labels(
    labels: Mapping[int, str], marks: Mapping[int, Mapping[str, str]]
) -> dict[int, str]:
    """The model's labels, with Andy's where he marked one wrong and gave the right kind."""
    final = dict(labels)
    for n, fields in marks.items():
        if fields.get("label") == "wrong" and fields.get("correct label"):
            final[n] = fields["correct label"]
    return final


def _check_marks(marks: Mapping[int, Mapping[str, str]]) -> None:
    """Refuse a 'wrong' mark with no correction (fix round 1, M3).

    The brief: "where Andy checked a page, his label is the one used" -- a 'wrong' mark with
    an empty correct label would otherwise silently keep the model's label, which is not what
    marking a page wrong means.
    """
    bad = sorted(
        n
        for n, fields in marks.items()
        if fields.get("label") == "wrong" and not fields.get("correct label")
    )
    if bad:
        pages = ", ".join(str(n) for n in bad)
        raise ConfigurationError(f"marked wrong with no correct label: page(s) {pages}")


def score_text(
    sample: Sequence[Mapping[str, object]],
    labels: Mapping[int, str],
    marks: Mapping[int, Mapping[str, str]],
    population: Mapping[str, int],
    cost_usd: float,
) -> str:
    """The results file: counts, and the evidence behind the cut-off and the stop rule."""
    _check_marks(marks)
    final = final_labels(labels, marks)
    # A page that failed to render (fix round 1, M7) has no image and no image-area share;
    # fix round 3, N1: it is left out of every count below, however Andy may have marked it
    # (a row's own render outcome, not the labeller's, decides whether it is used), so
    # `score_text` never has to parse its own placeholder as a number.
    drawable = [r for r in sample if not _undrawable(r)]
    not_drawable = len(sample) - len(drawable)
    agree = checked = 0
    confusion: Counter[tuple[str, str]] = Counter()
    for n, fields in marks.items():
        if fields.get("label") not in ("right", "wrong"):
            continue
        checked += 1
        if fields["label"] == "right":
            agree += 1
        elif fields.get("correct label"):
            confusion[(labels.get(n, "?"), fields["correct label"])] += 1
    # Each entry pairs a page's own frame kind with its final label (decision A, fix round
    # 2), so the photo-only stratum -- which can mix image-only and text-and-image pages --
    # is judged page by page rather than by one word set for the whole stratum.
    by_stratum: dict[str, list[tuple[str, str]]] = {}
    for row in drawable:
        n = int(str(row["n"]))
        if n in final:
            by_stratum.setdefault(str(row["stratum"]), []).append((str(row["kind"]), final[n]))
    share = weighted_word_share(by_stratum, population)
    mixed_rows = [
        (float(str(r["image_area_share"])), final[int(str(r["n"]))])
        for r in drawable
        if str(r["stratum"]).startswith("text and image") and int(str(r["n"])) in final
    ]
    evidence = cut_evidence(mixed_rows)
    cut = mixed_cut(mixed_rows)
    low, high = wilson(agree, checked)
    # The same total the weighted estimate divides by (fix round 1, M6; per-page kind, fix
    # round 2): only strata with at least one entry of a counted (image-bearing) kind
    # contribute, matching weighted_word_share's own rule.
    weighted_total = (
        sum(
            population.get(s, 0)
            for s, entries in by_stratum.items()
            if any(kind in WORDS for kind, _label in entries)
        )
        or 1
    )
    lines = [
        "# the inventory: what image-bearing pages show (S2.6 spec §6) -- counts only",
        f"sample: {len(sample)} pages from the dev-400 page frame, seed {SEED}; labeller "
        f"{MODEL} at minimal reasoning, instruction {LABEL.version}; labelled "
        f"{len(labels)}; not drawable: {not_drawable}; cost ${cost_usd:.4f}",
        "",
        "## labels by stratum (Andy's label where he checked the page; its own word share and "
        "population weight beside the weighted estimate, M6)",
    ]
    for stratum, entries in sorted(by_stratum.items()):
        counts = Counter(label for _kind, label in entries)
        # Each entry judged by its own kind (decision A): a mixed photo-only stratum has no
        # single kind to look up, but every entry that has a countable kind is used exactly
        # as an ordinary page of that kind would be.
        countable = [(kind, label) for kind, label in entries if kind in WORDS]
        if countable:
            stratum_share = sum(1 for kind, label in countable if label in WORDS[kind]) / len(
                countable
            )
            weight = population.get(stratum, 0) / weighted_total
            detail = f", {stratum_share:.1%} hold words, {weight:.1%} of the weighted estimate"
        else:
            detail = " -- a control stratum, not counted in the weighted estimate"
        lines.append(
            f"  {stratum} (population {population.get(stratum, 0)}{detail}): "
            + ", ".join(f"{label} {counts[label]}" for label in PAGE_LABELS if counts[label])
        )
    lines += [
        "",
        "## Andy's check",
        f"  {agree} of {checked} labels right ({agree / checked if checked else 0:.1%} "
        f"[{low:.1%}, {high:.1%}], Wilson 95%)",
        *(f"  labelled {a}, Andy says {b}: {k}" for (a, b), k in sorted(confusion.items())),
        "",
        "## the mixed-page cut-off (decision W3)",
        f"  {len(mixed_rows)} sampled text-and-image pages; at most 1 in "
        f"{round(1 / MAX_WORDS_BELOW_CUT)} below a cut may hold words:",
        *(
            f"    {cut_value:.0%}: {held} of {total} below the cut hold words "
            f"({'admissible' if admissible else 'not admissible'})"
            for cut_value, held, total, admissible in evidence
        ),
        (
            "  no cut: every text-and-image page is sent"
            if cut == 0.0
            else f"  cut: text-and-image pages whose images cover under {cut:.0%} of the page "
            f"are not sent"
        ),
        "",
        "## the stop rule (spec §6.4, decision W6)",
        f"  weighted over all image-bearing dev-400 pages: {stop_outcome(share)}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="page_inventory")
    parser.add_argument("command", choices=("sample", "probe", "label", "check", "score"))
    parser.add_argument("--marks", type=Path)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--workers", type=int, default=4)
    parser.add_argument("--retry-failed", action="store_true")
    args = parser.parse_args(argv)
    settings = Settings()
    documents = _documents(settings)
    folder = settings.data_dir / FOLDER
    if args.command == "sample":
        print(cmd_sample(settings, documents))
        return 0
    if args.command == "check":
        print(cmd_check(settings))
        return 0
    sample = _read_jsonl(folder / "sample.jsonl")
    if args.command == "probe":
        text, ok = cmd_probe(settings, documents, sample)
        print(text)
        return 0 if ok else 1
    if args.command == "label":
        # A page that failed to render (M7) is never sent to the labeller (fix round 3, N1):
        # `label`'s exit code then reflects only real labelling failures, not the sample's
        # own undrawable count, so one undrawable page never stops `make s26-inventory`
        # before `check` runs.
        drawable = [r for r in sample if not _undrawable(r)]
        not_drawable = len(sample) - len(drawable)
        done = run_preparation(
            kind="inventory",
            jobs=_jobs(drawable, documents),
            instruction=LABEL,
            settings=settings,
            commit=commit_state(),
            workers=args.workers,
            retry_failed=args.retry_failed,
            expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD,
        )
        failed = sum(1 for r in done if r.status == "failed")
        print(
            f"labelled {len(done)} pages, {failed} failed, not drawable: {not_drawable}, "
            f"${sum(r.cost_usd for r in done):.4f}"
        )
        return 1 if failed else 0
    cache = TranscriptionCache(settings.transcription_dir)
    records = {int(str(r["n"])): cache.get(_key(r)) for r in sample if not _undrawable(r)}
    labels = {n: rec.page_kind for n, rec in records.items() if rec and rec.page_kind}
    cost = sum(rec.cost_usd for rec in records.values() if rec)
    population = json.loads((folder / "population.json").read_text())
    marks = marking_page.read_marks(args.marks) if args.marks else {}
    text = score_text(sample, labels, marks, population, cost)
    # Private: the transcriber test (Task 13) draws its handwriting and photo pages from these.
    (folder / "labels.json").write_text(json.dumps(final_labels(labels, marks)))
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
