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
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import httpx

from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.render import RESOLUTION, render_pages
from ntsb_probable_cause.docket.transcribe import (
    LABEL,
    PAGE_LABELS,
    PageJob,
    TranscriptionCache,
    TranscriptionKey,
    read_page,
)
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.preparation import openrouter_clients, run_preparation
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
# layer already holds it. A photo-only page has no text layer, like an image-only one.
_IMAGE_ONLY_WORDS = frozenset({"typed text", "handwriting", "filled form", "mixed"})
WORDS = {
    "image only": _IMAGE_ONLY_WORDS,
    "text and image": frozenset({"handwriting", "filled form", "mixed"}),
    "photo-only": _IMAGE_ONLY_WORDS,
}
STOP_SHARE = 0.10
CUTS = (0.02, 0.05, 0.10, 0.20)
MAX_WORDS_BELOW_CUT = 1 / 20
FOLDER = Path("s26") / "inventory"


def sample_kind(row: Mapping[str, object]) -> str:
    """The page's kind for sampling: a page of a photo-only document is its own kind (W2)."""
    return "photo-only" if row.get("photo_only") else str(row["kind"])


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
    labels: Mapping[str, Sequence[str]],
    population: Mapping[str, int],
    *,
    counted: Mapping[str, frozenset[str]] = WORDS,
) -> float:
    """Of all image-bearing pages, the share whose label is ``counted`` for its kind.

    Weighted by each stratum's population in the frame. By default it counts pages whose
    images hold words (decision W6); the transcriber test's estimate passes the picture
    labels instead, to size the v3 probe.
    """
    total = 0.0
    hits = 0.0
    for stratum, stratum_labels in labels.items():
        kind = stratum.split("/")[0]
        if kind not in counted or not stratum_labels:
            continue
        share = sum(1 for label in stratum_labels if label in counted[kind]) / len(stratum_labels)
        hits += population[stratum] * share
        total += population[stratum]
    return hits / total if total else 0.0


def mixed_cut(rows: Sequence[tuple[float, str]]) -> float:
    """The largest run of admissible cuts of image-area share (decision W3)."""
    chosen = 0.0
    for cut in CUTS:
        below = [label for share, label in rows if share < cut]
        held = sum(1 for label in below if label in WORDS["text and image"])
        if below and held / len(below) > MAX_WORDS_BELOW_CUT:
            break
        chosen = cut
    return chosen


def stop_outcome(share: float) -> str:
    """Spec §6.4 with decision W6's number."""
    if share < STOP_SHARE:
        return (
            f"stop: {share:.1%} of image-bearing pages hold words in their images, under "
            f"{STOP_SHARE:.0%}; transcription is not worth its cost (spec §6.4)"
        )
    return f"go on: {share:.1%} of image-bearing pages hold words in their images"


# --- the subcommands (plumbing; the rules above are what the tests pin) ---


def _offline() -> httpx.BaseTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: the inventory reads the docket cache only")

    return httpx.MockTransport(refuse)


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


def _jobs(rows: Sequence[Mapping[str, object]], documents: CachedDocuments) -> list[PageJob]:
    return [
        PageJob(_key(r), documents.loader(int(str(r["mkey"])), int(str(r["document"]))), False)
        for r in rows
    ]


def cmd_sample(settings: Settings, documents: CachedDocuments) -> str:
    """Draw the sample; draw each page to a private JPEG; record hashes and image share."""
    folder = settings.data_dir / FOLDER
    (folder / "pages").mkdir(parents=True, exist_ok=True)
    frame = _read_jsonl(settings.data_dir / "s26" / "pages-dev-400.jsonl")
    sample = draw_sample(frame)
    for row in sample:
        data = documents.document(int(str(row["mkey"])), int(str(row["document"])))
        (page,) = render_pages(data, [int(str(row["page"]))])
        (folder / "pages" / f"{row['n']}.jpg").write_bytes(page.data)
        row["document_sha256"] = hashlib.sha256(data).hexdigest()
        row["image_area_share"] = page.image_area_share
    (folder / "sample.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sample))
    population = Counter(_stratum(sample_kind(r), r["fatal"]) for r in frame)
    (folder / "population.json").write_text(json.dumps(population))
    return f"{len(sample)} pages drawn to {folder}"


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


def final_labels(
    labels: Mapping[int, str], marks: Mapping[int, Mapping[str, str]]
) -> dict[int, str]:
    """The model's labels, with Andy's where he marked one wrong and gave the right kind."""
    final = dict(labels)
    for n, fields in marks.items():
        if fields.get("label") == "wrong" and fields.get("correct label"):
            final[n] = fields["correct label"]
    return final


def score_text(
    sample: Sequence[Mapping[str, object]],
    labels: Mapping[int, str],
    marks: Mapping[int, Mapping[str, str]],
    population: Mapping[str, int],
    cost_usd: float,
) -> str:
    """The results file: counts only."""
    final = final_labels(labels, marks)
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
    by_stratum: dict[str, list[str]] = {}
    for row in sample:
        n = int(str(row["n"]))
        if n in final:
            by_stratum.setdefault(str(row["stratum"]), []).append(final[n])
    share = weighted_word_share(by_stratum, population)
    mixed_rows = [
        (float(str(r["image_area_share"])), final[int(str(r["n"]))])
        for r in sample
        if str(r["stratum"]).startswith("text and image") and int(str(r["n"])) in final
    ]
    cut = mixed_cut(mixed_rows)
    low, high = wilson(agree, checked)
    lines = [
        "# the inventory: what image-bearing pages show (S2.6 spec §6) -- counts only",
        f"sample: {len(sample)} pages from the dev-400 page frame, seed {SEED}; labeller "
        f"{MODEL} at minimal reasoning, instruction {LABEL.version}; labelled "
        f"{len(labels)}; cost ${cost_usd:.4f}",
        "",
        "## labels by stratum (Andy's label where he checked the page)",
    ]
    for stratum, stratum_labels in sorted(by_stratum.items()):
        counts = Counter(stratum_labels)
        lines.append(
            f"  {stratum} (population {population.get(stratum, 0)}): "
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
        f"  cut: text-and-image pages whose images cover under {cut:.0%} of the page are not "
        f"sent (from {len(mixed_rows)} sampled text-and-image pages; candidates "
        + ", ".join(f"{c:.0%}" for c in CUTS)
        + f"; at most 1 in {round(1 / MAX_WORDS_BELOW_CUT)} below the cut may hold words)",
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
    args = parser.parse_args(argv)
    settings = Settings()
    documents = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline()))
    folder = settings.data_dir / FOLDER
    if args.command == "sample":
        print(cmd_sample(settings, documents))
        return 0
    if args.command == "check":
        print(cmd_check(settings))
        return 0
    sample = _read_jsonl(folder / "sample.jsonl")
    if args.command == "probe":
        with ExitStack() as stack:
            client = openrouter_clients(settings)(stack)()
            record = read_page(
                _jobs(sample[:1], documents)[0], client, LABEL, now=lambda: datetime.now(UTC)
            )
        print(
            f"probe: {record.status}, kind {record.page_kind}, error {record.error}, "
            f"{record.prompt_tokens}+{record.completion_tokens} tokens, ${record.cost_usd:.5f}"
        )
        return 0 if record.status == "transcribed" else 1
    if args.command == "label":
        done = run_preparation(
            kind="inventory",
            jobs=_jobs(sample, documents),
            instruction=LABEL,
            settings=settings,
            commit=commit_state(),
            workers=args.workers,
            expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD,
        )
        failed = sum(1 for r in done if r.status == "failed")
        print(f"labelled {len(done)} pages, {failed} failed, ${sum(r.cost_usd for r in done):.4f}")
        return 0
    cache = TranscriptionCache(settings.transcription_dir)
    records = {int(str(r["n"])): cache.get(_key(r)) for r in sample}
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
