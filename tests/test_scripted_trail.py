"""Done means 4: per-step scoring on a scripted three-step trail replayed through the fake."""

import json

import pytest

from ntsb_probable_cause.model.client import (
    ModelSettings,
    Payload,
    RecordingFakeClient,
)
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import parse_hypothesis
from ntsb_probable_cause.scoring.metrics import score_trail

T = load_tables()
VERDICT = Verdict(
    probable_cause=None,
    occurrence_codes=("552230",),
    finding_codes=("0206304044",),
    finding_codes_in_cause=("0206304044",),
)


def step(occ: list[tuple[str, str, float]], conf: float) -> str:
    return json.dumps(
        {
            "evidence_narrative": "n",
            "probable_cause": "p",
            "lay_explanation": "l",
            "confidence": conf,
            "abstain": False,
            "evidence_used": [],
            "occurrence": [{"phase": p, "event": e, "probability": pr} for p, e, pr in occ],
            "findings": [{"category6": "020630", "modifier": "44", "probability": 0.6}],
        }
    )


def test_three_step_trail_is_scored_step_by_step() -> None:
    client = RecordingFakeClient(
        [
            step([("551", "230", 0.5)], 0.4),
            step([("552", "230", 0.5), ("551", "230", 0.3)], 0.6),
            step([("552", "230", 0.8)], 0.85),
        ]
    )
    payload = Payload.from_evidence(
        Evidence(
            case_id="X",
            docket_url=None,
            phase_of_flight="Landing",
        )
    )
    trail = [
        parse_hypothesis(client.complete(payload, ModelSettings()).content or "", T)
        for _ in range(3)
    ]
    scored = score_trail(trail, VERDICT, T, seen_pairs={"551230", "552230"})
    assert [s.scores.occurrence_top1 for s in scored] == [
        False,
        True,
        True,
    ]
    assert [s.prob_on_true for s in scored] == [0.0, 0.5, 0.8]
    assert [round(s.information_gain, 6) for s in scored] == [
        0.0,
        0.5,
        pytest.approx(0.3),
    ]
    # step 2 -> 3: before {552230:.5, 551230:.3, other:.2}; after {552230:.8,
    # other:.2}
    # TV = 0.5*(|.5-.8| + |.3-0| + |.2-.2|) = 0.3
    assert scored[2].movement == pytest.approx(0.3)
    assert len(client.payloads) == 3
