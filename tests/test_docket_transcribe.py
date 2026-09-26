"""Transcription: request, reply, cache and pool, with a fake client (S2.6 §8)."""

import hashlib
import json
import threading
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pydantic
import pytest
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket import transcribe as transcribe_module
from ntsb_probable_cause.docket.transcribe import (
    ILLEGIBLE,
    LABEL,
    MIXED_PAGE_MIN_IMAGE_SHARE,
    TRANSCRIBE,
    Instruction,
    PageJob,
    ReadingLookup,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
    pages_to_read,
    parse_reply,
    read_page,
    transcribe_all,
)
from ntsb_probable_cause.errors import ConfigurationError, DocketError, SchemaError
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    RecordingFakeClient,
    Turn,
    Usage,
)

NOW = datetime(2026, 10, 1, tzinfo=UTC)
TYPED = "Engine sputtered at 800 ft. Switched tanks, no change."
DOC = build_pdf([PageSpec(text=TYPED), PageSpec(text=TYPED, images=("/DCTDecode",))])
# A document with enough pages for the pool tests (fix round 1: C1, C2, M1, M2), which need
# more than DOC's two pages of distinct, individually addressable pages.
BIG_DOC = build_pdf([PageSpec(text=TYPED)] * 9)


def _key(
    page: int = 1, model: str = "google/gemini-3.1-flash-lite", *, mixed: bool = False
) -> TranscriptionKey:
    return TranscriptionKey(
        document_sha256="d" * 64,
        page=page,
        model=model,
        instruction="t1+layer" if mixed else "t1",
        dpi=150,
    )


def _reply(text: str, kind: str = "handwriting") -> str:
    return json.dumps({"text": text, "page_kind": kind})


def test_the_instruction_forbids_guessing_and_describing() -> None:
    assert ILLEGIBLE in TRANSCRIBE.system
    assert "never guess" in TRANSCRIBE.system
    assert "Do not describe pictures" in TRANSCRIBE.system
    assert "Copy only words in the page's images" in TRANSCRIBE.mixed_system
    assert "text" in TRANSCRIBE.schema()["properties"]  # type: ignore[operator]
    assert "text" not in LABEL.schema()["properties"]  # type: ignore[operator]


def test_parse_reply_reads_words_and_kind() -> None:
    assert parse_reply(_reply(f"Switched to {ILLEGIBLE} tank"), TRANSCRIBE) == (
        f"Switched to {ILLEGIBLE} tank",
        "handwriting",
    )
    assert parse_reply(_reply("words it was told not to copy", "photograph"), LABEL) == (
        "",
        "photograph",
    )


@pytest.mark.parametrize(
    "content",
    [
        None,
        "not json",
        "[]",
        json.dumps({"text": "x", "page_kind": "poem"}),
        # Fix round 1, I1: a copying instruction's reply must itself carry a 'text' field; a
        # provider that ignores the schema and omits it is refused, not cached as an empty page.
        json.dumps({"page_kind": "typed text"}),
        # A 'text' field of the wrong type is refused too, not coerced.
        json.dumps({"text": 5, "page_kind": "typed text"}),
    ],
)
def test_parse_reply_refuses_a_bad_reply(content: str | None) -> None:
    with pytest.raises(SchemaError):
        parse_reply(content, TRANSCRIBE)


def test_read_page_sends_the_image_and_records_cost_and_kind() -> None:
    client = RecordingFakeClient(
        [_reply("Engine sputtered at 800 ft.")],
        usage=[Usage(prompt_tokens=1000, completion_tokens=20)],
    )
    record = read_page(
        PageJob(_key(), lambda: DOC, mixed=False), client, TRANSCRIBE, now=lambda: NOW
    )
    assert record.status == "transcribed"
    assert record.text == "Engine sputtered at 800 ft."
    assert record.page_kind == "handwriting"
    assert record.cost_usd == pytest.approx((1000 * 0.25 + 20 * 1.50) / 1e6)
    (payload,) = client.payloads
    assert payload.text == ""
    assert len(payload.images) == 1
    assert client.systems == [TRANSCRIBE.system]
    assert client.settings[0].price_variant == "standard"
    assert client.settings[0].reasoning_effort == "minimal"


def test_a_mixed_page_sends_its_own_text_layer_and_the_mixed_instruction() -> None:
    client = RecordingFakeClient([_reply("")])
    read_page(
        PageJob(_key(page=2, mixed=True), lambda: DOC, mixed=True),
        client,
        TRANSCRIBE,
        now=lambda: NOW,
    )
    assert TYPED.split(".", maxsplit=1)[0] in client.payloads[0].text
    assert client.systems == [TRANSCRIBE.mixed_system]


def test_a_mixed_and_a_full_reading_of_the_same_page_get_different_keys() -> None:
    """Fix round 1, I3: the mixed-page instruction changes what is sent, so it must not share
    a cache key with a full reading of the same page (amends decision 0085)."""
    full = _key(page=2)
    mixed = _key(page=2, mixed=True)
    assert full.digest() != mixed.digest()
    assert full.instruction == "t1"
    assert mixed.instruction == "t1+layer"
    assert transcribe_module.key_instruction(TRANSCRIBE, mixed=False) == "t1"
    assert transcribe_module.key_instruction(TRANSCRIBE, mixed=True) == "t1+layer"


def test_a_cached_full_reading_is_never_returned_for_a_mixed_job(tmp_path: Path) -> None:
    """Fix round 1, I3: a cache miss under the mixed key, never the full reading's text."""
    cache = TranscriptionCache(tmp_path)
    full_record = Transcription(
        key=_key(page=2),
        status="transcribed",
        text="full reading",
        page_kind="typed text",
        created=NOW,
    )
    cache.put(full_record, instruction=TRANSCRIBE)
    assert cache.get(_key(page=2, mixed=True)) is None
    assert cache.get(_key(page=2)) == full_record


def test_read_page_refuses_a_full_key_for_a_mixed_job() -> None:
    """Fix round 1, I3: a mixed job's key must carry the ``+layer`` variant."""
    with pytest.raises(ConfigurationError):
        read_page(
            PageJob(_key(page=2), lambda: DOC, mixed=True),  # key names the full instruction
            RecordingFakeClient([_reply("")]),
            TRANSCRIBE,
            now=lambda: NOW,
        )


def test_cache_put_refuses_a_mismatched_mixed_flag(tmp_path: Path) -> None:
    """Fix round 1, I3: the write path checks ``record.mixed`` against the key's variant too."""
    cache = TranscriptionCache(tmp_path)
    record = Transcription(
        key=_key(page=2),
        status="transcribed",
        text="",
        page_kind="blank",
        created=NOW,
        mixed=True,  # the record says it is mixed, but its key names the full instruction
    )
    with pytest.raises(ConfigurationError):
        cache.put(record, instruction=TRANSCRIBE)


def test_a_bad_reply_is_a_failed_page_that_still_costs() -> None:
    client = RecordingFakeClient(["no"], usage=[Usage(prompt_tokens=1000, completion_tokens=5)])
    record = read_page(
        PageJob(_key(), lambda: DOC, mixed=False), client, TRANSCRIBE, now=lambda: NOW
    )
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.startswith("schema:")
    assert record.cost_usd > 0
    assert record.text == ""


def test_the_key_changes_with_model_instruction_and_resolution() -> None:
    base = _key()
    assert base.digest() == _key().digest()
    assert base.digest() != _key(model="google/gemini-3.6-flash").digest()
    assert base.digest() != base.model_copy(update={"instruction": "t2"}).digest()
    assert base.digest() != base.model_copy(update={"dpi": 200}).digest()


def test_the_cache_round_trips(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    record = Transcription(
        key=_key(), status="transcribed", text="x", page_kind="blank", created=NOW
    )
    assert cache.get(_key()) is None
    cache.put(record)
    assert cache.get(_key()) == record


def test_transcribe_all_skips_cached_pages_and_reports_chunks(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    cache.put(
        Transcription(key=_key(1), status="transcribed", text="", page_kind="blank", created=NOW)
    )
    jobs = [PageJob(_key(n), lambda: DOC, mixed=False) for n in (1, 2)]
    chunks: list[int] = []
    made: list[int] = []
    lock = threading.Lock()

    def factory() -> RecordingFakeClient:
        with lock:
            made.append(1)
        return RecordingFakeClient([_reply("words")])

    def on_chunk(records: Sequence[Transcription]) -> None:
        chunks.append(len(records))

    done = transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=2, chunk=1, on_chunk=on_chunk)
    assert [r.key.page for r in done] == [2]
    assert chunks == [1]
    assert cache.get(_key(2)) is not None
    # Fix round 1, I2: this must actually check the factory ran, not just an upper bound that
    # a factory nobody called would also satisfy.
    assert 1 <= len(made) <= 2


def test_a_failed_page_is_retried_only_when_asked(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    cache.put(Transcription(key=_key(1), status="failed", error="model: ModelError", created=NOW))
    jobs = [PageJob(_key(1), lambda: DOC, mixed=False)]
    factory = lambda: RecordingFakeClient([_reply("words")])  # noqa: E731
    assert transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=1) == []
    (again,) = transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=1, retry_failed=True)
    assert again.status == "transcribed"


def test_read_page_records_a_render_failure_with_zero_cost() -> None:
    """Fix round 1, I2: the render-failure path -- a page number ``DOC`` does not have."""
    record = read_page(
        PageJob(_key(page=5), lambda: DOC, mixed=False),
        RecordingFakeClient([_reply("w")]),
        TRANSCRIBE,
        now=lambda: NOW,
    )
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.startswith("load-or-render:")
    assert record.cost_usd == 0.0


def test_a_pool_page_that_fails_after_its_call_still_costs_and_does_not_stop_the_run(
    tmp_path: Path,
) -> None:
    """Fix round 1, C2 and I2: one bad reply mid-pool becomes a failed, costed record, and

    the other pages in the same run still complete. ``workers=1`` keeps job order
    deterministic (a single worker drains its queue FIFO), which is what makes the first
    reply land on page 1 rather than an arbitrary page.
    """
    cache = TranscriptionCache(tmp_path)
    jobs = [PageJob(_key(n), lambda: BIG_DOC, mixed=False) for n in (1, 2, 3)]
    client = RecordingFakeClient(
        ["not json", _reply("w"), _reply("w")],
        usage=[Usage(prompt_tokens=10, completion_tokens=5)] * 3,
    )
    reported: list[Transcription] = []
    done = transcribe_all(
        jobs, lambda: client, cache, TRANSCRIBE, workers=1, on_chunk=reported.extend
    )
    statuses = {r.key.page: r.status for r in done}
    assert statuses == {1: "failed", 2: "transcribed", 3: "transcribed"}
    failed = next(r for r in done if r.key.page == 1)
    assert failed.cost_usd > 0
    assert failed.error is not None
    assert failed.error.startswith("schema:")
    reported_pages = [r.key.page for r in reported]
    assert sorted(reported_pages) == [1, 2, 3]
    assert len(reported_pages) == len(set(reported_pages))


def test_transcribe_all_runs_a_full_pool_without_crashing_pdfium(tmp_path: Path) -> None:
    """Fix round 1, C1: PDFium is not thread-safe; every render must run behind one lock.

    Before the fix, the review's ``pdfium_threads.py`` probe crashed the process 5 times out
    of 5 with 8 concurrent workers rendering distinct pages. This runs the same shape (more
    pending pages than workers, over real PDF bytes) through the real pool.
    """
    cache = TranscriptionCache(tmp_path)
    jobs = [PageJob(_key(n), lambda: BIG_DOC, mixed=False) for n in range(1, 10)]
    client = RecordingFakeClient(
        [_reply("w")] * 9, usage=[Usage(prompt_tokens=10, completion_tokens=5)] * 9
    )
    done = transcribe_all(jobs, lambda: client, cache, TRANSCRIBE, workers=8)
    assert len(done) == 9
    assert all(record.status == "transcribed" for record in done)
    assert {record.key.page for record in done} == set(range(1, 10))


def test_transcribe_all_reports_more_than_one_chunk_and_a_remainder(tmp_path: Path) -> None:
    """Fix round 1, I2: chunking beyond a single chunk, with a smaller remainder at the end."""
    cache = TranscriptionCache(tmp_path)
    jobs = [PageJob(_key(n), lambda: BIG_DOC, mixed=False) for n in range(1, 6)]
    client = RecordingFakeClient(
        [_reply("w")] * 5, usage=[Usage(prompt_tokens=10, completion_tokens=5)] * 5
    )
    chunks: list[int] = []

    def on_chunk(records: Sequence[Transcription]) -> None:
        chunks.append(len(records))

    done = transcribe_all(
        jobs, lambda: client, cache, TRANSCRIBE, workers=1, chunk=2, on_chunk=on_chunk
    )
    assert len(done) == 5
    assert chunks == [2, 2, 1]


def test_an_interruption_reports_every_finished_page_once(tmp_path: Path) -> None:
    """Fix round 1, C2: money spent by calls still running when the pool stops is reported.

    ``chunk=1`` makes ``on_chunk`` run after every single completed page, so raising from
    inside it on the very first call deterministically interrupts the loop before every
    pending page has been drained -- standing in for a Ctrl-C, without depending on thread
    timing (a native crash is a different matter: it ends the process outright and runs no
    ``finally`` block at all, so nothing here defends against one; the PDFium lock, C1/R3,
    is what prevents that specific crash).
    """
    cache = TranscriptionCache(tmp_path)
    jobs = [PageJob(_key(n), lambda: BIG_DOC, mixed=False) for n in range(1, 7)]
    client = RecordingFakeClient(
        [_reply("w")] * 6, usage=[Usage(prompt_tokens=10, completion_tokens=5)] * 6
    )
    reported: list[Transcription] = []

    def on_chunk(records: Sequence[Transcription]) -> None:
        reported.extend(records)
        if len(reported) == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        transcribe_all(
            jobs, lambda: client, cache, TRANSCRIBE, workers=4, chunk=1, on_chunk=on_chunk
        )
    cached_pages = {n for n in range(1, 7) if cache.get(_key(n)) is not None}
    reported_pages = [r.key.page for r in reported]
    assert cached_pages, "the pool should have paid for and cached at least one page"
    # More than the one page the raising on_chunk call itself saw: proves the finally block's
    # fold-in actually ran, rather than the test passing trivially because every other job
    # happened to be cancelled before it started (fix round 2, re-review).
    assert len(cached_pages) > 1
    assert set(reported_pages) == cached_pages
    assert len(reported_pages) == len(set(reported_pages))


def test_a_raising_on_chunk_does_not_report_the_same_record_twice(tmp_path: Path) -> None:
    """Fix round 1, M1: a batch is cleared before ``on_chunk`` runs, so it cannot be reported

    again from the ``finally`` block's own flush if ``on_chunk`` itself raises.
    """
    cache = TranscriptionCache(tmp_path)
    jobs = [PageJob(_key(n), lambda: BIG_DOC, mixed=False) for n in (1, 2)]
    client = RecordingFakeClient(
        [_reply("w"), _reply("w")], usage=[Usage(prompt_tokens=10, completion_tokens=5)] * 2
    )
    seen: list[Transcription] = []

    def flaky_on_chunk(records: Sequence[Transcription]) -> None:
        seen.extend(records)
        raise RuntimeError("on_chunk boom")

    with pytest.raises(RuntimeError, match="on_chunk boom"):
        transcribe_all(
            jobs, lambda: client, cache, TRANSCRIBE, workers=1, chunk=1, on_chunk=flaky_on_chunk
        )
    seen_pages = [r.key.page for r in seen]
    assert len(seen_pages) == len(set(seen_pages))


def test_duplicate_jobs_are_paid_for_once(tmp_path: Path) -> None:
    """Fix round 1, M2: the same page listed more than once is paid for once."""
    cache = TranscriptionCache(tmp_path)
    jobs = [PageJob(_key(1), lambda: DOC, mixed=False)] * 3
    made_clients: list[RecordingFakeClient] = []
    lock = threading.Lock()

    def factory() -> RecordingFakeClient:
        client = RecordingFakeClient([_reply("w")])
        with lock:
            made_clients.append(client)
        return client

    done = transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=3)
    assert len(done) == 1
    assert sum(len(client.payloads) for client in made_clients) == 1


def test_a_corrupted_cache_file_raises_naming_the_file(tmp_path: Path) -> None:
    """Fix round 1, M3: a corrupted cache file is reported by name, not silently dropped."""
    cache = TranscriptionCache(tmp_path)
    path = cache._path(_key())
    path.parent.mkdir(parents=True)
    path.write_text("{not json")
    with pytest.raises(DocketError, match=r"corrupted transcription cache file"):
        cache.get(_key())


def test_read_page_refuses_a_key_whose_instruction_does_not_match(tmp_path: Path) -> None:
    """Fix round 1, M4: a job's key must name the instruction actually being used."""
    with pytest.raises(ConfigurationError):
        read_page(
            PageJob(_key(), lambda: DOC, mixed=False),  # key names "t1"
            RecordingFakeClient([_reply("w")]),
            LABEL,  # "i1" is actually being used
            now=lambda: NOW,
        )


def test_cache_put_refuses_a_record_whose_key_does_not_match_the_instruction_given(
    tmp_path: Path,
) -> None:
    """Fix round 1, M4: the same check on the write path, for a caller that bypasses read_page."""
    cache = TranscriptionCache(tmp_path)
    record = Transcription(
        key=_key(), status="transcribed", text="", page_kind="blank", created=NOW
    )
    with pytest.raises(ConfigurationError):
        cache.put(record, instruction=LABEL)
    cache.put(record, instruction=TRANSCRIBE)
    assert cache.get(_key()) == record


def test_transcribe_all_refuses_a_key_whose_instruction_does_not_match(tmp_path: Path) -> None:
    """Fix round 1, M4: checked once, up front, before any page in the batch is even loaded."""
    cache = TranscriptionCache(tmp_path)
    jobs = [PageJob(_key(), lambda: DOC, mixed=False)]
    with pytest.raises(ConfigurationError):
        transcribe_all(jobs, lambda: RecordingFakeClient([_reply("w")]), cache, LABEL)


def test_transcription_key_dpi_is_typed_as_resolution() -> None:
    """Fix round 1, M5: an out-of-range resolution is rejected, not silently rendered at it."""
    with pytest.raises(pydantic.ValidationError):
        TranscriptionKey(document_sha256="d" * 64, page=1, model="m", instruction="t1", dpi=300)


def test_transcribe_all_refuses_an_unpriced_model_before_any_call(tmp_path: Path) -> None:
    """Fix round 2, R4: an unpriced model fails before any page is loaded or any call made."""
    cache = TranscriptionCache(tmp_path)
    jobs = [PageJob(_key(model="nobody/nothing"), lambda: DOC, mixed=False)]
    made: list[int] = []

    def factory() -> RecordingFakeClient:
        made.append(1)
        return RecordingFakeClient([_reply("w")])

    with pytest.raises(ConfigurationError):
        transcribe_all(jobs, factory, cache, TRANSCRIBE)
    assert made == []


def test_read_page_records_a_model_call_failure_with_zero_cost() -> None:
    """Fix round 1, C2: any exception the call itself raises costs nothing -- no reply came

    back to pay for, unlike a failure that happens after a reply is in hand.
    """

    class _Boom:
        def complete(
            self,
            payload: Payload,
            settings: ModelSettings,
            *,
            system: str = "",
            history: Sequence[Turn] = (),
        ) -> ModelReply:
            raise RuntimeError("boom (not a ModelError)")

    record = read_page(
        PageJob(_key(), lambda: DOC, mixed=False), _Boom(), TRANSCRIBE, now=lambda: NOW
    )
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.startswith("model:")
    assert record.cost_usd == 0.0


def test_read_page_records_a_cost_lookup_failure_after_a_real_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fix round 1, C2: a price lookup can fail after the call was already made (e.g. an

    unpriced model); the page is still recorded, with the cost it could not price at 0.0.
    """

    def _boom_cost(reply: object, settings: object) -> object:
        raise KeyError("no price on file for this model")

    monkeypatch.setattr(transcribe_module, "cost_usd", _boom_cost)
    client = RecordingFakeClient(
        [_reply("w")], usage=[Usage(prompt_tokens=10, completion_tokens=5)]
    )
    record = read_page(
        PageJob(_key(), lambda: DOC, mixed=False), client, TRANSCRIBE, now=lambda: NOW
    )
    assert record.status == "failed"
    assert record.error is not None
    assert record.error.startswith("cost:")
    assert record.cost_usd == 0.0
    assert record.prompt_tokens == 10


class _SlowFailingCache(TranscriptionCache):
    """A cache whose write for one page sleeps, then fails -- for the pool's finally block."""

    def __init__(self, root: Path, *, fail_page: int, delay: float) -> None:
        super().__init__(root)
        self._fail_page = fail_page
        self._delay = delay

    def put(self, record: Transcription, *, instruction: Instruction | None = None) -> None:
        if record.key.page == self._fail_page:
            time.sleep(self._delay)
            raise RuntimeError("disk full")
        super().put(record, instruction=instruction)


def test_a_page_whose_cache_write_fails_is_still_reported_then_the_write_error_surfaces(
    tmp_path: Path,
) -> None:
    """Fix round 2, R1: a paid page is reported even when its own cache write fails.

    The model call happened and was paid for regardless of whether the write afterwards
    succeeds, so the page must be reported either way; the write failure itself is raised
    only once every page has had its chance to be reported, not instead of reporting it.
    """
    cache = _SlowFailingCache(tmp_path, fail_page=2, delay=0.0)
    jobs = [
        PageJob(_key(1), lambda: BIG_DOC, mixed=False),
        PageJob(_key(2), lambda: BIG_DOC, mixed=False),
    ]
    client = RecordingFakeClient(
        [_reply("w"), _reply("w")], usage=[Usage(prompt_tokens=10, completion_tokens=5)] * 2
    )
    reported: list[Transcription] = []

    with pytest.raises(RuntimeError, match="disk full"):
        transcribe_all(jobs, lambda: client, cache, TRANSCRIBE, workers=2, on_chunk=reported.extend)
    assert sorted(r.key.page for r in reported) == [1, 2]
    assert cache.get(_key(1)) is not None
    assert cache.get(_key(2)) is None


def test_a_page_whose_cache_write_fails_during_the_fold_in_is_still_reported(
    tmp_path: Path,
) -> None:
    """Fix round 2, R1 and R2 together: the pool's ``finally`` block also tolerates a future

    that raised outright (a write failure after a real, paid call) rather than completing
    normally -- it is folded in and reported like any other finished page, not skipped, even
    though the interruption that triggered the fold-in is what ultimately propagates.
    """
    cache = _SlowFailingCache(tmp_path, fail_page=2, delay=0.2)
    jobs = [
        PageJob(_key(1), lambda: BIG_DOC, mixed=False),
        PageJob(_key(2), lambda: BIG_DOC, mixed=False),
    ]
    client = RecordingFakeClient(
        [_reply("w"), _reply("w")], usage=[Usage(prompt_tokens=10, completion_tokens=5)] * 2
    )
    reported: list[Transcription] = []

    def on_chunk(records: Sequence[Transcription]) -> None:
        reported.extend(records)
        if len(reported) == 1:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        transcribe_all(
            jobs, lambda: client, cache, TRANSCRIBE, workers=2, chunk=1, on_chunk=on_chunk
        )
    assert sorted(r.key.page for r in reported) == [1, 2]
    assert cache.get(_key(1)) is not None
    assert cache.get(_key(2)) is None


# --- Task 14: which pages v2 reads, and where their readings are ---


def test_pages_to_read_takes_image_pages_and_mixed_pages_over_the_cut() -> None:
    document = build_pdf(
        [
            PageSpec(text=TYPED),
            PageSpec(images=("/CCITTFaxDecode",)),
            PageSpec(text=TYPED, images=("/DCTDecode",)),
            PageSpec(),
        ]
    )
    # A 100 x 100 image on a letter page covers about 2% of it.
    chosen = pages_to_read(document)
    assert (2, False) in chosen
    logo_share = 100 * 100 / (612 * 792)
    assert ((3, True) in chosen) == (logo_share >= MIXED_PAGE_MIN_IMAGE_SHARE)
    assert all(page not in (1, 4) for page, _ in chosen)


def test_pages_to_read_leaves_out_a_mixed_page_under_the_cut(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = build_pdf(
        [PageSpec(images=("/DCTDecode",)), PageSpec(text=TYPED, images=("/DCTDecode",))]
    )
    monkeypatch.setattr(transcribe_module, "MIXED_PAGE_MIN_IMAGE_SHARE", 0.05)
    assert pages_to_read(document) == [(1, False)]
    monkeypatch.setattr(transcribe_module, "MIXED_PAGE_MIN_IMAGE_SHARE", 0.0)
    assert pages_to_read(document) == [(1, False), (2, True)]


def test_pages_to_read_refuses_a_file_that_is_not_a_pdf() -> None:
    with pytest.raises(DocketError, match="not a PDF"):
        pages_to_read(b"<html>not a pdf</html>")


def test_the_lookup_finds_a_documents_readings_and_the_done_file(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    document = build_pdf([PageSpec(images=("/DCTDecode",))])
    lookup = ReadingLookup(cache, model="m", instruction=TRANSCRIBE, dpi=150)
    sha = hashlib.sha256(document).hexdigest()
    key = TranscriptionKey(document_sha256=sha, page=1, model="m", instruction="t1", dpi=150)
    cache.put(
        Transcription(key=key, status="transcribed", text="x", page_kind="blank", created=NOW)
    )
    assert lookup.for_document(document) == {1: cache.get(key)}
    assert not lookup.is_done("dev-400")
    lookup.mark_done("dev-400", {"pages": 1})
    assert lookup.is_done("dev-400")
    assert json.loads(lookup.done_file("dev-400").read_text()) == {"pages": 1}
    assert lookup.done_file("dev-400").parent == tmp_path / "done"


def test_the_lookup_finds_a_mixed_reading_and_never_a_full_reading_for_it(
    tmp_path: Path,
) -> None:
    """Fix round 3, R4: a text-and-image page's reading is cached under the ``t1+layer`` key
    (0085, amended by Task 13's I3); a full ``t1`` reading of the same page -- from some other
    context that happened to read it without the layer -- must never be returned for it."""
    cache = TranscriptionCache(tmp_path)
    document = build_pdf([PageSpec(text=TYPED, images=("/DCTDecode",))])  # text and image
    lookup = ReadingLookup(cache, model="m", instruction=TRANSCRIBE, dpi=150)
    sha = hashlib.sha256(document).hexdigest()
    mixed_key = TranscriptionKey(
        document_sha256=sha, page=1, model="m", instruction="t1+layer", dpi=150
    )
    full_key = TranscriptionKey(document_sha256=sha, page=1, model="m", instruction="t1", dpi=150)
    cache.put(
        Transcription(
            key=mixed_key,
            status="transcribed",
            text="LEFT TANK 2 GAL",
            page_kind="mixed",
            mixed=True,
            created=NOW,
        )
    )
    cache.put(
        Transcription(
            key=full_key,
            status="transcribed",
            text="a full reading, never used for this page",
            page_kind="typed text",
            created=NOW,
        )
    )
    found = lookup.for_document(document)
    assert found[1].text == "LEFT TANK 2 GAL"
    assert found[1].key == mixed_key


def test_the_lookup_reads_nothing_for_a_text_page_another_model_or_an_unreadable_file(
    tmp_path: Path,
) -> None:
    cache = TranscriptionCache(tmp_path)
    document = build_pdf([PageSpec(text=TYPED), PageSpec(images=("/DCTDecode",))])
    sha = hashlib.sha256(document).hexdigest()
    for page in (1, 2):
        key = TranscriptionKey(document_sha256=sha, page=page, model="m", instruction="t1", dpi=150)
        cache.put(Transcription(key=key, status="transcribed", text="x", created=NOW))
    assert set(ReadingLookup(cache, model="m", dpi=150).for_document(document)) == {2}
    assert ReadingLookup(cache, model="other", dpi=150).for_document(document) == {}
    assert ReadingLookup(cache, model="m", dpi=150).for_document(b"not a pdf") == {}


def test_the_done_file_is_per_model_instruction_and_resolution(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    base = ReadingLookup(cache, model="m", instruction=TRANSCRIBE, dpi=150)
    assert base.done_file("dev-400") != ReadingLookup(cache, model="n").done_file("dev-400")
    assert base.done_file("dev-400") != ReadingLookup(cache, model="m", dpi=200).done_file(
        "dev-400"
    )
    assert base.done_file("dev-400") != base.done_file("heldout-400")
    assert cache.root == tmp_path
