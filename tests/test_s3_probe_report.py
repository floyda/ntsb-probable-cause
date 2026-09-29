"""Tests for ``scripts/s3_probe/report.py``, offline, from synthetic ``CaseTrail`` objects.

The fixtures (``tests/s3_probe_fixtures.py``) build three cases by hand rather than running the
loop, so every count checked here can be worked out on paper: ``case_a`` reaches every stage
(H_all runs); ``case_b`` fails at H0, before any stage or read choice is reached; ``case_c``
reads everything offered at choice 1, so H_all is "not needed". Every text field that must
never reach the report (the case ID, a document-choice reason, a tool result, a hypothesis's
own prose) carries the fixtures' ``MARKER``, which every test here asserts is absent.
"""

import json
from pathlib import Path

from scripts.s3_probe.report import build_report, cmd_report
from tests.s3_probe_fixtures import CASE_A_ID, CASE_B_ID, CASE_C_ID, MARKER, case_a, case_b, case_c

from ntsb_probable_cause.scoring.records import write_jsonl


def _write_job(tmp_path: Path) -> Path:
    job_dir = tmp_path / "s3-probe-20260929T000000-abc1234"
    job_dir.mkdir()
    probe = {
        "job_id": job_dir.name,
        "commit_sha": "abc1234",
        "dirty": False,
        "model": "openai/gpt-6-luna",
        "price_variant": "standard",
        "reasoning_effort": "medium",
        "max_output_tokens": 8000,
        "prompt_version": "s1-v6",
        "guidance": ["r3-loc-stall", "r6-aircraft-control"],
        "case_cap_usd": 0.15,
        "run_cap_usd": 3.0,
        "selection_seed": 20260929,
        "per_cell_counts": {
            "fatal=False has_scan=False": 1,
            "fatal=False has_scan=True": 0,
            "fatal=True has_scan=False": 0,
            "fatal=True has_scan=True": 1,
        },
        "cases_selected": 3,
        "cases_run": 3,
        "started": "2026-09-29T00:00:00+00:00",
        "finished": "2026-09-29T00:05:00+00:00",
    }
    (job_dir / "probe.json").write_text(json.dumps(probe))
    write_jsonl(job_dir / "trails.jsonl", [case_a(), case_b(), case_c()])
    return job_dir


def test_report_first_line(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert text.splitlines()[0] == (
        "Learning probe, not a result: n=3; every figure below is a signal, not a finding."
    )


def test_report_never_names_a_case(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    for needle in (CASE_A_ID, CASE_B_ID, CASE_C_ID, MARKER):
        assert needle not in text


def test_report_settings_block(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "model: openai/gpt-6-luna" in text
    assert "reasoning_effort: medium" in text
    assert "guidance: r3-loc-stall, r6-aircraft-control" in text
    assert "cases_selected: 3" in text


def test_documents_section_denominators(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    # Case A offers 3 at choice 1 (1 chosen) and 2 at choice 2 (1 chosen); case C offers 1 at
    # choice 1 (1 chosen) and 0 at choice 2; case B never reaches choice 1.
    assert "documents offered at choice 1: 4" in text
    assert "documents chosen at choice 1: 2 of 4 (50.0%)" in text
    assert "documents offered at choice 2: 2" in text
    assert "documents chosen at choice 2: 1 of 2 (50.0%)" in text
    # Read choice 2: ran in case A, skipped (nothing left) in case C, never reached in case B.
    assert "read choice 2 happened: 1 of 2 (50.0%) of cases with documents left" in text
    assert "nothing left to offer: 1; not reached: 1" in text


def test_hypotheses_section_denominators(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    # H0 is scored in cases A and C (case B never reaches it): both correct.
    assert "H0 occurrence top-1: 2 of 2 (100.0%)" in text
    assert "H0 occurrence top-3: 2 of 2 (100.0%)" in text
    # H_all is scored only in case A (not needed in C, never reached in B).
    assert "H_all occurrence top-1: 0 of 1 (0.0%)" in text
    assert "finding recall@10 mean at refined: 50.0% (n=1)" in text


def test_skip_regret_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "H_all ran: 1 of 3 (33.3%)" in text
    assert "H_all top-1 differs from H2: 1 of 1 (100.0%)" in text
    assert "H2 right, H_all wrong: 1 of 1" in text


def test_coding_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "cases that reached the coding checks: 2 of 3 (66.7%)" in text
    assert "tool calls by tool: describe_codes: 1, occurrence_usage: 1" in text
    assert "argument errors: 1 of 2 (50.0%) of tool calls" in text
    assert "distinct codes passed to coding tools: 2" in text


def test_cost_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "total cost: $0.0160 (n=3 cases)" in text
    # phase "h0" appears on every call attempt: case A (100), case B's two failed attempts
    # (90, 95) and case C (120) -- mean (100+90+95+120)/4 = 101.25.
    assert "h0: mean 101, max 120 (n=4)" in text


def test_cmd_report_writes_out_file(tmp_path: Path) -> None:
    job_dir = _write_job(tmp_path)
    out = tmp_path / "out.txt"
    text = cmd_report(job_dir, out=out)
    assert out.read_text() == text
    for needle in (CASE_A_ID, CASE_B_ID, CASE_C_ID, MARKER):
        assert needle not in out.read_text()
