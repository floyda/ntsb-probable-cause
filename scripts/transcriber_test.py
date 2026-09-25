"""The transcriber test: three answer keys, four candidates, a rule fixed in advance (0080).

Status
    One-shot (S2.6, Task 13). Subcommands, in order:
      keys        -- draw the typed, handwriting and photograph pages (paid: cents, for top-ups)
      probe       -- one invented page per candidate; records each reply as a test fixture
      run         -- all four candidates on every key page at 150 dpi (paid, ~$4-8)
      handwriting -- write Andy's handwriting-key page
      photos      -- write Andy's invented-words page
      mixed       -- write Andy's full-page-scan invented-words page (decision W7)
      resolution  -- the chosen model at 200 dpi on the handwriting and typed keys (paid)
      score       -- apply the rule; write docs/results/s26-transcriber-test.txt
      estimate    -- the stage's re-estimated cost (decision 0083 item 2's pause point)
    Keys, page images, Andy's sheets and every transcription live under data/ and are never
    committed; the results file holds counts only. The recorded probe replies are of an
    invented page and hold no docket text.
"""

import argparse
import hashlib
import html
import io
import json
import operator
import random
import re
import statistics
from collections import Counter
from collections.abc import Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from functools import reduce
from pathlib import Path
from typing import cast

import httpx
from PIL import Image, ImageDraw, ImageFont

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.classify import BORN_DIGITAL_MIN_CHARS_PER_PAGE, document_category
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.docket.documents import CachedDocuments
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.render import RESOLUTION, render_pages
from ntsb_probable_cause.docket.transcribe import (
    LABEL,
    MIXED_PAGE_MIN_IMAGE_SHARE,
    TRANSCRIBE,
    PageJob,
    TranscriptionCache,
    TranscriptionKey,
    parse_reply,
    request_for,
    settings_for,
)
from ntsb_probable_cause.errors import ModelError, SchemaError
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.model.client import cost_usd
from ntsb_probable_cause.scoring.budget import SPEND_FILE, SpendRecord, write_spend
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.preparation import openrouter_clients, run_preparation
from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts import page_inventory as inventory
from scripts.marking_page import Card, Choice

# The rule (spec §7.4, decision 0080), fixed before the test runs.
GATE_INVENTED_LINES_PER_100 = 2.0
GATE_INVENTED_PHOTO_SHARE = 1 / 20
GATE_INVENTED_MIXED_SHARE = 1 / 20  # decision W7: the photographs' bar
HANDWRITING_MARGIN = 0.05
TYPED_MARGIN_PER_100 = 1.0
RESOLUTION_MARGIN = 0.05
SPOT_CHECK_EVERY = 10

_WORD = re.compile(r"[A-Za-z0-9]{2,}")
_ILLEGIBLE_WORD = "illegible"


def lines_of(text: str) -> list[str]:
    """Non-empty lines with whitespace collapsed: the unit of the handwriting key."""
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def line_hits(key: Sequence[str], version: Sequence[str]) -> int:
    """Key lines the version holds exactly, each version line used at most once."""
    return sum((Counter(key) & Counter(version)).values())


def inventing_lines(key_text: str, version: Sequence[str]) -> int:
    """Version lines holding a word found nowhere in the page's key (the invented-text gate).

    A word where the key has ``[illegible]`` counts: that is the guess 0079 forbids.
    """
    known = {word.lower() for word in _WORD.findall(key_text)}
    return sum(
        1
        for line in version
        if any(
            word.lower() not in known and word.lower() != _ILLEGIBLE_WORD
            for word in _WORD.findall(line)
        )
    )


def typed_errors(key: str, version: str) -> tuple[int, int]:
    """(character errors, key characters), whitespace collapsed on both sides."""
    a, b = " ".join(key.split()), " ".join(version.split())
    matcher = SequenceMatcher(None, a, b, autojunk=False)
    matched = sum(block.size for block in matcher.get_matching_blocks())
    return max(len(a), len(b)) - matched, len(a)


def draft_letter(versions: Mapping[str, Sequence[str]]) -> str:
    """The version whose lines the other three share most: the draft Andy edits."""
    return max(
        sorted(versions),
        key=lambda v: sum(line_hits(versions[v], versions[o]) for o in versions if o != v),
    )


def agreed_lines(versions: Mapping[str, Sequence[str]], *, order: Sequence[str]) -> list[str]:
    """Lines every version holds, in the draft's order."""
    common = reduce(operator.and_, (Counter(v) for v in versions.values()))
    agreed: list[str] = []
    for line in order:
        if common[line] > 0:
            agreed.append(line)
            common[line] -= 1
    return agreed


@dataclass(frozen=True)
class CandidateResult:
    """One candidate's counts over the three keys, and its measured cost per test page."""

    model: str
    cost_per_page: float
    hw_lines: int
    hw_right: int
    hw_inventing: int
    photo_pages: int
    photo_invented: int
    typed_chars: int
    typed_errors: int
    mixed_pages: int = 0
    mixed_invented: int = 0

    @property
    def hw_accuracy(self) -> float:
        """Share of handwriting key lines reproduced exactly."""
        return self.hw_right / self.hw_lines if self.hw_lines else 0.0

    @property
    def invented_per_100_lines(self) -> float:
        """Inventing lines per 100 handwriting key lines."""
        return 100 * self.hw_inventing / self.hw_lines if self.hw_lines else 0.0

    @property
    def photo_invented_share(self) -> float:
        """Share of no-word photograph pages with an invented word."""
        return self.photo_invented / self.photo_pages if self.photo_pages else 0.0

    @property
    def mixed_invented_share(self) -> float:
        """Share of full-page scans whose added words hold an invented word (decision W7)."""
        return self.mixed_invented / self.mixed_pages if self.mixed_pages else 0.0

    @property
    def typed_errors_per_100(self) -> float:
        """Character errors per 100 characters of typed key."""
        return 100 * self.typed_errors / self.typed_chars if self.typed_chars else 0.0


def choose(results: Sequence[CandidateResult]) -> tuple[str | None, list[str]]:
    """Spec §7.4: the gate, then the cheapest within both margins of the best. Notes say why."""
    notes: list[str] = []
    passed: list[CandidateResult] = []
    for r in results:
        if r.invented_per_100_lines > GATE_INVENTED_LINES_PER_100:
            notes.append(
                f"{r.model}: out -- {r.invented_per_100_lines:.1f} inventing lines per 100 "
                f"handwriting lines (gate {GATE_INVENTED_LINES_PER_100:.0f})"
            )
        elif r.photo_invented_share > GATE_INVENTED_PHOTO_SHARE:
            notes.append(
                f"{r.model}: out -- invented words on {r.photo_invented} of {r.photo_pages} "
                "no-word photograph pages (gate 1 in 20)"
            )
        elif r.mixed_invented_share > GATE_INVENTED_MIXED_SHARE:
            notes.append(
                f"{r.model}: out -- invented added words on {r.mixed_invented} of "
                f"{r.mixed_pages} full-page scans (gate 1 in 20)"
            )
        else:
            passed.append(r)
    if not passed:
        notes.append("no candidate passed the gate: transcription stops (spec §7.4 item 3)")
        return None, notes
    best_hw = max(r.hw_accuracy for r in passed)
    best_typed = min(r.typed_errors_per_100 for r in passed)
    eligible = [
        r
        for r in passed
        if r.hw_accuracy >= best_hw - HANDWRITING_MARGIN
        and r.typed_errors_per_100 <= best_typed + TYPED_MARGIN_PER_100
    ]
    for r in passed:
        if r not in eligible:
            notes.append(f"{r.model}: passed the gate, outside a margin of the best")
    chosen = min(eligible, key=lambda r: r.cost_per_page)
    notes.append(f"{chosen.model}: chosen -- the cheapest within both margins")
    return chosen.model, notes


def choose_resolution(accuracy_150: float, accuracy_200: float) -> int:
    """Spec §7.5: 200 dpi only for more than 5 points of handwriting accuracy."""
    return 200 if accuracy_200 - accuracy_150 > RESOLUTION_MARGIN else 150


CANDIDATES = (
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.6-flash",
    "qwen/qwen3.5-122b-a10b",
    "openai/gpt-6-luna",
)
LETTERS = ("A", "B", "C", "D")
# Conservative per-page reservations; the spend rows record what was really spent.
EXPECTED_COST_PER_PAGE_USD = {
    "google/gemini-3.1-flash-lite": 0.003,
    "google/gemini-3.6-flash": 0.008,
    "qwen/qwen3.5-122b-a10b": 0.006,
    "openai/gpt-6-luna": 0.002,
}
LABELLER = "google/gemini-3.1-flash-lite"
AGENT_MODEL = "openai/gpt-6-luna"
SEED = 20260926
TYPED_PAGES, HANDWRITING_PAGES, PHOTO_PAGES, MIXED_PAGES = 100, 25, 50, 25
FULL_SCAN_SHARE = 0.70  # decision W7: a mixed page this much image is a scan with a text layer
TYPED_MAX_CHARS = 3000
TOP_UP_BATCH, TOP_UP_LIMIT = 25, 200
MONTH_BUDGET_USD = 40.0  # decision 0083
PICTURES = frozenset({"photograph", "diagram or chart", "mixed"})
FOLDER = Path("s26") / "transcriber-test"
PROBE_LINES = (
    "PILOT STATEMENT - INVENTED TEST PAGE",
    "Engine sputtered at 800 ft.",
    "Switched to right tank, no change.",
    "Fuel selector BOTH, mixture RICH.",
)
FIXTURES = Path("tests/fixtures/openrouter/transcription")


def _offline() -> httpx.BaseTransport:
    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: the transcriber test reads the docket cache only")

    return httpx.MockTransport(refuse)


def _read(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def _int(row: Mapping[str, object], name: str) -> int:
    return int(str(row[name]))


def _place(row: Mapping[str, object]) -> tuple[str, int, int]:
    return str(row["case_id"]), _int(row, "document"), _int(row, "page")


def _key(row: Mapping[str, object], model: str, *, instruction: str, dpi: int) -> TranscriptionKey:
    return TranscriptionKey(
        document_sha256=str(row["document_sha256"]),
        page=_int(row, "page"),
        model=model,
        instruction=instruction,
        dpi=dpi,
    )


def _hashed(rows: Sequence[Mapping[str, object]], docs: CachedDocuments) -> list[dict[str, object]]:
    hashed: list[dict[str, object]] = []
    for row in rows:
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        hashed.append({**row, "document_sha256": hashlib.sha256(data).hexdigest()})
    return hashed


def _category(row: Mapping[str, object], docs: CachedDocuments) -> str:
    for entry in docs.listing(_int(row, "mkey")).entries:
        if entry.index == _int(row, "document"):
            return document_category(entry.title)
    return "other"


def _text(cache: TranscriptionCache, row: Mapping[str, object], model: str, *, dpi: int) -> str:
    record = cache.get(_key(row, model, instruction=TRANSCRIBE.version, dpi=dpi))
    return record.text if record is not None and record.status == "transcribed" else ""


def _top_up(  # noqa: PLR0913, PLR0917 -- one parameter per fact the top-up needs (spec §7.3).
    have: list[dict[str, object]],
    pool: Sequence[Mapping[str, object]],
    want: int,
    label: str,
    docs: CachedDocuments,
    settings: Settings,
) -> list[dict[str, object]]:
    """Label pool pages 25 at a time with the inventory's labeller until ``want`` are found."""
    cache = TranscriptionCache(settings.transcription_dir)
    tried = 0
    while len(have) < want and tried < min(len(pool), TOP_UP_LIMIT):
        chunk = _hashed(pool[tried : tried + TOP_UP_BATCH], docs)
        tried += len(chunk)
        jobs = [
            PageJob(
                _key(row, LABELLER, instruction=LABEL.version, dpi=RESOLUTION),
                docs.loader(_int(row, "mkey"), _int(row, "document")),
                mixed=False,
            )
            for row in chunk
        ]
        run_preparation(
            kind="transcriber-test",
            jobs=jobs,
            instruction=LABEL,
            settings=settings,
            commit=commit_state(),
            expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD[LABELLER],
            workers=4,
        )
        for row in chunk:
            record = cache.get(_key(row, LABELLER, instruction=LABEL.version, dpi=RESOLUTION))
            if record is not None and record.page_kind == label:
                have.append(row)
    return have[:want]


def _typed_rows(
    frame: Sequence[Mapping[str, object]], rng: random.Random
) -> list[dict[str, object]]:
    typed: list[dict[str, object]] = []
    for fatal in (True, False):
        pool = sorted(
            (
                dict(row)
                for row in frame
                if row["kind"] == "text only"
                and row["fatal"] == fatal
                and BORN_DIGITAL_MIN_CHARS_PER_PAGE <= _int(row, "chars") <= TYPED_MAX_CHARS
            ),
            key=_place,
        )
        typed.extend(rng.sample(pool, min(TYPED_PAGES // 2, len(pool))))
    return typed


def _full_scans(
    frame: Sequence[Mapping[str, object]],
    sampled: set[tuple[str, int, int]],
    docs: CachedDocuments,
    rng: random.Random,
) -> list[dict[str, object]]:
    """Decision W7: text-and-image pages at least 70% image, in seeded order, until 25."""
    pool = sorted(
        (
            dict(r)
            for r in frame
            if r["kind"] == "text and image"
            and not r.get("photo_only")
            and _place(r) not in sampled
        ),
        key=_place,
    )
    rng.shuffle(pool)
    chosen: list[dict[str, object]] = []
    for row in pool:
        if len(chosen) >= MIXED_PAGES:
            break
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        (page,) = render_pages(data, [_int(row, "page")])
        if page.image_area_share >= FULL_SCAN_SHARE:
            chosen.append(row)
    return _hashed(chosen, docs)


def cmd_keys(settings: Settings, docs: CachedDocuments) -> str:
    """Draw the three keys (spec §7.3); top up with the labeller where the inventory is short."""
    s26 = settings.data_dir / "s26"
    frame = _read(s26 / "pages-dev-400.jsonl")
    sample = {_int(row, "n"): row for row in _read(s26 / "inventory" / "sample.jsonl")}
    labels_file = (s26 / "inventory" / "labels.json").read_text()
    labels = {int(n): label for n, label in json.loads(labels_file).items()}
    rng = random.Random(SEED)  # noqa: S311 -- sampling, not security
    typed = _hashed(_typed_rows(frame, rng), docs)
    sampled = {_place(row) for row in sample.values()}
    image_only = sorted(
        (dict(r) for r in frame if r["kind"] == "image only" and _place(r) not in sampled),
        key=_place,
    )
    rng.shuffle(image_only)

    def from_inventory(label: str) -> list[dict[str, object]]:
        return [dict(sample[n]) for n, lab in sorted(labels.items()) if lab == label]

    forms = [row for row in image_only if _category(row, docs) == "pilot_form_6120"]
    photo_docs = [row for row in image_only if _category(row, docs) == "photos"]
    handwriting = _top_up(
        from_inventory("handwriting"), forms, HANDWRITING_PAGES, "handwriting", docs, settings
    )
    photos = _top_up(
        from_inventory("photograph"), photo_docs, PHOTO_PAGES, "photograph", docs, settings
    )
    scans = _full_scans(frame, sampled, docs, rng)
    groups = (("typed", typed), ("handwriting", handwriting), ("photo", photos), ("mixed", scans))
    rows = [
        {**row, "set": name, "k": k}
        for name, group in groups
        for k, row in enumerate(group, start=1)
    ]
    folder = settings.data_dir / FOLDER
    (folder / "pages").mkdir(parents=True, exist_ok=True)
    for row in rows:
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        (page,) = render_pages(data, [_int(row, "page")])
        (folder / "pages" / f"{row['set']}-{row['k']}.jpg").write_bytes(page.data)
    (folder / "keys.jsonl").write_text("".join(json.dumps(row) + "\n" for row in rows))
    counts = Counter(str(row["set"]) for row in rows)
    return (
        f"keys: typed {counts['typed']}, handwriting {counts['handwriting']}, "
        f"photo {counts['photo']}, full-page scans {counts['mixed']}"
    )


def probe_page() -> bytes:
    """An invented, clinical page drawn as an image-only PDF: safe to transcribe and commit."""
    image = Image.new("L", (1275, 1650), 255)
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=40)
    for i, line in enumerate(PROBE_LINES):
        draw.text((100, 150 + 90 * i), line, fill=0, font=font)
    out = io.BytesIO()
    image.save(out, format="PDF", resolution=150)
    return out.getvalue()


def cmd_probe(settings: Settings) -> str:
    """One invented page per candidate; each reply is recorded as a test fixture."""
    (rendered,) = render_pages(probe_page())
    payload, system = request_for(rendered, TRANSCRIBE, text_layer=None)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    sha, dirty = commit_state()
    started = datetime.now(UTC)
    lines: list[str] = []
    total = 0.0
    with ExitStack() as stack:
        make = openrouter_clients(settings)(stack)
        for model in CANDIDATES:
            model_settings = settings_for(model, TRANSCRIBE)
            try:
                reply = make().complete(payload, model_settings, system=system)
            except ModelError as error:
                lines.append(f"{model}: FAILED -- {type(error).__name__}: {str(error)[:200]}")
                continue
            cost, _ = cost_usd(reply, model_settings)
            total += cost
            name = model.replace("/", "__") + ".json"
            (FIXTURES / name).write_text(reply.model_dump_json(indent=1) + "\n")
            try:
                text, kind = parse_reply(reply.content, TRANSCRIBE)
            except SchemaError as error:
                lines.append(f"{model}: the reply did not parse -- {error}")
                continue
            copied = sum(1 for line in PROBE_LINES if line in text)
            lines.append(
                f"{model}: ok, kind {kind}, {copied} of {len(PROBE_LINES)} lines copied, "
                f"{reply.usage.prompt_tokens}+{reply.usage.completion_tokens} tokens, "
                f"${cost:.5f}"
            )
    write_spend(
        settings.runs_dir,
        SpendRecord(
            job_id=f"{started:%Y%m%dT%H%M%S}-{sha}-transcriber-probe",
            kind="transcriber-test",
            model=",".join(CANDIDATES),
            started=started,
            calls=len(CANDIDATES),
            cost_usd=total,
            commit_sha=sha,
            dirty=dirty,
        ),
    )
    return "\n".join(lines)


def cmd_run(settings: Settings, docs: CachedDocuments, *, models: Sequence[str], dpi: int) -> str:
    """Each model reads every key page it is asked to, at one resolution."""
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    if dpi != RESOLUTION:  # the resolution comparison reads only the handwriting and typed keys
        keys = [row for row in keys if row["set"] in ("handwriting", "typed")]
    out: list[str] = []
    for model in models:
        done = run_preparation(
            kind="transcriber-test",
            jobs=[
                PageJob(
                    _key(row, model, instruction=TRANSCRIBE.version, dpi=dpi),
                    docs.loader(_int(row, "mkey"), _int(row, "document")),
                    mixed=row["set"] == "mixed",
                )
                for row in keys
            ],
            instruction=TRANSCRIBE,
            settings=settings,
            commit=commit_state(),
            expected_cost_per_page_usd=EXPECTED_COST_PER_PAGE_USD[model],
            workers=4,
        )
        failed = sum(1 for r in done if r.status == "failed")
        out.append(
            f"{model} at {dpi} dpi: {len(done)} pages read, {failed} failed, "
            f"${sum(r.cost_usd for r in done):.4f}"
        )
    return "\n".join(out)


def cmd_handwriting(settings: Settings) -> str:
    """Andy's key page: image, four lettered versions, agreed lines, spot checks, a draft."""
    folder = settings.data_dir / FOLDER
    rows = [r for r in _read(folder / "keys.jsonl") if r["set"] == "handwriting"]
    cache = TranscriptionCache(settings.transcription_dir)
    pages: dict[int, dict[str, object]] = {}
    for row in rows:
        k = _int(row, "k")
        order = random.Random(SEED + k).sample(CANDIDATES, len(CANDIDATES))  # noqa: S311
        letters = dict(zip(LETTERS, order, strict=True))
        versions = {
            letter: lines_of(_text(cache, row, model, dpi=RESOLUTION))
            for letter, model in letters.items()
        }
        draft = draft_letter(versions)
        pages[k] = {
            "letters": letters,
            "versions": versions,
            "draft": draft,
            "agreed": agreed_lines(versions, order=versions[draft]),
        }
    pooled = [(k, i) for k, page in pages.items() for i in range(len(page["agreed"]))]  # type: ignore[arg-type]
    spot_rng = random.Random(SEED + 1)  # noqa: S311 -- sampling, not security
    spot = set(spot_rng.sample(pooled, len(pooled) // SPOT_CHECK_EVERY))
    cards: list[Card] = []
    for k, page in sorted(pages.items()):
        agreed = cast("list[str]", page["agreed"])
        versions = cast("dict[str, list[str]]", page["versions"])
        page["spot"] = [line for i, line in enumerate(agreed) if (k, i) in spot]
        blocks = "".join(
            f"<h4>{letter}</h4><pre>{html.escape(chr(10).join(lines))}</pre>"
            for letter, lines in sorted(versions.items())
        )
        agreed_html = "".join(
            f"<li>{html.escape(line)}"
            f"{' <mark>check this line</mark>' if (k, i) in spot else ''}</li>"
            for i, line in enumerate(agreed)
        )
        cards.append(
            Card(
                row=k,
                body_html=(
                    f'<p class="meta">Handwriting page {k}</p>'
                    f'<img src="pages/handwriting-{k}.jpg" alt="page {k}">{blocks}'
                    f"<p>All four agree on (accepted):</p><ul>{agreed_html}</ul>"
                ),
                choices=(
                    Choice(
                        "spot check",
                        ("all correct", "some wrong, fixed in the key"),
                        required=bool(page["spot"]),
                    ),
                ),
                text_fields=(("key", "\n".join(versions[str(page["draft"])])),),
            )
        )
    (folder / "handwriting.json").write_text(json.dumps(pages))
    intro = (
        "<p>For each page: make the text box the page's true text, one line per written line. "
        "Write [illegible] for a word you cannot read either. The four versions are shown under "
        "letters, shuffled per page. Lines marked <mark>check this line</mark> are agreed by all "
        "four: check them against the image, fix any that are wrong in the box, and answer the "
        "spot check.</p>"
    )
    (folder / "handwriting.html").write_text(
        marking_page.render(
            title="Handwriting answer key (S2.6 spec §7.3)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-handwriting-key",
            csv_name="handwriting-key.csv",
        )
    )
    return f"page at {folder / 'handwriting.html'}"


def cmd_photos(settings: Settings) -> str:
    """Andy's page: every word any candidate wrote for a no-word photograph."""
    folder = settings.data_dir / FOLDER
    rows = [r for r in _read(folder / "keys.jsonl") if r["set"] == "photo"]
    cache = TranscriptionCache(settings.transcription_dir)
    sheet: dict[int, dict[str, object]] = {}
    cards: list[Card] = []
    for row in rows:
        k = _int(row, "k")
        order = random.Random(SEED + 100 + k).sample(CANDIDATES, len(CANDIDATES))  # noqa: S311
        for i, model in enumerate(order, start=1):
            text = _text(cache, row, model, dpi=RESOLUTION)
            if not re.search(r"[A-Za-z0-9]{2,}", text):
                continue
            number = 10 * k + i
            sheet[number] = {"k": k, "model": model}
            cards.append(
                Card(
                    row=number,
                    body_html=(
                        f'<p class="meta">Photograph {k}, version {LETTERS[i - 1]}</p>'
                        f'<img src="pages/photo-{k}.jpg" alt="photograph {k}">'
                        f"<pre>{html.escape(text)}</pre>"
                    ),
                    choices=(Choice("words", ("all on the page", "some invented")),),
                )
            )
    (folder / "photos.json").write_text(json.dumps(sheet))
    intro = (
        "<p>Each card is a photograph and the words one transcriber wrote for it. Most will be "
        "real (a registration, a placard). Mark <b>some invented</b> if any word is not on the "
        "page.</p>"
    )
    (folder / "photos.html").write_text(
        marking_page.render(
            title="Invented words on photographs (S2.6 spec §7.3)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-photo-words",
            csv_name="photo-words.csv",
        )
    )
    return f"{len(cards)} outputs with words; page at {folder / 'photos.html'}"


def cmd_mixed(settings: Settings, docs: CachedDocuments) -> str:
    """Andy's page (decision W7): the words each candidate added to a full-page scan."""
    folder = settings.data_dir / FOLDER
    rows = [r for r in _read(folder / "keys.jsonl") if r["set"] == "mixed"]
    cache = TranscriptionCache(settings.transcription_dir)
    sheet: dict[int, dict[str, object]] = {}
    cards: list[Card] = []
    for row in rows:
        k = _int(row, "k")
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        layer = page_text(data, _int(row, "page"))
        order = random.Random(SEED + 200 + k).sample(CANDIDATES, len(CANDIDATES))  # noqa: S311
        for i, model in enumerate(order, start=1):
            text = _text(cache, row, model, dpi=RESOLUTION)
            if not re.search(r"[A-Za-z0-9]{2,}", text):
                continue
            number = 10 * k + i
            sheet[number] = {"k": k, "model": model}
            cards.append(
                Card(
                    row=number,
                    body_html=(
                        f'<p class="meta">Full-page scan {k}, version {LETTERS[i - 1]}</p>'
                        f'<img src="pages/mixed-{k}.jpg" alt="page {k}">'
                        f"<details><summary>the page's text layer</summary>"
                        f"<pre>{html.escape(layer)}</pre></details>"
                        f"<p>Words this version added:</p><pre>{html.escape(text)}</pre>"
                    ),
                    choices=(
                        Choice(
                            "added words",
                            ("all on the page and new", "repeats the text layer", "some invented"),
                        ),
                    ),
                )
            )
    (folder / "mixed.json").write_text(json.dumps(sheet))
    intro = (
        "<p>Each card is a scanned page that already has a machine-read text layer, and the words "
        "one transcriber added to it. Mark <b>some invented</b> if any added word is not on the "
        "page; <b>repeats the text layer</b> if the added words are already in the text layer "
        "(open it under the image); otherwise <b>all on the page and new</b>.</p>"
    )
    (folder / "mixed.html").write_text(
        marking_page.render(
            title="Words added to full-page scans (S2.6, decision W7)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-mixed-words",
            csv_name="mixed-words.csv",
        )
    )
    return f"{len(cards)} outputs with added words; page at {folder / 'mixed.html'}"


def _result(  # noqa: PLR0913, PLR0917 -- one parameter per fact a candidate's score needs.
    model: str,
    keys: Sequence[Mapping[str, object]],
    key_texts: Mapping[int, str],
    photo_invented: int,
    typed_answers: Mapping[int, str],
    cache: TranscriptionCache,
    *,
    dpi: int,
    mixed_invented: int = 0,
) -> CandidateResult:
    hw_lines = hw_right = hw_inventing = 0
    for row in (r for r in keys if r["set"] == "handwriting"):
        key_text = key_texts[_int(row, "k")]
        version = lines_of(_text(cache, row, model, dpi=dpi))
        hw_lines += len(lines_of(key_text))
        hw_right += line_hits(lines_of(key_text), version)
        hw_inventing += inventing_lines(key_text, version)
    typed_chars = typed_errs = 0
    for row in (r for r in keys if r["set"] == "typed"):
        errors, chars = typed_errors(
            typed_answers[_int(row, "k")], _text(cache, row, model, dpi=dpi)
        )
        typed_errs += errors
        typed_chars += chars
    readings = [cache.get(_key(r, model, instruction=TRANSCRIBE.version, dpi=dpi)) for r in keys]
    costs = [r.cost_usd for r in readings if r is not None]
    return CandidateResult(
        model=model,
        cost_per_page=sum(costs) / len(costs) if costs else 0.0,
        hw_lines=hw_lines,
        hw_right=hw_right,
        hw_inventing=hw_inventing,
        photo_pages=sum(1 for r in keys if r["set"] == "photo"),
        photo_invented=photo_invented,
        typed_chars=typed_chars,
        typed_errors=typed_errs,
        mixed_pages=sum(1 for r in keys if r["set"] == "mixed"),
        mixed_invented=mixed_invented,
    )


def cmd_score(
    settings: Settings,
    docs: CachedDocuments,
    handwriting_csv: Path,
    photos_csv: Path,
    mixed_csv: Path,
) -> str:
    """Apply the rule to every candidate; add the resolution comparison once it has run."""
    folder = settings.data_dir / FOLDER
    keys = _read(folder / "keys.jsonl")
    cache = TranscriptionCache(settings.transcription_dir)
    pages = json.loads((folder / "handwriting.json").read_text())
    photo_sheet = json.loads((folder / "photos.json").read_text())
    hw_marks = marking_page.read_marks(handwriting_csv)
    photo_marks = marking_page.read_marks(photos_csv)
    unmarked = [n for n in photo_sheet if photo_marks.get(int(n), {}).get("words") == ""]
    if unmarked or len(photo_marks) < len(photo_sheet):
        raise SystemExit("some photograph outputs are unmarked")
    mixed_sheet = json.loads((folder / "mixed.json").read_text())
    mixed_marks = marking_page.read_marks(mixed_csv)
    if any(mixed_marks.get(int(n), {}).get("added words", "") == "" for n in mixed_sheet):
        raise SystemExit("some full-page scan outputs are unmarked")
    mixed_by_mark = Counter(
        (str(mixed_sheet[str(n)]["model"]), fields["added words"])
        for n, fields in mixed_marks.items()
        if str(n) in mixed_sheet
    )
    key_texts = {k: fields["key"] for k, fields in hw_marks.items()}
    typed_answers = {
        _int(r, "k"): page_text(
            docs.document(_int(r, "mkey"), _int(r, "document")), _int(r, "page")
        )
        for r in keys
        if r["set"] == "typed"
    }
    invented = Counter(
        str(photo_sheet[str(n)]["model"])
        for n, fields in photo_marks.items()
        if fields.get("words") == "some invented"
    )
    results = [
        _result(
            m,
            keys,
            key_texts,
            invented[m],
            typed_answers,
            cache,
            dpi=RESOLUTION,
            mixed_invented=mixed_by_mark[(m, "some invented")],
        )
        for m in CANDIDATES
    ]
    chosen, notes = choose(results)
    spot_total = spot_changed = picked = typed_lines = 0
    for k, page in pages.items():
        key_lines = Counter(lines_of(key_texts[int(k)]))
        spot_total += len(page.get("spot", []))
        spot_changed += sum(1 for line in page.get("spot", []) if key_lines[line] == 0)
        seen = {line for lines in page["versions"].values() for line in lines}
        for line in key_lines.elements():
            if line in seen:
                picked += 1
            else:
                typed_lines += 1
    lines = [
        "# the transcriber test (S2.6 spec §7, decision 0080) -- counts only",
        f"keys: {sum(1 for r in keys if r['set'] == 'typed')} typed pages, "
        f"{len(pages)} handwriting pages ({sum(r.hw_lines for r in results[:1])} key lines), "
        f"{results[0].photo_pages} no-word photographs; {RESOLUTION} dpi; instruction "
        f"{TRANSCRIBE.version}; standard prices (images cannot be batched)",
        f"handwriting key: {picked} lines picked from a version, {typed_lines} typed by Andy; "
        f"spot check of agreed lines: {spot_changed} of {spot_total} wrong in all four",
        "",
    ]
    for r in results:
        price = sources.price_of(r.model)
        low, high = wilson(r.hw_right, r.hw_lines)
        lines += [
            f"## {r.model} (${price.input_usd_per_mtok}/${price.output_usd_per_mtok} per M "
            f"tokens; measured ${r.cost_per_page:.5f} per test page)",
            f"  invented: {r.hw_inventing} lines ({r.invented_per_100_lines:.1f} per 100 "
            f"handwriting lines); {r.photo_invented} of {r.photo_pages} photographs",
            f"  handwriting lines right: {r.hw_right} of {r.hw_lines} ({r.hw_accuracy:.1%} "
            f"[{low:.1%}, {high:.1%}], Wilson 95%, lines not independent)",
            f"  typed errors: {r.typed_errors_per_100:.2f} per 100 characters "
            f"({r.typed_errors} of {r.typed_chars})",
            f"  full-page scans (decision W7): invented added words on {r.mixed_invented} of "
            f"{r.mixed_pages}; repeated the text layer on "
            f"{mixed_by_mark[(r.model, 'repeats the text layer')]}",
        ]
    lines += ["", "## the rule", *notes]
    if chosen is not None:
        at_200 = _result(chosen, keys, key_texts, 0, typed_answers, cache, dpi=200)
        if at_200.cost_per_page > 0:
            base = next(r for r in results if r.model == chosen)
            dpi = choose_resolution(base.hw_accuracy, at_200.hw_accuracy)
            lines += [
                "",
                "## resolution (spec §7.5)",
                f"  {chosen}: handwriting {base.hw_accuracy:.1%} at 150 dpi, "
                f"{at_200.hw_accuracy:.1%} at 200; typed errors {base.typed_errors_per_100:.2f} "
                f"and {at_200.typed_errors_per_100:.2f} per 100 characters",
                f"  chosen: {dpi} dpi",
            ]
    return "\n".join(lines)


def _latest_heldout_b_cost_per_case(settings: Settings) -> float:
    """Arm B's cost per case on its latest finished heldout-400 run (the S2.4 bar)."""
    records = [
        record
        for path in sorted(settings.runs_dir.glob("*-heldout-400-B/run.jsonl"))
        for record in read_jsonl(path, RunRecord)
        if record.finished is not None and record.arm == "B" and record.cases
    ]
    latest = max(records, key=lambda r: r.started)
    return latest.cost_usd / latest.cases


def cmd_estimate(settings: Settings, transcriber: str, dpi: int) -> str:
    """Decision 0083 item 2: the stage's spend so far plus its re-estimated rest, against $40."""
    s26 = settings.data_dir / "s26"
    spent = sum(
        s.cost_usd
        for path in sorted(settings.runs_dir.glob(f"*/{SPEND_FILE}"))
        for s in read_jsonl(path, SpendRecord)
    )
    frame = _read(s26 / "pages-dev-400.jsonl")
    sample = _read(s26 / "inventory" / "sample.jsonl")
    mixed = [r for r in sample if str(r["stratum"]).startswith("text and image")]
    sent_share = sum(
        1 for r in mixed if float(str(r["image_area_share"])) >= MIXED_PAGE_MIN_IMAGE_SHARE
    ) / max(1, len(mixed))
    image_only = sum(1 for r in frame if r["kind"] == "image only")
    text_and_image = sum(1 for r in frame if r["kind"] == "text and image")
    dev_pages = image_only + round(text_and_image * sent_share)
    cache = TranscriptionCache(settings.transcription_dir)
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    readings = [
        cache.get(_key(r, transcriber, instruction=TRANSCRIBE.version, dpi=dpi)) for r in keys
    ]
    per_page = statistics.mean(r.cost_usd for r in readings if r is not None)
    transcription = 2 * dev_pages * per_page  # held-out assumed equal to development (spec §11)
    b_case = _latest_heldout_b_cost_per_case(settings)
    # A floor: v2 adds transcribed text to every payload, which the S2.4 cost per case lacks.
    runs = (
        b_case * (401 + 401 + 400 + 400) + 2 * b_case * 401
    )  # four batch runs; W5's standard B-v2
    labels = json.loads((s26 / "inventory" / "labels.json").read_text())
    by_stratum: dict[str, list[tuple[str, str]]] = {}
    for row in sample:
        n = str(row["n"])
        if n in labels:
            by_stratum.setdefault(str(row["stratum"]), []).append((str(row["kind"]), labels[n]))
    population = json.loads((s26 / "inventory" / "population.json").read_text())
    picture_share = inventory.weighted_word_share(
        by_stratum,
        population,
        counted={"image only": PICTURES, "text and image": PICTURES, "photo-only": PICTURES},
    )
    luna_photo_tokens = [
        r.prompt_tokens
        for r in (
            cache.get(_key(row, AGENT_MODEL, instruction=TRANSCRIBE.version, dpi=RESOLUTION))
            for row in keys
            if row["set"] == "photo"
        )
        if r is not None
    ]
    image_tokens = statistics.median(luna_photo_tokens) - len(TRANSCRIBE.system) / 4
    images_per_case = (image_only + text_and_image) * picture_share / 401
    luna = sources.price_of(AGENT_MODEL)
    v3 = 401 * (2 * b_case + 2 * images_per_case * image_tokens * luna.input_usd_per_mtok / 1e6)
    total = spent + transcription + runs + v3
    verdict = (
        f"pause: the stage passes ${MONTH_BUDGET_USD:.0f} -- Andy decides (decision 0083 item 2)"
        if total > MONTH_BUDGET_USD
        else f"within ${MONTH_BUDGET_USD:.0f}"
    )
    return "\n".join(
        [
            f"spent on S2.6 so far (preparation spend rows): ${spent:.2f}",
            f"dev-400 pages to transcribe: {image_only} image-only + {sent_share:.0%} of "
            f"{text_and_image} text-and-image = {dev_pages}; held-out assumed the same",
            f"{transcriber} at {dpi} dpi: ${per_page:.5f} per page measured; transcription of "
            f"both samples ${transcription:.2f}",
            f"arm B runs (dev B-v1, B-v2, B-v2 standard; held-out B-v1, B-v2) at "
            f"${b_case:.5f} per case (latest heldout-400 arm B run): ${runs:.2f}, a floor",
            f"v3 probe: {images_per_case:.1f} picture pages per case at {image_tokens:.0f} tokens "
            f"each, GPT-6 Luna standard: ${v3:.2f}",
            f"stage total: ${total:.2f} -- {verdict}",
        ]
    )


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="transcriber_test")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("keys", "probe", "run", "handwriting", "photos", "mixed"):
        commands.add_parser(name)
    resolution_p = commands.add_parser("resolution")
    resolution_p.add_argument("--model", required=True, choices=CANDIDATES)
    score_p = commands.add_parser("score")
    score_p.add_argument("--handwriting", type=Path, required=True)
    score_p.add_argument("--photos", type=Path, required=True)
    score_p.add_argument("--mixed", type=Path, required=True)
    score_p.add_argument("--out", type=Path)
    estimate_p = commands.add_parser("estimate")
    estimate_p.add_argument("--model", required=True, choices=CANDIDATES)
    estimate_p.add_argument("--dpi", type=int, choices=(150, 200), default=RESOLUTION)
    args = parser.parse_args(argv)
    settings = Settings()
    docs = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline()))
    if args.command == "keys":
        text = cmd_keys(settings, docs)
    elif args.command == "probe":
        text = cmd_probe(settings)
    elif args.command == "run":
        text = cmd_run(settings, docs, models=CANDIDATES, dpi=RESOLUTION)
    elif args.command == "resolution":
        text = cmd_run(settings, docs, models=(args.model,), dpi=200)
    elif args.command == "handwriting":
        text = cmd_handwriting(settings)
    elif args.command == "photos":
        text = cmd_photos(settings)
    elif args.command == "mixed":
        text = cmd_mixed(settings, docs)
    elif args.command == "score":
        text = cmd_score(settings, docs, args.handwriting, args.photos, args.mixed)
        if args.out:
            args.out.write_text(text + "\n")
    else:
        text = cmd_estimate(settings, args.model, args.dpi)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
