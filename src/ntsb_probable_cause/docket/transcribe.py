"""Transcription: the words on a page image, copied and nothing else (S2.6 §7, §8; 0079-0081).

A dedicated transcriber reads each page once and the agent reads the text: the agent's own
model reads handwriting poorly (spec §7.1). Transcription is evidence preparation (0081):
cached once per page under ``NTSB_DATA_DIR``, paid once, reused by every run and arm, and
costed apart from the agent's per-case cap.

A request holds only the page image, a fixed instruction and -- on a mixed page -- that
page's own text layer (spec §8.2); ``tests/test_boundary.py`` checks nothing else is sent.
Every image call is synchronous at the standard price: the batch service rejects images
(``model/batch.py``).
"""

import hashlib
import json
import os
import threading
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.render import MEDIA_TYPE, RenderedPage, Resolution, render_pages
from ntsb_probable_cause.errors import DocketError, ModelError, SchemaError
from ntsb_probable_cause.model.client import (
    ModelClient,
    ModelSettings,
    PageImage,
    Payload,
    cost_usd,
)

PageLabel = Literal[
    "typed text",
    "handwriting",
    "filled form",
    "photograph",
    "diagram or chart",
    "logo or letterhead only",
    "mixed",
    "blank",
]
PAGE_LABELS: tuple[PageLabel, ...] = (
    "typed text",
    "handwriting",
    "filled form",
    "photograph",
    "diagram or chart",
    "logo or letterhead only",
    "mixed",
    "blank",
)
# Decision 0079: what the transcriber writes for a word it cannot read, instead of a guess.
ILLEGIBLE = "[illegible]"
MAX_OUTPUT_TOKENS = 4000
_ERROR_CHARS = 200


@dataclass(frozen=True)
class Instruction:
    """A fixed instruction, its version (in every cache key), and whether it copies words."""

    version: str
    system: str
    mixed_system: str
    copies_words: bool

    def schema(self) -> dict[str, object]:
        """The reply's JSON schema: the page kind, and the words when the instruction copies."""
        properties: dict[str, object] = {"page_kind": {"type": "string", "enum": list(PAGE_LABELS)}}
        if self.copies_words:
            properties["text"] = {"type": "string"}
        return {
            "type": "object",
            "properties": properties,
            "required": sorted(properties),
            "additionalProperties": False,
        }


_KINDS = "Say what the page mainly shows, as exactly one of: " + ", ".join(PAGE_LABELS) + "."
_COPY = (
    "You copy the words on one page image from an aviation accident investigation docket. "
    "Copy every word you can read, in reading order, one line of the page per line, exactly "
    "as written: keep numbers, units, dates, abbreviations and spelling as they are. Where you "
    f"cannot read a word, write {ILLEGIBLE} in its place; never guess. Do not describe "
    "pictures, summarise, explain, correct or add anything that is not written on the page. "
    "If the page holds no words, return an empty text. "
)
_MIXED = (
    " This page already has a text layer, which is given with the image. Copy only words in "
    "the page's images that are not already in that text layer; if there are none, return an "
    "empty text."
)
_LOOK = (
    "You see one page image from an aviation accident investigation docket. "
    + _KINDS
    + " Do not copy any words and do not describe the page."
)

# Version t1 (S2.6 Task 11): fixed before the transcriber test, which measures it. Any
# change is a new version, and so a new cache key and a re-run of the test.
TRANSCRIBE = Instruction("t1", _COPY + _KINDS, _COPY + _KINDS + _MIXED, copies_words=True)
# Version i1: the inventory's labeller (spec §6.2 item 3). Categories only, never words.
LABEL = Instruction("i1", _LOOK, _LOOK, copies_words=False)


class TranscriptionKey(BaseModel):
    """What identifies one reading of one page: the document, page, model, instruction, dpi."""

    model_config = ConfigDict(frozen=True)
    document_sha256: str
    page: int
    model: str
    instruction: str
    dpi: int

    def digest(self) -> str:
        """A stable hash of every field: the cache file's name."""
        return hashlib.sha256(self.model_dump_json().encode()).hexdigest()


class Transcription(BaseModel):
    """One page's reading, or why it failed, with what it cost (0081 item 3)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    key: TranscriptionKey
    status: Literal["transcribed", "failed"]
    text: str = ""
    page_kind: PageLabel | None = None
    image_sha256: str | None = None
    image_area_share: float | None = None
    mixed: bool = False
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost_usd: float = 0.0
    error: str | None = None
    created: datetime


class TranscriptionCache:
    """One JSON file per reading under a root directory, written atomically."""

    def __init__(self, root: Path) -> None:
        self._root = root

    def _path(self, key: TranscriptionKey) -> Path:
        digest = key.digest()
        return self._root / digest[:2] / f"{digest}.json"

    def get(self, key: TranscriptionKey) -> Transcription | None:
        """The cached reading for a key, or ``None``."""
        path = self._path(key)
        return Transcription.model_validate_json(path.read_text()) if path.is_file() else None

    def put(self, record: Transcription) -> None:
        """Write a reading; a kill mid-write leaves the old file or none, never half of one."""
        path = self._path(record.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.partial")
        partial.write_text(record.model_dump_json())
        partial.replace(path)


@dataclass(frozen=True)
class PageJob:
    """One page to read: its key, how to load its document's bytes, and whether it is mixed."""

    key: TranscriptionKey
    load: Callable[[], bytes]
    mixed: bool


def request_for(
    rendered: RenderedPage, instruction: Instruction, *, text_layer: str | None
) -> tuple[Payload, str]:
    """The only request a reading sends: the image, the instruction, the page's own text."""
    image = PageImage(media_type=MEDIA_TYPE, data=rendered.data)
    if text_layer:
        return Payload.for_page(image, text_layer=text_layer), instruction.mixed_system
    return Payload.for_page(image), instruction.system


def settings_for(model: str, instruction: Instruction) -> ModelSettings:
    """Standard price (images cannot be batched), temperature 0, lowest reasoning, recorded."""
    return ModelSettings(
        model=model,
        price_variant="standard",
        temperature=0.0,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        json_schema=instruction.schema(),
        schema_name="page",
        reasoning_effort=sources.LOWEST_REASONING[model],
    )


def parse_reply(content: str | None, instruction: Instruction) -> tuple[str, PageLabel]:
    """The words (empty for an instruction that copies none) and the page kind."""
    try:
        body = json.loads(content or "")
    except json.JSONDecodeError as error:
        raise SchemaError(f"reply is not JSON: {error.msg}") from error
    if not isinstance(body, dict):
        raise SchemaError("reply is not a JSON object")
    kind = body.get("page_kind")
    if kind not in PAGE_LABELS:
        raise SchemaError(f"page_kind is not one of the labels: {kind!r}")
    text = body.get("text", "") if instruction.copies_words else ""
    if not isinstance(text, str):
        raise SchemaError("text is not a string")
    return text.strip(), cast(PageLabel, kind)


def read_page(
    job: PageJob,
    client: ModelClient,
    instruction: Instruction,
    *,
    now: Callable[[], datetime],
) -> Transcription:
    """Draw the page, send it, parse the reply. Every outcome is a record; nothing raises."""
    key = job.key
    try:
        data = job.load()
        (rendered,) = render_pages(data, [key.page], dpi=cast(Resolution, key.dpi))
    except DocketError as error:
        return Transcription(
            key=key,
            status="failed",
            error=f"render: {error}"[:_ERROR_CHARS],
            mixed=job.mixed,
            created=now(),
        )
    text_layer = page_text(data, key.page) if job.mixed else None
    payload, system = request_for(rendered, instruction, text_layer=text_layer)
    settings = settings_for(key.model, instruction)
    try:
        reply = client.complete(payload, settings, system=system)
    except ModelError as error:
        return Transcription(
            key=key,
            status="failed",
            error=f"model: {type(error).__name__}",
            image_sha256=rendered.sha256,
            image_area_share=rendered.image_area_share,
            mixed=job.mixed,
            created=now(),
        )
    cost, _ = cost_usd(reply, settings)
    try:
        text, kind = parse_reply(reply.content, instruction)
    except SchemaError as error:
        return Transcription(
            key=key,
            status="failed",
            # Task 9A's lesson: a reply cut off by the output budget says so.
            error=f"schema: {error} (finish_reason={reply.finish_reason})"[:_ERROR_CHARS],
            image_sha256=rendered.sha256,
            image_area_share=rendered.image_area_share,
            mixed=job.mixed,
            prompt_tokens=reply.usage.prompt_tokens,
            completion_tokens=reply.usage.completion_tokens,
            cost_usd=cost,
            created=now(),
        )
    return Transcription(
        key=key,
        status="transcribed",
        text=text,
        page_kind=kind,
        image_sha256=rendered.sha256,
        image_area_share=rendered.image_area_share,
        mixed=job.mixed,
        prompt_tokens=reply.usage.prompt_tokens,
        completion_tokens=reply.usage.completion_tokens,
        cost_usd=cost,
        created=now(),
    )


def transcribe_all(  # noqa: PLR0913 -- every parameter is a seam a test or a caller needs.
    jobs: Sequence[PageJob],
    client_factory: Callable[[], ModelClient],
    cache: TranscriptionCache,
    instruction: Instruction,
    *,
    workers: int = 8,
    chunk: int = 50,
    on_chunk: Callable[[Sequence[Transcription]], None] = lambda _records: None,
    retry_failed: bool = False,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[Transcription]:
    """Read every page not already cached, on a pool of threads with one client each.

    Each reading is cached the moment it returns, so an interrupted job loses only the pages
    in flight. ``on_chunk`` is handed every ``chunk`` new readings, and the remainder at the
    end or on an interruption, so the caller can append a spend row (0081) as money is
    spent. A page cached as failed is read again only with ``retry_failed``. The caller owns
    the clients the factory makes and closes them afterwards.
    """
    pending = [
        job
        for job in jobs
        if (cached := cache.get(job.key)) is None or (retry_failed and cached.status == "failed")
    ]
    local = threading.local()

    def work(job: PageJob) -> Transcription:
        client = getattr(local, "client", None)
        if client is None:
            client = local.client = client_factory()
        record = read_page(job, client, instruction, now=now)
        cache.put(record)
        return record

    done: list[Transcription] = []
    unreported: list[Transcription] = []
    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [pool.submit(work, job) for job in pending]
    try:
        for future in as_completed(futures):
            record = future.result()
            done.append(record)
            unreported.append(record)
            if len(unreported) >= chunk:
                on_chunk(unreported)
                unreported = []
    finally:
        pool.shutdown(wait=True, cancel_futures=True)
        if unreported:
            on_chunk(unreported)
    return done
