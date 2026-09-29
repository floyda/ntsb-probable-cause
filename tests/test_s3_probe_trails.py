"""Tests for ``scripts/s3_probe/trails_md.py``, offline, reusing
``tests/s3_probe_fixtures.py``'s synthetic ``CaseTrail`` fixtures.

Unlike the report, these files are meant to carry the case ID and the agent's own words; the
tests check the opposite direction -- that the markers are *present* -- and that every file
lands under the job folder's own ``trails/`` directory, in run order, and nowhere else.
"""

from pathlib import Path

from scripts.s3_probe.trails_md import render_trail, write_trails
from tests.s3_probe_fixtures import CASE_A_ID, CASE_B_ID, CASE_C_ID, MARKER, case_a, case_b, case_c

from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.records import write_jsonl

TABLES = load_tables()


def _write_job(tmp_path: Path) -> Path:
    job_dir = tmp_path / "s3-probe-20260929T000000-abc1234"
    job_dir.mkdir()
    write_jsonl(job_dir / "trails.jsonl", [case_a(), case_b(), case_c()])
    return job_dir


def test_render_trail_carries_the_case_id_and_the_agents_own_words() -> None:
    text = render_trail(TABLES, case_a())
    assert text.startswith(f"# {CASE_A_ID}\n")
    assert MARKER in text  # the case's own reasons, expected effects and tool results


def test_render_trail_on_a_case_that_failed_at_h0() -> None:
    text = render_trail(TABLES, case_b())
    assert f"# {CASE_B_ID}" in text
    assert "(absent: not reached)" in text
    assert "(not reached: not reached)" in text  # neither read choice was ever reached
    assert "### Coding checks" in text
    assert "(none)" in text  # the coding checks were never reached either


def test_render_trail_on_a_case_where_h_all_was_not_needed() -> None:
    text = render_trail(TABLES, case_c())
    assert f"# {CASE_C_ID}" in text
    assert "(absent: not needed)" in text
    assert "true flagged findings: none" in text


def test_write_trails_writes_one_file_per_case_in_run_order(tmp_path: Path) -> None:
    job_dir = _write_job(tmp_path)
    n = write_trails(job_dir)
    assert n == 3
    out_dir = job_dir / "trails"
    names = sorted(p.name for p in out_dir.iterdir())
    assert names == ["1.md", "2.md", "3.md"]
    assert (out_dir / "1.md").read_text().startswith(f"# {CASE_A_ID}\n")
    assert (out_dir / "2.md").read_text().startswith(f"# {CASE_B_ID}\n")
    assert (out_dir / "3.md").read_text().startswith(f"# {CASE_C_ID}\n")


def test_write_trails_writes_only_under_the_job_folder(tmp_path: Path) -> None:
    job_dir = _write_job(tmp_path)
    write_trails(job_dir)
    for path in tmp_path.rglob("*.md"):
        assert job_dir in path.parents
