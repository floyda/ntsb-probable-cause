import copy
import json
from collections.abc import Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from tests.boundary import (
    CODE_LENGTH_THRESHOLD,
    RecordingBatchRunner,
    as_ongoing,
    assert_boundary_holds,
    assert_requests_clean,
    withheld_windows,
)
from tests.test_attach import _docket as _small_docket

from ntsb_probable_cause import fields
from ntsb_probable_cause.docket.attach import attach_docket
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.model import client as client_module
from ntsb_probable_cause.model.batch import BatchRequest
from ntsb_probable_cause.model.client import (
    ModelSettings,
    Payload,
    RecordingFakeClient,
    ToolCall,
    Turn,
)
from ntsb_probable_cause.recorder.cases import observe_case
from ntsb_probable_cause.records import split as split_module
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import runner as runner_module
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.runner import Runner, RunSpec
from ntsb_probable_cause.store import Store

_GOOD_STAGE1 = json.dumps(
    {
        "evidence_narrative": "n",
        "probable_cause": "p",
        "lay_explanation": "l",
        "confidence": 0.7,
        "abstain": False,
        "evidence_used": [],
        "occurrence": [{"phase": "552", "event": "230", "probability": 0.7}],
        "findings": [{"category6": "020630", "modifier": "44", "probability": 0.6}],
    }
)
_GOOD_REFINE = json.dumps({"items": [{"index": 0, "item8": "02063040"}]})


def test_boundary_holds_for_every_fixture(record_fixtures: list[dict[str, object]]) -> None:
    for raw in record_fixtures:
        assert_boundary_holds(raw)


def test_boundary_holds_and_hides_the_builder_name_for_amateur_built_aircraft(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Decision 0020: an invented builder name in aircraftMake never reaches the payload."""
    raw = copy.deepcopy(record_fixtures[0])
    aircrafts = raw["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftAmateurBuilt"] = True
    aircrafts[0]["aircraftMake"] = "INVENTED BUILDER"
    aircrafts[0]["aircraftModel"] = "INVENTED MODEL"

    assert_boundary_holds(raw)

    evidence, _, _ = split_record(raw)
    payload = Payload.from_evidence(evidence)
    assert "INVENTED BUILDER" not in payload.text
    assert "INVENTED MODEL" not in payload.text


def test_boundary_test_fails_when_the_splitter_leaks(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Mutation test: a splitter that copies the factual narrative into evidence must be caught."""

    def leaky_split(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
        evidence, synthesis, verdict = split_record(raw)
        leaked = evidence.model_copy(update={"prelim_narrative": synthesis.factual_narrative})
        return leaked, synthesis, verdict

    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    with pytest.raises(AssertionError, match=r"^provenance"):
        assert_boundary_holds(raw, leaky_split)


def test_boundary_test_fails_when_a_value_comes_from_the_wrong_place(
    record_fixtures: list[dict[str, object]],
) -> None:
    def swapped_split(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
        evidence, synthesis, verdict = split_record(raw)
        return (
            evidence.model_copy(update={"aircraft_make": "NOT FROM THE RECORD"}),
            synthesis,
            verdict,
        )

    with pytest.raises(AssertionError, match=r"^provenance"):
        assert_boundary_holds(record_fixtures[0], swapped_split)


def test_boundary_fails_when_only_the_tripwire_can_catch_a_leak(
    record_fixtures: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation test: prove the tripwire layer itself can fail, not just provenance.

    The other two mutation tests above both fail on provenance, because their mutated evidence
    disagrees with what the real extractor reads from the raw record. This test mutates the raw
    record itself so an evidence extractor's own faithful reading equals the record's probable
    cause -- provenance holds -- and disables ``split_record``'s own leakage guard, so only
    ``assert_boundary_holds``'s tripwire block can catch the leak.
    """
    raw = next(r for r in record_fixtures if fields.probable_cause(r))
    mutated = copy.deepcopy(raw)
    aircrafts = mutated["aircrafts"]
    assert isinstance(aircrafts, list)
    aircrafts[0]["aircraftMake"] = fields.probable_cause(raw)

    monkeypatch.setattr(split_module, "find_leaks", lambda *_a, **_k: [])

    with pytest.raises(AssertionError, match=r"^tripwire"):
        assert_boundary_holds(mutated)


def test_runner_never_sends_withheld_text_as_system_text(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Decision 0028/spec §8: only ``scoring/judge.py`` may put withheld text in a system prompt.

    Runs the real ``Runner`` over every fixture with a fake client and inspects every system
    string the fake actually received (``RecordingFakeClient.systems``, not what the runner
    intended to send). This would fail if an answering system prompt ever carried the case's
    factual narrative or probable cause -- for example if the case-number/prompt machinery in
    ``scoring/runner.py`` or ``scoring/prompt.py`` were changed to include withheld text.
    """
    client = RecordingFakeClient([_GOOD_STAGE1, _GOOD_REFINE] * len(record_fixtures))
    spec = RunSpec(
        sample="dev-400",
        arm="ceiling",
        sync=True,
        price_variant="standard",
        expected_cost_per_case_usd=0.001,
    )
    run = Runner(
        client,
        batch=None,
        tables=load_tables(),
        seen_pairs=frozenset(),
        runs_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.md",
        month_spent_usd=0.0,
        commit=("abc1234", False),
        now=lambda: datetime(2026, 9, 15, tzinfo=UTC),
    )
    run.run(spec, record_fixtures)

    assert client.systems, "the run should have made at least one answering call"
    withheld: list[tuple[str, str]] = []
    for raw in record_fixtures:
        narrative = fields.factual_narrative(raw)
        cause = fields.probable_cause(raw)
        if narrative:
            withheld.append(("factual narrative", narrative))
        if cause:
            withheld.append(("probable cause", cause))

    for system in client.systems:
        for kind, text in withheld:
            assert text not in system, f"tripwire: {kind} reached an answering system prompt"


def _withheld(record_fixtures: list[dict[str, object]]) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for raw in record_fixtures:
        narrative = fields.factual_narrative(raw)
        cause = fields.probable_cause(raw)
        if narrative:
            found.append(("factual narrative", narrative))
        if cause:
            found.append(("probable cause", cause))
    assert found, "fixtures carry no withheld text: the boundary test would be vacuous"
    return found


def _batch_runner(tmp_path: Path, batch: RecordingBatchRunner) -> Runner:
    return Runner(
        RecordingFakeClient([]),
        batch=batch,
        tables=load_tables(),
        seen_pairs=frozenset(),
        runs_dir=tmp_path / "runs",
        ledger_path=tmp_path / "ledger.md",
        month_spent_usd=0.0,
        commit=("abc1234", False),
        now=lambda: datetime(2026, 9, 18, tzinfo=UTC),
    )


def test_batch_runner_never_sends_withheld_text_in_any_request(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """The batch path is the default; it must be checked like the sync path (spec §3.1)."""
    batch = RecordingBatchRunner(stage1=_GOOD_STAGE1, stage2=_GOOD_REFINE)
    spec = RunSpec(sample="dev-400", arm="ceiling", expected_cost_per_case_usd=0.001)
    _batch_runner(tmp_path, batch).run(spec, record_fixtures)

    assert batch.requests, "the run should have submitted at least one batch request"
    assert_requests_clean(batch.requests, _withheld(record_fixtures))


def test_batch_boundary_test_fails_when_a_system_prompt_leaks(
    tmp_path: Path,
    record_fixtures: list[dict[str, object]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mutation test: the batch assertion must be able to fail (decision 0016)."""
    leaked = next(
        fields.factual_narrative(r) for r in record_fixtures if fields.factual_narrative(r)
    )

    def leaky_retry_system(system: str, error: str | None) -> str:
        return f"{system}\n\n{leaked}"

    monkeypatch.setattr(runner_module.Runner, "_retry_system", staticmethod(leaky_retry_system))
    batch = RecordingBatchRunner(stage1=_GOOD_STAGE1, stage2=_GOOD_REFINE)
    spec = RunSpec(sample="dev-400", arm="ceiling", expected_cost_per_case_usd=0.001)
    _batch_runner(tmp_path, batch).run(spec, record_fixtures)

    with pytest.raises(AssertionError, match=r"^tripwire"):
        assert_requests_clean(batch.requests, _withheld(record_fixtures))


@pytest.mark.parametrize(
    "where",
    ["system", "payload", "history", "tool_payload", "tool_call_arguments"],
)
def test_assert_requests_clean_trips_on_every_surface(where: str) -> None:
    """Each surface _request_texts inspects must be able to fail, not only the system prompt."""
    needle = "the pilot did not extend the landing gear"
    clean = Payload(text="clean evidence", _token=client_module._CONSTRUCTION_TOKEN)
    history: tuple[Turn, ...] = ()
    if where == "history":
        history = (Turn(role="assistant", content=needle),)
    elif where == "tool_payload":
        history = (
            Turn(
                role="tool",
                tool_call_id="c1",
                payload=Payload(text=needle, _token=client_module._CONSTRUCTION_TOKEN),
            ),
        )
    elif where == "tool_call_arguments":
        history = (
            Turn(
                role="assistant",
                content=None,
                tool_calls=(ToolCall(call_id="c1", name="list_docket", arguments=needle),),
            ),
        )
    request = BatchRequest(
        custom_id="case-1",
        payload=(
            Payload(text=needle, _token=client_module._CONSTRUCTION_TOKEN)
            if where == "payload"
            else clean
        ),
        settings=ModelSettings(),
        system=needle if where == "system" else "",
        history=history,
    )
    with pytest.raises(AssertionError, match=r"^tripwire"):
        assert_requests_clean([request], [("factual narrative", needle)])


def test_assert_requests_clean_passes_when_nothing_leaks() -> None:
    """The negative case: a request with none of the withheld text passes."""
    request = BatchRequest(
        custom_id="case-1",
        payload=Payload(text="clean evidence", _token=client_module._CONSTRUCTION_TOKEN),
        settings=ModelSettings(),
        system="you are an investigator",
        history=(Turn(role="assistant", content="a clean turn"),),
    )
    assert_requests_clean([request], [("factual narrative", "the pilot did not extend the gear")])


def test_batch_boundary_assertion_reads_tool_turn_payloads(
    record_fixtures: list[dict[str, object]],
) -> None:
    """A tool turn's payload is one of the texts the batch assertion inspects."""
    raw = next(r for r in record_fixtures if fields.factual_narrative(r))
    evidence, synthesis, _ = split_record(raw)
    leaked = evidence.model_copy(update={"prelim_narrative": synthesis.factual_narrative})
    request = BatchRequest(
        custom_id="x",
        payload=Payload.from_evidence(evidence),
        settings=ModelSettings(),
        system="",
        history=(Turn(role="tool", tool_call_id="c1", payload=Payload.from_evidence(leaked)),),
    )
    with pytest.raises(AssertionError, match=r"tool turn payload"):
        assert_requests_clean([request], [("factual narrative", synthesis.factual_narrative or "")])


def test_boundary_holds_on_a_case_context_with_documents(
    record_fixtures: list[dict[str, object]],
) -> None:
    docket = _small_docket({1: "[page 1 of 3]\nThe crankshaft was intact.\n"})
    context = attach_docket(record_fixtures[0], docket, documents=[1]).context
    assert_boundary_holds(context)


def test_synthesis_document_never_reaches_the_payload(
    record_fixtures: list[dict[str, object]],
) -> None:
    """Roadmap §9 / spec §12: a document holding withheld text is stopped whatever its title."""
    raw = next(r for r in record_fixtures if fields.probable_cause(r))
    cause = fields.probable_cause(raw) or ""
    docket = _small_docket({1: f"[page 1 of 3]\nFactual Report. {cause}\n"})
    context = attach_docket(raw, docket, documents=[1]).context
    with pytest.raises(LeakageError):
        split_record(context)
    with pytest.raises(AssertionError, match=r"^tripwire"):
        assert_boundary_holds(context, lambda r: split_record(r, min_sentence_chars=10**9))


@pytest.fixture
def closing_record(record_fixtures: list[dict[str, object]]) -> dict[str, object]:
    """A closed dev-split record carrying a full set of withheld text and codes (deep-copied).

    Picked so ``withheld_windows`` has something of every kind to check: a probable cause, two
    *different* narratives (a fixture whose factual and analysis narratives are identical would
    let a factual-narrative check pass by accident against the analysis narrative), a factual
    narrative over 4KB with characters JSON escapes (a quote or a newline) -- long and escapable
    enough to exercise both leak shapes fix round 1 found undetected -- and at least one
    occurrence code and one finding code long enough to qualify under
    ``CODE_LENGTH_THRESHOLD``. Otherwise the store boundary test below could pass vacuously,
    checking nothing, or checking too little to catch a real leak.
    """
    raw = next(
        r
        for r in record_fixtures
        if fields.probable_cause(r)
        and fields.factual_narrative(r)
        and fields.analysis_narrative(r)
        and fields.factual_narrative(r) != fields.analysis_narrative(r)
        and len(fields.factual_narrative(r) or "") > 4096
        and (
            '"' in (fields.factual_narrative(r) or "")
            or "\n" in (fields.factual_narrative(r) or "")
        )
        and fields.occurrence_codes(r)
        and fields.finding_codes(r)
    )
    return copy.deepcopy(raw)


def _leaky_split(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
    """A splitter that copies the factual narrative into the preliminary narrative (Task 7)."""
    evidence, synthesis, verdict = split_record(raw)
    leaked = evidence.model_copy(update={"prelim_narrative": synthesis.factual_narrative})
    return leaked, synthesis, verdict


def _leaky_split_via_snapshot(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
    """A splitter that copies the factual narrative into an ordinary evidence field.

    Unlike ``_leaky_split`` (which leaks through ``prelim_narratives.text``, a plain TEXT
    column), this leaks through ``field_snapshots.value_json``, written with
    ``json.dumps(value, sort_keys=True)`` -- so the stored bytes are the *escaped* form of the
    narrative, not the raw form. Fix round 1, Important 1: this is one of the two leak shapes
    the original boundary check could not see.
    """
    evidence, synthesis, verdict = split_record(raw)
    leaked = evidence.model_copy(update={"weather_metar": synthesis.factual_narrative})
    return leaked, synthesis, verdict


def _read_store_bytes(db_path: Path) -> bytes:
    """A store's ``.sqlite`` file plus any not-yet-checkpointed ``-wal`` file, concatenated."""
    wal_path = db_path.with_name(db_path.name + "-wal")
    if wal_path.exists():
        return db_path.read_bytes() + wal_path.read_bytes()
    return db_path.read_bytes()


def test_store_never_holds_synthesis_or_verdict(
    tmp_path: Path, closing_record: dict[str, object]
) -> None:
    """Night 1: Ongoing, with a preliminary narrative. Night 2: the case closes.

    Two nights instead of one so the byte check also covers the prelim-narrative table, the
    status transition and the tail, not only the closing record's own field snapshots (fix
    round 1). The closing record carries the probable cause and both narratives; none of it,
    raw or JSON-escaped, in any window, reaches the file.
    """
    ongoing = as_ongoing(
        closing_record,
        prelim_text="Preliminary information indicates the flight departed on a local flight.",
    )
    store = Store(tmp_path / "r.sqlite")
    store.migrate()
    observe_case(store, ongoing, run_id=1, today=date(2026, 10, 1))
    observe_case(store, closing_record, run_id=2, today=date(2026, 10, 2))
    store.close()
    blob = _read_store_bytes(tmp_path / "r.sqlite")

    # Each kind (cause, narrative, codes) must be present on the fixture, or this test could
    # pass by checking nothing of that kind rather than because nothing leaked.
    assert fields.probable_cause(closing_record)
    assert fields.factual_narrative(closing_record)
    assert fields.analysis_narrative(closing_record)
    qualifying_codes = [
        code
        for code in fields.occurrence_codes(closing_record) + fields.finding_codes(closing_record)
        if len(code) >= CODE_LENGTH_THRESHOLD
    ]
    assert qualifying_codes

    windows = withheld_windows(closing_record)
    assert windows
    for window in windows:
        assert window.encode() not in blob, "withheld string in store"


def test_store_boundary_test_fails_when_the_split_is_bypassed(
    tmp_path: Path, closing_record: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation: a splitter that leaks through the plain-text prelim table must be caught."""
    monkeypatch.setattr("ntsb_probable_cause.recorder.cases.split_record", _leaky_split)
    with pytest.raises(AssertionError, match="withheld string in store"):
        test_store_never_holds_synthesis_or_verdict(tmp_path, closing_record)


def test_store_boundary_test_fails_when_a_snapshot_role_leaks(
    tmp_path: Path, closing_record: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation: a splitter that leaks through a JSON-escaped field_snapshots row must be
    caught too -- proves the escaped-form windows, not just the raw-form ones, are checked."""
    monkeypatch.setattr(
        "ntsb_probable_cause.recorder.cases.split_record", _leaky_split_via_snapshot
    )
    with pytest.raises(AssertionError, match="withheld string in store"):
        test_store_never_holds_synthesis_or_verdict(tmp_path, closing_record)


def _has_withheld_text(raw: Mapping[str, object]) -> bool:
    return bool(
        fields.probable_cause(raw)
        or fields.factual_narrative(raw)
        or fields.analysis_narrative(raw)
    )


def test_store_never_holds_synthesis_or_verdict_for_every_fixture(
    tmp_path: Path, record_fixtures: list[dict[str, object]]
) -> None:
    """Every development fixture carrying withheld text is checked, not just one (fix round 1).

    A single hand-picked fixture proved the mechanism works; this sweeps every fixture that
    actually carries withheld content, so a leak that only one particular record's shape would
    trigger cannot hide behind the others never being tried.
    """
    carriers = [raw for raw in record_fixtures if _has_withheld_text(raw)]
    assert carriers, "no fixture carries withheld text: this test would be vacuous"

    store = Store(tmp_path / "sweep.sqlite")
    store.migrate()
    for index, raw in enumerate(carriers):
        observe_case(store, raw, run_id=index + 1, today=date(2026, 10, 1))
    store.close()
    blob = _read_store_bytes(tmp_path / "sweep.sqlite")

    for raw in carriers:
        for window in withheld_windows(raw):
            assert window.encode() not in blob, "withheld string in store"
