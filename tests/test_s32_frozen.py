"""S3.2 changes nothing the model sees, and no round's money goes uncounted (spec §4.1, 0135).

Three pins, none of which drives a change:

1. The loop's prompt version is the one S3.1 froze (decision 142). The version fingerprints the
   source of ten files (``agent.texts.TEXT_SOURCES``), a comment included, so an edit to any of
   them fails here.
2. Every call arm C and arm B's tool post-pass send carries temperature 0.0, read from the exact
   JSON body the OpenRouter client would post.
3. A batch run whose dead round reported a cost counts that cost in the monthly guard: the run's
   billed total is every round's reported cost, the dead one included (decision 0135, item 1).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.test_agent_armb import POST, _post, _requests, _source
from tests.test_agent_drive import _scripts, _sync_replies
from tests.test_agent_run import _runner, _sync_spec
from tests.test_boundary import _arm_c_batch_requests, _arm_c_raws
from tests.test_budget import _record

from ntsb_probable_cause.agent import run, texts
from ntsb_probable_cause.agent.drive import REPLIES_FILE, ROUNDS_FILE, ReplyRow, RoundRow
from ntsb_probable_cause.agent.run import round_costs
from ntsb_probable_cause.model.batch import BatchRequest
from ntsb_probable_cause.model.client import RecordingFakeClient
from ntsb_probable_cause.model.openrouter import request_body
from ntsb_probable_cause.scoring.budget import month_spent, spent_usd
from ntsb_probable_cause.scoring.records import write_jsonl

FROZEN = "s3-v1+ge17fecdc66ec+p947fac1c86a4"


def test_the_loops_prompt_version_is_the_frozen_one() -> None:
    """Spec §4.1, decision 142: S3.2 changes no byte the model sees."""
    assert texts.prompt_version(run.GUIDANCE) == FROZEN


def _temperatures(requests: Sequence[BatchRequest]) -> list[object]:
    """The ``temperature`` of the JSON body each request would be posted as."""
    return [
        request_body(r.payload, r.settings, system=r.system, history=r.history)["temperature"]
        for r in requests
    ]


def test_every_arm_c_and_arm_b_post_pass_call_is_sent_at_temperature_zero(tmp_path: Path) -> None:
    """Spec §2: temperature 0.0 on every call, in a synchronous run and in a batch round."""
    sync = RecordingFakeClient([r for r in _sync_replies(_scripts()) if r is not None])
    _runner(tmp_path / "c-runs", client=sync).run(_sync_spec(), _arm_c_raws())
    arm_c_sync = _requests(sync)
    arm_c_batch = _arm_c_batch_requests(tmp_path / "c-batch")

    runs = tmp_path / "b-runs"
    source, _ = _source(runs)
    post = RecordingFakeClient(POST)
    _post(runs, source, client=post)
    arm_b_post = _requests(post)

    for requests in (arm_c_sync, arm_c_batch, arm_b_post):
        assert len(requests) >= 4, "the calls were made: the check is not vacuous"
        assert set(_temperatures(requests)) == {0.0}


def test_a_dead_rounds_reported_cost_is_part_of_the_billed_total_the_guard_counts(
    tmp_path: Path,
) -> None:
    """Decision 0135 item 1: a round that returned no replies was still billed."""
    started = datetime(2026, 10, 3, 9, tzinfo=UTC)
    folder = tmp_path / "20261003T090000-abc1234-dev-400-C"
    rounds = [
        RoundRow(
            round=1,
            batch_id="b1",
            submitted_at=started,
            custom_ids=("case-a#0",),
            finished_at=started,
            status="expired",
            reported_cost_usd=0.01,
        ),
        RoundRow(
            round=2,
            batch_id="b2",
            submitted_at=started,
            custom_ids=("case-a#0",),
            finished_at=started,
            status="completed",
            reported_cost_usd=0.02,
        ),
    ]
    reply = ReplyRow(
        case_id="case-a",
        call_index=0,
        reply=None,
        error="model: boom",
        sent_at=started,
        returned_at=started,
        batch_id="b2",
    )
    write_jsonl(folder / ROUNDS_FILE, rounds)
    write_jsonl(folder / REPLIES_FILE, [reply])

    costs = round_costs(folder)
    assert costs.dead_usd == pytest.approx(0.01)  # only b1 returned nothing
    assert costs.reported_usd == pytest.approx(0.03)  # both rounds

    record = _record(
        run_id=folder.name,
        started=started,
        batch_ids=costs.batch_ids,
        cost_usd=0.09,
        reported_batch_cost_usd=costs.reported_usd,
    )
    write_jsonl(folder / "run.jsonl", [record])

    assert spent_usd(record) == pytest.approx(0.03)
    assert month_spent(tmp_path, now=started) == pytest.approx(0.03)
