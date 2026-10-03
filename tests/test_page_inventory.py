"""scripts/page_inventory.py: the sample, the weights, the cut-off and the stop rule."""

import hashlib
import json
import random
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from scripts import page_inventory as inv
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.transcribe import TranscriptionCache
from ntsb_probable_cause.errors import ConfigurationError, DocketError
from ntsb_probable_cause.model.client import RecordingFakeClient, Usage
from ntsb_probable_cause.scoring.budget import month_spent, open_reservations
from ntsb_probable_cause.settings import Settings


def _frame() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for kind, count in (("image only", 200), ("text and image", 400), ("text only", 300)):
        for i in range(count):
            rows.append(
                {
                    "case_id": f"C{i % 40}",
                    "mkey": i,
                    "fatal": i % 2 == 0,
                    "document": 1,
                    "page": i,
                    "pages": 999,
                    "kind": kind,
                }
            )
    return rows


def test_the_sample_follows_the_allocation_and_the_seed() -> None:
    first = inv.draw_sample(_frame())
    again = inv.draw_sample(_frame())
    assert len(first) == 300
    assert [r["n"] for r in first] == list(range(1, 301))
    assert first == again
    assert sum(1 for r in first if r["stratum"] == "text only/fatal") == 15


def test_photo_only_pages_are_their_own_stratum() -> None:
    """Decision W2: a photograph page is never drawn as an ordinary scan."""
    photos = [
        {
            "case_id": f"P{i}",
            "mkey": i,
            "fatal": i % 2 == 0,
            "document": 9,
            "page": i,
            "pages": 99,
            "kind": "image only",
            "photo_only": True,
        }
        for i in range(40)
    ]
    sample = inv.draw_sample(_frame() + photos)
    assert sum(1 for r in sample if r["stratum"] == "photo-only/fatal") == 15
    assert not any(
        r.get("photo_only")
        for r in sample
        if r["stratum"] != "photo-only/fatal" and r["stratum"] != "photo-only/non-fatal"
    )


def test_weighted_share_weights_each_stratum_by_its_population() -> None:
    labels = {
        "image only/fatal": [("image only", "handwriting"), ("image only", "photograph")],
        "text and image/fatal": [
            ("text and image", "typed text"),
            ("text and image", "typed text"),
        ],
    }
    population = {"image only/fatal": 100, "text and image/fatal": 300}
    assert inv.weighted_word_share(labels, population) == 0.125  # (100 x 1/2 + 0) / 400


def test_a_photo_only_page_holds_words_by_its_own_kind() -> None:
    """Decision A (fix round 2): the photo-only stratum has no single word set of its own --
    each page is judged exactly like an ordinary page of its own kind."""
    # A photo-only page whose own kind is text-and-image: typed text is already in its text
    # layer, so it does not count (same rule as an ordinary text-and-image page).
    assert (
        inv.weighted_word_share(
            {"photo-only/fatal": [("text and image", "typed text")]}, {"photo-only/fatal": 10}
        )
        == 0.0
    )
    # A photo-only page whose own kind is image-only: nothing else holds its typed text.
    assert (
        inv.weighted_word_share(
            {"photo-only/fatal": [("image only", "typed text")]}, {"photo-only/fatal": 10}
        )
        == 1.0
    )
    # A photo-only stratum mixing both kinds is judged page by page, not as one kind.
    mixed = inv.weighted_word_share(
        {
            "photo-only/fatal": [
                ("image only", "typed text"),
                ("text and image", "typed text"),
            ]
        },
        {"photo-only/fatal": 10},
    )
    assert mixed == 0.5


def test_a_non_image_bearing_photo_only_row_takes_no_kind() -> None:
    """Decision A: a text-only or blank photo-only row is drawn and weighted in neither pool."""
    assert inv.sample_kind({"photo_only": True, "kind": "text only"}) is None
    assert inv.sample_kind({"photo_only": True, "kind": "blank"}) is None
    assert inv.sample_kind({"photo_only": True, "kind": "image only"}) == "photo-only"
    assert inv.sample_kind({"photo_only": True, "kind": "text and image"}) == "photo-only"
    assert inv.sample_kind({"kind": "text only"}) == "text only"  # ordinary pages are untouched


def test_photo_only_draw_excludes_non_image_bearing_rows_and_still_totals_330() -> None:
    """Decision A: the photo-only pool never draws a text-only or blank photo-only page, and
    the whole sample still totals 330 and is still deterministic at seed 20260924."""
    photos: list[dict[str, object]] = []
    for i in range(40):
        photos.append(
            {
                "case_id": f"P{i}",
                "mkey": i,
                "fatal": i % 2 == 0,
                "document": 9,
                "page": i,
                "pages": 99,
                "kind": "image only" if i % 2 == 0 else "text and image",
                "photo_only": True,
            }
        )
    excluded: list[dict[str, object]] = []
    for i in range(60):
        excluded.append(
            {
                "case_id": f"Q{i}",
                "mkey": 10_000 + i,  # a mkey range no other row in this frame ever uses
                "fatal": i % 2 == 0,
                "document": 9,
                "page": i,
                "pages": 99,
                "kind": "text only" if i % 2 == 0 else "blank",
                "photo_only": True,
            }
        )
    frame = _frame() + photos + excluded
    first = inv.draw_sample(frame)
    again = inv.draw_sample(frame)
    assert len(first) == 330
    assert first == again
    photo_only_rows = [r for r in first if str(r["stratum"]).startswith("photo-only")]
    assert sum(1 for r in photo_only_rows if r["stratum"] == "photo-only/fatal") == 15
    assert sum(1 for r in photo_only_rows if r["stratum"] == "photo-only/non-fatal") == 15
    assert all(r["kind"] in ("image only", "text and image") for r in photo_only_rows)
    excluded_mkeys = {r["mkey"] for r in excluded}
    assert not any(r["mkey"] in excluded_mkeys for r in first)


def test_the_cut_off_is_the_largest_run_of_admissible_cuts() -> None:
    rows = [(0.01, "logo or letterhead only")] * 58 + [(0.01, "handwriting")]
    rows += [(0.07, "logo or letterhead only")] * 9 + [(0.07, "handwriting")] * 3
    rows += [(0.5, "photograph")] * 10
    assert inv.mixed_cut(rows) == 0.05


def test_no_admissible_cut_sends_every_page() -> None:
    assert inv.mixed_cut([(0.01, "handwriting")] * 5) == 0.0


def test_andys_correction_replaces_the_models_label() -> None:
    marks = {1: {"label": "wrong", "correct label": "handwriting"}, 2: {"label": "right"}}
    assert inv.final_labels({1: "typed text", 2: "blank"}, marks) == {
        1: "handwriting",
        2: "blank",
    }


def test_the_stop_rule() -> None:
    assert inv.stop_outcome(0.09).startswith("stop")
    assert inv.stop_outcome(0.10).startswith("go on")


def test_stop_outcome_prints_enough_precision_near_the_threshold() -> None:
    """Fix round 3, N2: a share that rounds to 10.00% at two decimals must not read that way
    while the text beside it still says "under 10%"."""
    text = inv.stop_outcome(0.09999)
    assert text.startswith("stop")
    assert "10.00%" not in text
    assert "9.999%" in text


def test_allocation_totals_330() -> None:
    """Fix round 1, M10: the 330 the brief's sample section fixes."""
    assert sum(inv.ALLOCATION.values()) == 330


def test_a_cut_with_no_sampled_pages_below_it_is_not_admissible() -> None:
    """Fix round 1, M2: zero evidence is not evidence for the cut, so it stops there."""
    assert inv.mixed_cut([(0.5, "photograph")] * 10) == 0.0


def test_cut_evidence_reports_each_candidate() -> None:
    """Fix round 1, I4: the numbers behind the chosen cut, one row per candidate."""
    rows = [(0.01, "logo or letterhead only")] * 58 + [(0.01, "handwriting")]
    rows += [(0.07, "logo or letterhead only")] * 9 + [(0.07, "handwriting")] * 3
    rows += [(0.5, "photograph")] * 10
    assert inv.cut_evidence(rows) == [
        (0.02, 1, 59, True),
        (0.05, 1, 59, True),
        (0.10, 4, 71, False),
        (0.20, 4, 71, False),
    ]


def test_score_refuses_a_wrong_mark_with_no_correct_label() -> None:
    """Fix round 1, M3: a 'wrong' mark with nothing to replace it is refused, not ignored."""
    marks = {1: {"label": "wrong", "correct label": ""}}
    with pytest.raises(ConfigurationError, match="page"):
        inv.score_text([], {}, marks, {}, 0.0)


def test_score_text_reports_cut_evidence_and_stratum_shares() -> None:
    """Fix round 1: I4 (the cut's evidence), M5 (a zero cut's wording) and M6 (per-stratum
    word share and population weight beside the weighted estimate) on a small fixture."""
    sample: list[dict[str, object]] = [
        {
            "n": 1,
            "stratum": "image only/fatal",
            "kind": "image only",
            "document_sha256": "a" * 64,
            "image_area_share": 1.0,
        },
        {
            "n": 2,
            "stratum": "image only/fatal",
            "kind": "image only",
            "document_sha256": "b" * 64,
            "image_area_share": 1.0,
        },
        {
            "n": 3,
            "stratum": "text and image/fatal",
            "kind": "text and image",
            "document_sha256": "c" * 64,
            "image_area_share": 0.01,
        },
        {
            "n": 4,
            "stratum": "text and image/fatal",
            "kind": "text and image",
            "document_sha256": "d" * 64,
            "image_area_share": 0.01,
        },
        {
            "n": 5,
            "stratum": "text only/fatal",
            "kind": "text only",
            "document_sha256": "e" * 64,
            "image_area_share": 0.0,
        },
    ]
    labels = {
        1: "handwriting",
        2: "typed text",
        3: "logo or letterhead only",
        4: "logo or letterhead only",
        5: "typed text",
    }
    population = {
        "image only/fatal": 200,
        "text and image/fatal": 400,
        "text only/fatal": 300,
    }
    text = inv.score_text(sample, labels, {}, population, 0.01)
    assert "2%: 0 of 2 below the cut hold words (admissible)" in text
    assert "20%: 0 of 2 below the cut hold words (admissible)" in text
    assert "cut: text-and-image pages whose images cover under 20% of the page are not sent" in text
    assert "100.0% hold words" in text  # image only/fatal: handwriting + typed text both count
    assert "0.0% hold words" in text  # text and image/fatal: two logos, neither counts
    assert "33.3% of the weighted estimate" in text  # 200 of 600 (200 + 400)
    assert "66.7% of the weighted estimate" in text  # 400 of 600
    assert "a control stratum, not counted in the weighted estimate" in text  # text only


def test_score_text_prints_no_cut_when_nothing_is_admissible() -> None:
    """Fix round 1, M5: a cut of 0 reads as 'no cut', not 'under 0%'."""
    sample: list[dict[str, object]] = [
        {
            "n": 1,
            "stratum": "text and image/fatal",
            "kind": "text and image",
            "document_sha256": "a" * 64,
            "image_area_share": 0.01,
        },
    ]
    labels = {1: "handwriting"}
    population = {"text and image/fatal": 100}
    text = inv.score_text(sample, labels, {}, population, 0.0)
    assert "no cut: every text-and-image page is sent" in text


def test_undrawable_identifies_a_page_with_no_document_hash() -> None:
    """Fix round 3, N1: a page that failed to render has no ``document_sha256``."""
    assert inv._undrawable({"document_sha256": None}) is True
    assert inv._undrawable({"document_sha256": "a" * 64}) is False


def test_score_text_leaves_an_undrawable_page_out_of_the_cut_off_and_the_word_share() -> None:
    """Fix round 3, N1: a page that failed to render never reaches a stratum's word share or
    the cut-off rows, and never crashes ``score_text`` trying to parse its placeholder as a
    number -- even when Andy's own mark would otherwise have given it a label."""
    sample: list[dict[str, object]] = [
        {
            "n": 1,
            "stratum": "text and image/fatal",
            "kind": "text and image",
            "document_sha256": None,
            "image_area_share": None,
        },
    ]
    marks = {1: {"label": "wrong", "correct label": "handwriting"}}
    population = {"text and image/fatal": 100}
    text = inv.score_text(sample, {}, marks, population, 0.0)  # must not raise
    assert "not drawable: 1" in text
    assert "0 sampled text-and-image pages" in text


def test_undrawable_pages_are_left_out_of_the_label_jobs() -> None:
    """Fix round 3, N1: the page filtered out before ``_jobs`` is built never gets a job."""
    sample: list[dict[str, object]] = [
        {"n": 1, "mkey": 1, "document": 1, "page": 1, "document_sha256": "a" * 64},
        {"n": 2, "mkey": 2, "document": 1, "page": 1, "document_sha256": None},
    ]
    drawable = [r for r in sample if not inv._undrawable(r)]
    documents = _FakeDocuments(build_pdf([PageSpec(text="x")]))
    jobs = inv._jobs(drawable, documents)
    assert len(jobs) == 1
    assert jobs[0].key.document_sha256 == "a" * 64


def test_documents_fails_fast_on_a_cache_miss(tmp_path: Path) -> None:
    """Fix round 1, M1: the shared documents reader must not retry an offline miss."""
    settings = Settings(data_dir=tmp_path)
    documents = inv._documents(settings)
    started = time.monotonic()
    with pytest.raises(DocketError):
        documents.document(999999999, 1)
    assert time.monotonic() - started < 1.0


class _FlakyDocuments:
    """A document source that fails for one mkey and succeeds for every other (M7)."""

    def __init__(self, data: bytes, *, fails: int) -> None:
        self._data = data
        self._fails = fails

    def document(self, mkey: int, index: int) -> bytes:
        if mkey == self._fails:
            raise DocketError("boom: page did not load")
        return self._data


def test_draw_pages_records_a_render_failure_and_continues(tmp_path: Path) -> None:
    """Fix round 1, M7: one page failing to draw does not abort the rest of the sample."""
    doc = build_pdf([PageSpec(text="hello")])
    documents = _FlakyDocuments(doc, fails=2)
    sample: list[dict[str, object]] = [
        {"n": 1, "mkey": 1, "document": 1, "page": 1},
        {"n": 2, "mkey": 2, "document": 1, "page": 1},
        {"n": 3, "mkey": 3, "document": 1, "page": 1},
    ]
    folder = tmp_path / "inventory"
    (folder / "pages").mkdir(parents=True)
    failed = inv._draw_pages(sample, documents, folder)
    assert failed == 1
    assert sample[0]["document_sha256"] is not None
    assert sample[1]["document_sha256"] is None
    assert "render_error" in sample[1]
    assert sample[2]["document_sha256"] is not None
    assert (folder / "pages" / "1.jpg").exists()
    assert not (folder / "pages" / "2.jpg").exists()
    assert (folder / "pages" / "3.jpg").exists()


class _FakeDocuments:
    """A document source that always returns the same bytes, for ``cmd_probe`` (I3)."""

    def __init__(self, data: bytes) -> None:
        self._data = data

    def loader(self, mkey: int, index: int) -> Callable[[], bytes]:
        return lambda: self._data


def _probe_row(document_sha256: str) -> dict[str, object]:
    return {"mkey": 1, "document": 1, "page": 1, "document_sha256": document_sha256}


def test_cmd_probe_runs_through_run_preparation_and_caches_the_page(tmp_path: Path) -> None:
    """Fix round 1, I3: the probe's spend is visible, and the page is cached for `label`."""
    settings = Settings(data_dir=tmp_path)
    doc = build_pdf([PageSpec(text="Engine sputtered.")])
    documents = _FakeDocuments(doc)
    row = _probe_row(hashlib.sha256(doc).hexdigest())
    client = RecordingFakeClient(
        [json.dumps({"page_kind": "typed text"})],
        usage=[Usage(prompt_tokens=100, completion_tokens=10)],
    )
    text, ok = inv.cmd_probe(
        settings, documents, [row], client_factory=lambda stack: lambda: client
    )
    assert ok
    assert "probe: transcribed" in text
    assert month_spent(settings.runs_dir, now=datetime.now(UTC)) > 0
    cache = TranscriptionCache(settings.transcription_dir)
    assert cache.get(inv._key(row)) is not None
    assert open_reservations(settings.runs_dir) == {}


def test_cmd_probe_reports_an_already_cached_page_without_a_second_call(tmp_path: Path) -> None:
    """Fix round 1, I3: a re-run of the probe reads the cache rather than calling again."""
    moment = datetime(2026, 10, 2, tzinfo=UTC)
    settings = Settings(data_dir=tmp_path)
    doc = build_pdf([PageSpec(text="Engine sputtered.")])
    documents = _FakeDocuments(doc)
    row = _probe_row(hashlib.sha256(doc).hexdigest())
    client = RecordingFakeClient(
        [json.dumps({"page_kind": "typed text"})],
        usage=[Usage(prompt_tokens=100, completion_tokens=10)],
    )
    inv.cmd_probe(
        settings,
        documents,
        [row],
        client_factory=lambda stack: lambda: client,
        now=lambda: moment,
    )

    def _must_not_be_called(_stack: object) -> Callable[[], RecordingFakeClient]:
        def make() -> RecordingFakeClient:
            raise AssertionError("a cached page must not be labelled a second time")

        return make

    # A distinct `now` (fix round 3, M9): two jobs of the same kind cannot share one folder,
    # so the second probe -- like any second job -- needs its own second to claim.
    text, ok = inv.cmd_probe(
        settings,
        documents,
        [row],
        client_factory=_must_not_be_called,
        now=lambda: moment + timedelta(seconds=1),
    )
    assert ok
    assert "already cached" in text


def test_cmd_check_writes_the_seeded_60_deterministically(tmp_path: Path) -> None:
    """Fix round 1, M10: `check` writes 60 cards, reproducibly, at seed 20260925."""
    settings = Settings(data_dir=tmp_path)
    folder = settings.data_dir / inv.FOLDER
    folder.mkdir(parents=True)
    sample = [
        {"n": i, "stratum": "image only/fatal", "document_sha256": "a" * 64, "page": i}
        for i in range(1, 331)
    ]
    (folder / "sample.jsonl").write_text("".join(json.dumps(r) + "\n" for r in sample))
    inv.cmd_check(settings)
    first = (folder / "check.html").read_text()
    assert first.count('class="card"') == inv.CHECK_SIZE
    rng = random.Random(inv.CHECK_SEED)  # noqa: S311 -- sampling, not security
    expected = sorted(int(str(r["n"])) for r in rng.sample(sample, inv.CHECK_SIZE))
    assert f'data-row="{expected[0]}"' in first
    assert f'data-row="{expected[-1]}"' in first
    inv.cmd_check(settings)
    second = (folder / "check.html").read_text()
    assert first == second
