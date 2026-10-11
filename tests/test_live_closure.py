"""Closure record version 2 from an invented run folder (decision 0176)."""

import hashlib
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import respx
from tests.test_live_morning import NOW, _call, _docket, _result

from ntsb_probable_cause import sources
from ntsb_probable_cause.agent.drive import REPLIES_FILE, ReplyRow
from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.live.closure import CASES_FILE, RUN_FILE, Prepared, build_records
from ntsb_probable_cause.live.queue import QueuedCase
from ntsb_probable_cause.scoring.records import RunRecord, write_jsonl

MKEY = 4242
CASE = "XXX26LA001"


def _run() -> RunRecord:
    return RunRecord(
        run_id="r",
        sample="live",
        arm="C",
        exclusions=(),
        includes=(),
        prompt_version="v",
        model="openai/gpt-6-luna",
        price_variant="batch",
        cap_usd=0.3,
        budget_usd=40.0,
        commit_sha="abc",
        dirty=False,
        started=datetime(2026, 10, 8, 1, tzinfo=UTC),
        finished=datetime(2026, 10, 8, 2, tzinfo=UTC),
    )


def _reply(n: int, sha: str | None) -> ReplyRow:
    return ReplyRow(
        case_id=CASE,
        call_index=n,
        reply=None,
        error="x",
        sent_at=NOW,
        returned_at=NOW,
        batch_id=None,
        request_sha256=sha,
    )


def test_record_carries_event_date_hashes_and_replies(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    write_jsonl(folder / RUN_FILE, [_run()])
    write_jsonl(folder / CASES_FILE, [_result(CASE)])
    write_jsonl(folder / REPLIES_FILE, [_reply(0, "1" * 64), _reply(1, None), _reply(2, "2" * 64)])
    write_jsonl(
        folder / TRAIL_FILE,
        [
            _call(CASE, "answer", 0, reply_model="m2", reply_provider="zeta"),
            _call(CASE, "answer", 1, reply_model="m1", reply_provider="alpha"),
            _call(CASE, "answer", 2, reply_model="m1", reply_provider=None),
        ],
    )
    cache = tmp_path / "cache"
    with respx.mock as router:
        router.get(sources.docket_url(MKEY)).mock(return_value=httpx.Response(200, text="page"))
        router.get(sources.docket_document_url("/d/2")).mock(
            return_value=httpx.Response(200, content=b"doc")
        )
        with DocketClient(cache, sleep=lambda _s: None) as client:
            client.listing_html(MKEY)
            client.document(MKEY, 2, "/d/2")
    prepared = Prepared(
        case=QueuedCase(
            mkey=MKEY,
            case_id=CASE,
            event_date=date(2026, 9, 1),
            closed_on=date(2026, 10, 5),
            closure_run=1,
        ),
        raw={},
        docket=_docket(MKEY, {1: "read", 2: "read"}),
    )
    (record,) = build_records(folder, [prepared], "0" * 64, cache)
    assert record.format == "live-closure/2"
    assert record.event_date == date(2026, 9, 1)
    assert record.request_sha256s == ("1" * 64, "2" * 64)
    assert record.replied_models == ("m1", "m2")
    assert record.providers == ("alpha", "zeta")
    assert record.listing_sha256 == hashlib.sha256(b"page").hexdigest()
    assert [d.sha256 for d in record.documents] == [None, hashlib.sha256(b"doc").hexdigest()]


def test_a_case_with_no_cache_has_no_hashes(tmp_path: Path) -> None:
    folder = tmp_path / "run"
    folder.mkdir()
    write_jsonl(folder / RUN_FILE, [_run()])
    write_jsonl(folder / CASES_FILE, [_result(CASE)])
    prepared = Prepared(
        case=QueuedCase(
            mkey=MKEY,
            case_id=CASE,
            event_date=date(2026, 9, 1),
            closed_on=date(2026, 10, 5),
            closure_run=1,
        ),
        raw={},
        docket=_docket(MKEY, {1: "read"}),
    )
    (record,) = build_records(folder, [prepared], "0" * 64, tmp_path / "none")
    assert record.listing_sha256 is None
    assert record.request_sha256s == ()
    assert record.documents[0].sha256 is None
