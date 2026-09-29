"""Tests for ``scripts/s3_probe/loop.py``, ``budget.py`` and ``trail.py``: one case, offline.

Every test drives ``run_case`` with a ``RecordingFakeClient`` and scripted, schema-valid
replies. The record is a real development fixture (``ANC09CA024``) relabelled with a
``dev-400`` case ID, because no committed fixture record is itself a ``dev-400`` case and the
loop refuses any other ID. The docket is built in memory (as ``tests/test_attach.py`` and the
earlier probe tests do): a born-digital document, a scanned document read through a cached
transcription (``transcribed_pages=2``), an unreadable scan, and a second born-digital one.
"""

import json
import threading
from pathlib import Path
from typing import Any

import pytest
from scripts.s3_probe.budget import CODING_RESERVE_USD, CaseBudget, RunBudget, call_settings
from scripts.s3_probe.loop import MAX_CODING_CALLS, run_case
from scripts.s3_probe.prompts import base_system
from scripts.s3_probe.trail import NOT_REACHED, CaseTrail

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.attach import prepare_attachment
from ntsb_probable_cause.docket.listing import Listing, ListingEntry
from ntsb_probable_cause.docket.manifest import Docket, DocumentRecord
from ntsb_probable_cause.fields import factual_narrative
from ntsb_probable_cause.model.client import Payload, RecordingFakeClient, Usage
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import CodingStats, PoolCase, build
from ntsb_probable_cause.scoring.hypothesis import HYPOTHESIS_SCHEMA
from ntsb_probable_cause.scoring.samples import sample_ids

TABLES = load_tables()
FIXTURE = Path(__file__).parent / "fixtures" / "records" / "ANC09CA024.json"
DEV_ID = sample_ids("dev-400")[0]
TRUTH, OTHER = "552230", "552090"  # the fixture's verdict: primary, then second occurrence
TITLES = {
    1: "Powerplant Examination Report ZQX-ONE",
    2: "Pilot Operator Report ZQX-TWO",
    3: "Weather Study ZQX-THREE",
    4: "Maintenance Records ZQX-FOUR",
}
TEXTS = {
    1: "[page 1 of 2]\nThe crankcase showed no breach and the valve train moved freely.\n",
    2: "[page 1 of 2]\nThe pilot reported a gust as the airplane touched down.\n",
    4: "[page 1 of 2]\nThe last annual inspection was recorded eleven months earlier.\n",
}


def _raw(case_id: str = DEV_ID) -> dict[str, object]:
    record: dict[str, object] = json.loads(FIXTURE.read_text())["record"]
    record["ntsbNumber"] = case_id
    return record


def _docket(
    texts: dict[int, str] | None = None, *, readable: tuple[int, ...] = (1, 2, 4)
) -> Docket:
    texts = dict(TEXTS if texts is None else texts)
    kinds = {1: "born-digital", 2: "scan", 3: "scan", 4: "born-digital"}
    records = tuple(
        DocumentRecord(
            entry=ListingEntry(
                index=i,
                title=TITLES[i],
                pages=2,
                photos=0,
                doc_type="Report",
                extension="pdf",
                href="/x",
            ),
            category="exam_site",
            status="read" if i in readable else "unreadable: scan",
            pages=2,
            readable_pages=2 if i in readable else 0,
            estimated_tokens=len(texts.get(i, "")) // 4,
            kind=kinds[i],
            transcribed_pages=2 if i == 2 and i in readable else 0,
        )
        for i in (1, 2, 3, 4)
    )
    listing = Listing(mkey=1, declared_items=4, entries=tuple(r.entry for r in records))
    kept = {i: t for i, t in texts.items() if i in readable}
    return Docket(mkey=1, listing=listing, documents=records, texts=kept)


def _stats() -> CodingStats:
    # OTHER defines more pool cases than TRUTH, so the pool's top choice is OTHER.
    cases = [
        PoolCase(year=2010, group="Landing", sequence=(OTHER,)),
        PoolCase(year=2011, group="Landing", sequence=(OTHER, TRUTH)),
        PoolCase(year=2012, group="Landing", sequence=(TRUTH,)),
    ]
    return build(cases, built_from="test")


def _guess(code: str, p: float) -> dict[str, Any]:
    return {"phase": code[:3], "event": code[3:], "probability": p}


def _hyp(*, findings: bool = True, abstain: bool = False, top: str = TRUTH) -> str:
    second = OTHER if top == TRUTH else TRUTH
    return json.dumps(
        {
            "evidence_narrative": "The airplane touched down in a gust.",
            "occurrence": [_guess(top, 0.6), _guess(second, 0.3)],
            "findings": (
                [{"category6": "010620", "modifier": "20", "probability": 0.5}] if findings else []
            ),
            "probable_cause": "Loss of directional control on landing.",
            "lay_explanation": "The pilot lost control on landing.",
            "confidence": 0.5,
            "abstain": abstain,
            "evidence_used": [],
        }
    )


def _choice(decisions: dict[int, bool]) -> str:
    return json.dumps(
        {
            "documents": [
                {"index": i, "read": read, "expected_effect": "may confirm the event"}
                for i, read in decisions.items()
            ],
            "reason": "read what bears on the hypothesis",
        }
    )


def _coding(
    *,
    done: bool = False,
    tool: str | None = "occurrence_usage",
    codes: tuple[str, ...] = (TRUTH, OTHER),
    top3: list[dict[str, Any]] | None = None,
) -> str:
    return json.dumps(
        {
            "done": done,
            "tool": None if done else tool,
            "kind": None if done else "occurrence",
            "codes": [] if done else list(codes),
            "reason": "check the defining event",
            "expected_effect": "the usual phase for this event",
            "top3": top3 or [_guess(TRUTH, 0.6)],
        }
    )


REFINE = json.dumps({"items": [{"index": 0, "item8": "01062020"}]})
DONE = _coding(done=True)


def _run(
    replies: list[str],
    *,
    docket: Docket | None = None,
    budget: RunBudget | None = None,
    usage: tuple[Usage, ...] = (),
    raw: dict[str, object] | None = None,
) -> tuple[CaseTrail, RecordingFakeClient]:
    client = RecordingFakeClient(replies, usage=usage)
    trail = run_case(
        raw or _raw(),
        docket or _docket(),
        client=client,
        tables=TABLES,
        stats=_stats(),
        seen_pairs=frozenset(),
        budget=budget or RunBudget(),
    )
    return trail, client


def _ctx(indices: tuple[int, ...], docket: Docket | None = None) -> Payload:
    raw = _raw()
    context = prepare_attachment(raw, docket or _docket()).context_for(indices).context
    return Payload.from_evidence(split_record(context)[0])


def _phases(trail: CaseTrail) -> list[str]:
    return [c.phase for c in trail.calls]


HAPPY = [
    _hyp(),  # h0
    _choice({1: True, 2: False, 4: False}),  # choice1
    _hyp(),  # h1
    _choice({2: True, 4: False}),  # choice2
    _hyp(),  # h2
    _hyp(top=OTHER),  # h_all
    _coding(),  # coding: one tool call
    DONE,  # coding: done
    _hyp(),  # final
    REFINE,  # refine
]


# --------------------------------------------------------------------------------------------
# The happy path
# --------------------------------------------------------------------------------------------


def test_happy_path_records_every_phase_in_order() -> None:
    usage = (Usage(prompt_tokens=1000, completion_tokens=100),)
    trail, client = _run(HAPPY, usage=usage)
    assert trail.stop_reason == "done"
    assert trail.coding_stop == "done"
    assert _phases(trail) == [
        "h0",
        "choice1",
        "h1",
        "choice2",
        "h2",
        "h_all",
        "coding",
        "coding",
        "final",
        "refine",
    ]
    assert not any(c.parse_retry for c in trail.calls)
    for stage in (trail.h0, trail.h1, trail.h2, trail.h_all, trail.final, trail.refined):
        assert stage.hypothesis is not None
        assert stage.note is None
        assert stage.scores is not None
    assert trail.choice1 is not None
    assert trail.choice1.offered == (1, 2, 4)
    assert trail.choice1.chosen == (1,)
    assert trail.choice2 is not None
    assert trail.choice2.offered == (2, 4)
    assert trail.choice2.chosen == (2,)
    assert trail.h0.scores is not None
    assert trail.h0.scores.occurrence_top1
    assert trail.h0.scores.finding_recall_10 is None
    assert trail.h_all.scores is not None
    assert not trail.h_all.scores.occurrence_top1
    assert trail.h_all.scores.occurrence_top3
    assert trail.refined.scores is not None
    assert trail.refined.scores.finding_recall_10 is not None
    assert trail.refined.scores.finding_recall_10 > 0
    # One tool call, then done.
    assert [s.done for s in trail.coding_steps] == [False, True]
    assert trail.coding_steps[0].result_text is not None
    assert trail.coding_steps[0].result_chars == len(trail.coding_steps[0].result_text)
    assert trail.coding_steps[1].result_text is None
    # Truth, pool and cost.
    assert trail.true_primary == TRUTH
    assert trail.true_in_arguments is True
    assert trail.pool_top == OTHER
    assert trail.follows_pool is False
    assert trail.cost_usd > 0
    assert trail.cost_usd == pytest.approx(sum(c.cost_usd for c in trail.calls))
    assert len(client.payloads) == 10
    assert trail.leak is None
    assert trail.failure is None


def test_documents_are_recorded_by_their_facts() -> None:
    trail, _ = _run(HAPPY)
    by_index = {d.index: d for d in trail.documents}
    assert [d.index for d in trail.documents] == [1, 2, 3, 4]
    assert by_index[2].kind == "scan"
    assert by_index[2].transcribed_pages == 2
    assert by_index[2].attachable
    assert not by_index[3].attachable
    assert trail.has_scan is True
    assert trail.fatal is False


def test_every_payload_is_one_the_split_produced() -> None:
    _, client = _run(HAPPY)
    structured = Payload.from_evidence(split_record(_raw())[0])
    expected = [
        structured,  # h0
        _ctx(()),  # choice1: structured evidence plus the listing
        _ctx((1,)),  # h1
        _ctx((1,)),  # choice2: what was read so far
        _ctx((1, 2)),  # h2
        _ctx((1, 2, 4)),  # h_all
        _ctx((1, 2)),  # coding
        _ctx((1, 2)),  # coding
        _ctx((1, 2)),  # final
        _ctx((1, 2)),  # refine
    ]
    assert client.payloads == expected
    assert all(not p.images for p in client.payloads)


def test_docket_titles_and_texts_appear_only_in_payloads_never_in_system_text() -> None:
    _, client = _run(HAPPY)
    for system in client.systems:
        for title in TITLES.values():
            assert title not in system
        for text in TEXTS.values():
            assert text.strip().splitlines()[-1] not in system
    assert TITLES[1] in client.payloads[1].text
    assert TITLES[4] in client.payloads[1].text


def test_history_carries_only_the_agents_own_replies() -> None:
    _, client = _run(HAPPY)
    lengths = [len(h) for h in client.histories]
    # h0, choice1, h1, choice2, h2, h_all, coding, coding, final, refine
    assert lengths == [0, 1, 2, 3, 4, 0, 5, 6, 7, 1]
    for history in client.histories:
        for turn in history:
            assert turn.role == "assistant"
            assert turn.payload is None
    # The coding history is H0 ... H2 as sent; the refine history is the final reply alone.
    assert [t.content for t in client.histories[6]] == HAPPY[:5]
    assert [t.content for t in client.histories[9]] == [HAPPY[8]]


def test_system_texts_follow_the_flow() -> None:
    _, client = _run(HAPPY)
    h0_system = base_system(TABLES)
    assert client.systems[0] == h0_system
    assert client.systems[2] == h0_system  # h1
    assert client.systems[4] == h0_system  # h2
    assert client.systems[5] == h0_system  # h_all
    assert client.systems[1].startswith(h0_system)
    assert "1: 2 pages, 2 readable" in client.systems[1]
    assert "transcribed pages: 2" in client.systems[1]
    assert "Already read: 1" in client.systems[3]
    assert "Tool results so far:\nnone" in client.systems[6]
    assert "1. occurrence_usage" in client.systems[7]
    assert client.systems[8].endswith("Give your final hypothesis after the checks.")
    assert client.systems[9].startswith("You already chose a finding category")


def test_every_call_uses_the_probe_settings() -> None:
    _, client = _run(HAPPY)
    names = [s.schema_name for s in client.settings]
    assert names == [
        "hypothesis",
        "read_choice",
        "hypothesis",
        "read_choice",
        "hypothesis",
        "hypothesis",
        "coding_action",
        "coding_action",
        "hypothesis",
        "refinement",
    ]
    for settings in client.settings:
        assert settings.model == sources.DEFAULT_MODEL
        assert settings.price_variant == "standard"
        assert settings.reasoning_effort == sources.DEFAULT_REASONING_EFFORT
        assert settings.max_output_tokens == 8000
        assert settings.temperature == 0.0
        assert settings.json_schema is not None


def test_the_trail_round_trips_through_json() -> None:
    trail, _ = _run(HAPPY)
    assert CaseTrail.model_validate_json(trail.model_dump_json()) == trail


# --------------------------------------------------------------------------------------------
# Branches of the flow
# --------------------------------------------------------------------------------------------


def test_choosing_nothing_skips_h1_and_h2() -> None:
    replies = [
        _hyp(),
        _choice({1: False, 2: False, 4: False}),
        _choice({1: False, 2: False, 4: False}),
        _hyp(),  # h_all
        DONE,
        _hyp(),
        REFINE,
    ]
    trail, client = _run(replies)
    assert _phases(trail) == ["h0", "choice1", "choice2", "h_all", "coding", "final", "refine"]
    assert trail.h1.note == "skipped: nothing chosen"
    assert trail.h1.hypothesis == trail.h0.hypothesis
    assert trail.h2.note == "skipped: nothing more chosen"
    assert trail.choice2 is not None
    assert trail.choice2.offered == (1, 2, 4)
    # With nothing read, the coding payload is the structured evidence plus the listing.
    assert client.payloads[4] == _ctx(())
    assert trail.stop_reason == "done"


def test_reading_everything_skips_h_all_as_not_needed() -> None:
    # H1 (and so H2) without findings: the answer reserve then prices the refinement's
    # system text without a findings block.
    h1 = _hyp(findings=False)
    replies = [_hyp(), _choice({1: True, 2: True, 4: True}), h1, DONE, _hyp(), REFINE]
    trail, client = _run(replies)
    assert _phases(trail) == ["h0", "choice1", "h1", "coding", "final", "refine"]
    assert trail.choice2 is None
    assert trail.choice2_note == "skipped: nothing left to offer"
    assert trail.h_all.hypothesis is None
    assert trail.h_all.note == "not needed"
    assert trail.h2.note == "skipped: nothing more chosen"
    assert client.payloads[3] == _ctx((1, 2, 4))


def test_no_attachable_document_skips_both_choices() -> None:
    docket = _docket(readable=())
    trail, _ = _run([_hyp(), DONE, _hyp(), REFINE], docket=docket)
    assert _phases(trail) == ["h0", "coding", "final", "refine"]
    assert trail.choice1_note == "skipped: nothing to offer"
    assert trail.choice2_note == "skipped: nothing left to offer"
    assert trail.h_all.note == "not needed"
    assert trail.has_scan is False


def test_a_coding_loop_that_never_sets_done_stops_at_six_tool_calls() -> None:
    replies = [
        _hyp(),
        _choice({1: True, 2: True, 4: True}),
        _hyp(),
        *[_coding()] * MAX_CODING_CALLS,
        _hyp(),
        REFINE,
    ]
    trail, client = _run(replies)
    assert trail.stop_reason == "max_calls"
    assert trail.coding_stop == "max_calls"
    assert len(trail.coding_steps) == MAX_CODING_CALLS
    assert not any(s.done for s in trail.coding_steps)
    assert _phases(trail).count("coding") == MAX_CODING_CALLS
    assert _phases(trail)[-2:] == ["final", "refine"]
    final_system = client.systems[-2]
    assert f"{MAX_CODING_CALLS}. occurrence_usage" in final_system
    assert trail.final.hypothesis is not None


def test_an_unknown_code_is_an_argument_error_and_not_retried() -> None:
    replies = [
        _hyp(),
        _choice({1: True, 2: True, 4: True}),
        _hyp(),
        _coding(codes=("999999",)),
        DONE,
        _hyp(),
        REFINE,
    ]
    trail, _ = _run(replies)
    step = trail.coding_steps[0]
    assert step.argument_errors == 1
    assert step.result_text == "unknown occurrence code: 999999"
    assert not any(c.parse_retry for c in trail.calls)
    assert trail.true_in_arguments is False


def test_duplicate_top3_guesses_are_recorded_as_given() -> None:
    top3 = [_guess(TRUTH, 0.7), _guess(TRUTH, 0.7)]
    replies = [
        _hyp(),
        _choice({1: True, 2: True, 4: True}),
        _hyp(),
        _coding(top3=top3),
        _coding(done=True, top3=top3),
        _hyp(),
        REFINE,
    ]
    trail, _ = _run(replies)
    assert len(trail.coding_steps[0].top3) == 2
    assert sum(g.probability for g in trail.coding_steps[1].top3) > 1
    assert trail.stop_reason == "done"


def test_refinement_is_skipped_when_the_final_answer_abstains() -> None:
    replies = [_hyp(), _choice({1: True, 2: True, 4: True}), _hyp(), DONE, _hyp(abstain=True)]
    trail, _ = _run(replies)
    assert "refine" not in _phases(trail)
    assert trail.refined.note == "not run: abstained"
    assert trail.refined.hypothesis == trail.final.hypothesis
    assert trail.stop_reason == "done"


def test_refinement_is_skipped_when_the_final_answer_has_no_findings() -> None:
    replies = [_hyp(), _choice({1: True, 2: True, 4: True}), _hyp(), DONE, _hyp(findings=False)]
    trail, _ = _run(replies)
    assert "refine" not in _phases(trail)
    assert trail.refined.note == "not run: no findings"


# --------------------------------------------------------------------------------------------
# Failures
# --------------------------------------------------------------------------------------------


def test_a_malformed_reply_is_retried_once_then_fails_the_case() -> None:
    trail, client = _run(["not json", "still not json"])
    assert trail.stop_reason == "failed: h0"
    assert [c.parse_retry for c in trail.calls] == [False, True]
    assert "Your previous reply was rejected: " in client.systems[1]
    assert trail.h0 == NOT_REACHED
    assert trail.failure is not None
    assert trail.final == NOT_REACHED


def test_a_later_failure_keeps_everything_recorded_so_far() -> None:
    missing_index = _choice({1: True})  # 2 and 4 were offered too
    trail, client = _run([_hyp(), missing_index, missing_index])
    assert trail.stop_reason == "failed: choice1"
    assert trail.h0.hypothesis is not None
    assert _phases(trail) == ["h0", "choice1", "choice1"]
    assert client.histories[2] == client.histories[1]  # the retry keeps the same history
    assert trail.cost_usd == pytest.approx(0.0)


def test_a_retry_that_parses_continues_the_case() -> None:
    replies = [_hyp(), "{}", *HAPPY[1:]]
    trail, _ = _run(replies)
    assert trail.stop_reason == "done"
    assert _phases(trail)[:3] == ["h0", "choice1", "choice1"]
    assert [c.parse_retry for c in trail.calls][:4] == [False, False, True, False]


def test_a_leak_from_the_split_ends_the_case_and_is_recorded() -> None:
    narrative = factual_narrative(_raw()) or ""
    assert narrative
    texts = {**TEXTS, 1: f"[page 1 of 2]\nAs the NTSB found: {narrative}\n"}
    docket = _docket(texts)
    trail, client = _run([_hyp(), _choice({1: True, 2: False, 4: False})], docket=docket)
    assert trail.stop_reason == "failed: leak"
    assert trail.leak is not None
    assert "docket_documents" in trail.leak
    assert trail.h0.hypothesis is not None
    assert trail.choice1 is not None
    assert len(client.payloads) == 2  # nothing was sent after the refused split


def test_a_parse_failure_in_h_all_is_recorded_and_the_case_goes_on() -> None:
    replies = [
        _hyp(),
        _choice({1: True, 2: False, 4: False}),
        _hyp(),
        _choice({2: False, 4: False}),
        "not json",  # h_all
        "still not json",  # h_all retry
        DONE,
        _hyp(),
        REFINE,
    ]
    trail, _ = _run(replies)
    assert trail.h_all.hypothesis is None
    assert trail.h_all.note == "failed: parse"
    assert _phases(trail) == [
        "h0",
        "choice1",
        "h1",
        "choice2",
        "h_all",
        "h_all",
        "coding",
        "final",
        "refine",
    ]
    assert trail.stop_reason == "done"
    assert trail.coding_stop == "done"
    assert trail.final.hypothesis is not None
    assert trail.failure is None


def test_a_leak_in_a_document_not_chosen_refuses_h_all_only() -> None:
    narrative = factual_narrative(_raw()) or ""
    docket = _docket({**TEXTS, 4: f"[page 1 of 2]\nAs the NTSB found: {narrative}\n"})
    replies = [
        _hyp(),
        _choice({1: True, 2: False, 4: False}),
        _hyp(),
        _choice({2: False, 4: False}),
        DONE,
        _hyp(),
        REFINE,
    ]
    trail, client = _run(replies, docket=docket)
    assert trail.h_all.note == "failed: leak"
    assert trail.leak is not None
    assert "docket_documents" in trail.leak
    assert "h_all" not in _phases(trail)  # refused at the split, before any call
    assert _phases(trail)[-3:] == ["coding", "final", "refine"]
    assert trail.stop_reason == "done"
    assert trail.final.hypothesis is not None
    for payload in client.payloads:
        assert narrative not in payload.text


def test_a_case_outside_dev_400_is_refused_before_any_call() -> None:
    client = RecordingFakeClient([_hyp()])
    with pytest.raises(ValueError, match="not in dev-400"):
        run_case(
            _raw("ANC09CA024"),
            _docket(),
            client=client,
            tables=TABLES,
            stats=_stats(),
            seen_pairs=frozenset(),
            budget=RunBudget(),
        )
    assert client.payloads == []


# --------------------------------------------------------------------------------------------
# Cost limits
# --------------------------------------------------------------------------------------------


def _h0_estimate() -> float:
    payload = Payload.from_evidence(split_record(_raw())[0])
    settings = call_settings(HYPOTHESIS_SCHEMA, "hypothesis")
    return CaseBudget.estimate(base_system(TABLES), payload, (), settings)


def test_the_estimate_is_characters_over_four_plus_the_full_reply_budget() -> None:
    payload = Payload.from_evidence(split_record(_raw())[0])
    settings = call_settings(HYPOTHESIS_SCHEMA, "hypothesis")
    price = sources.price_of(settings.model_id())
    chars = len("system") + len(payload.text)
    expected = (chars / 4 * price.input_usd_per_mtok + 8000 * price.output_usd_per_mtok) / 1e6
    assert CaseBudget.estimate("system", payload, (), settings) == pytest.approx(expected)


def test_the_case_cap_stops_the_case_before_the_call_that_would_pass_it() -> None:
    # H0 fits; choice 1 (longer system, the listing, one history turn) would pass the cap.
    budget = RunBudget(case_cap_usd=_h0_estimate() + 1e-9)
    trail, client = _run(HAPPY, budget=budget)
    assert trail.stop_reason == "cap"
    assert _phases(trail) == ["h0"]
    assert len(client.payloads) == 1
    assert trail.h0.hypothesis is not None
    assert trail.h1 == NOT_REACHED


def test_h_all_is_not_run_when_it_would_leave_no_room_for_the_coding_checks() -> None:
    big = "[page 1 of 2]\n" + "The logbook entry was legible. " * 4000 + "\n"
    docket = _docket({**TEXTS, 4: big})
    payload = _ctx((1, 2, 4), docket)
    estimate = CaseBudget.estimate(
        base_system(TABLES), payload, (), call_settings(HYPOTHESIS_SCHEMA, "hypothesis")
    )
    budget = RunBudget(case_cap_usd=estimate + CODING_RESERVE_USD - 1e-9)
    replies = [_hyp(), _choice({1: True, 2: False, 4: False}), _hyp()]
    replies += [_choice({2: False, 4: False}), DONE, _hyp(), REFINE]
    trail, _ = _run(replies, docket=docket, budget=budget)
    assert trail.h_all.note == "not run: cap"
    assert "h_all" not in _phases(trail)
    assert trail.stop_reason == "done"


def test_the_coding_checks_stop_early_to_keep_room_for_the_answer() -> None:
    # Every single call fits under $0.01 (about $0.004 of reply budget plus the input); a
    # coding call plus the final call plus the refinement (about $0.013) does not.
    budget = RunBudget(case_cap_usd=0.01)
    replies = [_hyp(), _choice({1: True, 2: True, 4: True}), _hyp(), _hyp(), REFINE]
    trail, _ = _run(replies, budget=budget)
    assert _phases(trail) == ["h0", "choice1", "h1", "final", "refine"]
    assert trail.coding_steps == ()
    assert trail.coding_stop == "cap"
    assert trail.stop_reason == "coding_cap"
    assert trail.final.hypothesis is not None
    assert trail.refined.note is None
    assert all(c.estimated_usd <= 0.01 for c in trail.calls)


def test_the_coding_checks_stop_after_a_tool_call_when_the_room_runs_out() -> None:
    # Zero cost until the first coding call, which costs enough that the next one, with the
    # answer held back (about $0.013), would pass the cap; the final call alone still fits.
    free = Usage(prompt_tokens=0, completion_tokens=0)
    spent = Usage(prompt_tokens=0, completion_tokens=0, reported_cost_usd=0.02)
    budget = RunBudget(case_cap_usd=0.03)
    replies = [_hyp(), _choice({1: True, 2: True, 4: True}), _hyp(), _coding(), _hyp(), REFINE]
    trail, _ = _run(replies, budget=budget, usage=(free, free, free, spent, free))
    assert _phases(trail) == ["h0", "choice1", "h1", "coding", "final", "refine"]
    assert len(trail.coding_steps) == 1
    assert trail.coding_stop == "cap"
    assert trail.stop_reason == "coding_cap"


def test_the_run_cap_stops_a_second_case() -> None:
    docket = _docket(readable=())
    small = Usage(prompt_tokens=1, completion_tokens=1, reported_cost_usd=0.001)
    large = Usage(prompt_tokens=1, completion_tokens=1, reported_cost_usd=0.2)
    budget = RunBudget(run_cap_usd=0.205)
    first, _ = _run(
        [_hyp(), DONE, _hyp(), REFINE],
        docket=docket,
        budget=budget,
        usage=(small, small, small, large),
    )
    assert first.stop_reason == "done"
    assert budget.spent == pytest.approx(0.203)
    second, client = _run([_hyp(), DONE, _hyp(), REFINE], docket=docket, budget=budget)
    assert second.stop_reason == "run_cap"
    assert second.calls == ()
    assert client.payloads == []
    assert budget.spent == pytest.approx(0.203)


def test_the_run_budget_holds_reservations_under_one_lock() -> None:
    budget = RunBudget(run_cap_usd=1.0)
    granted: list[bool] = []
    lock = threading.Lock()

    def reserve() -> None:
        ok = budget.reserve(0.1)
        with lock:
            granted.append(ok)

    threads = [threading.Thread(target=reserve) for _ in range(40)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert granted.count(True) == 10
    budget.settle(0.1, 0.05)
    assert budget.spent == pytest.approx(0.05)
    # 0.9 still reserved and 0.05 spent: 0.05 more fits, 0.1 more does not.
    assert not budget.reserve(0.1)
    assert budget.reserve(0.05)


def test_a_call_that_raises_releases_its_reservation() -> None:
    class Boom(RecordingFakeClient):
        def complete(self, *args: object, **kwargs: object) -> Any:
            raise RuntimeError("transport down")

    budget = RunBudget(run_cap_usd=_h0_estimate() * 1.5)
    with pytest.raises(RuntimeError, match="transport down"):
        run_case(
            _raw(),
            _docket(),
            client=Boom(),
            tables=TABLES,
            stats=_stats(),
            seen_pairs=frozenset(),
            budget=budget,
        )
    assert budget.spent == 0.0
    assert budget.reserve(_h0_estimate())
