"""The boundary check: inspect what actually reached the (fake) model, not what was intended."""

import copy
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field

from ntsb_probable_cause import fields
from ntsb_probable_cause.fields import EvidenceValue
from ntsb_probable_cause.model.batch import (
    BatchCounts,
    BatchRequest,
    BatchResult,
    BatchStatus,
)
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    RecordingFakeClient,
    Usage,
)
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.guard import find_leaks
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.sources import docket_url

Splitter = Callable[[Mapping[str, object]], tuple[Evidence, Synthesis, Verdict]]

# Every occurrence code in the fixtures is 6 digits and every finding code 10 (checked against
# every development-split fixture; see the Task 7 report). A short numeric code -- the brief's
# own example is "240" -- is not distinctive: it can appear by chance in a binary SQLite file's
# row ids, byte counts or other encoded integers, which would make a check built on it flaky or
# vacuous. Six digits, all-numeric, checked as an exact substring of raw bytes, is long enough
# that an accidental match against unrelated binary data is not a real risk, and it is also the
# shortest code this project actually has, so the threshold excludes nothing real.
CODE_LENGTH_THRESHOLD = 6

# Comfortably under an SQLite page's ~4KB usable payload. A withheld string that clears about
# 4KB (a long factual narrative does) spans more than one page once it is stored, and the
# pages are not contiguous in the file, so the whole string stops being one contiguous byte
# run -- a store boundary check built on the whole string alone would then miss it (Task 7 fix
# round 1, Important 1). WINDOW_CHARS caps how long a single window is ever allowed to be, so
# a window that does land inside one page (the common case) is small next to that page's
# capacity.
WINDOW_CHARS = 200
# The shortest window this module will ever emit. Long enough that a match cannot plausibly be
# chance (fix round 2: raised from the guard's 20-character minimum sentence length, which was
# tuned for a different purpose -- distinguishing real sentence quotation from coincidence in
# free text -- not for this check's "could this string exist in unrelated binary data by
# accident" question).
_MIN_WINDOW_CHARS = 50
# Windows overlap by at least half their own length (stride = window length // 2). Fix round 2,
# finding 1a: round 1's windows did not overlap at all, so a withheld string no longer than one
# window (WINDOW_CHARS + a folded remainder, i.e. up to 219 characters -- six of the nine
# development fixtures' probable-cause texts qualify) produced exactly ONE window equal to the
# whole string, and a single SQLite page split landing anywhere inside that one window defeated
# it completely: the reviewer's sweep found 155 of 4200 page alignments (3.7%) undetected.
# Overlap fixes this: for any single split point inside the tiled text, at most the one or two
# windows whose span straddles that point are affected, and every other generated window --
# there are always at least two, and usually several more -- is left as a contiguous run on one
# side of the split, so at least one window is always still there to find. Verified empirically
# against the reviewer's own construction in
# test_boundary_windows_survive_every_page_alignment, which also demonstrates that round 1's
# non-overlapping scheme fails it (see the Task 7 report).
_STRIDE_DIVISOR = 2


def _json_escaped(text: str) -> str:
    """``text`` as it reads inside a JSON string: backslash escapes, no surrounding quotes.

    ``field_snapshots.value_json`` is written with ``json.dumps``, which rewrites ``"``,
    ``\\n`` and every non-ASCII character -- so a leak stored there does not read like the
    source text any more, and a check that only looks for the raw form misses it.
    """
    return json.dumps(text)[1:-1]


def _windows(text: str, size: int = WINDOW_CHARS, min_size: int = _MIN_WINDOW_CHARS) -> list[str]:
    """Overlapping windows tiling ``text``, each at least ``min_size`` characters.

    A text no longer than ``min_size`` is returned whole: it cannot be usefully subdivided
    (there is no room for even one full-length window inside it), so it keeps whatever
    single-window risk that implies. Otherwise the per-window length is capped at both
    ``size`` (well under an SQLite page) and half of ``text``'s own length, so a text shorter
    than one full-size window still gets at least two genuinely overlapping windows rather
    than the single whole-string window round 1 produced for anything under 219 characters.
    Consecutive windows are spaced by half a window's length (``_STRIDE_DIVISOR``), and the
    final window is snapped to end exactly at the text's own end, so the whole text is covered
    and the overlap guarantee (see ``_STRIDE_DIVISOR``'s comment) holds all the way to the end.

    A text only a little longer than ``min_size`` (the shortest development-fixture probable
    cause is 52 characters, against a 50-character minimum) cannot get more than two windows
    with heavy mutual overlap -- there simply is not room for a third, differently-positioned
    window -- so a split landing in that large shared overlap is not fully protected against.
    This is accepted, not hidden: it is the same kind of small residual risk as the whole-code
    check below, for the same reason (there is a hard floor on how short a checkable window can
    be), and is smaller than round 1's gap, which covered every text under 219 characters, not
    only texts within a few characters of the 50-character floor.
    """
    length = len(text)
    if length <= min_size:
        return [text]
    window = min(size, max(min_size, length // 2))
    stride = max(1, window // _STRIDE_DIVISOR)
    windows: list[str] = []
    start = 0
    while True:
        if start + window >= length:
            windows.append(text[length - window :])
            break
        windows.append(text[start : start + window])
        start += stride
    return windows


def withheld_windows(raw: Mapping[str, object]) -> list[str]:
    """Every substring a store boundary test should check for in a case's raw record.

    The probable cause and both narratives, each in both raw and JSON-escaped form and cut
    into overlapping windows well under an SQLite page (see ``_windows``, ``_json_escaped``),
    plus every occurrence and finding code long enough to be distinctive
    (``CODE_LENGTH_THRESHOLD``) -- codes are short, all-numeric and unaffected by JSON
    escaping, so they are checked whole, not windowed.

    Codes are a real, accepted gap this function does NOT close: a 6-to-10-character code that
    happens to be split across a page boundary is not detected, because a code is too short to
    subdivide into windows at all without falling below any length that could not also match
    unrelated binary data by chance (``CODE_LENGTH_THRESHOLD`` already sits at that floor).
    This is a residual risk, not a covered case -- it is not claimed to be covered.

    Empty/``None`` values are omitted.
    """
    texts = [
        text
        for text in (
            fields.probable_cause(raw),
            fields.factual_narrative(raw),
            fields.analysis_narrative(raw),
        )
        if text
    ]
    codes = [
        code
        for code in fields.occurrence_codes(raw) + fields.finding_codes(raw)
        if len(code) >= CODE_LENGTH_THRESHOLD
    ]
    windows: list[str] = list(codes)
    for text in texts:
        windows.extend(_windows(text))
        windows.extend(_windows(_json_escaped(text)))
    return windows


# fields.WITHHELD_SUBTREES's narrative keys (fields.py:62-69), less the docket roles, which do
# not exist on a raw API record at all (fields.py:244-249) and so need no stripping.
_WITHHELD_NARRATIVE_KEYS = ("concatenatedFactualNarrative", "analysisNarrative", "probableCause")


def as_ongoing(raw: Mapping[str, object], *, prelim_text: str) -> dict[str, object]:
    """A deep copy of a closed dev-split record, edited to read like a live one.

    ``completionStatus`` becomes ``Ongoing`` and every ``fields.WITHHELD_SUBTREES`` path is
    stripped, so the record carries no synthesis or verdict content -- the shape a case
    actually has while it is open. ``prelim_text`` becomes the preliminary narrative: none of
    the development fixtures' closed records still carry one (the API clears it at closure).
    """
    record = copy.deepcopy(dict(raw))
    record["completionStatus"] = "Ongoing"

    narratives = record.get("narratives")
    assert isinstance(narratives, list)
    assert narratives
    narrative = narratives[0]
    assert isinstance(narrative, dict)
    for key in _WITHHELD_NARRATIVE_KEYS:
        narrative.pop(key, None)
    narrative["prelimNarrative"] = prelim_text

    aircrafts = record.get("aircrafts")
    assert isinstance(aircrafts, list)
    assert aircrafts
    for aircraft in aircrafts:
        assert isinstance(aircraft, dict)
        aircraft.pop("events", None)
        aircraft.pop("findings", None)

    record.pop("richNarratives", None)
    return record


def _as_evidence_value(value: object) -> EvidenceValue:
    if isinstance(value, list):
        return tuple(str(v) for v in value)
    if isinstance(value, int | float) and not isinstance(value, bool):
        return float(value)
    return value if isinstance(value, str) or value is None else str(value)


def assert_boundary_holds(raw: Mapping[str, object], split: Splitter = split_record) -> None:
    """Run ``split`` then the model boundary, and check what the model received.

    Provenance: each sent value equals its declared extractor's value on the raw record.
    Bookkeeping: neither the case number nor the docket URL was sent.
    Tripwire: withheld text and codes, read directly from the raw record, are absent.
    """
    evidence, _, _ = split(raw)
    client = RecordingFakeClient()
    client.complete(Payload.from_evidence(evidence), ModelSettings())
    (sent,) = client.payloads
    received = {role: _as_evidence_value(value) for role, value in sent.fields().items()}

    expected = {
        f.role.value: f.extract(raw)
        for f in fields.EVIDENCE_FIELDS
        if f.role not in evidence.excluded
    }
    present = {role for role, value in expected.items() if value is not None}
    assert set(received) == present, (
        f"provenance: sent roles {sorted(received)}, record has {sorted(present)}"
    )
    for role, value in received.items():
        assert value == expected.get(role), (
            f"provenance: {role} sent {value!r}, record has {expected.get(role)!r}"
        )

    assert str(raw.get("ntsbNumber")) not in sent.text, "bookkeeping: case number was sent"
    mkey = raw.get("mKey")
    expected_docket_url = docket_url(mkey) if isinstance(mkey, int) else None
    if expected_docket_url:
        assert expected_docket_url not in sent.text, "bookkeeping: docket URL was sent"

    withheld = {
        "factual_narrative": fields.factual_narrative(raw),
        "analysis_narrative": fields.analysis_narrative(raw),
        "probable_cause": fields.probable_cause(raw),
    }
    codes = fields.occurrence_codes(raw) + fields.finding_codes(raw)
    leaks = find_leaks(received, withheld, codes)
    assert not leaks, "tripwire: " + "; ".join(str(leak) for leak in leaks)


@dataclass
class RecordingBatchRunner:
    """A ``BatchRunner`` for boundary tests: keeps every request it was given, replies by stage.

    The stage is read off each request's ``settings.schema_name`` (``hypothesis`` for
    stage 1, ``refinement`` for stage 2), so one instance serves a whole two-stage run.
    """

    stage1: str
    stage2: str
    requests: list[BatchRequest] = field(default_factory=list)
    _pending: dict[str, list[BatchRequest]] = field(default_factory=dict)

    def submit(self, requests: Sequence[BatchRequest]) -> str:
        batch_id = f"boundary-{len(self._pending) + 1}"
        self.requests.extend(requests)
        self._pending[batch_id] = list(requests)
        return batch_id

    def wait(
        self, batch_id: str, *, on_status: Callable[[BatchStatus], None] = lambda _s: None
    ) -> BatchStatus:
        results = tuple(
            BatchResult(
                custom_id=r.custom_id,
                reply=ModelReply(
                    content=self.stage1 if r.settings.schema_name == "hypothesis" else self.stage2,
                    usage=Usage(prompt_tokens=100, completion_tokens=50),
                    model=r.settings.model_id(),
                    response_id="fake",
                ),
                error=None,
            )
            for r in self._pending[batch_id]
        )
        status = BatchStatus(
            batch_id=batch_id,
            status="completed",
            results=results,
            reported_cost_usd=None,
            counts=BatchCounts(len(results), len(results), 0),
        )
        on_status(status)
        return status


def _request_texts(request: BatchRequest) -> list[tuple[str, str]]:
    """Every string a batch request would send: system, payload, each turn and its tool calls."""
    texts = [("system", request.system), ("payload", request.payload.text)]
    for turn in request.history:
        if turn.content is not None:
            texts.append((f"{turn.role} turn", turn.content))
        if turn.payload is not None:
            texts.append((f"{turn.role} turn payload", turn.payload.text))
        for call in turn.tool_calls:
            texts.append((f"{turn.role} turn tool call", call.arguments))
    return texts


def assert_requests_clean(
    requests: Sequence[BatchRequest], withheld: Sequence[tuple[str, str]]
) -> None:
    """No withheld text in any system prompt, payload or history turn of any request."""
    for request in requests:
        for where, text in _request_texts(request):
            for kind, needle in withheld:
                assert needle not in text, (
                    f"tripwire: {kind} reached a batch request's {where} ({request.custom_id})"
                )
