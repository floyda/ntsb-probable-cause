"""The boundary check: inspect what actually reached the (fake) model, not what was intended."""

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


def withheld_strings(raw: Mapping[str, object]) -> list[str]:
    """Every withheld string a store boundary test can check for in a case's raw record.

    The probable cause and both narratives, plus every occurrence and finding code long enough
    to be distinctive (see ``CODE_LENGTH_THRESHOLD``). Empty/``None`` values are omitted.
    """
    texts = [
        fields.probable_cause(raw),
        fields.factual_narrative(raw),
        fields.analysis_narrative(raw),
    ]
    codes = fields.occurrence_codes(raw) + fields.finding_codes(raw)
    return [text for text in texts if text] + [
        code for code in codes if len(code) >= CODE_LENGTH_THRESHOLD
    ]


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
