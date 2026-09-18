import copy
import json
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.boundary import RecordingBatchRunner, assert_boundary_holds, assert_requests_clean

from ntsb_probable_cause import fields
from ntsb_probable_cause.model.client import Payload, RecordingFakeClient
from ntsb_probable_cause.records import split as split_module
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.records.synthesis import Synthesis
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring import runner as runner_module
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.runner import Runner, RunSpec

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
