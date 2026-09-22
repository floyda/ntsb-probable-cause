import copy
import json
from collections.abc import Callable, Mapping
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from tests.boundary import (
    CODE_LENGTH_THRESHOLD,
    RecordingBatchRunner,
    _window_spans,
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
    ``json.dumps(value, sort_keys=True)``. This exercises the ``field_snapshots`` leak path,
    one of the two shapes fix round 1, Important 1 found the original check could not see --
    but it does NOT by itself prove the *escaped*-form windows are load-bearing: most of an
    8000-character narrative contains no character JSON escapes, so plenty of plain raw-form
    windows still match and this test would pass even with the escaped-form windows removed
    (fix round 2, finding 1b, corrects this docstring's earlier, mistaken claim to the
    contrary). ``test_store_boundary_test_fails_when_only_the_escaped_form_can_catch_the_leak``
    below is the test that actually needs the escaped form.
    """
    evidence, synthesis, verdict = split_record(raw)
    leaked = evidence.model_copy(update={"weather_metar": synthesis.factual_narrative})
    return leaked, synthesis, verdict


def _leaky_split_via_snapshot_escaped_only(
    raw: Mapping[str, object],
) -> tuple[Evidence, Synthesis, Verdict]:
    """A splitter that leaks the probable cause through an evidence field, escaped-only.

    The probable cause this is run against (see the mutation test below) is edited to contain
    a double quote, which ``json.dumps`` rewrites to ``\\"``. Once stored, the raw form (with a
    literal ``"``) is never written to the file at all -- only the escaped form is -- so this
    leak can be caught only by a check that includes the escaped-form windows (fix round 2,
    finding 1b).
    """
    evidence, synthesis, verdict = split_record(raw)
    leaked = evidence.model_copy(update={"weather_metar": verdict.probable_cause})
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
    """Mutation: a splitter that leaks through a ``field_snapshots`` row must be caught."""
    monkeypatch.setattr(
        "ntsb_probable_cause.recorder.cases.split_record", _leaky_split_via_snapshot
    )
    with pytest.raises(AssertionError, match="withheld string in store"):
        test_store_never_holds_synthesis_or_verdict(tmp_path, closing_record)


def test_withheld_windows_include_the_escaped_form(closing_record: dict[str, object]) -> None:
    """Unit check, fix round 2 finding 1b: ``withheld_windows`` really does emit windows

    built from the JSON-escaped form of a withheld text, not only the raw form -- checked
    directly on the function's own output, independent of any store or mutation test, so a
    regression that silently dropped the escaped form would be caught here even if some other
    raw-form window happened to still catch a given mutation test's specific leak.
    """
    mutated = copy.deepcopy(closing_record)
    narratives = mutated["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["probableCause"] = 'The pilot\'s failure to maintain control, per "witness A".'

    windows = withheld_windows(mutated)
    assert any('\\"' in window for window in windows), (
        "no window carried the escaped-quote form; escaped windows are not being produced"
    )


def test_store_boundary_test_fails_when_only_the_escaped_form_can_catch_the_leak(
    tmp_path: Path, closing_record: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Mutation: a leak that ONLY its escaped form can find must be caught.

    Fix round 2, finding 1b: ``test_store_boundary_test_fails_when_a_snapshot_role_leaks``
    (above) exercises the ``field_snapshots`` leak path but does not need the escaped-form
    windows to catch it, since most of an 8000-character narrative contains no character JSON
    escapes at all. This test edits the probable cause to contain a double quote, which
    ``json.dumps`` rewrites to ``\\"`` -- so the raw form (with a literal ``"``) is never
    written to the file, and only a check that includes the escaped-form windows can catch it.
    Confirmed, outside pytest, to fail when ``_json_escaped`` is replaced by the identity
    function (Task 7 report).
    """
    mutated = copy.deepcopy(closing_record)
    narratives = mutated["narratives"]
    assert isinstance(narratives, list)
    narratives[0]["probableCause"] = 'The pilot\'s failure to maintain control, per "witness A".'

    monkeypatch.setattr(
        "ntsb_probable_cause.recorder.cases.split_record", _leaky_split_via_snapshot_escaped_only
    )
    with pytest.raises(AssertionError, match="withheld string in store"):
        test_store_never_holds_synthesis_or_verdict(tmp_path, mutated)


# Fix round 2, finding 1a: the reviewer's own alignment sweep (0..4199, every offset) found 155
# of 4200 page alignments undetected with round 1's non-overlapping windows. This reproduces it
# at a coarser stride so it stays fast in CI (measured: ~2 seconds for all 600 real stores, one
# store per alignment, each closed and read back as bytes -- see the Task 7 report).
_ALIGNMENT_STRIDE = 7
_ALIGNMENT_RANGE = range(0, 4200, _ALIGNMENT_STRIDE)  # exactly 600 alignments


def _leaky_padded_weather_metar(
    padded: str,
) -> Callable[[Mapping[str, object]], tuple[Evidence, Synthesis, Verdict]]:
    def leaky(raw: Mapping[str, object]) -> tuple[Evidence, Synthesis, Verdict]:
        evidence, synthesis, verdict = split_record(raw)
        leaked = evidence.model_copy(update={"weather_metar": padded})
        return leaked, synthesis, verdict

    return leaky


def test_boundary_windows_survive_every_page_alignment(
    tmp_path: Path, closing_record: dict[str, object], monkeypatch: pytest.MonkeyPatch
) -> None:
    """SLOW (~600 real SQLite stores, one per page alignment; budget a few seconds).

    Fix round 2, finding 1a. The probable cause is embedded in ``"x" * 5000 + cause + "y" * n``
    (the reviewer's own construction) for 600 values of ``n`` spanning one page's width, so the
    cause lands at a different byte offset relative to whatever SQLite page split occurs for
    each ``n``. A real ``Store`` is built and closed for every alignment -- there is no cheaper
    way to see where SQLite actually splits a page than to let it happen -- so this is
    intentionally the slowest test in this file, capped at 600 stores by ``_ALIGNMENT_STRIDE``.
    Every alignment must be caught: 0 misses. Demonstrated, outside pytest, to fail (22 of the
    600 alignments undetected) against round 1's non-overlapping windows (Task 7 report).
    """
    cause = fields.probable_cause(closing_record)
    assert cause
    windows = withheld_windows(closing_record)
    assert windows

    # Fix round 3, Minor: the "x"*5000 prefix and the 0..4200 alignment range below assume
    # SQLite's default 4096-byte page; fail loudly rather than silently testing nothing if that
    # default ever changes.
    probe_store = Store(tmp_path / "page-size-probe.sqlite")
    probe_store.migrate()
    assert probe_store.connection.execute("PRAGMA page_size").fetchone()[0] == 4096
    probe_store.close()

    misses: list[int] = []
    for n in _ALIGNMENT_RANGE:
        padded = "x" * 5000 + cause + "y" * n
        monkeypatch.setattr(
            "ntsb_probable_cause.recorder.cases.split_record", _leaky_padded_weather_metar(padded)
        )
        db_path = tmp_path / f"align-{n}.sqlite"
        store = Store(db_path)
        store.migrate()
        observe_case(store, closing_record, run_id=1, today=date(2026, 10, 1))
        store.close()
        blob = _read_store_bytes(db_path)
        if not any(window.encode() in blob for window in windows):
            misses.append(n)

    assert misses == [], f"{len(misses)}/{len(_ALIGNMENT_RANGE)} alignments undetected: {misses}"


def _unprotected_split_positions(length: int) -> list[int]:
    """Every split position (1..``length``-1) that leaves no window entirely on one side of it.

    A window ``(start, end)`` "protects" position ``p`` if the window does not straddle it --
    ``end <= p`` or ``start >= p`` -- so it would still be one contiguous run of bytes in the
    file even if the text were cut exactly at ``p``. A position with no protecting window at
    all is unprotected: every generated window straddles it, so a single cut there defeats the
    whole check for that position. Pure arithmetic on ``_window_spans``, no text or store
    needed, so this is cheap enough to run over many lengths (fix round 3, Minor 1).
    """
    spans = _window_spans(length)
    return [p for p in range(1, length) if not any(end <= p or start >= p for start, end in spans)]


def test_windows_gap_below_99_characters_is_the_measured_size() -> None:
    """Fix round 3, Important: pin the residual `_windows` leaves, instead of only describing

    it in prose. The reviewer measured these exact counts by running the real window
    arithmetic over every length from 1 to 5000 and every split position; this test is that
    measurement, kept in the suite so the residual cannot silently grow (a regression that
    widened the gap, e.g. by shrinking `_MIN_WINDOW_CHARS` or `_STRIDE_DIVISOR`, would fail
    this test, not just look wrong in a docstring nobody re-reads).

    Two of the nine development-fixture probable causes (52 and CEN11CA664's 83 characters)
    fall inside this gap; the 52-character count here (47/51) also matches the real-store
    sweep in the Task 7 report (47 of 4200 alignments missed for that exact cause).
    """
    # The gap: 51-98 characters, every one of them has at least one unprotected position.
    assert len(_unprotected_split_positions(51)) > 0
    for length in range(51, 99):
        assert len(_unprotected_split_positions(length)) > 0, (
            f"{length} characters: expected at least one unprotected split position"
        )

    # The reviewer's own spot-measured counts, exactly, so any change to the window geometry
    # that shifts these is caught here rather than in a docstring's stale numbers.
    measured = {52: 47, 60: 39, 75: 24, 83: 16, 98: 1}
    for length, expected_unprotected in measured.items():
        actual = len(_unprotected_split_positions(length))
        assert actual == expected_unprotected, (
            f"{length} characters: expected {expected_unprotected} unprotected positions, "
            f"got {actual} -- the measured residual in the docstrings is now stale"
        )
        # A regression that widens the gap (more unprotected positions than measured) must
        # fail; the bound is <=, per the fix-round-3 instruction, so a future improvement that
        # narrows the gap further does not also have to be re-pinned to stay green.
        assert actual <= expected_unprotected

    # Full protection: 99 characters (2 * _MIN_WINDOW_CHARS - 1) onward, no unprotected
    # position at all, checked at the boundary and comfortably above it.
    assert _unprotected_split_positions(99) == []
    for length in (100, 150, 200, 219, 300, 1000, 8000):
        assert _unprotected_split_positions(length) == [], f"{length} characters: expected 0"

    # 50 characters or fewer: one window, unprotected at every split position.
    for length in (10, 49, 50):
        assert len(_unprotected_split_positions(length)) == length - 1


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
        outcome = observe_case(store, raw, run_id=index + 1, today=date(2026, 10, 1))
        # A fixture whose split failed would leave nothing written for it, so the byte check
        # below would trivially find no leak -- not because none occurred, but because nothing
        # was ever checked against. Fix round 2, Minor.
        assert outcome.failed is None, f"fixture split failed unexpectedly: {outcome.failed}"
    store.close()
    blob = _read_store_bytes(tmp_path / "sweep.sqlite")

    for raw in carriers:
        for window in withheld_windows(raw):
            assert window.encode() not in blob, "withheld string in store"
