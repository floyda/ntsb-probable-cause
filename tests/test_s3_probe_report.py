"""Tests for ``scripts/s3_probe/report.py``, offline, from synthetic ``CaseTrail`` objects.

The fixtures (``tests/s3_probe_fixtures.py``) build three cases by hand rather than running the
loop, so every count checked here can be worked out on paper: ``case_a`` reaches every stage,
with H_all a genuine skip-regret comparison; ``case_b`` fails at H0, before any stage or read
choice is reached; ``case_c`` reads everything offered at choice 1, so H_all runs as the
noise-only control (``"control: all read"``, F7). Every text field that must never reach the
report (the case ID, a document-choice reason, a tool result, a hypothesis's own prose) carries
the fixtures' ``MARKER``, which every test here asserts is absent.
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
    # H_all is scored in cases A (skip-regret) and C (the "all read" control), never reached
    # in B: both are wrong.
    assert "H_all occurrence top-1: 0 of 2 (0.0%)" in text
    assert "finding recall@10 mean at refined: 50.0% (n=1)" in text


def test_skip_regret_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    # H_all ran in case A (skip-regret) and case C (the "all read" control); never in B.
    assert "H_all ran: 2 of 3 (66.7%)" in text
    assert "skip-regret cases (a document was actually skipped):" in text
    assert "control cases (agent read everything" in text
    # Both groups have exactly one paired case, and it differs from H2 in both.
    assert text.count("H_all top-1 differs from H2: 1 of 1 (100.0%)") == 2
    assert text.count("H2 right, H_all wrong: 1 of 1") == 2


def test_coding_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "cases that reached the coding checks: 2 of 3 (66.7%)" in text
    assert "tool calls by tool: describe_codes: 1, occurrence_usage: 1" in text
    assert "argument errors: 1 of 2 (50.0%) of tool calls" in text
    assert "distinct codes passed to coding tools: 2" in text


def test_case_outcomes_section(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "## Case outcomes" in text
    # case_a "done", case_b "failed: h0", case_c "done".
    assert "case stop reasons: done: 2, failed: h0: 1" in text
    assert "cases with no trail (exception): 0 of 3" in text


def test_case_outcomes_section_counts_missing_trails(tmp_path: Path) -> None:
    job_dir = _write_job(tmp_path)
    probe = json.loads((job_dir / "probe.json").read_text())
    probe["cases_run"] = 5  # two selected cases raised and produced no trail
    (job_dir / "probe.json").write_text(json.dumps(probe))
    text = build_report(job_dir)
    assert "cases with no trail (exception): 2 of 5" in text


def test_transitions_are_split_by_whether_a_coding_tool_was_called(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    # Case A made a coding tool call and its final top-1 stayed right (0 of 1 differs). Case C
    # never called a tool (its one coding step was already "done") and its final top-1 flipped
    # right-to-wrong (1 of 1 differs).
    assert "cases with at least one coding tool call:" in text
    assert "cases with no coding tool call (re-asking control):" in text
    idx_with = text.index("cases with at least one coding tool call:")
    idx_without = text.index("cases with no coding tool call (re-asking control):")
    with_block = text[idx_with:idx_without]
    without_block = text[idx_without : idx_without + 200]
    assert "final top-1 differs from H2: 0 of 1 (0.0%)" in with_block
    assert "final top-1 differs from H2: 1 of 1 (100.0%)" in without_block
    assert "right to wrong: 1 of 1" in without_block


def test_follow_pool_excludes_single_code_final_top3(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    # Only case A's final top-3 has two distinct codes; case C's is a single (duplicated) code.
    assert (
        "followed the pool's top choice (final top-3 with 2+ distinct codes): 0 of 1 (0.0%)" in text
    )
    assert "single-code final top-3 (follow/override not applicable): 1 of 2 (50.0%)" in text


def test_documents_section_transcription_and_either_choice_breakdowns(tmp_path: Path) -> None:
    text = build_report(_write_job(tmp_path))
    assert "choice 1, by kind (after transcription):" in text
    assert "choice 1, by transcription:" in text
    assert "choice 2, by transcription:" in text
    # None of the fixture documents carry a transcribed page.
    assert "  has transcribed pages: 0 of 0 (—)" in text
    assert "  text layer only: 2 of 4 (50.0%)" in text
    assert "read at either choice: 3 of 4 (75.0%)" in text


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
