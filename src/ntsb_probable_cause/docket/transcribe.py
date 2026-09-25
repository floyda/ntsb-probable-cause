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
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal, cast

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.pages import page_text
from ntsb_probable_cause.docket.render import MEDIA_TYPE, RenderedPage, Resolution, render_pages
from ntsb_probable_cause.errors import ConfigurationError, DocketError, SchemaError
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
# Decision W3 / 0079 item 3: a text-and-image page whose images cover less than this share of
# the page is not sent -- its images are logos. Chosen by the rule fixed in the S2.6 plan
# (Task 12), from docs/results/s26-inventory.txt: no candidate cut was admissible (1 of the 17
# sampled pages under 2% holds words, more than 1 in 20), so every text-and-image page is sent.
MIXED_PAGE_MIN_IMAGE_SHARE = 0.0
# Decision 0087: chosen provisionally, as a post-hoc override of decision 0080's rule, which
# chose no candidate in either pass (docs/results/s26-transcriber-test.txt, -pass2.txt).
# Whether transcription goes forward is decided by the dev-400 B-v1 against B-v2 comparison.
TRANSCRIBER = "qwen/qwen3.5-122b-a10b"
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


def key_instruction(instruction: Instruction, *, mixed: bool) -> str:
    """The ``instruction`` value a reading's key carries: distinct for a mixed reading.

    Fix round 1, I3 (amends decision 0085): a mixed reading sends the page's own text layer
    alongside the instruction and so reads differently from a full reading of the same page
    under the same nominal instruction version -- the two must never share a cache key, or a
    later reader (Task 14's v2) could take a full reading, which repeats the page's text
    layer, for "the words in the page's images". Used here (``read_page``, ``_validate_jobs``,
    ``TranscriptionCache.put``), by the transcriber test's own key builder, and, from Task 14,
    by v2.
    """
    return f"{instruction.version}+layer" if mixed else instruction.version


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
    dpi: Resolution

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
        """The cached reading for a key, or ``None``.

        A file this cache itself wrote never fails to parse; one that does (fix round 1, M3)
        is reported by name rather than treated as a miss, so it is not silently re-read (and
        re-paid for) or -- worse -- silently overwritten in place.
        """
        path = self._path(key)
        if not path.is_file():
            return None
        try:
            return Transcription.model_validate_json(path.read_text())
        except Exception as error:
            raise DocketError(f"corrupted transcription cache file: {path}") from error

    def put(self, record: Transcription, *, instruction: Instruction | None = None) -> None:
        """Write a reading; a kill mid-write leaves the old file or none, never half of one.

        ``instruction``, when given, must be the instruction that actually produced
        ``record`` (fix round 1, M4): a record whose key names a different instruction version
        is refused, so an inventory (i1) reading can never be cached under a transcriber (t1)
        key and later served as a transcription with no words and no sign of the mistake. A
        mixed reading's key must carry the ``+layer`` variant (fix round 1, I3), judged by
        ``record.mixed``, so a full and a mixed reading of the same page can never collide.
        """
        if instruction is not None:
            expected = key_instruction(instruction, mixed=record.mixed)
            if record.key.instruction != expected:
                raise ConfigurationError(
                    f"record for page {record.key.page} names instruction "
                    f"{record.key.instruction!r}, not the instruction actually used "
                    f"({expected!r})"
                )
        path = self._path(record.key)
        path.parent.mkdir(parents=True, exist_ok=True)
        partial = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.partial")
        with partial.open("w") as handle:
            handle.write(record.model_dump_json())
            handle.flush()
            os.fsync(handle.fileno())
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
    """The words (empty for an instruction that copies none) and the page kind.

    A reply from an instruction that copies words (t1) must itself carry a ``text`` field
    (fix round 1, I1): a provider that ignores the schema and omits it is refused rather than
    cached as a transcribed, empty page, which would look exactly like a page that really has
    no words and would never be read again (``retry_failed`` only re-reads failures).
    """
    try:
        body = json.loads(content or "")
    except json.JSONDecodeError as error:
        raise SchemaError(f"reply is not JSON: {error.msg}") from error
    if not isinstance(body, dict):
        raise SchemaError("reply is not a JSON object")
    kind = body.get("page_kind")
    if kind not in PAGE_LABELS:
        raise SchemaError(f"page_kind is not one of the labels: {kind!r}")
    if instruction.copies_words:
        if "text" not in body:
            raise SchemaError("reply is missing the required 'text' field")
        text = body["text"]
    else:
        text = ""
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
    """Draw the page, send it, parse the reply.

    Never raises for a page's own reading (fix round 1, C2): a failure before the model call
    (loading the document, rendering the page) costs nothing and is recorded failed with zero
    cost; a failure the call itself raises costs nothing either, because no reply came back to
    pay for; but once a reply has come back, every dollar it cost is real, so any failure after
    that point (pricing it, parsing its schema) is recorded failed while keeping that cost. The
    one thing this does raise is a ``ConfigurationError`` when the job's key names a different
    instruction than the one actually used (fix round 1, M4) -- a caller bug to fail loudly on
    before any page is even loaded, not a reading to record as failed.
    """
    key = job.key
    expected = key_instruction(instruction, mixed=job.mixed)
    if key.instruction != expected:
        raise ConfigurationError(
            f"page {key.page}'s key names instruction {key.instruction!r}, not the "
            f"instruction actually used ({expected!r})"
        )
    try:
        data = job.load()
        (rendered,) = render_pages(data, [key.page], dpi=key.dpi)
    except Exception as error:
        return Transcription(
            key=key,
            status="failed",
            error=f"load-or-render: {type(error).__name__}: {error}"[:_ERROR_CHARS],
            mixed=job.mixed,
            created=now(),
        )
    text_layer = page_text(data, key.page) if job.mixed else None
    payload, system = request_for(rendered, instruction, text_layer=text_layer)
    settings = settings_for(key.model, instruction)
    try:
        reply = client.complete(payload, settings, system=system)
    except Exception as error:
        return Transcription(
            key=key,
            status="failed",
            error=f"model: {type(error).__name__}: {error}"[:_ERROR_CHARS],
            image_sha256=rendered.sha256,
            image_area_share=rendered.image_area_share,
            mixed=job.mixed,
            created=now(),
        )

    # The call has returned, so it has been paid for: every record from here keeps that cost.
    def _paid_failure(prefix: str, detail: object, *, cost: float) -> Transcription:
        return Transcription(
            key=key,
            status="failed",
            error=f"{prefix}: {detail}"[:_ERROR_CHARS],
            image_sha256=rendered.sha256,
            image_area_share=rendered.image_area_share,
            mixed=job.mixed,
            prompt_tokens=reply.usage.prompt_tokens,
            completion_tokens=reply.usage.completion_tokens,
            cost_usd=cost,
            created=now(),
        )

    try:
        cost, _ = cost_usd(reply, settings)
    except Exception as error:
        # A price lookup can fail after the call was already made, e.g. an unpriced model
        # (fix round 1, C2). The dollar amount cannot be known, but the page must still be
        # recorded rather than silently dropped, so it costs 0.0 here and the error names why.
        return _paid_failure("cost", f"{type(error).__name__}: {error}", cost=0.0)
    try:
        text, kind = parse_reply(reply.content, instruction)
    except Exception as error:
        # Task 9A's lesson: a reply cut off by the output budget says so.
        return _paid_failure("schema", f"{error} (finish_reason={reply.finish_reason})", cost=cost)
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


def _validate_jobs(jobs: Sequence[PageJob], instruction: Instruction) -> None:
    """Fail fast, before any page is loaded or any call made.

    Every job's key must name the instruction actually being used (fix round 1, M4), and every
    model named must already have a price on file (fix round 2, R4) -- both are configuration
    bugs, not a page's own reading, so both are checked once up front rather than per page.
    """
    for job in jobs:
        expected = key_instruction(instruction, mixed=job.mixed)
        if job.key.instruction != expected:
            raise ConfigurationError(
                f"page {job.key.page}'s key names instruction {job.key.instruction!r}, not "
                f"the instruction actually used ({expected!r})"
            )
    for model in {job.key.model for job in jobs}:
        try:
            sources.price_of(model)
        except KeyError as error:
            raise ConfigurationError(
                f"no price on file for model {model!r}; add it to sources.py before "
                "transcribing with it"
            ) from error


def _pending_jobs(
    jobs: Sequence[PageJob], cache: TranscriptionCache, *, retry_failed: bool
) -> list[PageJob]:
    """Every job worth paying for: not already cached, and not a repeat of one that is pending.

    De-duplicated by ``key.digest()`` (fix round 1, M2): an identical document, such as a
    standard form, can appear in more than one docket, and each page is paid for once.
    """
    seen_keys: set[str] = set()
    pending: list[PageJob] = []
    for job in jobs:
        digest = job.key.digest()
        if digest in seen_keys:
            continue
        seen_keys.add(digest)
        cached = cache.get(job.key)
        if cached is None or (retry_failed and cached.status == "failed"):
            pending.append(job)
    return pending


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

    ``on_chunk`` is handed every ``chunk`` new readings, and the remainder at the end --
    including on an interruption or an unexpected exception (fix round 1, C2) -- so every
    dollar spent stays visible to the budget guard, and never twice (M1) even if ``on_chunk``
    itself raises. A page whose call succeeded but whose cache write then failed is still
    reported, with that write error raised only after every page has had its chance to be
    reported (fix round 2, R1): paid means reported, even when the page could not be cached
    (it is simply read again next time, the same as any other cache miss). A page cached as
    failed is read again only with ``retry_failed``. The same page listed more than once is
    paid for once (fix round 1, M2): an identical document, such as a standard form, can
    appear in more than one docket. Every model named in ``jobs`` must already have a price on
    file (fix round 2, R4), checked once before any call is made. The caller owns the clients
    the factory makes and closes them afterwards.

    One limitation remains undefended (fix round 2, R2): a second interruption that lands
    while this function is already waiting inside ``pool.shutdown`` -- for example a repeated
    Ctrl-C, or a real process kill -- can still leave in-flight paid pages unreported for this
    call. They are cached the moment their own call finishes, so a later call reads them from
    the cache rather than paying for them again; only that run's report of them is lost.
    """
    _validate_jobs(jobs, instruction)
    pending = _pending_jobs(jobs, cache, retry_failed=retry_failed)

    local = threading.local()

    def work(job: PageJob) -> tuple[Transcription, Exception | None]:
        client = getattr(local, "client", None)
        if client is None:
            client = local.client = client_factory()
        record = read_page(job, client, instruction, now=now)
        try:
            cache.put(record, instruction=instruction)
        except Exception as error:  # fix round 2, R1: the call already happened and was paid
            return record, error  # for; it must still be reported even though it was never
        return record, None  # cached, not silently dropped along with the write failure.

    done: list[Transcription] = []
    unreported: list[Transcription] = []
    write_errors: list[Exception] = []

    def flush() -> None:
        if not unreported:
            return
        batch = list(unreported)
        # Cleared before on_chunk runs: if on_chunk itself raises, these records are already
        # gone from `unreported`, so nothing here can be handed to it a second time (M1).
        unreported.clear()
        on_chunk(batch)

    def take(future: Future[tuple[Transcription, Exception | None]]) -> None:
        """Queue one future's record before marking it handled (fix round 2, R2).

        Queuing first means an interruption between the two can at worst cause the fold-in
        below to see this future as still unhandled and process it again -- itself harmless,
        since a future's result can be read more than once -- rather than lose the record
        outright, which reordering the other way around could do.
        """
        record, error = future.result()
        if error is not None:
            write_errors.append(error)
        done.append(record)
        unreported.append(record)
        handled.add(id(future))

    pool = ThreadPoolExecutor(max_workers=workers)
    futures = [pool.submit(work, job) for job in pending]
    handled: set[int] = set()
    try:
        for future in as_completed(futures):
            take(future)
            if len(unreported) >= chunk:
                flush()
    finally:
        # A KeyboardInterrupt or another exception raised above can end the loop before every
        # future is drained. This does not defend against a native crash, which ends the
        # process outright and runs no `finally` block at all -- the PDFium lock (fix round 1,
        # C1; fix round 2, R3) is what prevents that specific crash, not this code.
        # `shutdown(wait=True)` blocks until every future still running finishes (and cancels
        # every one not yet started), so by the time it returns each future is done, cancelled,
        # or still failed for a reason of its own; anything done that the loop above never saw
        # is folded in and flushed here, so a paid-for page is never left unreported by this
        # run (subject to the second-interruption limit this function's docstring names).
        pool.shutdown(wait=True, cancel_futures=True)
        for future in futures:
            if id(future) in handled or future.cancelled() or future.exception() is not None:
                continue
            take(future)
        flush()
    if write_errors:
        raise write_errors[0]
    return done
