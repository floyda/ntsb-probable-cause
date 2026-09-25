"""Transcription: request, reply, cache and pool, with a fake client (S2.6 §8)."""

import json
import threading
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.transcribe import (
    ILLEGIBLE,
    LABEL,
    TRANSCRIBE,
    PageJob,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
    parse_reply,
    read_page,
    transcribe_all,
)
from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.model.client import RecordingFakeClient, Usage

NOW = datetime(2026, 10, 1, tzinfo=UTC)
TYPED = "Engine sputtered at 800 ft. Switched tanks, no change."
DOC = build_pdf([PageSpec(text=TYPED), PageSpec(text=TYPED, images=("/DCTDecode",))])


def _key(page: int = 1, model: str = "google/gemini-3.1-flash-lite") -> TranscriptionKey:
    return TranscriptionKey(
        document_sha256="d" * 64, page=page, model=model, instruction="t1", dpi=150
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
    "content", [None, "not json", "[]", json.dumps({"text": "x", "page_kind": "poem"})]
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
    read_page(PageJob(_key(page=2), lambda: DOC, mixed=True), client, TRANSCRIBE, now=lambda: NOW)
    assert TYPED.split(".", maxsplit=1)[0] in client.payloads[0].text
    assert client.systems == [TRANSCRIBE.mixed_system]


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
    assert len(made) <= 2


def test_a_failed_page_is_retried_only_when_asked(tmp_path: Path) -> None:
    cache = TranscriptionCache(tmp_path)
    cache.put(Transcription(key=_key(1), status="failed", error="model: ModelError", created=NOW))
    jobs = [PageJob(_key(1), lambda: DOC, mixed=False)]
    factory = lambda: RecordingFakeClient([_reply("words")])  # noqa: E731
    assert transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=1) == []
    (again,) = transcribe_all(jobs, factory, cache, TRANSCRIBE, workers=1, retry_failed=True)
    assert again.status == "transcribed"
