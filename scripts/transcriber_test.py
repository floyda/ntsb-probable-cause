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
      photos-recheck, handwriting-recheck
                  -- decision 0086's second pass: Andy's two recheck pages (free), read
                     against the first pass's CSVs kept under <data_dir>/s26/transcriber-test/pass1/
      score --pass2 -- the second pass: the first-pass CSVs (--handwriting, --photos, --mixed;
                     the pass1/ copies) overridden row by row by the two recheck CSVs;
                     write docs/results/s26-transcriber-test-pass2.txt
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
import subprocess
from collections import Counter
from collections.abc import Collection, Mapping, Sequence
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from difflib import SequenceMatcher
from fractions import Fraction
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
    Instruction,
    PageJob,
    TranscriptionCache,
    TranscriptionKey,
    key_instruction,
    parse_reply,
    request_for,
    settings_for,
)
from ntsb_probable_cause.errors import ConfigurationError, ModelError, SchemaError
from ntsb_probable_cause.gitinfo import commit_state, commits_since
from ntsb_probable_cause.model.client import cost_usd
from ntsb_probable_cause.scoring.budget import (
    SPEND_FILE,
    SpendRecord,
    month_spent,
    open_reservations,
    reserve_within_budget,
    settle,
    write_spend,
)
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.preparation import openrouter_clients, run_preparation
from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts import page_inventory as inventory
from scripts.marking_page import Card, Choice

# The rule (spec §7.4, decision 0080), fixed before the test runs. The gates stay plain floats
# (the review's own boundary sweep found 0 misfires on them); the two margins and the
# resolution threshold are exact fractions (fix round 1, I7): a plain float 0.05 is not itself
# exactly representable, and a boundary case -- an exact 5-point handwriting gap, an exact
# 1-per-100 typed gap -- could be misjudged by that rounding alone, before any division even
# enters. `choose` and `choose_resolution` compare `Fraction`s built from the raw integer
# counts, never a pre-divided float, at every place a boundary can be hit.
GATE_INVENTED_LINES_PER_100 = 2.0
GATE_INVENTED_PHOTO_SHARE = 1 / 20
GATE_INVENTED_MIXED_SHARE = 1 / 20  # decision W7: the photographs' bar
# Decision 0086 item 2 (the second pass only): a model that returns fewer than half a
# handwriting page's key lines on more than 1 in 20 pages is out. An exact fraction built from
# the integer counts, so 1 page in 20 passes and 2 in 20 do not, with no rounding either way.
GATE_FORMAT_FAILED_SHARE = Fraction(1, 20)
HANDWRITING_MARGIN = Fraction(1, 20)
TYPED_MARGIN_PER_100 = Fraction(1, 1)
RESOLUTION_MARGIN = Fraction(1, 20)
SPOT_CHECK_EVERY = 10

_WORD = re.compile(r"[A-Za-z0-9]{2,}")
_ILLEGIBLE_WORD = "illegible"


def lines_of(text: str) -> list[str]:
    """Non-empty lines with whitespace collapsed: the unit of the handwriting key."""
    return [" ".join(line.split()) for line in text.splitlines() if line.strip()]


def line_hits(key: Sequence[str], version: Sequence[str]) -> int:
    """Key lines the version holds exactly, each version line used at most once."""
    return sum((Counter(key) & Counter(version)).values())


def format_failed(key: Sequence[str], version: Sequence[str]) -> bool:
    """Decision 0086 item 2: the reply has fewer than half as many lines as the key.

    Integer arithmetic (``2 * len(version) < len(key)``): against a 10-line key a 5-line
    reply is not a format failure and a 4-line reply is.
    """
    return 2 * len(version) < len(key)


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
    """Lines every non-empty version holds, in the draft's order.

    Fix round 1, M3: a version with no lines at all (a failed reading, or a page one
    candidate genuinely read as blank) takes no part in the intersection -- agreement is
    judged among whichever versions actually have something, so one such version does not
    wipe out every accepted line.
    """
    present = [v for v in versions.values() if v]
    if not present:
        return []
    common = reduce(operator.and_, (Counter(v) for v in present))
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
    # Decision 0086 item 2 (the second pass): handwriting pages scored, and those whose reply
    # had fewer than half the key's lines. Always 0 format failures in the first pass.
    hw_pages: int = 0
    hw_format_failed: int = 0

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


def _fraction(numerator: int, denominator: int) -> Fraction:
    """``numerator / denominator`` exactly, or 0 when there is nothing to divide by."""
    return Fraction(numerator, denominator) if denominator else Fraction(0)


def choose(results: Sequence[CandidateResult]) -> tuple[str | None, list[str]]:
    """Spec §7.4: the gate, then the cheapest within both margins of the best. Notes say why.

    Fix round 2, C1 (Andy, "handwriting first"): the spec did not say what happens when no
    passing candidate is within both margins at once -- the review's own example (a candidate
    with the best handwriting more than 1 error per 100 characters behind on typed text, and
    the candidate with the best typed text more than 5 points behind on handwriting) makes
    ``eligible`` empty and used to raise. Andy's answer: handwriting comes first. When no
    candidate is within both margins, the cheapest candidate within 5 points of the best
    handwriting line accuracy is chosen instead, typed errors per 100 characters breaking a
    cost tie (lower wins), then the documented order in ``CANDIDATES`` (fix round 1, M7's tie
    rule, unchanged). When no candidate passes the gate at all, the result is still "no
    transcriber" (spec §7.4 item 3) -- that case is untouched by this decision.

    A tie in cost within both margins (fix round 1, M7) goes to whichever tied candidate is
    listed first in ``CANDIDATES``: ``min`` returns the first minimum it meets, and ``results``
    is built from ``CANDIDATES`` in order.

    Decision 0086 item 2 adds one gate, for the second pass only: more than 1 in 20
    handwriting pages with a reply of fewer than half the key's lines. The first pass never
    counts such pages (``hw_format_failed`` stays 0), so the gate cannot fire there.
    """
    notes: list[str] = []
    passed: list[CandidateResult] = []
    for r in results:
        if r.invented_per_100_lines > GATE_INVENTED_LINES_PER_100:
            notes.append(
                f"{r.model}: out -- {r.invented_per_100_lines:.1f} inventing lines per 100 "
                f"handwriting lines (gate {GATE_INVENTED_LINES_PER_100:.0f})"
            )
        elif _fraction(r.hw_format_failed, r.hw_pages) > GATE_FORMAT_FAILED_SHARE:
            notes.append(
                f"{r.model}: out -- a transcribed reply with fewer than half the key's lines "
                f"on {r.hw_format_failed} of {r.hw_pages} handwriting pages (gate 1 in 20, "
                "decision 0086; failed readings not counted)"
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
    hw = {r.model: _fraction(r.hw_right, r.hw_lines) for r in passed}
    typed = {r.model: 100 * _fraction(r.typed_errors, r.typed_chars) for r in passed}
    best_hw = max(hw.values())
    best_typed = min(typed.values())
    both_margins = [
        r
        for r in passed
        if hw[r.model] >= best_hw - HANDWRITING_MARGIN
        and typed[r.model] <= best_typed + TYPED_MARGIN_PER_100
    ]
    for r in passed:
        if r not in both_margins:
            notes.append(f"{r.model}: passed the gate, outside a margin of the best")
    if both_margins:
        chosen = min(both_margins, key=lambda r: r.cost_per_page)
        notes.append(f"{chosen.model}: chosen -- the cheapest within both margins")
        return chosen.model, notes
    # Fix round 2, C1: no candidate was within both margins -- handwriting first. Ties (on
    # cost, then on typed errors) go to whichever tied candidate comes first in ``passed``,
    # the same way M7's within-both-margins tie already works: ``min`` keeps the first
    # element it meets with the smallest key, and ``passed`` preserves ``CANDIDATES`` order.
    hw_eligible = [r for r in passed if hw[r.model] >= best_hw - HANDWRITING_MARGIN]
    chosen = min(hw_eligible, key=lambda r: (r.cost_per_page, typed[r.model]))
    notes.append(
        f"{chosen.model}: chosen -- handwriting first: no candidate was within both margins"
    )
    return chosen.model, notes


def choose_resolution(accuracy_150: Fraction, accuracy_200: Fraction) -> int:
    """Spec §7.5: 200 dpi only for more than 5 points of handwriting accuracy.

    Fix round 1, I7 built this on exact ``Fraction`` arithmetic so a 5-point gap is judged
    exactly, never nudged either way by ``0.05``'s own floating-point rounding. Fix round 3,
    R6 narrows the parameters to ``Fraction`` only, checked at runtime: accepting a ``float``
    let a caller reintroduce the very rounding this function exists to avoid (1,960 misfires
    in the review's boundary sweep on the float path).
    """
    if not isinstance(accuracy_150, Fraction) or not isinstance(accuracy_200, Fraction):
        raise TypeError("choose_resolution requires exact Fraction accuracies, not float")
    return 200 if accuracy_200 - accuracy_150 > RESOLUTION_MARGIN else 150


CANDIDATES = (
    "google/gemini-3.1-flash-lite",
    "google/gemini-3.6-flash",
    "qwen/qwen3.5-122b-a10b",
    "openai/gpt-6-luna",
)
# Fix round 1, M4: sized to CANDIDATES itself, not fixed at four -- a candidate dropped after
# the probe (spec §17 allows this) must not make `zip(LETTERS, order, strict=True)` raise.
LETTERS = tuple("ABCDEFGH"[: len(CANDIDATES)])
# Conservative per-page reservations; the spend rows record what was really spent.
# Fix round 1, M8: at 200 key pages per candidate (100 + 25 + 50 + 25), the original figures
# reserved 200 x (0.003+0.008+0.006+0.002) = $3.80 for the 150 dpi run -- below the brief's own
# "$4-8" estimate, so not conservative if that estimate is right. Raised by about a fifth (a
# round number, not a re-measurement) to 200 x 0.024 = $4.80; the spend rows record what the
# run actually costs regardless.
EXPECTED_COST_PER_PAGE_USD = {
    "google/gemini-3.1-flash-lite": 0.004,
    "google/gemini-3.6-flash": 0.010,
    "qwen/qwen3.5-122b-a10b": 0.007,
    "openai/gpt-6-luna": 0.003,
}
LABELLER = "google/gemini-3.1-flash-lite"
AGENT_MODEL = "openai/gpt-6-luna"
SEED = 20260926
TYPED_PAGES, HANDWRITING_PAGES, PHOTO_PAGES, MIXED_PAGES = 100, 25, 50, 25
FULL_SCAN_SHARE = 0.70  # decision W7: a mixed page this much image is a scan with a text layer
TYPED_MAX_CHARS = 3000
TOP_UP_BATCH, TOP_UP_LIMIT = 25, 200
# Fix round 1, I5: `estimate` reads `settings.monthly_budget_usd` (decision 0083) directly,
# rather than a second constant that could drift from it.
# Fix round 4, T1: which spend is S2.6's own is decided by commit, not by date. 90ceab9 is the
# S2.4 merge commit on main ("S2.4: the model switch (#11)"). S2.6 was branched before it and
# merged it in, so its commits are among those reachable from HEAD but not from it (`git
# rev-list 90ceab9..HEAD`). Not exactly S2.6's (final review triage, T13-U1): that range also
# holds S2.5's commits, merged in from the S2.5 branch, so an S2.5 spend row would be counted
# as S2.6's; none exists. A run record or spend row counts towards the stage total only if
# its recorded commit is one of these. Fix round 3's date filter (2026-09-24) counted
# $2.164 of S2.4's own runs made that day, and would count any later run from another branch.
STAGE_BASE = "90ceab9"
# git's own shortest abbreviation; a shorter recorded sha would match too many commits.
MIN_SHA_PREFIX = 4
PICTURES = frozenset({"photograph", "diagram or chart", "mixed"})
FOLDER = Path("s26") / "transcriber-test"
# Decision 0086: the first pass's three CSVs, kept unchanged beside the second pass's pages.
PASS1 = "pass1"
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


def _key(
    row: Mapping[str, object],
    model: str,
    *,
    instruction: Instruction,
    dpi: int,
    mixed: bool = False,
) -> TranscriptionKey:
    """A reading's key.

    ``mixed`` (fix round 1, I3) must match the job it identifies: a full and a mixed reading
    of the same page must never share one (``key_instruction``, amending decision 0085).
    """
    return TranscriptionKey(
        document_sha256=str(row["document_sha256"]),
        page=_int(row, "page"),
        model=model,
        instruction=key_instruction(instruction, mixed=mixed),
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
    mixed = row.get("set") == "mixed"
    record = cache.get(_key(row, model, instruction=TRANSCRIBE, dpi=dpi, mixed=mixed))
    return record.text if record is not None and record.status == "transcribed" else ""


def _top_up(  # noqa: PLR0913, PLR0917 -- one parameter per fact the top-up needs (spec §7.3).
    have: list[dict[str, object]],
    pool: Sequence[Mapping[str, object]],
    want: int,
    labels: tuple[str, ...],
    docs: CachedDocuments,
    settings: Settings,
) -> list[dict[str, object]]:
    """Label pool pages 25 at a time with the inventory's labeller until ``want`` are found.

    A pool page is kept when the labeller calls it any of ``labels`` (fix round 2, C2: the
    handwriting top-up accepts ``handwriting`` or ``filled form``, since the labeller calls a
    hand-filled pilot form the latter far more often than the former). Every row ``have``
    starts with must already carry ``"source"`` and ``"page_kind"`` (the caller tags the
    inventory's own rows before calling this); a page this function adds gets
    ``"source": "top-up"`` and the label that admitted it, so the results file can report
    where each key page came from.

    Fix round 3, R5: a batch already fully cached (every page already labelled, from an
    earlier run of ``keys``) never calls ``run_preparation`` at all. The handwriting and
    photograph top-ups are both a ``transcriber-test`` job under the labeller model, so a
    ``keys`` re-run after a late crash -- one top-up already done, the other not yet reached --
    would otherwise have both top-ups claim the same job id in the same second once their
    already-labelled batches return instantly (the collision fix round 1's I1 closed for
    ``cmd_run``, which uses a different model per job, does not reach: here the model is the
    same for both).
    """
    cache = TranscriptionCache(settings.transcription_dir)
    tried = 0
    while len(have) < want and tried < min(len(pool), TOP_UP_LIMIT):
        chunk = _hashed(pool[tried : tried + TOP_UP_BATCH], docs)
        tried += len(chunk)
        jobs = [
            PageJob(
                _key(row, LABELLER, instruction=LABEL, dpi=RESOLUTION),
                docs.loader(_int(row, "mkey"), _int(row, "document")),
                mixed=False,
            )
            for row in chunk
        ]
        if any(cache.get(job.key) is None for job in jobs):
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
            record = cache.get(_key(row, LABELLER, instruction=LABEL, dpi=RESOLUTION))
            if record is not None and record.page_kind in labels:
                have.append({**row, "source": "top-up", "page_kind": record.page_kind})
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


def cmd_keys(settings: Settings, docs: CachedDocuments, *, force: bool = False) -> str:
    """Draw the three keys (spec §7.3); top up with the labeller where the inventory is short.

    Fix round 1, M6: refuses to overwrite an existing ``keys.jsonl`` unless ``force`` is
    given. A re-run would draw a fresh, differently-numbered set of pages (the top-up and the
    full-page-scan draw both call the labeller and the seeded shuffle again, and the inventory
    or the frame may have changed underneath), silently shifting ``k`` under any marks Andy has
    already saved against the old numbering.
    """
    folder = settings.data_dir / FOLDER
    if not force and (folder / "keys.jsonl").exists():
        raise ConfigurationError(
            f"{folder / 'keys.jsonl'} already exists: `keys` would draw a fresh set of pages "
            "and could shift the numbering under any marks already saved against it. Pass "
            "--force to overwrite."
        )
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
        # Fix round 2, C2: tagged "inventory" / its own label, so the results file can report
        # where each key page came from.
        return [
            {**dict(sample[n]), "source": "inventory", "page_kind": lab}
            for n, lab in sorted(labels.items())
            if lab == label
        ]

    forms = [row for row in image_only if _category(row, docs) == "pilot_form_6120"]
    photo_docs = [row for row in image_only if _category(row, docs) == "photos"]
    # Fix round 2, C2 (Andy, "hand-filled pilot forms"): the top-up accepts a pilot-form page
    # the labeller calls either handwriting or filled form -- of 97 sampled pilot-form pages
    # the labeller called none handwriting and 90 filled form (docs/results/s26-inventory.txt).
    handwriting = _top_up(
        from_inventory("handwriting"),
        forms,
        HANDWRITING_PAGES,
        ("handwriting", "filled form"),
        docs,
        settings,
    )
    photos = _top_up(
        from_inventory("photograph"), photo_docs, PHOTO_PAGES, ("photograph",), docs, settings
    )
    scans = _full_scans(frame, sampled, docs, rng)
    groups = (("typed", typed), ("handwriting", handwriting), ("photo", photos), ("mixed", scans))
    rows = [
        {**row, "set": name, "k": k}
        for name, group in groups
        for k, row in enumerate(group, start=1)
    ]
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
    """One invented page per candidate; each reply is recorded as a test fixture.

    Fix round 1, I4: reserved, spent and settled like any paid preparation job -- not routed
    through `run_preparation` itself, which returns `Transcription` records rather than the
    raw `ModelReply` this fixture needs to record. The client factory is built (which raises
    if `OPENROUTER_API_KEY` is missing) before the reservation, the same order
    `run_preparation` uses (its own fix round 1, I2), so that failure never leaves a
    reservation open with nothing to settle it. The spend row's `calls` is the number that
    actually completed, not `len(CANDIDATES)`, and is written -- with `settle` -- in a
    `finally`, so an exception partway through still records what was spent.
    """
    (rendered,) = render_pages(probe_page())
    payload, system = request_for(rendered, TRANSCRIBE, text_layer=None)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    sha, dirty = commit_state()
    started = datetime.now(UTC)
    job_id = f"{started:%Y%m%dT%H%M%S}-{sha}-transcriber-probe"
    client_factory = openrouter_clients(settings)
    reserve_within_budget(
        settings.runs_dir,
        job_id,
        len(CANDIDATES) * max(EXPECTED_COST_PER_PAGE_USD.values()),
        settings.monthly_budget_usd,
        now=started,
    )
    lines: list[str] = []
    calls = 0
    total = 0.0
    try:
        with ExitStack() as stack:
            make = client_factory(stack)
            for model in CANDIDATES:
                model_settings = settings_for(model, TRANSCRIBE)
                try:
                    reply = make().complete(payload, model_settings, system=system)
                except ModelError as error:
                    lines.append(f"{model}: FAILED -- {type(error).__name__}: {str(error)[:200]}")
                    continue
                calls += 1
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
    finally:
        write_spend(
            settings.runs_dir,
            SpendRecord(
                job_id=job_id,
                kind="transcriber-test",
                model=",".join(CANDIDATES),
                started=started,
                calls=calls,
                cost_usd=total,
                commit_sha=sha,
                dirty=dirty,
            ),
        )
        settle(settings.runs_dir, job_id)
    return "\n".join(lines)


def cmd_run(
    settings: Settings,
    docs: CachedDocuments,
    *,
    models: Sequence[str],
    dpi: int,
    retry_failed: bool = False,
) -> str:
    """Each model reads every key page it is asked to, at one resolution.

    Fix round 3, R1 (decision 3, "after one retry"): ``retry_failed`` re-reads every page a
    model's cached reading records as ``"failed"`` -- one retry per invocation, not a bounded
    count of its own. It does not record that a retry happened, so calling it a second time
    would retry again; the invocations that decide the answer key (``s26-transcriber-run``,
    ``s26-transcriber-resolution``) call it exactly once, right after the first read, which is
    what makes "after one retry" true in practice. A page still failed at that point is scored
    as wrong for that model (``ReadingCounts``, `_choose_or_hold`), not retried further.
    """
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    if dpi != RESOLUTION:  # the resolution comparison reads only the handwriting and typed keys
        keys = [row for row in keys if row["set"] in ("handwriting", "typed")]
    out: list[str] = []
    for model in models:
        done = run_preparation(
            kind="transcriber-test",
            jobs=[
                PageJob(
                    _key(row, model, instruction=TRANSCRIBE, dpi=dpi, mixed=row["set"] == "mixed"),
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
            retry_failed=retry_failed,
        )
        failed = sum(1 for r in done if r.status == "failed")
        out.append(
            f"{model} at {dpi} dpi: {len(done)} pages read, {failed} failed, "
            f"${sum(r.cost_usd for r in done):.4f}"
        )
    return "\n".join(out)


# Andy, 2026-09-25 (display only; the fields, rows, storage key and CSV are unchanged, so marks
# already made reload): each card is two columns -- the page image, held in view while the card
# scrolls, and beside it the versions side by side, the agreed lines and the key box.
_HANDWRITING_LAYOUT = """<style>
body{max-width:none;margin:1rem}
.card{display:grid;grid-template-columns:minmax(0,5fr) minmax(0,7fr);column-gap:1rem}
.card>*{grid-column:2}
.card>.pic{grid-column:1;grid-row:1/span 50;align-self:start;position:sticky;top:0;
max-height:100vh;overflow:auto}
.pic img{width:100%;cursor:zoom-in}.pic img.big{width:220%;cursor:zoom-out}
.vers{display:grid;grid-template-columns:repeat(auto-fit,minmax(10rem,1fr));gap:.5rem}
.vers pre{font-size:.8rem;max-height:45vh;overflow:auto;margin:0}
.vers h4{margin:.2rem 0}
.card textarea{min-height:20rem}
.only{background:#fca5a5}.some{background:#fde68a}
</style>"""


def _word(token: str) -> str:
    """A token as compared across versions: case and surrounding punctuation ignored."""
    return re.sub(r"^[^\w\[]+|[^\w\]]+$", "", token).lower()


def _highlighted(lines: Sequence[str], versions: Mapping[str, Sequence[str]]) -> str:
    """One version's lines, escaped, each word coloured by how many versions hold it.

    A word every version that read something holds is left plain; one only this version holds
    is ``only``; one some but not all hold is ``some``. A display aid for Andy's key, never
    part of the measures.
    """
    present = [{_word(t) for line in v for t in line.split()} for v in versions.values() if v]
    out: list[str] = []
    for line in lines:
        words: list[str] = []
        for token in line.split():
            key = _word(token)
            held = sum(1 for vocab in present if key in vocab)
            css = (
                ""
                if not key or len(present) <= 1 or held == len(present)
                else ("only" if held == 1 else "some")
            )
            text = html.escape(token)
            words.append(f'<span class="{css}">{text}</span>' if css else text)
        out.append(" ".join(words))
    return "\n".join(out)


def _handwriting_card(  # noqa: PLR0913 -- one keyword per part of a card that varies.
    k: int,
    versions: Mapping[str, Sequence[str]],
    agreed: Sequence[str],
    *,
    spot_indices: Collection[int],
    choices: tuple[Choice, ...],
    key: str,
) -> Card:
    """One handwriting page's card: image, lettered versions, agreed lines, the key box.

    Shared by the first pass (``cmd_handwriting``) and the second pass's recheck page
    (decision 0086 item 3), so both show a page the same way.
    """
    blocks = (
        '<div class="vers">'
        + "".join(
            f"<div><h4>{letter}</h4><pre>{_highlighted(lines, versions)}</pre></div>"
            for letter, lines in sorted(versions.items())
        )
        + "</div>"
    )
    agreed_html = "".join(
        f"<li>{html.escape(line)}"
        f"{' <mark>check this line</mark>' if i in spot_indices else ''}</li>"
        for i, line in enumerate(agreed)
    )
    # Fix round 1, M3: says how many versions actually read something, so a blank or failed
    # reading (which agreed_lines already excludes from the intersection) is visible to Andy
    # rather than silently folded into "agree on".
    present = sum(1 for lines in versions.values() if lines)
    return Card(
        row=k,
        body_html=(
            f'<p class="meta">Handwriting page {k} ({present} of {len(versions)} '
            "versions read something)</p>"
            f'<div class="pic"><img src="pages/handwriting-{k}.jpg" alt="page {k}" '
            "onclick=\"this.classList.toggle('big')\"></div>"
            f"{blocks}"
            "<p>Lines every version that read something agrees on (accepted):</p>"
            f"<ul>{agreed_html}</ul>"
        ),
        choices=choices,
        text_fields=(("key", key),),
    )


_HANDWRITING_LEGEND = (
    "<p>Words in a version are coloured where the versions disagree: "
    '<span class="only">only this version has it</span>, '
    '<span class="some">some versions have it, not all</span>; uncoloured words are in '
    "every version that read something. Check the coloured words against the image. "
    "Click the image to enlarge it; it stays in view while you scroll the card.</p>"
)


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
        cards.append(
            _handwriting_card(
                k,
                versions,
                agreed,
                spot_indices={i for i in range(len(agreed)) if (k, i) in spot},
                choices=(
                    Choice(
                        "spot check",
                        ("all correct", "some wrong, fixed in the key"),
                        required=bool(page["spot"]),
                    ),
                ),
                key="\n".join(versions[str(page["draft"])]),
            )
        )
    (folder / "handwriting.json").write_text(json.dumps(pages))
    # Fix round 3, R7: says how many versions are shown and that agreement is among whichever
    # of them read something, matching M3's own wording on each card -- not "the four
    # versions"/"all four", which is both stale (a candidate can be dropped after the probe,
    # spec §17, M4) and wrong whenever a version reads a page as blank or fails on it.
    intro = (
        _HANDWRITING_LAYOUT
        + _HANDWRITING_LEGEND
        + f"<p>For each page: make the text box the page's true text, one line per written "
        "line. Write [illegible] for a word you cannot read either. The "
        f"{len(CANDIDATES)} versions are shown under letters, shuffled per page. Lines marked "
        "<mark>check this line</mark> are agreed by every version that read something: check "
        "them against the image, fix any that are wrong in the box, and answer the spot "
        "check.</p>"
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


def draft_anchored(
    pages: Mapping[str, Mapping[str, object]], hw_marks: Mapping[int, Mapping[str, str]]
) -> list[int]:
    """Handwriting pages whose first-pass key is exactly the prefilled draft (0086 item 3).

    Compared as ``lines_of``, the unit of the handwriting measure: a key Andy left as the draft
    (or changed only in whitespace) counts; one he edited in any word does not.
    """
    return sorted(
        int(k)
        for k, page in pages.items()
        if lines_of(hw_marks.get(int(k), {}).get("key", ""))
        == list(cast("dict[str, list[str]]", page["versions"])[str(page["draft"])])
    )


# Decision 0086 item 3: the recheck page asks whether each key was already right, so a page
# Andy checked and left unchanged still counts as marked (the page's progress counts only rows
# he has touched, fix round 1, M5) and `score --pass2` can refuse a page nobody looked at.
_KEY_CHECKED = Choice("checked", ("key right as it stands", "key corrected in the box"))


def cmd_handwriting_recheck(settings: Settings) -> str:
    """Decision 0086 item 3: only the draft-anchored pages, prefilled with the first-pass key.

    Reads ``handwriting.json`` (the pages exactly as the first pass showed them) and the
    first-pass CSV kept under ``pass1/``; the spot checks are not repeated.
    """
    folder = settings.data_dir / FOLDER
    pages = json.loads((folder / "handwriting.json").read_text())
    first = marking_page.read_marks(folder / PASS1 / "handwriting-key.csv")
    anchored = draft_anchored(pages, first)
    cards = [
        _handwriting_card(
            k,
            cast("dict[str, list[str]]", pages[str(k)]["versions"]),
            cast("list[str]", pages[str(k)]["agreed"]),
            spot_indices=(),
            choices=(_KEY_CHECKED,),
            key=first[k]["key"],
        )
        for k in anchored
    ]
    intro = (
        _HANDWRITING_LAYOUT + "<p><b>Second pass (decision 0086).</b> These are the "
        f"{len(cards)} pages whose key was left as the prefilled draft in the first pass. On "
        "each page, the box holds your first-pass key: check it against the image and correct "
        "it in the box, one line per written line. Write [illegible] for a word you cannot "
        "read either. Then say whether the key was right as it stands or corrected.</p>"
        + _HANDWRITING_LEGEND
    )
    (folder / "handwriting-recheck.html").write_text(
        marking_page.render(
            title="Handwriting answer key, second pass (S2.6, decision 0086)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-handwriting-key-pass2",
            csv_name="handwriting-key-pass2.csv",
        )
    )
    return f"{len(cards)} draft-anchored pages; page at {folder / 'handwriting-recheck.html'}"


# Andy, 2026-09-25 (display only): each image is shown once, held in view on the left, with
# each version's words as its own card in columns on the right. Every version keeps its own
# card, row number and mark, so the CSVs, scoring and marks already made are unchanged.
_GROUPED_LAYOUT = """<style>
body{max-width:none;margin:1rem}
.side>pre.layer{max-height:35vh;overflow:auto;font-size:.8rem}
.card pre{font-size:.85rem}
.inlayer{background:#cbd5e1}.new{background:#fde68a}
</style>"""


def _image_head(title: str, src: str) -> str:
    """A group's left column: its title and its image (click to enlarge)."""
    return (
        f'<h3>{html.escape(title)}</h3><img src="{src}" alt="{html.escape(title)}" '
        "onclick=\"this.classList.toggle('big')\">"
    )


def _same_as(seen: dict[str, str], text: str, letter: str) -> str:
    """Note a version whose words are exactly an earlier version's; record this one's."""
    earlier = seen.get(text)
    seen.setdefault(text, letter)
    return f" -- same words as version {earlier}" if earlier else ""


def _against_layer(text: str, layer: str) -> str:
    """Added words, escaped, coloured by whether the page's text layer already holds each.

    ``inlayer``: the word is already in the text layer (a sign of "repeats the text layer");
    ``new``: it is not, so check it against the image. A display aid for Andy, never part of
    the measures; case and surrounding punctuation are ignored, as in ``_highlighted``.
    """
    vocab = {_word(token) for token in layer.split()}
    lines: list[str] = []
    for line in text.splitlines():
        words: list[str] = []
        for token in line.split():
            key = _word(token)
            css = "" if not key else ("inlayer" if key in vocab else "new")
            text_html = html.escape(token)
            words.append(f'<span class="{css}">{text_html}</span>' if css else text_html)
        lines.append(" ".join(words))
    return "\n".join(lines)


_PHOTO_WORDS = Choice("words", ("all on the page", "some invented"))
_PhotoCards = tuple[dict[int, dict[str, object]], list[Card], dict[str, tuple[str, str]]]


def _photo_cards(settings: Settings) -> _PhotoCards:
    """Every candidate output with words on a no-word photograph: the sheet, cards and groups.

    Shared by the first pass (``cmd_photos``) and the second pass's recheck page (decision
    0086 item 1), so both number and show a card the same way.
    """
    folder = settings.data_dir / FOLDER
    rows = [r for r in _read(folder / "keys.jsonl") if r["set"] == "photo"]
    cache = TranscriptionCache(settings.transcription_dir)
    sheet: dict[int, dict[str, object]] = {}
    cards: list[Card] = []
    groups: dict[str, tuple[str, str]] = {}
    for row in rows:
        k = _int(row, "k")
        order = random.Random(SEED + 100 + k).sample(CANDIDATES, len(CANDIDATES))  # noqa: S311
        seen: dict[str, str] = {}
        groups[str(k)] = (_image_head(f"Photograph {k}", f"pages/photo-{k}.jpg"), "")
        for i, model in enumerate(order, start=1):
            text = _text(cache, row, model, dpi=RESOLUTION)
            if not re.search(r"[A-Za-z0-9]{2,}", text):
                continue
            number = 10 * k + i
            sheet[number] = {"k": k, "model": model}
            letter = LETTERS[i - 1]
            cards.append(
                Card(
                    row=number,
                    body_html=(
                        f'<p class="meta">Photograph {k}, version {letter}'
                        + _same_as(seen, text, letter)
                        + f"</p><pre>{html.escape(text)}</pre>"
                    ),
                    choices=(_PHOTO_WORDS,),
                    group=str(k),
                )
            )
    return sheet, cards, groups


def cmd_photos(settings: Settings) -> str:
    """Andy's page: every word any candidate wrote for a no-word photograph."""
    folder = settings.data_dir / FOLDER
    sheet, cards, groups = _photo_cards(settings)
    (folder / "photos.json").write_text(json.dumps(sheet))
    intro = (
        _GROUPED_LAYOUT + "<p>Each photograph is shown once on the left, held in view, with the "
        "words each transcriber wrote for it as cards on the right, one per version. Most will "
        "be real (a registration, a placard). Mark <b>some invented</b> if any word is not on "
        "the page. Click a photograph to enlarge it.</p>"
    )
    (folder / "photos.html").write_text(
        marking_page.render(
            title="Invented words on photographs (S2.6 spec §7.3)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-photo-words",
            csv_name="photo-words.csv",
            groups=groups,
        )
    )
    return f"{len(cards)} outputs with words; page at {folder / 'photos.html'}"


def invented_rows(photo_marks: Mapping[int, Mapping[str, str]]) -> list[int]:
    """Photograph cards the first pass marked "some invented": the ones 0086 item 1 re-marks."""
    return sorted(n for n, fields in photo_marks.items() if fields.get("words") == "some invented")


def cmd_photos_recheck(settings: Settings) -> str:
    """Decision 0086 item 1: only the cards first marked "some invented", re-marked.

    The cards are rebuilt as the first pass built them and must carry the same row numbers
    for the same photograph and model as ``photos.json``; if they no longer do, the page is
    refused rather than shown against the wrong rows.
    """
    folder = settings.data_dir / FOLDER
    stored = json.loads((folder / "photos.json").read_text())
    first = marking_page.read_marks(folder / PASS1 / "photo-words.csv")
    rows = set(invented_rows(first))
    sheet, cards, groups = _photo_cards(settings)
    drifted = sorted(n for n in rows if n not in sheet or sheet[n] != stored.get(str(n)))
    if drifted:
        raise ConfigurationError(
            f"photograph card row(s) {drifted} no longer match photos.json: the recheck page "
            "would not mark the outputs the first pass marked"
        )
    kept = [card for card in cards if card.row in rows]
    intro = (
        _GROUPED_LAYOUT + "<p><b>Second pass (decision 0086).</b> These are the "
        f"{len(kept)} outputs you marked <b>some invented</b> in the first pass; mark each "
        "again under one corrected rule. A word printed on the page as part of the docket's "
        "photo label counts as on the page, even when the icon hides part of it (for example "
        '"Photo", whose "Pho" the icon covers). Anything else is judged as before: a misread '
        "registration is still invented. Mark <b>some invented</b> if any other word is not on "
        "the page. Click a photograph to enlarge it.</p>"
    )
    (folder / "photos-recheck.html").write_text(
        marking_page.render(
            title="Invented words on photographs, second pass (S2.6, decision 0086)",
            intro_html=intro,
            cards=kept,
            storage_key="s26-photo-words-pass2",
            csv_name="photo-words-pass2.csv",
            groups={card.group: groups[card.group] for card in kept},
        )
    )
    return f"{len(kept)} outputs to re-mark; page at {folder / 'photos-recheck.html'}"


def cmd_mixed(settings: Settings, docs: CachedDocuments) -> str:
    """Andy's page (decision W7): the words each candidate added to a full-page scan."""
    folder = settings.data_dir / FOLDER
    rows = [r for r in _read(folder / "keys.jsonl") if r["set"] == "mixed"]
    cache = TranscriptionCache(settings.transcription_dir)
    sheet: dict[int, dict[str, object]] = {}
    cards: list[Card] = []
    groups: dict[str, tuple[str, str]] = {}
    for row in rows:
        k = _int(row, "k")
        data = docs.document(_int(row, "mkey"), _int(row, "document"))
        layer = page_text(data, _int(row, "page"))
        order = random.Random(SEED + 200 + k).sample(CANDIDATES, len(CANDIDATES))  # noqa: S311
        seen: dict[str, str] = {}
        groups[str(k)] = (
            _image_head(f"Full-page scan {k}", f"pages/mixed-{k}.jpg"),
            f'<p>The page\'s text layer:</p><pre class="layer">{html.escape(layer)}</pre>',
        )
        for i, model in enumerate(order, start=1):
            text = _text(cache, row, model, dpi=RESOLUTION)
            if not re.search(r"[A-Za-z0-9]{2,}", text):
                continue
            number = 10 * k + i
            sheet[number] = {"k": k, "model": model}
            letter = LETTERS[i - 1]
            cards.append(
                Card(
                    row=number,
                    body_html=(
                        f'<p class="meta">Full-page scan {k}, version {letter}'
                        + _same_as(seen, text, letter)
                        + "</p><p>Words this version added:</p>"
                        + f"<pre>{_against_layer(text, layer)}</pre>"
                    ),
                    choices=(
                        Choice(
                            "added words",
                            ("all on the page and new", "repeats the text layer", "some invented"),
                        ),
                    ),
                    group=str(k),
                )
            )
    (folder / "mixed.json").write_text(json.dumps(sheet))
    intro = (
        _GROUPED_LAYOUT + "<p>Each scanned page is shown once on the left, held in view. On the "
        "right are its machine-read text layer and the words each transcriber added, one card "
        "per version. Added words are coloured: "
        '<span class="inlayer">already in the text layer</span>, '
        '<span class="new">not in the text layer (check against the image)</span>. '
        "Mark <b>some invented</b> if any added word is not on the page; <b>repeats the text "
        "layer</b> if the added words are already in the text layer; otherwise <b>all on the "
        "page and new</b>. Click the image to enlarge it.</p>"
    )
    (folder / "mixed.html").write_text(
        marking_page.render(
            title="Words added to full-page scans (S2.6, decision W7)",
            intro_html=intro,
            cards=cards,
            storage_key="s26-mixed-words",
            csv_name="mixed-words.csv",
            groups=groups,
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
    format_gate: bool = False,
) -> CandidateResult:
    """One candidate's counts. ``format_gate`` applies decision 0086 item 2 (second pass).

    With it, a handwriting page whose transcribed reply has fewer than half the key's lines
    counts as wrong for this model (none of its lines right) and is counted as format-failed;
    its lines still count towards the invented lines, exactly as any other page's. A failed
    reading (controller ruling on 0086, fix round 1, I1) is scored as wrong through decision
    3's path -- ``_text`` gives it no lines -- and is never counted as a format failure: it
    returned no reply to judge the format of.
    """
    hw_lines = hw_right = hw_inventing = hw_pages = hw_format_failed = 0
    for row in (r for r in keys if r["set"] == "handwriting"):
        key_text = key_texts[_int(row, "k")]
        key_lines = lines_of(key_text)
        version = lines_of(_text(cache, row, model, dpi=dpi))
        record = cache.get(_key(row, model, instruction=TRANSCRIBE, dpi=dpi))
        transcribed = record is not None and record.status == "transcribed"
        hw_pages += 1
        hw_lines += len(key_lines)
        hw_inventing += inventing_lines(key_text, version)
        if format_gate and transcribed and format_failed(key_lines, version):
            hw_format_failed += 1
        else:
            hw_right += line_hits(key_lines, version)
    typed_chars = typed_errs = 0
    for row in (r for r in keys if r["set"] == "typed"):
        errors, chars = typed_errors(
            typed_answers[_int(row, "k")], _text(cache, row, model, dpi=dpi)
        )
        typed_errs += errors
        typed_chars += chars
    readings = [
        cache.get(_key(r, model, instruction=TRANSCRIBE, dpi=dpi, mixed=r["set"] == "mixed"))
        for r in keys
    ]
    # Fix round 1, I2: a failed reading still cost real money (docket/transcribe.py keeps the
    # cost of any call that got a reply back), so it counts here too -- excluding it would
    # make a model that fails often look artificially cheap.
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
        hw_pages=hw_pages,
        hw_format_failed=hw_format_failed,
    )


_KEY_SETS = ("typed", "handwriting", "photo", "mixed")


@dataclass(frozen=True)
class ReadingCounts:
    """One key set's pages with no cached reading, and pages whose reading failed.

    Fix round 2 (Andy, "count it as wrong"): a page a candidate still failed to read after
    ``run --retry-failed`` is scored as wrong for that candidate, not held back from scoring --
    only a page with no reading at all (never attempted) still blocks `score` (``incomplete``).
    """

    missing: int
    failed: int

    @property
    def incomplete(self) -> int:
        """Pages with no reading at all: the only thing that still blocks scoring."""
        return self.missing


def _reading_counts(
    cache: TranscriptionCache, keys: Sequence[Mapping[str, object]], model: str, *, dpi: int
) -> dict[str, ReadingCounts]:
    """Per key set, pages with no reading and pages whose reading failed (fix round 1, I2).

    Fix round 2 (Andy): a failed reading counts as wrong for that candidate rather than
    blocking scoring; only a missing reading (never attempted) still does. Both are counted
    and printed either way, so nothing is silently scored without a visible count behind it.
    """
    counts: dict[str, ReadingCounts] = {}
    for set_name in _KEY_SETS:
        missing = failed = 0
        for row in (r for r in keys if r["set"] == set_name):
            record = cache.get(
                _key(row, model, instruction=TRANSCRIBE, dpi=dpi, mixed=set_name == "mixed")
            )
            if record is None:
                missing += 1
            elif record.status == "failed":
                failed += 1
        counts[set_name] = ReadingCounts(missing=missing, failed=failed)
    return counts


def _choose_or_hold(
    reading_counts: Mapping[str, Mapping[str, ReadingCounts]], results: Sequence[CandidateResult]
) -> tuple[str | None, list[str]]:
    """Hold off `choose` while any candidate has a page with no reading at all.

    Fix round 1, I2; narrowed by fix round 2's "count it as wrong". A page never attempted
    (no cached record at all) still holds off scoring: nothing is known
    about it, so there is nothing to score. A page a candidate *tried* and failed -- even after
    `run --retry-failed` -- is different: Andy's decision is to count it as wrong for that
    candidate (`_result` already does, since `_text` returns "" for a failed reading, exactly
    the same as a blank one) rather than hold up scoring on a persistent failure.
    """
    incomplete = {
        m: counts for m, counts in reading_counts.items() if any(c.missing for c in counts.values())
    }
    if not incomplete:
        return choose(results)
    total_missing = sum(c.missing for counts in incomplete.values() for c in counts.values())
    return None, [
        f"not chosen: {total_missing} page(s) across {len(incomplete)} of "
        f"{len(CANDIDATES)} candidates have no reading at all -- run `transcriber_test run` "
        "and score again"
    ]


def _readings_lines(reading_counts: Mapping[str, Mapping[str, ReadingCounts]]) -> list[str]:
    """One line per candidate: missing and failed readings, per key set (fix round 1, I2)."""
    return [
        "  "
        + m
        + ": "
        + ", ".join(
            f"{name} {c.missing} missing/{c.failed} failed" for name, c in reading_counts[m].items()
        )
        for m in CANDIDATES
    ]


def _handwriting_key_summary(
    pages: Mapping[str, Mapping[str, object]],
    key_texts: Mapping[int, str],
    hw_marks: Mapping[int, Mapping[str, str]],
) -> tuple[int, int, int, int, int]:
    """Every handwriting page's key line counts (spec §17; fix round 1, M2 adds the last).

    Returns (picked, typed, spot total, spot wrong, spot-answer mismatches).
    """
    spot_total = spot_changed = picked = typed_lines = spot_answer_mismatches = 0
    for k, page in pages.items():
        key_lines = Counter(lines_of(key_texts[int(k)]))
        page_spot = cast("list[str]", page.get("spot", []))
        spot_total += len(page_spot)
        page_wrong = sum(1 for line in page_spot if key_lines[line] == 0)
        spot_changed += page_wrong
        if page_spot:
            # Fix round 1, M2: Andy's own spot-check answer, read and checked against the
            # computed outcome rather than left unread.
            answer = hw_marks.get(int(k), {}).get("spot check", "")
            said_wrong = answer == "some wrong, fixed in the key"
            if said_wrong != (page_wrong > 0):
                spot_answer_mismatches += 1
        seen = {
            line
            for lines in cast("dict[str, list[str]]", page["versions"]).values()
            for line in lines
        }
        for line in key_lines.elements():
            if line in seen:
                picked += 1
            else:
                typed_lines += 1
    return picked, typed_lines, spot_total, spot_changed, spot_answer_mismatches


@dataclass(frozen=True)
class Recheck:
    """Decision 0086's second pass: Andy's two recheck CSVs, applied over the first pass's."""

    handwriting_csv: Path
    photos_csv: Path


FIRST_PASS_RESULTS = Path("docs/results/s26-transcriber-test.txt")
PASS2_HEADER = "# the transcriber test -- SECOND PASS (post-hoc, decision 0086)"


def overridden(
    first: Mapping[int, Mapping[str, str]], recheck: Mapping[int, Mapping[str, str]]
) -> dict[int, dict[str, str]]:
    """First-pass marks, overridden row by row by a recheck's (decision 0086).

    A row the recheck holds takes the recheck's value for every field the recheck has; the
    first pass's other fields on that row (a handwriting page's spot check) stay. Every other
    row is the first pass's, unchanged.
    """
    return {
        row: {**first.get(row, {}), **recheck.get(row, {})}
        for row in sorted(first.keys() | recheck.keys())
    }


def _apply_recheck(
    pages: Mapping[str, Mapping[str, object]],
    hw_marks: Mapping[int, Mapping[str, str]],
    photo_marks: Mapping[int, Mapping[str, str]],
    recheck: Recheck,
) -> tuple[dict[int, dict[str, str]], dict[int, dict[str, str]], list[str]]:
    """The final handwriting and photograph marks, and the second pass's header lines.

    Refuses a recheck CSV that does not hold exactly the rows decision 0086 re-marks -- the
    draft-anchored handwriting pages and the photograph cards first marked "some invented",
    both judged from the first-pass CSVs given -- or that leaves any of them unmarked.
    """
    anchored = draft_anchored(pages, hw_marks)
    invented = invented_rows(photo_marks)
    hw_again = marking_page.read_marks(recheck.handwriting_csv)
    photo_again = marking_page.read_marks(recheck.photos_csv)
    if sorted(hw_again) != anchored:
        raise SystemExit(
            f"the handwriting recheck holds page(s) {sorted(hw_again)}, not the first pass's "
            f"draft-anchored page(s) {anchored}"
        )
    if sorted(photo_again) != invented:
        raise SystemExit(
            f"the photograph recheck holds {len(photo_again)} row(s), not the {len(invented)} "
            "the first pass marked some invented"
        )
    unmarked = [
        k
        for k in anchored
        if not hw_again[k].get("key", "").strip() or not hw_again[k].get(_KEY_CHECKED.name)
    ]
    if unmarked:
        raise SystemExit(f"handwriting recheck unmarked or empty for page(s): {unmarked}")
    if any(not photo_again[n].get(_PHOTO_WORDS.name) for n in invented):
        raise SystemExit("some photograph recheck outputs are unmarked")
    final_hw = overridden(hw_marks, hw_again)
    final_photo = overridden(photo_marks, photo_again)
    keys_changed = {
        k for k in anchored if lines_of(final_hw[k]["key"]) != lines_of(hw_marks[k]["key"])
    }
    said_changed = {
        k for k in anchored if hw_again[k][_KEY_CHECKED.name] == _KEY_CHECKED.options[1]
    }
    marks_changed = sum(1 for n in invented if final_photo[n]["words"] != photo_marks[n]["words"])
    header = [
        PASS2_HEADER,
        "corrections (decision 0086, fixed before re-marking): 1. a word of the docket's "
        'stamped photo label ("Photo"), even partly hidden by the icon, is on the page; '
        "2. a reply with fewer than half the key's lines fails that handwriting page, and more "
        "than 1 in 20 such pages is out; 3. the draft-anchored handwriting keys are re-checked",
        f"re-marked: {len(invented)} photograph cards ({marks_changed} marks changed); "
        f"{len(anchored)} handwriting pages ({len(keys_changed)} keys changed; "
        f"{len(keys_changed ^ said_changed)} pages where Andy's own answer disagrees)",
        f"the first pass stands unchanged in {FIRST_PASS_RESULTS}",
        "",
    ]
    return final_hw, final_photo, header


def _candidate_lines(r: CandidateResult, mixed_repeats: int, *, pass2: bool) -> list[str]:
    """One candidate's section of the results file; the second pass adds its format count."""
    price = sources.price_of(r.model)
    low, high = wilson(r.hw_right, r.hw_lines)
    lines = [
        f"## {r.model} (${price.input_usd_per_mtok}/${price.output_usd_per_mtok} per M "
        f"tokens; measured ${r.cost_per_page:.5f} per test page)",
        f"  invented: {r.hw_inventing} lines ({r.invented_per_100_lines:.1f} per 100 "
        f"handwriting lines); {r.photo_invented} of {r.photo_pages} photographs",
        f"  handwriting lines right: {r.hw_right} of {r.hw_lines} ({r.hw_accuracy:.1%} "
        f"[{low:.1%}, {high:.1%}], Wilson 95%, lines not independent)",
        f"  typed errors: {r.typed_errors_per_100:.2f} per 100 characters "
        f"({r.typed_errors} of {r.typed_chars})",
        f"  full-page scans (decision W7): invented added words on {r.mixed_invented} of "
        f"{r.mixed_pages}; repeated the text layer on {mixed_repeats}",
    ]
    if pass2:
        lines.append(
            "  format-failed handwriting pages (decision 0086: a transcribed reply with fewer "
            "than half the key's lines, scored as wrong; a failed reading is scored as wrong "
            f"but not counted here): {r.hw_format_failed} of {r.hw_pages}"
        )
    return lines


def _with_override(
    chosen: str | None, notes: list[str], override: str | None
) -> tuple[str | None, list[str]]:
    """The model the resolution comparison is for, and the rule's notes with any override.

    Decision 0087: only when the rule chose none does an override name a model, and it is
    recorded as its own line, after the rule's unchanged outcome.
    """
    if chosen is not None or override is None:
        return chosen, notes
    return override, [
        *notes,
        f"decision 0087 (post hoc): {override} chosen provisionally, overriding the rule's "
        "outcome; the dev-400 B-v1 against B-v2 comparison decides whether v2 goes forward",
    ]


def cmd_score(  # noqa: PLR0913 -- the three first-pass sheets, and the second pass's rechecks.
    settings: Settings,
    docs: CachedDocuments,
    handwriting_csv: Path,
    photos_csv: Path,
    mixed_csv: Path,
    *,
    recheck: Recheck | None = None,
    override: str | None = None,
) -> str:
    """Apply the rule to every candidate; add the resolution comparison once it has run.

    ``override`` (decision 0087) names a transcriber chosen after the rule chose none: the
    rule's outcome is printed unchanged, a line records the override, and the resolution
    comparison is made for that model, labelled as the override's.

    With ``recheck`` (decision 0086's second pass), the first-pass marks are overridden row by
    row by the recheck CSVs, handwriting pages are scored with the format rule, and the text
    starts with the second pass's header.
    """
    folder = settings.data_dir / FOLDER
    keys = _read(folder / "keys.jsonl")
    cache = TranscriptionCache(settings.transcription_dir)
    pages = json.loads((folder / "handwriting.json").read_text())
    photo_sheet = json.loads((folder / "photos.json").read_text())
    hw_marks: Mapping[int, Mapping[str, str]] = marking_page.read_marks(handwriting_csv)
    photo_marks: Mapping[int, Mapping[str, str]] = marking_page.read_marks(photos_csv)
    header: list[str] = []
    if recheck is not None:
        hw_marks, photo_marks, header = _apply_recheck(pages, hw_marks, photo_marks, recheck)
    unmarked = [n for n in photo_sheet if photo_marks.get(int(n), {}).get("words") == ""]
    if unmarked or len(photo_marks) < len(photo_sheet):
        raise SystemExit("some photograph outputs are unmarked")
    mixed_sheet = json.loads((folder / "mixed.json").read_text())
    mixed_marks = marking_page.read_marks(mixed_csv)
    if any(mixed_marks.get(int(n), {}).get("added words", "") == "" for n in mixed_sheet):
        raise SystemExit("some full-page scan outputs are unmarked")
    # Fix round 1, M2: a page missing from the handwriting CSV altogether used to raise a bare
    # KeyError below, naming no page; an empty key box (Andy never touched it) used to count
    # silently as a page of zero lines. Both are refused here, by page number.
    missing_hw = sorted(
        int(k) for k in pages if not hw_marks.get(int(k), {}).get("key", "").strip()
    )
    if missing_hw:
        raise SystemExit(f"handwriting key is missing or empty for page(s): {missing_hw}")
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
            format_gate=recheck is not None,
        )
        for m in CANDIDATES
    ]
    reading_counts = {m: _reading_counts(cache, keys, m, dpi=RESOLUTION) for m in CANDIDATES}
    chosen, notes = _choose_or_hold(reading_counts, results)
    resolved, notes = _with_override(chosen, notes, override)
    picked, typed_lines, spot_total, spot_changed, spot_answer_mismatches = (
        _handwriting_key_summary(pages, key_texts, hw_marks)
    )
    # Fix round 2, C2: how many handwriting key pages came from the inventory's own handwriting
    # label against the pilot-form top-up, and by the label that admitted each.
    hw_sources = Counter(
        (str(r.get("source", "inventory")), str(r.get("page_kind", "handwriting")))
        for r in keys
        if r["set"] == "handwriting"
    )
    hw_sources_line = ", ".join(
        f"{n} {source} ({label})" for (source, label), n in sorted(hw_sources.items())
    )
    lines = [
        *header,
        "# the transcriber test (S2.6 spec §7, decision 0080) -- counts only",
        f"keys: {sum(1 for r in keys if r['set'] == 'typed')} typed pages, "
        f"{len(pages)} handwriting pages ({sum(r.hw_lines for r in results[:1])} key lines), "
        f"{results[0].photo_pages} no-word photographs; {RESOLUTION} dpi; instruction "
        f"{TRANSCRIBE.version}; standard prices (images cannot be batched)",
        f"handwriting key sources (fix round 2, C2): {hw_sources_line}",
        f"handwriting key: {picked} lines picked from a version, {typed_lines} typed by Andy; "
        f"spot check of agreed lines: {spot_changed} of {spot_total} wrong in all four "
        f"({spot_answer_mismatches} pages where Andy's own spot-check answer disagrees)",
        "",
        "## readings (fix round 1, I2)",
        *_readings_lines(reading_counts),
        "",
    ]
    for r in results:
        lines += _candidate_lines(
            r, mixed_by_mark[(r.model, "repeats the text layer")], pass2=recheck is not None
        )
    lines += ["", "## the rule", *notes]
    if resolved is not None:
        # Fix round 3, R2: the resolution comparison only reads the handwriting and typed
        # keys at 200 dpi (`cmd_run`'s own filter). A reading missing there must refuse the
        # same way `score` does at 150 dpi (decision 3): an interrupted resolution run's
        # unread pages would otherwise score as empty, silently pushing the choice to 150 dpi.
        resolution_keys = [r for r in keys if r["set"] in ("handwriting", "typed")]
        missing_200 = sum(
            1
            for r in resolution_keys
            if cache.get(_key(r, resolved, instruction=TRANSCRIBE, dpi=200)) is None
        )
        if missing_200 == len(resolution_keys):
            pass  # the resolution comparison has not been run yet: say nothing
        elif missing_200:
            lines += [
                "",
                "## resolution (spec §7.5)",
                f"  resolution: not decided -- {missing_200} pages have no reading at 200 dpi",
            ]
        else:
            at_200 = _result(
                resolved,
                keys,
                key_texts,
                0,
                typed_answers,
                cache,
                dpi=200,
                format_gate=recheck is not None,
            )
            base = next(r for r in results if r.model == resolved)
            # Fix round 1, I7: exact fractions from the raw line counts, not the pre-divided
            # floats -- an exact 5-point gap must not be misjudged by floating-point error.
            base_acc = _fraction(base.hw_right, base.hw_lines)
            at_200_acc = _fraction(at_200.hw_right, at_200.hw_lines)
            dpi = choose_resolution(base_acc, at_200_acc)
            lines += [
                "",
                "## resolution (spec §7.5)"
                + (" -- for decision 0087's override" if chosen is None else ""),
                f"  {resolved}: handwriting {float(base_acc):.1%} at 150 dpi, "
                f"{float(at_200_acc):.1%} at 200; typed errors {base.typed_errors_per_100:.2f} "
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
    if not records:
        raise ConfigurationError(
            "no finished heldout-400 arm B run under NTSB_RUNS_DIR; `estimate` needs one to "
            "price v3 against the S2.4 bar"
        )
    latest = max(records, key=lambda r: r.started)
    return latest.cost_usd / latest.cases


def _stage_commits(repo: Path = Path()) -> frozenset[str]:
    """S2.6's own commits, full SHAs: ``git rev-list STAGE_BASE..HEAD`` (fix round 4, T1).

    Refuses rather than guesses when git cannot answer: without the list, no spend can be
    attributed to the stage, and a stage total built on a guess is worse than none.
    """
    try:
        return frozenset(commits_since(STAGE_BASE, repo))
    except (OSError, subprocess.CalledProcessError) as error:
        raise ConfigurationError(
            f"`estimate` needs git to list S2.6's commits (`git rev-list {STAGE_BASE}..HEAD`) "
            f"and git could not: {error}; run it from the repository with git on PATH"
        ) from error


def _in_stage(sha: str, stage_commits: Collection[str]) -> bool:
    """Whether a recorded (usually abbreviated) commit is one of the stage's full SHAs."""
    return len(sha) >= MIN_SHA_PREFIX and any(full.startswith(sha) for full in stage_commits)


def _estimate_verdict(stage_total: float, rest: float, headroom: float, budget: float) -> str:
    """Apply both decision 0083 item 2's stage-total test and fix round 1's headroom test.

    Either can fail on its own -- for example when ``estimate`` runs in a later month than
    most of S2.6's spend (fix round 3, R3).
    """
    over_stage = stage_total > budget
    over_headroom = rest > headroom
    if not (over_stage or over_headroom):
        return (
            f"fits: stage total ${stage_total:.2f} within ${budget:.0f}, remaining ${rest:.2f} "
            f"within the month's ${headroom:.2f} headroom"
        )
    reasons = []
    if over_stage:
        reasons.append(
            f"the stage total ${stage_total:.2f} passes the ${budget:.0f} stage line "
            "(decision 0083 item 2)"
        )
    if over_headroom:
        reasons.append(
            f"the remaining ${rest:.2f} does not fit the month's ${headroom:.2f} headroom"
        )
    return "pause: ask Andy -- " + "; ".join(reasons)


def cmd_estimate(
    settings: Settings,
    transcriber: str,
    dpi: int,
    *,
    stage_commits: Collection[str] | None = None,
) -> str:
    """Decision 0083 item 2: both the stage total and the remaining spend, judged separately.

    Fix round 1, I5 judged only the second (``settings.monthly_budget_usd - month_spent(...)``
    minus open reservations), which by itself can miss decision 0083 item 2's own test: if
    ``estimate`` runs in a later month than most of S2.6's spend, the month's headroom looks
    almost untouched while the stage total is well past $40. Fix round 3, R3 restores the
    stage-total test alongside it, naming whichever test fails. Fix round 4, T1: the stage's
    spend so far is every spend row and run record whose commit is one of ``stage_commits``
    (by default, ``git rev-list STAGE_BASE..HEAD``; tests pass their own list).
    """
    commits = _stage_commits() if stage_commits is None else stage_commits
    s26 = settings.data_dir / "s26"
    now = datetime.now(UTC)
    month = month_spent(settings.runs_dir, now=now)
    reserved = sum(open_reservations(settings.runs_dir).values())
    headroom = settings.monthly_budget_usd - month - reserved
    stage_spent = sum(
        s.cost_usd
        for path in sorted(settings.runs_dir.glob(f"*/{SPEND_FILE}"))
        for s in read_jsonl(path, SpendRecord)
        if _in_stage(s.commit_sha, commits)
    )
    # Fix round 3, R3: S2.6's own evaluation runs (the reply-budget runs, Task 9A) are not
    # preparation spend rows, so they were missing from the stage total entirely.
    stage_runs = sum(
        record.cost_usd
        for path in sorted(settings.runs_dir.glob("*/run.jsonl"))
        for record in read_jsonl(path, RunRecord)
        if _in_stage(record.commit_sha, commits)
    )
    frame = _read(s26 / "pages-dev-400.jsonl")
    sample = _read(s26 / "inventory" / "sample.jsonl")
    mixed = [r for r in sample if str(r["stratum"]).startswith("text and image")]
    sent_share = sum(
        1 for r in mixed if float(str(r["image_area_share"])) >= MIXED_PAGE_MIN_IMAGE_SHARE
    ) / max(1, len(mixed))
    image_only = sum(1 for r in frame if r["kind"] == "image only")
    text_and_image = sum(1 for r in frame if r["kind"] == "text and image")
    # The frame's own case count (fix round 1, I5): dev-400 has 401 sample cases, but only the
    # ones with a fetched docket contribute a page here -- 395, not 401, at the time of writing.
    cases_with_dockets = len({r["case_id"] for r in frame}) or 1
    dev_pages = image_only + round(text_and_image * sent_share)
    cache = TranscriptionCache(settings.transcription_dir)
    keys = _read(settings.data_dir / FOLDER / "keys.jsonl")
    readings = [
        cache.get(_key(r, transcriber, instruction=TRANSCRIBE, dpi=dpi, mixed=r["set"] == "mixed"))
        for r in keys
    ]
    reading_costs = [r.cost_usd for r in readings if r is not None]
    if not reading_costs:
        raise ConfigurationError(
            f"no cached {transcriber!r} reading at {dpi} dpi under NTSB_DATA_DIR; run `run` "
            "(and, at 200 dpi, `resolution`) first"
        )
    per_page = statistics.mean(reading_costs)  # fix round 1, I2: a failed reading's cost counts
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
            cache.get(_key(row, AGENT_MODEL, instruction=TRANSCRIBE, dpi=RESOLUTION))
            for row in keys
            if row["set"] == "photo"
        )
        if r is not None
    ]
    if not luna_photo_tokens:
        raise ConfigurationError(
            "no cached GPT-6 Luna reading of a photo key page under NTSB_DATA_DIR; run `run` "
            "first (v3's token estimate needs at least one)"
        )
    image_tokens = statistics.median(luna_photo_tokens) - len(TRANSCRIBE.system) / 4
    images_per_case = (image_only + text_and_image) * picture_share / cases_with_dockets
    luna = sources.price_of(AGENT_MODEL)
    v3 = 401 * (2 * b_case + 2 * images_per_case * image_tokens * luna.input_usd_per_mtok / 1e6)
    rest = (
        transcription + runs + v3
    )  # what remains to spend, not yet in month_spent or stage_so_far
    stage_so_far = stage_spent + stage_runs
    stage_total = stage_so_far + rest
    verdict = _estimate_verdict(stage_total, rest, headroom, settings.monthly_budget_usd)
    return "\n".join(
        [
            f"month spent so far: ${month:.2f}; open reservations: ${reserved:.2f}; headroom "
            f"against the ${settings.monthly_budget_usd:.0f} budget: ${headroom:.2f}",
            f"spent on S2.6 so far: ${stage_so_far:.2f} (${stage_spent:.2f} preparation spend "
            f"rows, ${stage_runs:.2f} evaluation runs; counted by commit, the "
            f"{len(commits)} commits since the S2.4 merge {STAGE_BASE})",
            f"dev-400 pages to transcribe: {image_only} image-only + {sent_share:.0%} of "
            f"{text_and_image} text-and-image = {dev_pages}; held-out assumed the same",
            f"{transcriber} at {dpi} dpi: ${per_page:.5f} per page measured; transcription of "
            f"both samples ${transcription:.2f}",
            f"arm B runs (dev B-v1, B-v2, B-v2 standard; held-out B-v1, B-v2) at "
            f"${b_case:.5f} per case (latest heldout-400 arm B run): ${runs:.2f}, a floor",
            f"v3 probe: {images_per_case:.1f} picture pages per case ({cases_with_dockets} cases "
            f"with a docket) at {image_tokens:.0f} tokens each, GPT-6 Luna standard: ${v3:.2f}",
            f"stage rest to spend: ${rest:.2f}; stage total: ${stage_total:.2f} -- {verdict}",
        ]
    )


def _recheck_of(parser: argparse.ArgumentParser, args: argparse.Namespace) -> Recheck | None:
    """``score``'s second-pass arguments (decision 0086), refused unless complete and safe.

    ``--pass2`` needs both recheck CSVs, the recheck CSVs need ``--pass2``, and a second pass
    may never be written over the first pass's published results file.
    """
    rechecks = (args.handwriting_recheck, args.photos_recheck)
    if not args.pass2:
        if any(rechecks):
            parser.error("--handwriting-recheck and --photos-recheck need --pass2")
        return None
    if not all(rechecks):
        parser.error("--pass2 needs --handwriting-recheck and --photos-recheck")
    if args.out is not None and args.out.name == FIRST_PASS_RESULTS.name:
        parser.error(f"the first pass's {FIRST_PASS_RESULTS} is never rewritten by --pass2")
    return Recheck(handwriting_csv=args.handwriting_recheck, photos_csv=args.photos_recheck)


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="transcriber_test")
    commands = parser.add_subparsers(dest="command", required=True)
    pages_only = {
        "handwriting": cmd_handwriting,
        "photos": cmd_photos,
        "handwriting-recheck": cmd_handwriting_recheck,
        "photos-recheck": cmd_photos_recheck,
    }
    for name in ("probe", "mixed", *pages_only):
        commands.add_parser(name)
    keys_p = commands.add_parser("keys")
    keys_p.add_argument("--force", action="store_true")
    run_p = commands.add_parser("run")
    run_p.add_argument("--retry-failed", action="store_true")
    resolution_p = commands.add_parser("resolution")
    resolution_p.add_argument("--model", required=True, choices=CANDIDATES)
    resolution_p.add_argument("--retry-failed", action="store_true")
    score_p = commands.add_parser("score")
    score_p.add_argument("--handwriting", type=Path, required=True)
    score_p.add_argument("--photos", type=Path, required=True)
    score_p.add_argument("--mixed", type=Path, required=True)
    score_p.add_argument("--out", type=Path)
    score_p.add_argument("--pass2", action="store_true")
    score_p.add_argument("--handwriting-recheck", type=Path)
    score_p.add_argument("--photos-recheck", type=Path)
    score_p.add_argument("--override-model", choices=CANDIDATES)
    estimate_p = commands.add_parser("estimate")
    estimate_p.add_argument("--model", required=True, choices=CANDIDATES)
    estimate_p.add_argument("--dpi", type=int, choices=(150, 200), default=RESOLUTION)
    args = parser.parse_args(argv)
    recheck = _recheck_of(parser, args) if args.command == "score" else None
    settings = Settings()
    # max_attempts=1 (fix round 1, M1, as Task 12's own M1): a cache miss here means a genuine
    # bug, not a transient network fault, and must fail at once rather than sleep through five
    # retries' backoff.
    docs = CachedDocuments(DocketClient(settings.docket_dir, transport=_offline(), max_attempts=1))
    if args.command == "keys":
        text = cmd_keys(settings, docs, force=args.force)
    elif args.command == "probe":
        text = cmd_probe(settings)
    elif args.command == "run":
        text = cmd_run(
            settings, docs, models=CANDIDATES, dpi=RESOLUTION, retry_failed=args.retry_failed
        )
    elif args.command == "resolution":
        text = cmd_run(
            settings, docs, models=(args.model,), dpi=200, retry_failed=args.retry_failed
        )
    elif args.command in pages_only:
        text = pages_only[args.command](settings)
    elif args.command == "mixed":
        text = cmd_mixed(settings, docs)
    elif args.command == "score":
        if args.override_model and recheck is None:
            parser.error("--override-model (decision 0087) follows the second pass: add --pass2")
        text = cmd_score(
            settings,
            docs,
            args.handwriting,
            args.photos,
            args.mixed,
            recheck=recheck,
            override=args.override_model,
        )
        if args.out:
            args.out.write_text(text + "\n")
    else:
        text = cmd_estimate(settings, args.model, args.dpi)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
