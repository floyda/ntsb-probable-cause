# S2.7 — Coding guidance, track 1: implementation plan

**Spec:** docs/specs/2026-09-26-s27-coding-guidance-design.md

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Tick a step in the same commit as its code (decision 0017). Log every departure from the specification in the **Deviations** section at the end. A step marked **STOP** is Andy's: stop there, report, and wait.

**Goal:** Measure where arm B's `dev-400` misses come from (Round 0), test an ordering check after the answer (Round 1), add coding guidance in registered rounds until the stop rule, then — with track 2's transcriber — compare v1 against v2 and check the final setup once on a sealed development sample, so S3's loop faces arm B without coding-convention losses (decisions 0093–0099).

**Architecture:** Everything new is either a pure library function under `scoring/` (`misses.py`, `coding_stats.py`, `ordering.py`, `checkpass.py`, and guidance files under `scoring/guidance/`) or a committed script under `scripts/` that prints counts to `docs/results/`. The ordering check runs as a **post-pass** over a finished run's `cases.jsonl` and writes a derived run folder, so it works the same for batch and sync runs and never touches the answering path (walkthrough W2). Guidance enters only the system text next to the code tables, is named on every run record, and a run refuses guidance whose round registration is not committed. The sealed sample and the statistics pool are guarded in code, with tests that prove the guards can fail.

**Tech Stack:** Python 3.14, uv + hatchling, pydantic v2, httpx + respx, pyarrow, pytest + pytest-socket + hypothesis, ruff, mypy --strict, import-linter. No new dependency.

## Global Constraints

- **Branch and base.** Work on `s27-coding-guidance` in `.claude/worktrees/s27-coding-guidance`, cut from `main` at the S2.6 merge `971ee40`. Track 2 (`docs/plans/2026-09-26-s27-track2-transcriber.md`) runs on `s27-transcriber`, which is cut from this branch **after Task 1 is committed** (it needs `scripts/stage_spend.py`), and merges back in Task 16. Until then this plan never edits `docket/transcribe.py`, `scripts/transcriber_test.py`, `apps/eval/__main__.py:_cmd_transcribe` beyond the sealed-sample refusal of Task 2, or the transcriber entries of `sources.py`; track 2 never edits `scoring/runner.py`, `scoring/records.py`, `scoring/report.py` or `_cmd_run` (spec §11).
- **The split is the only split** (CLAUDE.md rule 1). No new code builds evidence from a raw record except through `records/split.py:split_record` or the existing `fields` extractors the baseline already uses. The ordering check's payload is built from a finished run's recorded hypothesis, the committed count table and the phase-group evidence value, never from the verdict, the synthesis or the docket (decision 0096 item 2).
- **Development cases only.** Every script and command added here refuses a held-out or open-split run or sample, before reading its cases. `dev-seal-400` is refused everywhere until `docs/rounds/s27-sealed.md` is committed (decision 0095). The statistics pool never holds a `dev-400`, `dev-seal-400`, held-out or open case (decision 0094).
- **Private material lives under `data/`** (git-ignored) and is never committed: marking pages, sheets, marks CSVs, judge rows. Only counts go to `docs/results/` and `docs/rounds/`.
- **Every model call goes through `ModelClient`** (OpenRouter, decision 0009), except Jev, which goes through `model/typesafe.py` for the ordering check on development runs only (decision 0097). Tests never reach the network (`--disable-socket`); replies are `RecordingFakeClient` or respx-mocked saved fixtures.
- **Budget.** $40 a month (0083) and **$25 for S2.7** (0098 item 6), counted by commit from `971ee40` on both branches. Every paid `make` target runs `uv run python -m scripts.stage_spend --estimate <USD>` first and stops if it would pass the line.
- **Paid commands handed to Andy** always state: `export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data`, the expected cost and duration, and what the tree looks like afterwards. They are run from a shell script that exports `OPENROUTER_API_KEY="$(pass show api/openrouter)"` (and, for Jev, `TYPESAFE_API_KEY="$(pass show api/typesafe)"`) and never prints either.
- **Batch timing.** Paid batches are submitted between about 01:00 and 12:00 UTC (OpenRouter's slow window is 12:00–19:00 UTC). A batch run in trouble is resumed with `--resume`, never re-run.
- **One reply budget.** Every arm B run uses 8,000 output tokens (0084) and GPT-6 Luna at `medium` (0073); guidance never changes either.
- **Numbers reported anywhere come from a script.** The ad-hoc numbers in the spec are re-derived by Tasks 3, 4 and 5 before they are cited.
- **Decision numbers.** Records written during this track take the next free number above 0100, up to 119 (spec §11). Never write a four-digit number in any document until its record exists: `scripts/check_docs.py` fails on it.
- `make check` = ruff format, ruff check, lint-imports, deptry, vulture, mypy --strict, pytest; coverage gate `--cov-fail-under=90`, branch coverage. Google-style docstrings on every public symbol; line length 100. Every module in `scripts/` carries a `Status` paragraph beneath its summary line (decision 0059).
- Commit messages end with the attribution lines the session gives. Never commit to `main`. The stage pull request is titled `S2.7: coding guidance` and merged with a merge commit, never squashed (0033).

---

## Decisions for Andy before any code (the walkthrough)

The spec is approved; these are the places where writing the plan found something the spec did not settle, or where an assumption in it turned out false. Each is marked in the task that depends on it. They are taken one per message; each outcome is written beside it below and in the Deviations section.

- **W1. No mapping from the phase group to the three-digit phase exists.** The phase-of-flight evidence is the defining event's CICTT phase group, a name such as `"Landing"` or `"Maneuvering"` (`fields.py:_phase_of_flight`); the code tables' phases are three-digit prefixes (`552`, `452`). Spec §5.2 item 4 and §5.3 need "the phase prefixes within the phase group". *Planned as:* Task 3 learns the mapping from the pool — for each pool case, the defining event's group and its code's first three digits — and a prefix belongs to a group when the pool records it there at all. The report prints the mapping so it can be read. *Rejected:* a hand-written mapping (not from a script; would need defending prefix by prefix).
- **W2. The ordering check runs as a post-pass, not inside the runner.** Spec §5.5 put it "after the answer, before the finding refinement turn". Inside the runner it would need a third batch stage for the model-asked ways and a second path for sync runs. The check touches only the occurrence codes, and the refinement turn only the findings, so the order between them changes no score. *Planned as:* `ntsb-eval check RUN_ID --way rule|luna|jev` reads a finished run and writes a derived folder `<run id>-check-<way>` whose cases carry the original step plus a second step, `tool="ordering_check"`, with the reordered hypothesis, its input fingerprint, model and cost; occurrence scores are recomputed, finding scores carried over. Its run record's cost is the check's cost only, so month and stage spend never count the answer twice. `report --against` compares derived folders like any run. *Rejected:* building it into `Runner` (a third batch stage, more code on the path every arm uses, for no change in any score).
- **W3. GPT-6 Luna's check runs synchronously at the standard price.** A post-pass has no batch plumbing, and 399 short calls take minutes. Estimate (arithmetic, $0.10/$0.50 per million tokens, about 1,500 prompt and 1,500 output tokens a case including reasoning): about $0.90 per 1,000 cases, so **about $0.36 per answer set, $0.72 for Round 1**, against the spec's $0.12 per set at batch prices. *Planned as:* synchronous, standard price, recorded on each step. *Rejected:* batch (more code for about $0.36 saved).
- **W4. The judge writes into the run it judges.** `ntsb-eval judge` is standard-price only (`scoring/judge.py:_ensure_priced` refuses batch), writes `judge.jsonl` inside the judged run's folder (replacing any earlier one) and appends a `<run id>-judge` cost row to its `run.jsonl`. Round 0 judges S2.6's B-v1 and B-v2 folders. *Planned as:* Task 7 first checks neither folder holds a `judge.jsonl` (none is expected: S2.6 judged no run); if one does, it is copied aside under `data/s27/` before judging. The cost row carries S2.7's commit, so the stage counts it. *Rejected:* copying the S2.6 run folders first (two copies of the same cases, and `month_spent` would count their costs twice).
- **W5. The prompt version for guided runs.** Spec §6.1 said "for example `s27-g1`". *Planned as:* `prompt.prompt_version(guidance)` returns `s1-v5` with no guidance and `s1-v5+r2-loc-stall+r3-…` with guidance — the base version plus every guidance file in order — and the run record also stores the files' combined SHA-256. The new `spec.json` keys are written only when guidance is present, so resuming a pre-S2.7 run is unaffected. *Rejected:* a hand-bumped constant per round (two rounds with the same number but different files would look identical).
- **W6. The "no sentence shared with a development narrative" check cannot run in CI.** CI holds no case data. *Planned as:* CI checks the guidance files and the count table for case-number patterns; `scripts/check_guidance.py` checks every guidance sentence against every development case's factual narrative, analysis narrative and probable cause on the local processed file, and a round's registration is committed only after it passes (Task 13, Task 15 Step 3). The same holds for spec §12's "the draw is reproducible": re-drawing needs the processed file, so it is `scripts/draw_sealed.py --verify`, run locally when the list is drawn and again before the sealed run (Task 2 Step 8, Task 18 Step 4); CI checks the committed list's shape and disjointness (Task 2 Step 9). *Rejected:* committing development narratives, or the processed file's index, as a CI fixture (withheld text, or data, in the repository).
- **W7. A miss group may hold fewer than eight cases.** Spec §4.4 draws 8 per miss group. *Planned as:* a group with fewer than 8 contributes all its cases; the shortfall is not topped up from another group, and the results file prints each group's card count. *Rejected:* topping up (it would over-weight the largest group in the validation).
- **W8. Stage spend is counted on both branches.** Before the merge back, `git rev-list 971ee40..HEAD` on this branch does not see track 2's commits, so track 2's spend would be missed and the $25 line under-counted. *Planned as:* `scripts/stage_spend.py` counts commits reachable from `HEAD`, `s27-coding-guidance` and `s27-transcriber` (those that exist), excluding `971ee40`'s ancestors. *Rejected:* counting by date (S2.6 found a date filter caught another stage's runs).

---

## File structure

| path | task | responsibility |
|---|---|---|
| `src/ntsb_probable_cause/gitinfo.py` | 1, 2 | `commits_between`, `branch_exists`, `is_committed` |
| `src/ntsb_probable_cause/scoring/budget.py` | 1 | `in_stage`, `stage_spent` |
| `scripts/stage_spend.py` | 1 | S2.7's spend by commit on both branches; refuses a step past $25 |
| `src/ntsb_probable_cause/scoring/samples.py` | 2 | `dev-seal-400`; `draw(..., exclude=)`; `refuse_sealed` |
| `scripts/draw_sealed.py`, `tests/fixtures/eval/dev_seal_400_ids.csv` | 2 | the sealed draw, once, and its verification |
| `src/ntsb_probable_cause/scoring/coding_stats.py` | 3 | `PoolCase`, `CodingStats`, `build`, `load_stats` |
| `scripts/coding_stats.py`, `src/ntsb_probable_cause/scoring/tables/coding_stats.json` | 3 | the pool, the counts, `docs/results/s27-coding-stats.txt` |
| `src/ntsb_probable_cause/scoring/misses.py` | 4 | the six groups, finding depth, event phrases |
| `scripts/occurrence_misses.py` | 4 | extended: groups, finding depth, confidence, own words, churn |
| `scripts/judge_outcomes.py` | 5 | the four outcomes from `judge.jsonl`, and their movement |
| `scripts/round0_handread.py` | 6 | Andy's cards and the narrative-label validation |
| `src/ntsb_probable_cause/scoring/ordering.py` | 8 | candidate list, plain rule, check text, ranking parse, reorder |
| `src/ntsb_probable_cause/model/typesafe.py`, `settings.py`, `sources.py` | 9 | the Jev client, ported |
| `src/ntsb_probable_cause/scoring/checkpass.py`, `scoring/metrics.py`, `apps/eval` `check` | 10 | the post-pass and `rescore_occurrence` |
| `scripts/round1_report.py` | 11 | Round 1's reading rule |
| `src/ntsb_probable_cause/scoring/guidance/`, `scoring/prompt.py`, `scoring/runner.py`, `scoring/records.py`, `scoring/report.py`, `apps/eval` `run` | 13 | guidance files, prompt version, run fields, the registration refusal |
| `scripts/check_guidance.py` | 13 | the local sentence check |
| `scripts/round_result.py`, `docs/rounds/` | 14, 15 | a round's reading rule; registrations and results |
| `scoring/runner.py`, `scoring/records.py`, `scoring/report.py`, `apps/eval` `run` | 16 | `transcriber` and `page_rule` on v2 runs |
| `scripts/sealed_report.py` | 18 | the sealed result beside `dev-400`; the prediction scored |
| `docs/results/s27-*.txt` | throughout | the stage's results, counts only |

Task numbers in this table are final; the tasks below use them.

---

## Part A — foundation (free)

### Task 1: S2.7's spend, counted by commit on both branches (spec §10, decision 0098 item 6; W8)

**Files:**
- Modify: `src/ntsb_probable_cause/gitinfo.py`
- Modify: `src/ntsb_probable_cause/scoring/budget.py`
- Create: `scripts/stage_spend.py`
- Modify: `Makefile`
- Test: `tests/test_gitinfo.py` (create), `tests/test_budget.py`, `tests/test_stage_spend.py` (create)

**Interfaces:**
- Produces: `gitinfo.commits_between(base: str, heads: Sequence[str], repo: Path = Path()) -> tuple[str, ...]`; `gitinfo.branch_exists(name: str, repo: Path = Path()) -> bool`; `budget.in_stage(sha: str, stage_commits: Collection[str]) -> bool`; `budget.stage_spent(runs_dir: Path, stage_commits: Collection[str]) -> tuple[float, float]` (evaluation runs, preparation spend rows); `scripts.stage_spend.STAGE_BASE = "971ee40"`, `STAGE_LINE_USD = 25.0`, `stage_commits(repo: Path = Path()) -> frozenset[str]`, `main(argv) -> int` (exit 1 when over the line). Track 2 calls `uv run python -m scripts.stage_spend --estimate USD` and `make stage-spend EST=USD`.

**Why a library function.** `scripts/transcriber_test.py` already counts S2.6's spend by commit (`_stage_commits`, `_in_stage`), privately. S2.7 needs the same count from two tracks and from every paid target; moving the counting into `scoring/budget.py` gives one tested implementation. `transcriber_test.py` is not changed (it is S2.6's record).

- [ ] **Step 1: Write the failing gitinfo tests**

```python
"""gitinfo: commits reachable from several heads, branches, and committed files (S2.7)."""

import subprocess
from pathlib import Path

from ntsb_probable_cause import gitinfo


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), "-c", "user.email=t@example.com", "-c", "user.name=t", *args],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    (repo / "a.txt").write_text("a\n")
    _git(repo, "add", "a.txt")
    _git(repo, "commit", "-q", "-m", "base")
    return repo, _git(repo, "rev-parse", "HEAD")


def _commit(repo: Path, name: str) -> str:
    (repo / name).write_text(name + "\n")
    _git(repo, "add", name)
    _git(repo, "commit", "-q", "-m", name)
    return _git(repo, "rev-parse", "HEAD")


def test_commits_between_counts_every_head_once_and_never_the_base(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    one = _commit(repo, "one.txt")
    _git(repo, "checkout", "-q", "-b", "other")
    two = _commit(repo, "two.txt")
    _git(repo, "checkout", "-q", "main")
    three = _commit(repo, "three.txt")
    found = gitinfo.commits_between(base, ["HEAD", "other"], repo)
    assert set(found) == {one, two, three}
    assert base not in found
    assert len(found) == len(set(found))


def test_branch_exists(tmp_path: Path) -> None:
    repo, _base = _repo(tmp_path)
    assert gitinfo.branch_exists("main", repo)
    assert not gitinfo.branch_exists("s27-transcriber", repo)
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_gitinfo.py -v`
Expected: FAIL with `AttributeError: module 'ntsb_probable_cause.gitinfo' has no attribute 'commits_between'`

- [ ] **Step 3: Add the two functions to `gitinfo.py`**

Add `from collections.abc import Sequence` to the imports, and after `commits_since`:

```python
def commits_between(base: str, heads: Sequence[str], repo: Path = Path()) -> tuple[str, ...]:
    """Full SHAs reachable from any of ``heads`` but not from ``base``, each once.

    S2.7 runs as two branches until track 2 merges back (decision 0093); a stage's spend
    must count both, so this takes several heads where :func:`commits_since` takes HEAD.
    Raises as :func:`commits_since` does.
    """
    listing = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "rev-list", *heads, f"^{base}"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return tuple(dict.fromkeys(listing.split()))


def branch_exists(name: str, repo: Path = Path()) -> bool:
    """Whether a local branch called ``name`` exists."""
    found = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", f"refs/heads/{name}"],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    return found.returncode == 0
```

- [ ] **Step 4: Run the gitinfo tests to verify they pass**

Run: `uv run pytest tests/test_gitinfo.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Write the failing budget tests** (append to `tests/test_budget.py`)

```python
from datetime import UTC, datetime

from ntsb_probable_cause.scoring.budget import (
    SpendRecord,
    in_stage,
    stage_spent,
    write_spend,
)
from ntsb_probable_cause.scoring.records import RunRecord, write_jsonl

_STAGE = frozenset({"abcdef1234567890", "1234567abcdef000"})


def _run(runs_dir, run_id: str, sha: str, cost: float) -> None:
    write_jsonl(
        runs_dir / run_id / "run.jsonl",
        [
            RunRecord(
                run_id=run_id,
                sample="dev-400",
                arm="B",
                exclusions=(),
                includes=(),
                prompt_version="s1-v5",
                model="openai/gpt-6-luna",
                price_variant="batch",
                cap_usd=0.05,
                budget_usd=40.0,
                commit_sha=sha,
                dirty=False,
                started=datetime(2026, 9, 27, tzinfo=UTC),
                cost_usd=cost,
            )
        ],
    )


def test_in_stage_matches_a_short_sha_by_prefix_and_refuses_a_too_short_one() -> None:
    assert in_stage("abcdef1", _STAGE)
    assert not in_stage("abc", _STAGE)
    assert not in_stage("fffffff", _STAGE)


def test_stage_spent_counts_runs_and_spend_rows_of_the_stage_only(tmp_path) -> None:
    runs = tmp_path / "runs"
    _run(runs, "in-stage", "abcdef1", 1.25)
    _run(runs, "other-stage", "9999999", 7.0)
    write_spend(
        runs,
        SpendRecord(
            job_id="job",
            kind="transcription",
            model="m",
            started=datetime(2026, 9, 27, tzinfo=UTC),
            calls=3,
            cost_usd=0.5,
            commit_sha="1234567",
            dirty=False,
        ),
    )
    assert stage_spent(runs, _STAGE) == (1.25, 0.5)
```

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest tests/test_budget.py -v -k stage`
Expected: FAIL with `ImportError: cannot import name 'in_stage'`

- [ ] **Step 7: Add `in_stage` and `stage_spent` to `scoring/budget.py`**

Add `from collections.abc import Collection` and `from ntsb_probable_cause.scoring.records import RunRecord, read_jsonl` if not already imported (check the module's imports; `month_spent` already reads both record kinds), then:

```python
# Recorded commit SHAs are short (``git rev-parse --short``); a stage's commits are full. A
# recorded SHA matches by prefix, and one shorter than this is refused as ambiguous.
MIN_SHA_PREFIX = 4


def in_stage(sha: str, stage_commits: Collection[str]) -> bool:
    """Whether a recorded (short) commit SHA is one of a stage's (full) commits."""
    return len(sha) >= MIN_SHA_PREFIX and any(full.startswith(sha) for full in stage_commits)


def stage_spent(runs_dir: Path, stage_commits: Collection[str]) -> tuple[float, float]:
    """A stage's spend by commit: (evaluation run records, preparation spend rows).

    Counted by commit, not by date, because S2.6 found a date filter caught another stage's
    runs (decision 0098 item 6). A judge pass is a run record (``<run id>-judge``) and counts.
    """
    runs = sum(
        record.cost_usd
        for path in sorted(runs_dir.glob("*/run.jsonl"))
        for record in read_jsonl(path, RunRecord)
        if in_stage(record.commit_sha, stage_commits)
    )
    spend = sum(
        row.cost_usd
        for path in sorted(runs_dir.glob(f"*/{SPEND_FILE}"))
        for row in read_jsonl(path, SpendRecord)
        if in_stage(row.commit_sha, stage_commits)
    )
    return runs, spend
```

- [ ] **Step 8: Run the budget tests to verify they pass**

Run: `uv run pytest tests/test_budget.py -v`
Expected: PASS

- [ ] **Step 9: Write the failing script tests** (`tests/test_stage_spend.py`)

```python
"""scripts/stage_spend.py: S2.7's spend against its $25 line (decision 0098 item 6)."""

from pathlib import Path

import pytest
from scripts import stage_spend as ss


def test_report_passes_under_the_line_and_refuses_over_it() -> None:
    text, over = ss.report(runs=10.0, spend=5.0, estimate=9.0)
    assert not over
    assert "S2.7 spend so far: $15.00" in text
    text, over = ss.report(runs=10.0, spend=5.0, estimate=10.01)
    assert over
    assert "refused" in text


def test_main_exits_1_over_the_line(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("NTSB_RUNS_DIR", str(tmp_path))
    monkeypatch.setattr(ss, "stage_commits", lambda repo=Path(): frozenset())
    monkeypatch.setattr(ss, "stage_spent", lambda runs_dir, commits: (24.0, 0.5))
    assert ss.main(["--estimate", "0.40"]) == 0
    assert ss.main(["--estimate", "0.60"]) == 1


def test_stage_commits_asks_for_the_branches_that_exist(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[list[str]] = []
    monkeypatch.setattr(ss, "branch_exists", lambda name, repo=Path(): name == "s27-transcriber")
    monkeypatch.setattr(
        ss,
        "commits_between",
        lambda base, heads, repo=Path(): asked.append([base, *heads]) or ("c1",),
    )
    assert ss.stage_commits() == frozenset({"c1"})
    assert asked == [["971ee40", "HEAD", "s27-transcriber"]]
```

- [ ] **Step 10: Run them to verify they fail**

Run: `uv run pytest tests/test_stage_spend.py -v`
Expected: FAIL with `ImportError: cannot import name 'stage_spend' from 'scripts'`

- [ ] **Step 11: Write `scripts/stage_spend.py`**

```python
"""S2.7's spend, counted by commit on both of its branches, against its $25 line.

Status
    Live check for S2.7 (decision 0098 item 6). Every paid ``make`` target of both tracks runs
    it first with the step's estimate; it exits 1 when the stage's spend plus the estimate
    would pass the line. Free: reads run folders only.

Why
    The line is the stage's stop rule's second half. Spend is counted by commit because S2.6
    found a date filter caught another stage's runs, and on both branches because until track
    2 merges back its commits are not reachable from this branch's HEAD (plan walkthrough W8).

Usage
    uv run python -m scripts.stage_spend [--estimate USD]
"""

import argparse
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.gitinfo import branch_exists, commits_between
from ntsb_probable_cause.scoring.budget import stage_spent
from ntsb_probable_cause.settings import Settings

STAGE_BASE = "971ee40"
STAGE_LINE_USD = 25.0
BRANCHES = ("s27-coding-guidance", "s27-transcriber")


def stage_commits(repo: Path = Path()) -> frozenset[str]:
    """Every commit of the stage: reachable from HEAD or either branch, not from the base."""
    heads = ["HEAD", *(name for name in BRANCHES if branch_exists(name, repo))]
    try:
        return frozenset(commits_between(STAGE_BASE, heads, repo))
    except (OSError, subprocess.CalledProcessError) as error:
        raise ConfigurationError(f"stage_spend: git could not list the stage's commits: {error}") from error


def report(*, runs: float, spend: float, estimate: float) -> tuple[str, bool]:
    """The printed lines, and whether the step is refused."""
    spent = runs + spend
    over = spent + estimate > STAGE_LINE_USD
    lines = [
        f"S2.7 spend so far: ${spent:.2f} (${runs:.2f} evaluation runs, ${spend:.2f} "
        f"preparation spend rows; counted by commit from {STAGE_BASE} on both branches)",
        f"this step's estimate: ${estimate:.2f}; the stage line: ${STAGE_LINE_USD:.2f}",
        (
            f"refused: ${spent + estimate:.2f} would pass the line (decision 0098 item 6)"
            if over
            else f"within the line: ${STAGE_LINE_USD - spent - estimate:.2f} left after this step"
        ),
    ]
    return "\n".join(lines), over


def main(argv: Sequence[str] | None = None) -> int:
    """Print the stage's spend; exit 1 if the estimate would pass the line."""
    parser = argparse.ArgumentParser(prog="stage_spend")
    parser.add_argument("--estimate", type=float, default=0.0, metavar="USD")
    args = parser.parse_args(argv)
    runs, spend = stage_spent(Settings().runs_dir, stage_commits())
    text, over = report(runs=runs, spend=spend, estimate=args.estimate)
    print(text)
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

(`ruff` may ask to wrap the long `raise` line; wrap it, behaviour unchanged.)

- [ ] **Step 12: Run the script tests to verify they pass**

Run: `uv run pytest tests/test_stage_spend.py -v`
Expected: PASS (3 tests)

- [ ] **Step 13: Add the Makefile target**

Add `stage-spend` to `.PHONY`, and:

```make
stage-spend:
	uv run python -m scripts.stage_spend --estimate $(or $(EST),0)
# S2.7 (decision 0098 item 6): the stage's spend by commit on both branches, free. Every paid
# S2.7 target runs this first with its estimate and stops if the $25 line would be passed.
```

- [ ] **Step 14: Run the full check**

Run: `make check`
Expected: PASS

- [ ] **Step 15: Commit**

```bash
git add src/ntsb_probable_cause/gitinfo.py src/ntsb_probable_cause/scoring/budget.py scripts/stage_spend.py Makefile tests/test_gitinfo.py tests/test_budget.py tests/test_stage_spend.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 1: the stage's spend by commit on both branches, against the \$25 line"
```

- [ ] **Step 16: Cut the track 2 branch**

Track 2 starts here (Global Constraints). From the main checkout:

```bash
git -C /Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause worktree add .claude/worktrees/s27-transcriber -b s27-transcriber s27-coding-guidance
git push -u origin s27-transcriber
```

---

### Task 2: The sealed sample (spec §3.1, §9.1, decision 0095)

**Files:**
- Modify: `src/ntsb_probable_cause/scoring/samples.py`
- Modify: `src/ntsb_probable_cause/gitinfo.py`
- Create: `scripts/draw_sealed.py`
- Create (by running the script): `tests/fixtures/eval/dev_seal_400_ids.csv`
- Modify: `apps/eval/__main__.py` (`_cmd_run`, `_cmd_transcribe`: one line each)
- Modify: `tests/fixtures/eval/README.md`
- Test: `tests/test_samples.py`, `tests/test_gitinfo.py`, `tests/test_contamination.py`, `tests/test_eval_app.py`

**Interfaces:**
- Consumes: `gitinfo` (Task 1).
- Produces: `samples.SAMPLES` includes `"dev-seal-400"`; `samples.SEALED_REGISTRATION = Path("docs/rounds/s27-sealed.md")`; `samples.refuse_sealed(sample: str, *, is_committed: Callable[[Path], bool]) -> None` (raises `ConfigurationError`); `samples.draw(processed, split, *, per_slice=200, seed=20260914, exclude: AbstractSet[str] = frozenset())`; `gitinfo.is_committed(path: Path, repo: Path = Path()) -> bool`. Task 10 and Task 13 call `refuse_sealed` too.

**Why the guard reads git, not a flag.** A flag can be passed by mistake; a committed registration naming the final setup is the event decision 0095 opens the sample on, and git records when it happened.

- [ ] **Step 1: Write the failing tests**

In `tests/test_gitinfo.py` (reusing `_repo` and `_git` from Task 1):

```python
def test_is_committed_needs_a_tracked_unchanged_file(tmp_path: Path) -> None:
    repo, _base = _repo(tmp_path)
    target = repo / "docs" / "rounds" / "s27-sealed.md"
    assert not gitinfo.is_committed(Path("docs/rounds/s27-sealed.md"), repo)
    target.parent.mkdir(parents=True)
    target.write_text("setup\n")
    assert not gitinfo.is_committed(Path("docs/rounds/s27-sealed.md"), repo)  # untracked
    _git(repo, "add", "docs/rounds/s27-sealed.md")
    _git(repo, "commit", "-q", "-m", "register")
    assert gitinfo.is_committed(Path("docs/rounds/s27-sealed.md"), repo)
    target.write_text("changed\n")
    assert not gitinfo.is_committed(Path("docs/rounds/s27-sealed.md"), repo)  # modified
```

In `tests/test_samples.py` (reusing its `_raw` and `_write_cases` helpers):

```python
def test_draw_excludes_the_given_cases_and_is_unchanged_without_them(tmp_path) -> None:
    rows = [_raw(f"CEN1{i}FA{i:03d}", fatal=i % 2 == 0, klass="F") for i in range(40)]
    processed = _write_cases(tmp_path, rows)
    plain = samples.draw(processed, Split.DEV, per_slice=5, seed=7)
    assert samples.draw(processed, Split.DEV, per_slice=5, seed=7, exclude=frozenset()) == plain
    excluded = frozenset(case for case, _date in plain)
    again = samples.draw(processed, Split.DEV, per_slice=5, seed=7, exclude=excluded)
    assert not excluded & {case for case, _date in again}


def test_refuse_sealed_opens_only_on_a_committed_registration() -> None:
    samples.refuse_sealed("dev-400", is_committed=lambda _path: False)
    with pytest.raises(ConfigurationError, match="sealed"):
        samples.refuse_sealed("dev-seal-400", is_committed=lambda _path: False)
    seen: list[Path] = []
    samples.refuse_sealed("dev-seal-400", is_committed=lambda path: seen.append(path) or True)
    assert seen == [Path("docs/rounds/s27-sealed.md")]
```

(Match `_raw`'s real keyword names in `tests/test_samples.py`; if it takes the class as `investigation_class=`, use that.)

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_gitinfo.py tests/test_samples.py -v -k "committed or exclude or sealed"`
Expected: FAIL (`is_committed`, `exclude`, `refuse_sealed` missing)

- [ ] **Step 3: Implement**

`gitinfo.py`:

```python
def is_committed(path: Path, repo: Path = Path()) -> bool:
    """Whether ``path`` (relative to ``repo``) is tracked and has no uncommitted change."""
    tracked = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "ls-files", "--error-unmatch", str(path)],  # noqa: S607
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode != 0:
        return False
    status = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "-C", str(repo), "status", "--porcelain", "--", str(path)],  # noqa: S607
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return not status.strip()
```

`samples.py`: add `from collections.abc import Callable, Sequence, Set as AbstractSet` (keep `Sequence`), `from ntsb_probable_cause.errors import ConfigurationError`, then:

```python
SAMPLES = ("heldout-40", "heldout-400", "dev-400", "dev-seal-400")
_FILES = {
    "heldout-40": "decidability_ids.csv",
    "heldout-400": "heldout_400_ids.csv",
    "dev-400": "dev_400_ids.csv",
    "dev-seal-400": "dev_seal_400_ids.csv",
}
# Decision 0095: the sealed development sample opens once, when the registration naming the
# final setup is committed. Every command that would score, read, fetch or transcribe it calls
# :func:`refuse_sealed` first.
SEALED = frozenset({"dev-seal-400"})
SEALED_REGISTRATION = Path("docs/rounds/s27-sealed.md")


def refuse_sealed(sample: str, *, is_committed: Callable[[Path], bool]) -> None:
    """Refuse a sealed sample until its registration is committed (decision 0095).

    Raises:
        ConfigurationError: ``sample`` is sealed and the registration is not committed.
    """
    if sample in SEALED and not is_committed(SEALED_REGISTRATION):
        raise ConfigurationError(
            f"{sample} is sealed: commit {SEALED_REGISTRATION}, naming the final setup, "
            "before anything reads it (decision 0095)"
        )
```

In `draw`, add the keyword `exclude: AbstractSet[str] = frozenset()` and filter it in the row comprehension (`if s == split.value and c in {"C", "F", "L"} and n not in exclude`); document it in the docstring: "``exclude``: case ids never drawn (``dev-seal-400`` excludes ``dev-400``, decision 0095)". With `exclude` empty the draw is byte-for-byte the old one.

`apps/eval/__main__.py`: import `from ntsb_probable_cause import gitinfo`; first line of `_cmd_run` and of `_cmd_transcribe`:

```python
    samples.refuse_sealed(args.sample, is_committed=gitinfo.is_committed)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_gitinfo.py tests/test_samples.py -v`
Expected: PASS

- [ ] **Step 5: Write the failing app test** (append to `tests/test_eval_app.py`)

```python
def test_run_and_transcribe_refuse_the_sealed_sample_before_anything_is_read(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setattr(gitinfo, "is_committed", lambda _path, repo=Path(): False)
    assert main(["run", "--arm", "B", "--sample", "dev-seal-400"]) == 1
    assert "sealed" in capsys.readouterr().err
    assert main(
        ["transcribe", "--sample", "dev-seal-400", "--expected-cost-per-page-usd", "0.001"]
    ) == 1
    assert "sealed" in capsys.readouterr().err
```

(Add `from ntsb_probable_cause import gitinfo` to the test's imports. `main` prints a `ConfigurationError` to stderr and returns 1, as for every other refusal.)

- [ ] **Step 6: Run it, confirm it passes with Step 3's app change**

Run: `uv run pytest tests/test_eval_app.py -v -k sealed`
Expected: PASS. Then comment out the `refuse_sealed` line in `_cmd_run` and re-run: Expected FAIL (the run tries to read the missing ids file). Restore the line.

- [ ] **Step 7: Write `scripts/draw_sealed.py`**

```python
"""Draw the sealed development sample once, or verify the committed list against a re-draw.

Status
    One-shot for S2.7 (decision 0095): ``draw`` writes tests/fixtures/eval/dev_seal_400_ids.csv
    and refuses to overwrite it; ``--verify`` re-draws and compares, free, reading only the
    processed file's index columns (no case is scored, read or fetched).

Why
    The sealed sample is the one clean check that guidance written from dev-400 generalises.
    It is drawn exactly as dev-400 was (0026) with a new seed and every dev-400 case excluded.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.draw_sealed [--verify]
"""

import argparse
import csv
from collections import Counter
from collections.abc import Sequence

from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split

SEED = 20260926
OUT = samples.EVAL_DIR / "dev_seal_400_ids.csv"


def drawn() -> list[tuple[str, str]]:
    """The sealed draw: dev split, classes C/F/L, 200 fatal and 200 non-fatal, no dev-400 case."""
    processed = Settings().data_dir / "processed"
    return samples.draw(
        processed, Split.DEV, seed=SEED, exclude=frozenset(samples.sample_ids("dev-400"))
    )


def main(argv: Sequence[str] | None = None) -> int:
    """Write the list once, or verify it."""
    parser = argparse.ArgumentParser(prog="draw_sealed")
    parser.add_argument("--verify", action="store_true")
    args = parser.parse_args(argv)
    rows = drawn()
    if args.verify:
        with OUT.open(newline="") as handle:
            committed = [(r["case_id"], r["event_date"]) for r in csv.DictReader(handle)]
        same = committed == rows
        print(f"dev-seal-400: {len(committed)} committed, {len(rows)} re-drawn, identical: {same}")
        return 0 if same else 1
    if OUT.exists():
        raise SystemExit(f"{OUT} exists: the sealed sample is drawn once (decision 0095)")
    with OUT.open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["case_id", "event_date"])
        writer.writerows(rows)
    years = Counter(date[:4] for _case, date in rows)
    print(f"dev-seal-400: {len(rows)} cases written to {OUT}; by year {dict(sorted(years.items()))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Draw the sample** (free; reads the processed file's index columns and raw injury level only)

Run:
```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
uv run python -m scripts.draw_sealed
uv run python -m scripts.draw_sealed --verify
```
Expected: about 400 cases written (the rounding in `draw` gave 401 for `dev-400`); the verify line ends `identical: True`.

- [ ] **Step 9: Write the contamination tests** (append to `tests/test_contamination.py`, using its `eval_ids` fixture)

```python
def test_the_sealed_sample_is_development_and_shares_no_case(eval_ids) -> None:
    sealed = eval_ids["dev_seal_400_ids"]
    assert 395 <= len(sealed) <= 405
    assert all(date[:4] <= "2019" for date in sealed.values())
    assert not set(sealed) & set(eval_ids["dev_400_ids"])
    assert not set(sealed) & set(eval_ids["heldout_400_ids"])
    assert not set(sealed) & set(eval_ids["decidability_ids"])
```

Add a line for `dev_seal_400_ids.csv` to `tests/fixtures/eval/README.md` ("the sealed development sample, decision 0095; drawn by `scripts/draw_sealed.py`, seed 20260926, excluding `dev-400`; opened once").

- [ ] **Step 10: Run the full check**

Run: `make check`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add src/ntsb_probable_cause/scoring/samples.py src/ntsb_probable_cause/gitinfo.py scripts/draw_sealed.py tests/fixtures/eval/dev_seal_400_ids.csv tests/fixtures/eval/README.md apps/eval/__main__.py tests/test_samples.py tests/test_gitinfo.py tests/test_contamination.py tests/test_eval_app.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 2: the sealed development sample, drawn once and refused until registered"
```

---

### Task 3: The statistics pool and the coding counts (spec §3.2, decision 0094; W1)

**Files:**
- Create: `src/ntsb_probable_cause/scoring/coding_stats.py`
- Create: `scripts/coding_stats.py`
- Create (by running the script): `src/ntsb_probable_cause/scoring/tables/coding_stats.json`, `docs/results/s27-coding-stats.txt`
- Modify: `pyproject.toml` (import-linter: add `ntsb_probable_cause.scoring.coding_stats` to the "Only the splitter constructs synthesis and verdict" source list)
- Modify: `Makefile`
- Test: `tests/test_coding_stats.py` (create), `tests/test_coding_stats_script.py` (create)

**Interfaces:**
- Produces:
  - `coding_stats.PoolCase(year: int, group: str | None, sequence: tuple[str, ...])` (frozen dataclass; `sequence[0]` is the defining event, as `fields.occurrence_codes` orders it).
  - `coding_stats.HALVES: tuple[tuple[str, int, int], ...] = (("2009-2014", 2009, 2014), ("2015-2019", 2015, 2019))`.
  - `coding_stats.CodingStats` (pydantic, frozen) with fields `built_from: str`, `cases: dict[str, int]`, `present: dict[str, dict[str, int]]`, `defining_given_present: dict[str, dict[str, dict[str, int]]]`, `pairs: dict[str, dict[str, dict[str, int]]]`, `group_defining: dict[str, dict[str, dict[str, int]]]` — each keyed first by half — and methods `present_n(code) -> int`, `defining_given(code) -> dict[str, int]`, `pair(a, b) -> dict[str, int]`, `group_defining_n(group, code) -> int`, `group_top(group, k) -> list[str]`, `group_phases(group) -> dict[str, int]`, `defining_n(code) -> int`, `to_json() -> str`.
  - `coding_stats.build(cases: Iterable[PoolCase], *, built_from: str) -> CodingStats`; `coding_stats.load_stats() -> CodingStats` (cached; reads the committed JSON); `coding_stats.NO_GROUP = "(none)"`.
  - `scripts.coding_stats.pool_cases(rows, *, excluded: AbstractSet[str]) -> tuple[list[PoolCase], list[str]]` and `scripts.coding_stats.check_pool(ids, *, excluded, splits) -> None` (raises `LeakageError`).
- Task 8 consumes `CodingStats` and `load_stats`.

**What each count means, with the example that motivates it.** `present[half][c]` is the number of pool cases whose sequence contains code `c` anywhere. `defining_given_present[half][c][d]` is, among those, the number where `d` is the defining event: "when `451241` (stall/spin) appears, `451240` (loss of control in flight) is defining in N of M". `pairs[half]["a|b"]` (codes sorted) holds `both` (cases containing both) and, for each of `a` and `b`, the cases where it is the defining event: "when loss of control and stall both occur, loss of control is defining in N of `both`". `group_defining[half][g][d]` is the number of pool cases whose phase group is `g` and whose defining code is `d`; it gives the commonest defining codes for a group and, by the first three digits of `d`, **which phase prefixes the NTSB uses within a group** (W1).

- [ ] **Step 1: Write the failing library tests** (`tests/test_coding_stats.py`)

```python
"""scoring/coding_stats.py: counts of how the NTSB codes occurrences (decision 0094)."""

from ntsb_probable_cause.scoring.coding_stats import NO_GROUP, CodingStats, PoolCase, build

LOC, STALL, CFIT = "452240", "452241", "452120"

CASES = [
    PoolCase(year=2010, group="Maneuvering", sequence=(LOC, STALL)),
    PoolCase(year=2012, group="Maneuvering", sequence=(LOC, STALL, CFIT)),
    PoolCase(year=2016, group="Maneuvering", sequence=(STALL, LOC)),
    PoolCase(year=2017, group="Landing", sequence=("552300",)),
    PoolCase(year=2018, group=None, sequence=(CFIT,)),
    PoolCase(year=2019, group="Landing", sequence=()),  # no codes: not counted
]


def _stats() -> CodingStats:
    return build(CASES, built_from="test")


def test_cases_are_counted_by_half_and_empty_sequences_skipped() -> None:
    stats = _stats()
    assert stats.cases == {"2009-2014": 2, "2015-2019": 3}


def test_present_and_defining_given_present() -> None:
    stats = _stats()
    assert stats.present_n(STALL) == 3
    assert stats.defining_given(STALL) == {LOC: 2, STALL: 1}
    assert stats.defining_given(CFIT) == {LOC: 1, CFIT: 1}


def test_pairs_count_both_and_each_side_defining() -> None:
    stats = _stats()
    assert stats.pair(STALL, LOC) == {"both": 3, LOC: 2, STALL: 1}
    assert stats.pair(LOC, "999999") == {"both": 0}


def test_groups_give_defining_codes_and_phase_prefixes() -> None:
    stats = _stats()
    assert stats.group_defining_n("Maneuvering", LOC) == 2
    assert stats.group_top("Maneuvering", 2) == [LOC, STALL]
    assert stats.group_phases("Maneuvering") == {"452": 3}
    assert stats.group_defining_n(NO_GROUP, CFIT) == 1


def test_json_round_trip() -> None:
    stats = _stats()
    assert CodingStats.model_validate_json(stats.to_json()) == stats
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_coding_stats.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'ntsb_probable_cause.scoring.coding_stats'`

- [ ] **Step 3: Write `scoring/coding_stats.py`**

```python
"""Counts of how the NTSB codes occurrences, from the statistics pool (decision 0094).

The pool is every development case in classes C, F and L outside ``dev-400`` and
``dev-seal-400``; ``scripts/coding_stats.py`` builds it and commits the counts beside the code
tables. This module holds the counts and reads them; it never reads a case, and nothing here
names one. Every count is kept per half of the decade so a habit that changed is visible.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from functools import cache
from importlib import resources

from pydantic import BaseModel, ConfigDict

HALVES: tuple[tuple[str, int, int], ...] = (("2009-2014", 2009, 2014), ("2015-2019", 2015, 2019))
# A case whose phase-of-flight evidence is blank is counted under this group name.
NO_GROUP = "(none)"
_RESOURCE = "tables/coding_stats.json"


@dataclass(frozen=True)
class PoolCase:
    """One pool case, reduced to what is counted: no case number, no text."""

    year: int
    group: str | None
    sequence: tuple[str, ...]


def _half(year: int) -> str:
    for name, first, last in HALVES:
        if first <= year <= last:
            return name
    raise ValueError(f"year {year} is outside the development split's halves")


def _pair_key(a: str, b: str) -> str:
    return "|".join(sorted((a, b)))


class CodingStats(BaseModel):
    """The counts, keyed first by half (see :data:`HALVES`)."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    built_from: str
    cases: dict[str, int]
    present: dict[str, dict[str, int]]
    defining_given_present: dict[str, dict[str, dict[str, int]]]
    pairs: dict[str, dict[str, dict[str, int]]]
    group_defining: dict[str, dict[str, dict[str, int]]]

    def present_n(self, code: str) -> int:
        """Pool cases whose sequence contains ``code``."""
        return sum(half.get(code, 0) for half in self.present.values())

    def defining_given(self, code: str) -> dict[str, int]:
        """Among pool cases containing ``code``: defining code -> cases."""
        total: Counter[str] = Counter()
        for half in self.defining_given_present.values():
            total.update(half.get(code, {}))
        return dict(total)

    def pair(self, a: str, b: str) -> dict[str, int]:
        """Cases holding both codes (``both``), and for each code the cases it is defining."""
        total: Counter[str] = Counter({"both": 0})
        for half in self.pairs.values():
            total.update(half.get(_pair_key(a, b), {}))
        return dict(total)

    def group_defining_n(self, group: str, code: str) -> int:
        """Pool cases with phase group ``group`` whose defining code is ``code``."""
        return sum(half.get(group, {}).get(code, 0) for half in self.group_defining.values())

    def defining_n(self, code: str) -> int:
        """Pool cases whose defining code is ``code``, over every group."""
        return sum(
            codes.get(code, 0) for half in self.group_defining.values() for codes in half.values()
        )

    def group_top(self, group: str, k: int) -> list[str]:
        """The ``k`` commonest defining codes in ``group``; ties by code."""
        total: Counter[str] = Counter()
        for half in self.group_defining.values():
            total.update(half.get(group, {}))
        return [code for code, _n in sorted(total.items(), key=lambda kv: (-kv[1], kv[0]))[:k]]

    def group_phases(self, group: str) -> dict[str, int]:
        """Phase prefix -> pool cases in ``group`` whose defining code has it (plan W1)."""
        total: Counter[str] = Counter()
        for half in self.group_defining.values():
            for code, n in half.get(group, {}).items():
                total[code[:3]] += n
        return dict(total)

    def to_json(self) -> str:
        """The committed form: one-space indent, keys as built (sorted)."""
        return self.model_dump_json(indent=1)


def _sorted(tree: object) -> object:
    if isinstance(tree, dict):
        return {key: _sorted(tree[key]) for key in sorted(tree)}
    return tree


def build(cases: Iterable[PoolCase], *, built_from: str) -> CodingStats:
    """Count ``cases``; a case with no occurrence codes is skipped."""
    counted: Counter[str] = Counter()
    present: defaultdict[str, Counter[str]] = defaultdict(Counter)
    given: defaultdict[str, defaultdict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    pairs: defaultdict[str, defaultdict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    groups: defaultdict[str, defaultdict[str, Counter[str]]] = defaultdict(lambda: defaultdict(Counter))
    for case in cases:
        if not case.sequence:
            continue
        half = _half(case.year)
        counted[half] += 1
        defining = case.sequence[0]
        codes = sorted(set(case.sequence))
        for code in codes:
            present[half][code] += 1
            given[half][code][defining] += 1
        for i, a in enumerate(codes):
            for b in codes[i + 1 :]:
                key = _pair_key(a, b)
                pairs[half][key]["both"] += 1
                if defining in (a, b):
                    pairs[half][key][defining] += 1
        groups[half][case.group or NO_GROUP][defining] += 1
    return CodingStats.model_validate(
        _sorted(
            {
                "built_from": built_from,
                "cases": dict(counted),
                "present": {h: dict(c) for h, c in present.items()},
                "defining_given_present": {
                    h: {c: dict(d) for c, d in by.items()} for h, by in given.items()
                },
                "pairs": {h: {k: dict(v) for k, v in by.items()} for h, by in pairs.items()},
                "group_defining": {
                    h: {g: dict(d) for g, d in by.items()} for h, by in groups.items()
                },
            }
        )
    )


@cache
def load_stats() -> CodingStats:
    """The committed counts (``scoring/tables/coding_stats.json``)."""
    text = resources.files("ntsb_probable_cause.scoring").joinpath(_RESOURCE).read_text()
    return CodingStats.model_validate_json(text)
```

(`_sorted` returns `object`; `model_validate` accepts it. If mypy objects to the `dict` comprehension inside `_sorted`, annotate the parameter as `dict[str, object] | object` and cast; keep behaviour.)

- [ ] **Step 4: Run the library tests to verify they pass**

Run: `uv run pytest tests/test_coding_stats.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Add the module to the import-linter contract**

In `pyproject.toml`, add `"ntsb_probable_cause.scoring.coding_stats",` to the source list of "Only the splitter constructs synthesis and verdict" (after `scoring.codes`). Run `uv run lint-imports`. Expected: all contracts kept.

- [ ] **Step 6: Write the failing script tests** (`tests/test_coding_stats_script.py`)

```python
"""scripts/coding_stats.py: the pool, and the contamination guard (decision 0094)."""

import pytest
from scripts import coding_stats as cs

from ntsb_probable_cause.errors import LeakageError


def _row(case: str, date: str, split: str, klass: str, codes: tuple[str, ...], group: str):
    events = [
        {
            "eventCode": code,
            "isDefiningEvent": i == 0,
            "sequenceNumber": i + 1,
            "cicttPhaseSOEGroup": group,
        }
        for i, code in enumerate(codes)
    ]
    return case, date, split, klass, {"aircrafts": [{"events": events}]}


ROWS = [
    _row("POOL1", "2011-05-01", "dev", "C", ("552300",), "Landing"),
    _row("POOL2", "2016-05-01", "dev", "F", ("452240", "452241"), "Maneuvering"),
    _row("DEV400", "2012-01-01", "dev", "C", ("552300",), "Landing"),
    _row("OTHERCLASS", "2012-01-01", "dev", "I", ("552300",), "Landing"),
    _row("HELD", "2021-01-01", "heldout", "C", ("552300",), "Landing"),
    _row("OPEN", "2025-01-01", "open", "C", ("552300",), "Landing"),
]


def test_pool_keeps_dev_classes_c_f_l_outside_the_samples() -> None:
    cases, ids = cs.pool_cases(ROWS, excluded=frozenset({"DEV400"}))
    assert ids == ["POOL1", "POOL2"]
    assert [c.sequence for c in cases] == [("552300",), ("452240", "452241")]
    assert cases[1].group == "Maneuvering"


def test_check_pool_refuses_a_sample_case_or_a_non_development_case() -> None:
    cs.check_pool(["POOL1"], excluded=frozenset({"DEV400"}), splits={"POOL1": "dev"})
    with pytest.raises(LeakageError, match="DEV400"):
        cs.check_pool(["DEV400"], excluded=frozenset({"DEV400"}), splits={"DEV400": "dev"})
    with pytest.raises(LeakageError, match="HELD"):
        cs.check_pool(["HELD"], excluded=frozenset(), splits={"HELD": "heldout"})


def test_report_prints_counts_and_both_halves_without_case_numbers() -> None:
    cases, _ids = cs.pool_cases(ROWS, excluded=frozenset({"DEV400"}))
    stats = cs.build(cases, built_from="test")
    text = cs.report(stats)
    assert "2009-2014: 1 cases; 2015-2019: 1 cases" in text
    assert "POOL" not in text
```

- [ ] **Step 7: Run them to verify they fail**

Run: `uv run pytest tests/test_coding_stats_script.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 8: Write `scripts/coding_stats.py`**

```python
"""Build the statistics pool's coding counts, once (decision 0094).

Status
    One build for S2.7, free: streams the processed file, writes
    src/ntsb_probable_cause/scoring/tables/coding_stats.json (the counts the ordering check and
    the guidance read) and docs/results/s27-coding-stats.txt (the same counts, readable).
    Counts and code labels only; no case number or text is written.

Why
    The ordering check and the guidance need the NTSB's own coding habits. They come from
    development cases outside both samples, so no scored case helps answer itself; a guard
    refuses the build if a sample, held-out or open case reaches the pool.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.coding_stats [--out PATH]
"""

import argparse
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.coding_stats import HALVES, CodingStats, PoolCase, build
from ntsb_probable_cause.settings import Settings

POOL_CLASSES = frozenset({"C", "F", "L"})
EXCLUDED_SAMPLES = ("dev-400", "dev-seal-400")
JSON_OUT = Path("src/ntsb_probable_cause/scoring/tables/coding_stats.json")
BUILT_FROM = (
    "development split, classes C/F/L, excluding dev-400 and dev-seal-400 "
    "(scripts/coding_stats.py, decision 0094)"
)
TOP = 40
_GROUP = next(f for f in fields.EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)

Row = tuple[str, str, str, str, Mapping[str, object]]


def processed_rows(processed: Path) -> Iterator[Row]:
    """Stream (case, event date, split, class, raw) from the processed file."""
    columns = ["ntsb_number", "event_date", "split", "investigation_class", "raw_json"]
    with pq.ParquetFile(processed / "cases.parquet") as parquet:
        for batch in parquet.iter_batches(batch_size=512, columns=columns):
            yield from (
                (str(n), str(d), str(s), str(c), json.loads(r))
                for n, d, s, c, r in zip(
                    *(batch.column(col).to_pylist() for col in columns), strict=True
                )
            )


def pool_cases(rows: Iterable[Row], *, excluded: AbstractSet[str]) -> tuple[list[PoolCase], list[str]]:
    """The pool: development, classes C/F/L, not in ``excluded``; and its case ids, in order."""
    cases: list[PoolCase] = []
    ids: list[str] = []
    for case, date, split, klass, raw in rows:
        if split != "dev" or klass not in POOL_CLASSES or case in excluded:
            continue
        group = _GROUP.extract(raw)
        cases.append(
            PoolCase(
                year=int(date[:4]),
                group=group if isinstance(group, str) else None,
                sequence=fields.occurrence_codes(raw),
            )
        )
        ids.append(case)
    return cases, ids


def check_pool(ids: Sequence[str], *, excluded: AbstractSet[str], splits: Mapping[str, str]) -> None:
    """Refuse a pool holding a sample case or any case outside the development split."""
    leaked = sorted(set(ids) & excluded)
    if leaked:
        raise LeakageError(f"the statistics pool holds sample cases: {leaked[:5]} (decision 0094)")
    foreign = sorted(i for i in ids if splits.get(i) != "dev")
    if foreign:
        raise LeakageError(f"the statistics pool holds non-development cases: {foreign[:5]}")


def _label(code: str, tables: CodeTables) -> str:
    return f"{code} {tables.phases.get(code[:3], '?')} / {tables.events.get(code[3:], '?')}"


def report(stats: CodingStats, tables: CodeTables | None = None) -> str:
    """The readable counts: both halves printed beside the total."""
    tables = tables or load_tables()
    halves = [name for name, _first, _last in HALVES]
    lines = [
        "coding counts from the statistics pool (scripts/coding_stats.py; counts only, decision 0094)",
        f"built from: {stats.built_from}",
        "; ".join(f"{h}: {stats.cases.get(h, 0)} cases" for h in halves),
        "",
        f"## when a code appears, which code is defining (the {TOP} commonest codes; n = cases containing it)",
    ]
    commonest = sorted(
        {c for half in stats.present.values() for c in half},
        key=lambda c: (-stats.present_n(c), c),
    )[:TOP]
    for code in commonest:
        given = sorted(stats.defining_given(code).items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        by_half = ", ".join(
            f"{h} n={stats.present.get(h, {}).get(code, 0)}" for h in halves
        )
        lines.append(f"- {_label(code, tables)}: n={stats.present_n(code)} ({by_half})")
        lines.extend(f"    defining: {_label(d, tables)} {k}" for d, k in given)
    lines += ["", f"## pairs occurring together (the {TOP} commonest)"]
    pairs = sorted(
        {key for half in stats.pairs.values() for key in half},
        key=lambda key: (-stats.pair(*key.split("|"))["both"], key),
    )[:TOP]
    for key in pairs:
        a, b = key.split("|")
        counts = stats.pair(a, b)
        halves_text = "; ".join(
            f"{h}: both {stats.pairs.get(h, {}).get(key, {}).get('both', 0)}, "
            f"{a} {stats.pairs.get(h, {}).get(key, {}).get(a, 0)}, "
            f"{b} {stats.pairs.get(h, {}).get(key, {}).get(b, 0)}"
            for h in halves
        )
        lines.append(
            f"- {_label(a, tables)} + {_label(b, tables)}: both {counts['both']}, "
            f"{a} defining {counts.get(a, 0)}, {b} defining {counts.get(b, 0)} ({halves_text})"
        )
    lines += ["", "## phase groups: phase prefixes used, and the three commonest defining codes"]
    groups = sorted({g for half in stats.group_defining.values() for g in half})
    for group in groups:
        phases = sorted(stats.group_phases(group).items(), key=lambda kv: (-kv[1], kv[0]))
        lines.append(f"- {group}: phases " + ", ".join(f"{p} {tables.phases.get(p, '?')} {n}" for p, n in phases))
        lines.extend(
            f"    {_label(c, tables)} {stats.group_defining_n(group, c)}" for c in stats.group_top(group, 3)
        )
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """Build the pool, guard it, write the JSON and the report."""
    parser = argparse.ArgumentParser(prog="coding_stats")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    processed = Settings().data_dir / "processed"
    excluded = frozenset(i for name in EXCLUDED_SAMPLES for i in samples.sample_ids(name))
    # One streaming pass: holding every raw record at once costs about 600 MB (the note on
    # samples.seen_pairs); only each case's split is kept beside the pool.
    splits: dict[str, str] = {}

    def tapped() -> Iterator[Row]:
        for row in processed_rows(processed):
            splits[row[0]] = row[2]
            yield row

    cases, ids = pool_cases(tapped(), excluded=excluded)
    check_pool(ids, excluded=excluded, splits=splits)
    stats = build(cases, built_from=BUILT_FROM)
    JSON_OUT.write_text(stats.to_json() + "\n")
    text = report(stats)
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

The test module calls `cs.build`; the script's `from ... import build` line provides it. Lines ruff asks to wrap are wrapped; behaviour unchanged.

- [ ] **Step 9: Run the script tests to verify they pass**

Run: `uv run pytest tests/test_coding_stats_script.py -v`
Expected: PASS (3 tests)

- [ ] **Step 10: Add the Makefile target**

```make
s27-coding-stats:
	uv run python -m scripts.coding_stats --out docs/results/s27-coding-stats.txt
# S2.7 spec §3.2, free: the statistics pool's coding counts, once (decision 0094). Writes the
# committed JSON beside the code tables and the readable results file.
```

- [ ] **Step 11: Build the counts** (free)

Run:
```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
make s27-coding-stats
```
Expected: the halves line shows about 12,490 cases in all (spec §3.1, ad hoc); the "phase groups" section shows, for example, `Maneuvering` with prefixes in the 450s. Read the stall/loss-of-control pair line: it re-derives the spec's ad-hoc observation that loss of control is usually defining.

- [ ] **Step 12: Add a CI test that the committed counts name no case** (append to `tests/test_coding_stats.py`)

```python
import re
from pathlib import Path

_CASE_NUMBER = re.compile(r"\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}[A-Z]?\b")


def test_the_committed_counts_load_and_name_no_case() -> None:
    from ntsb_probable_cause.scoring.coding_stats import load_stats

    stats = load_stats()
    assert "excluding dev-400 and dev-seal-400" in stats.built_from
    for path in (
        Path("src/ntsb_probable_cause/scoring/tables/coding_stats.json"),
        Path("docs/results/s27-coding-stats.txt"),
    ):
        assert not _CASE_NUMBER.search(path.read_text()), path
```

- [ ] **Step 13: Run the full check**

Run: `make check`
Expected: PASS

- [ ] **Step 14: Commit**

```bash
git add src/ntsb_probable_cause/scoring/coding_stats.py src/ntsb_probable_cause/scoring/tables/coding_stats.json scripts/coding_stats.py docs/results/s27-coding-stats.txt pyproject.toml Makefile tests/test_coding_stats.py tests/test_coding_stats_script.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 3: the statistics pool's coding counts, guarded against contamination"
```

---

## Part B — Round 0: look before changing anything (spec §4)

### Task 4: The six miss groups, finding depth and the model's own words (spec §4.1)

**Files:**
- Create: `src/ntsb_probable_cause/scoring/misses.py`
- Modify: `scripts/occurrence_misses.py`
- Modify: `pyproject.toml` (import-linter source list: add `ntsb_probable_cause.scoring.misses`)
- Test: `tests/test_misses.py` (create), `tests/test_occurrence_misses.py`

**Interfaces:**
- Produces:
  - `misses.MissGroup = Literal["exact", "right event, wrong phase", "in sequence, not defining", "a later guess in sequence", "event under another phase", "nothing in common", "abstained"]`; `misses.GROUPS: tuple[MissGroup, ...]` in that order; `misses.MISS_GROUPS` = the five miss groups (every group but `exact` and `abstained`).
  - `misses.miss_group(guesses: Sequence[str], truth: Sequence[str], *, abstain: bool) -> MissGroup`.
  - `misses.FindingDepth` (frozen dataclass: `flagged`, `found`, `item_right_modifier_wrong`, `category_right_item_wrong`, `category_wrong`, all `int`; `__add__`); `misses.finding_depth(predicted: Sequence[str], flagged: Sequence[str]) -> FindingDepth`.
  - `misses.EVENT_PHRASES: Mapping[str, tuple[str, ...]]`; `misses.names_event(text: str, event: str) -> bool | None` (None when the event has no phrase list).
  - `scripts.occurrence_misses.detail(cases, tables) -> str`; `scripts.occurrence_misses.churn(a, b) -> str`; `main` gains `--against RUN_ID`.
- Tasks 6 and 11 consume `miss_group` and `MISS_GROUPS`.

**The groups, with an example each.** The NTSB's sequence is `(452240, 452241)` (loss of control in flight, defining; then stall/spin). A first guess of `452240` is *exact*; `450240` is *right event, wrong phase*; `452241` is *in sequence, not defining*; guesses `(470470, 452241)` are *a later guess in sequence*; `(450241,)` is *event under another phase*; `(552300,)` is *nothing in common*. The groups are tested in that order, so each case lands in exactly one.

- [ ] **Step 1: Write the failing tests** (`tests/test_misses.py`)

```python
"""scoring/misses.py: where a first guess lands, and how deep a finding miss goes."""

import pytest

from ntsb_probable_cause.scoring.misses import (
    GROUPS,
    MISS_GROUPS,
    FindingDepth,
    finding_depth,
    miss_group,
    names_event,
)

TRUTH = ("452240", "452241")


@pytest.mark.parametrize(
    ("guesses", "group"),
    [
        (("452240",), "exact"),
        (("450240", "452241"), "right event, wrong phase"),
        (("452241",), "in sequence, not defining"),
        (("470470", "452241"), "a later guess in sequence"),
        (("450241",), "event under another phase"),
        (("552300",), "nothing in common"),
    ],
)
def test_each_case_lands_in_one_group(guesses: tuple[str, ...], group: str) -> None:
    assert miss_group(guesses, TRUTH, abstain=False) == group


def test_abstained_and_empty_truth() -> None:
    assert miss_group(("452240",), TRUTH, abstain=True) == "abstained"
    assert miss_group(("452240",), (), abstain=False) == "nothing in common"


def test_the_group_lists() -> None:
    assert GROUPS[0] == "exact"
    assert "exact" not in MISS_GROUPS
    assert "abstained" not in MISS_GROUPS
    assert len(MISS_GROUPS) == 5


def test_finding_depth_counts_each_flagged_finding_once_at_its_deepest_match() -> None:
    flagged = ("0106201220", "0206304044", "0303403591", "0204152044")
    predicted = ("0106201220", "0206304099", "0303403000")
    assert finding_depth(predicted, flagged) == FindingDepth(
        flagged=4, found=1, item_right_modifier_wrong=1, category_right_item_wrong=1, category_wrong=1
    )
    assert finding_depth((), ()) + finding_depth((), ("0106201220",)) == FindingDepth(
        flagged=1, found=0, item_right_modifier_wrong=0, category_right_item_wrong=0, category_wrong=1
    )


def test_names_event_is_a_fixed_phrase_list() -> None:
    assert names_event("The pilot LOST CONTROL of the airplane.", "240") is True
    assert names_event("The airplane stalled.", "240") is False
    assert names_event("anything", "999") is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_misses.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write `scoring/misses.py`**

```python
"""Where a first occurrence guess lands in the NTSB's sequence, and how deep a finding miss goes.

S2.7 spec §4.1. Pure functions over codes: no case, no text but the model's own. A six-digit
occurrence code is a three-digit phase and a three-digit event; the NTSB's sequence lists the
defining event first (``fields.occurrence_codes``).
"""

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

MissGroup = Literal[
    "exact",
    "right event, wrong phase",
    "in sequence, not defining",
    "a later guess in sequence",
    "event under another phase",
    "nothing in common",
    "abstained",
]
GROUPS: tuple[MissGroup, ...] = (
    "exact",
    "right event, wrong phase",
    "in sequence, not defining",
    "a later guess in sequence",
    "event under another phase",
    "nothing in common",
    "abstained",
)
MISS_GROUPS: tuple[MissGroup, ...] = GROUPS[1:6]


def miss_group(guesses: Sequence[str], truth: Sequence[str], *, abstain: bool) -> MissGroup:
    """The one group a case's first guess falls in, tested in the order of :data:`GROUPS`."""
    if abstain:
        return "abstained"
    if not truth or not guesses:
        return "nothing in common"
    first, defining = guesses[0], truth[0]
    if first == defining:
        return "exact"
    if first[3:] == defining[3:]:
        return "right event, wrong phase"
    if first in truth:
        return "in sequence, not defining"
    if any(guess in truth for guess in guesses[1:]):
        return "a later guess in sequence"
    if any(guess[3:] == code[3:] for guess in guesses for code in truth):
        return "event under another phase"
    return "nothing in common"


@dataclass(frozen=True)
class FindingDepth:
    """For the NTSB's flagged findings: how many the model found, and how deep each miss was."""

    flagged: int
    found: int
    item_right_modifier_wrong: int
    category_right_item_wrong: int
    category_wrong: int

    def __add__(self, other: FindingDepth) -> FindingDepth:
        return FindingDepth(
            self.flagged + other.flagged,
            self.found + other.found,
            self.item_right_modifier_wrong + other.item_right_modifier_wrong,
            self.category_right_item_wrong + other.category_right_item_wrong,
            self.category_wrong + other.category_wrong,
        )


def finding_depth(predicted: Sequence[str], flagged: Sequence[str]) -> FindingDepth:
    """Each flagged ten-digit finding at its deepest match among the model's findings."""
    found = modifier = item = category = 0
    for code in flagged:
        if code in predicted:
            found += 1
        elif any(p[:8] == code[:8] for p in predicted):
            modifier += 1
        elif any(p[:6] == code[:6] for p in predicted):
            item += 1
        else:
            category += 1
    return FindingDepth(len(flagged), found, modifier, item, category)


# A fixed, crude list, committed so "the model's own words name the NTSB's event" is counted
# the same way every time (spec §4.1 item 4). Lower case; matched as substrings.
EVENT_PHRASES: Mapping[str, tuple[str, ...]] = {
    "090": ("bounced", "porpois", "abnormal runway contact"),
    "092": ("hard landing", "landed hard"),
    "120": ("controlled flight into terrain", "cfit"),
    "191": ("fuel starvation", "starved", "fuel selector"),
    "192": ("fuel exhaustion", "ran out of fuel", "exhausted the fuel", "no usable fuel"),
    "220": ("low altitude", "low-altitude", "low level", "low-level"),
    "230": ("loss of control", "lost control", "ground loop", "veered"),
    "240": ("loss of control", "lost control", "loss of aircraft control"),
    "241": ("stall", "spin"),
    "300": ("runway excursion", "departed the runway", "exited the runway", "ran off", "overran"),
    "341": ("total loss of engine power", "total loss of power", "engine stopped", "engine quit"),
    "342": ("partial loss of engine power", "partial loss of power", "lost partial power"),
    "401": ("instrument meteorological", "imc", "cloud", "fog", "visibility"),
    "470": ("collided with", "collision with", "struck", "impacted"),
}


def names_event(text: str, event: str) -> bool | None:
    """Whether ``text`` names ``event`` by the fixed list; None when the event has no list."""
    phrases = EVENT_PHRASES.get(event)
    if phrases is None:
        return None
    lowered = text.lower()
    return any(phrase in lowered for phrase in phrases)
```

- [ ] **Step 4: Run the tests to verify they pass; add the import-linter entry**

Run: `uv run pytest tests/test_misses.py -v && uv run lint-imports`
Expected: PASS; contracts kept (after adding `"ntsb_probable_cause.scoring.misses",` to the "Only the splitter…" source list).

- [ ] **Step 5: Write the failing script tests** (append to `tests/test_occurrence_misses.py`, reusing its `_case`, `_step`, `CASES`, `_write_run`)

```python
def test_detail_prints_the_six_groups_confidence_and_own_words() -> None:
    text = om.detail(CASES, load_tables())
    assert "## the six groups (first guess)" in text
    for group in ("exact", "right event, wrong phase", "nothing in common"):
        assert group in text
    assert "median confidence" in text
    assert "## the model's own words" in text


def _hit(case: CaseResult, top1: bool) -> CaseResult:
    return case.model_copy(update={"scores": replace(_SCORES, occurrence_top1=top1)})


def test_churn_counts_changed_first_guesses_and_hits_gained_and_lost() -> None:
    # this run: C1 right, C2 wrong; the second run: C1 wrong (other guess), C2 wrong (same guess)
    this = [
        _hit(_case("C1", ("452240",), ("452240",)), top1=True),
        _hit(_case("C2", ("452240",), ("452241",)), top1=False),
    ]
    other = [
        _hit(_case("C1", ("452240",), ("452241",)), top1=False),
        _hit(_case("C2", ("452240",), ("452241",)), top1=False),
    ]
    text = om.churn(this, other)
    assert "same first guess: 1 of 2" in text
    assert "top-1 gained 1, lost 0" in text


def test_main_with_against_prints_churn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    first, second = "20260926T000000-abc1234-dev-400-B", "20260927T000000-abc1234-dev-400-B"
    for run_id in (first, second):
        folder = _write_run(runs, run_id)
        write_jsonl(folder / "cases.jsonl", CASES)
    assert om.main(["--run", first, "--against", second]) == 0
    out = capsys.readouterr().out
    assert "## the six groups (first guess)" in out
    assert "same first guess: 5 of 5" in out
```

(Add `from dataclasses import replace` to the test module's imports. `churn` counts "gained" as right in this run and wrong in the second, "lost" the other way.)

- [ ] **Step 6: Run them to verify they fail**

Run: `uv run pytest tests/test_occurrence_misses.py -v`
Expected: the new tests FAIL (`detail`, `churn`, `--against` missing); the old ones PASS.

- [ ] **Step 7: Extend `scripts/occurrence_misses.py`**

Add to the imports `import statistics`, `from ntsb_probable_cause.scoring.misses import GROUPS, FindingDepth, finding_depth, miss_group, names_event`. Add to the module docstring's Status: "Extended in S2.7 (spec §4.1): the six groups, finding depth, confidence by group, the model's own words, and churn against a second run." Then:

```python
def _guesses(case: CaseResult) -> tuple[str, ...]:
    return tuple(g.phase + g.event for g in case.steps[-1].hypothesis.occurrence)


def _scored(cases: Sequence[CaseResult]) -> list[CaseResult]:
    return [c for c in cases if c.scores is not None and c.steps]


def detail(cases: Sequence[CaseResult], tables: CodeTables) -> str:
    """S2.7 §4.1: the six groups, confidence, finding depth, and the model's own words."""
    scored = _scored(cases)
    by_group: dict[str, list[CaseResult]] = {g: [] for g in GROUPS}
    depth = FindingDepth(0, 0, 0, 0, 0)
    named = asked = 0
    for case in scored:
        hypothesis = case.steps[-1].hypothesis
        group = miss_group(_guesses(case), case.verdict_occurrence, abstain=hypothesis.abstain)
        by_group[group].append(case)
        depth = depth + finding_depth(hypothesis.finding_codes(tables), case.verdict_findings_in_cause)
        if group not in ("exact", "abstained") and case.verdict_occurrence:
            said = names_event(
                f"{hypothesis.evidence_narrative} {hypothesis.probable_cause}",
                case.verdict_occurrence[0][3:],
            )
            if said is not None:
                asked += 1
                named += said
    total = len(scored)
    lines = ["", "## the six groups (first guess)"]
    for group in GROUPS:
        members = by_group[group]
        median = (
            f"{statistics.median(c.steps[-1].hypothesis.confidence for c in members):.2f}"
            if members
            else "-"
        )
        lines.append(f"- {group}: {_share(len(members), total)}; median confidence {median}")
    lines += [
        "",
        "## finding depth (the NTSB's flagged findings, each at its deepest match)",
        f"flagged {depth.flagged}: found {depth.found}; item right, modifier wrong "
        f"{depth.item_right_modifier_wrong}; category right, item wrong "
        f"{depth.category_right_item_wrong}; category wrong {depth.category_wrong}",
        "",
        "## the model's own words (misses whose NTSB event has a phrase list, "
        "scoring/misses.py:EVENT_PHRASES)",
        f"the model's narrative or cause names the NTSB's defining event: {_share(named, asked)}",
    ]
    return "\n".join(lines)


def churn(a: Sequence[CaseResult], b: Sequence[CaseResult]) -> str:
    """Two runs on the same cases: how many first guesses changed, and top-1 gained and lost."""
    right = {c.case_id: c for c in _scored(b)}
    pairs = [(c, right[c.case_id]) for c in _scored(a) if c.case_id in right]
    same = sum(_guesses(x)[:1] == _guesses(y)[:1] for x, y in pairs)
    gained = sum(bool(x.scores and x.scores.occurrence_top1) and not (y.scores and y.scores.occurrence_top1) for x, y in pairs)
    lost = sum(bool(y.scores and y.scores.occurrence_top1) and not (x.scores and x.scores.occurrence_top1) for x, y in pairs)
    return "\n".join(
        [
            "",
            "## churn against the second run (cases scored in both)",
            f"same first guess: {same} of {len(pairs)}",
            f"top-1 gained {gained}, lost {lost} (this run against the second)",
        ]
    )
```

Replace `main` with this version (the refusals are unchanged and now apply to both runs; `summarise`'s output is unchanged, so S2.6's results file stays reproducible):

```python
def _read_run(run_id: str) -> tuple[RunRecord, list[CaseResult]]:
    """One development arm B run's record and cases, after every refusal."""
    folder = Settings().runs_dir / run_id
    if "heldout" in run_id:
        raise SystemExit(
            f"occurrence_misses: {run_id} is a held-out run; this script reads development "
            "runs only"
        )
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    _refuse_unless_development_arm_b(run_id, record)
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(case.split != "dev" for case in cases):
        raise SystemExit(f"occurrence_misses: {run_id} holds a case outside the dev split")
    return record, cases


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, one run's counts (and churn against a second)."""
    parser = argparse.ArgumentParser(prog="occurrence_misses")
    parser.add_argument("--run", required=True, metavar="RUN_ID")
    parser.add_argument("--against", default=None, metavar="RUN_ID")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    record, cases = _read_run(args.run)
    tables = load_tables()
    text = (
        "occurrence misses (scripts/occurrence_misses.py; counts only, decision 0024)\n"
        + provenance(record).rstrip("\n")
        + "\n\n"
        + summarise(cases, tables)
        + "\n"
        + detail(cases, tables)
    )
    if args.against is not None:
        _other_record, other = _read_run(args.against)
        text += "\n" + churn(cases, other) + f"\nsecond run: {args.against}"
    print(text)
    if args.out is not None:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text + "\n")
    return 0
```

- [ ] **Step 8: Run the tests to verify they pass**

Run: `uv run pytest tests/test_occurrence_misses.py tests/test_misses.py -v`
Expected: PASS

- [ ] **Step 9: Run the full check and commit**

Run: `make check` (Expected: PASS)

```bash
git add src/ntsb_probable_cause/scoring/misses.py scripts/occurrence_misses.py pyproject.toml tests/test_misses.py tests/test_occurrence_misses.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 4: the six miss groups, finding depth, own words and churn"
```

---

### Task 5: The four outcomes from the judge's labels (spec §4.3, decision 0099)

**Files:**
- Create: `scripts/judge_outcomes.py`
- Test: `tests/test_judge_outcomes.py` (create)

**Interfaces:**
- Consumes: a judged run folder holds `judge.jsonl` (rows `case_id, cost_usd, narrative, cause, lay`, written by `ntsb-eval judge`) beside `cases.jsonl`; `scoring.judge.JudgeLabels`.
- Produces: `Outcome = Literal["right", "understood, miscoded", "thin evidence", "misread"]`; `outcome(top1: bool, narrative: str) -> Outcome`; `read_labels(folder: Path) -> dict[str, JudgeLabels]`; `outcomes(cases, labels) -> dict[str, Outcome]`; `shares(name, cases, outs, labels) -> str`; `movement(a: Mapping[str, Outcome], b: Mapping[str, Outcome]) -> tuple[int, int]`; `main(argv) -> int` with `--runs V1 REPEAT V2`, `--label-status {validated,unvalidated}` (default `unvalidated`), `--out`.
- Task 6 consumes `read_labels`; Task 15 runs `main` on each kept round.

**Why "unvalidated" is the default.** Until Task 6's rule passes, the four outcomes carry no claim (decision 0099 item 3); every printed heading says so unless the caller states the label was validated, and Task 7 passes `validated` only when Task 6's results line says it.

- [ ] **Step 1: Write the failing tests** (`tests/test_judge_outcomes.py`)

```python
"""scripts/judge_outcomes.py: the four outcomes and their movement (decision 0099)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest
from scripts import judge_outcomes as jo

from ntsb_probable_cause.scoring.judge import JudgeLabels
from tests.test_occurrence_misses import _SCORES, _case  # the shared CaseResult builders


def _labels(narrative: str, cause: str = "related") -> JudgeLabels:
    return JudgeLabels(narrative=narrative, cause=cause, lay="does_not")


@pytest.mark.parametrize(
    ("top1", "narrative", "expected"),
    [
        (True, "contradicts", "right"),
        (False, "consistent", "understood, miscoded"),
        (False, "less_detailed", "thin evidence"),
        (False, "contradicts", "misread"),
        (False, "adds_unsupported_facts", "misread"),
    ],
)
def test_outcome(top1: bool, narrative: str, expected: str) -> None:
    assert jo.outcome(top1, narrative) == expected


def test_read_labels_reads_judge_rows(tmp_path: Path) -> None:
    rows = [{"case_id": "C1", "cost_usd": 0.001, "narrative": "consistent", "cause": "same_cause", "lay": "does_not"}]
    (tmp_path / "judge.jsonl").write_text("\n".join(json.dumps(r) for r in rows) + "\n")
    assert jo.read_labels(tmp_path) == {"C1": _labels("consistent", "same_cause")}


def test_movement_counts_cases_whose_outcome_changed() -> None:
    a = {"C1": "misread", "C2": "right", "C3": "thin evidence"}
    b = {"C1": "understood, miscoded", "C2": "right"}
    assert jo.movement(a, b) == (1, 2)


def test_shares_says_unvalidated_and_splits_fatal() -> None:
    right = _case("C1", ("452240",), ("452240",)).model_copy(
        update={"fatal": True, "scores": replace(_SCORES, occurrence_top1=True)}
    )
    wrong = _case("C2", ("452240",), ("452241",))
    cases = [right, wrong]
    labels = {"C1": _labels("consistent"), "C2": _labels("contradicts")}
    outs = jo.outcomes(cases, labels)
    assert outs == {"C1": "right", "C2": "misread"}
    text = jo.shares("B-v1", cases, outs, labels, status="unvalidated")
    assert "unvalidated" in text
    assert "misread: 1 of 2" in text
    assert "fatal (1 cases):" in text
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_judge_outcomes.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `scripts/judge_outcomes.py`**

```python
"""The four outcomes from the judge's labels, per run, and how they move between runs.

Status
    Live for S2.7 (spec §4.3, decision 0099), free: reads judge.jsonl and cases.jsonl from
    judged development run folders; counts only. Round 0 runs it on B-v1, its repeat and B-v2;
    each kept guidance round runs it again.

Why
    A miss is either "understood, miscoded" (guidance can fix it) or "misread"/"thin evidence"
    (reading better can). The judge's narrative label separates them, once validated by Andy's
    hand-read (scripts/round0_handread.py); until then every heading says "unvalidated".

Usage
    uv run python -m scripts.judge_outcomes --runs V1 REPEAT V2 [--label-status validated] [--out PATH]
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Literal

from ntsb_probable_cause.scoring.judge import JudgeLabels
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.settings import Settings

Outcome = Literal["right", "understood, miscoded", "thin evidence", "misread"]
OUTCOMES: tuple[Outcome, ...] = ("right", "understood, miscoded", "thin evidence", "misread")
JUDGE_FILE = "judge.jsonl"


def outcome(top1: bool, narrative: str) -> Outcome:
    """Decision 0099 item 1."""
    if top1:
        return "right"
    if narrative == "consistent":
        return "understood, miscoded"
    if narrative == "less_detailed":
        return "thin evidence"
    return "misread"


def read_labels(folder: Path) -> dict[str, JudgeLabels]:
    """A judged run's labels by case id."""
    labels: dict[str, JudgeLabels] = {}
    for line in (folder / JUDGE_FILE).read_text().splitlines():
        if line:
            row = json.loads(line)
            labels[row.pop("case_id")] = JudgeLabels.model_validate(
                {k: v for k, v in row.items() if k != "cost_usd"}
            )
    return labels


def outcomes(cases: Sequence[CaseResult], labels: Mapping[str, JudgeLabels]) -> dict[str, Outcome]:
    """Each judged, scored case's outcome."""
    return {
        c.case_id: outcome(c.scores.occurrence_top1, labels[c.case_id].narrative)
        for c in cases
        if c.scores is not None and c.case_id in labels
    }


def _block(title: str, ids: Sequence[str], outs: Mapping[str, Outcome], labels: Mapping[str, JudgeLabels]) -> list[str]:
    counts = Counter(outs[i] for i in ids)
    lines = [f"{title} ({len(ids)} cases):"]
    for name in OUTCOMES:
        causes = Counter(labels[i].cause for i in ids if outs[i] == name)
        cause_text = ", ".join(f"{k} {v}" for k, v in sorted(causes.items()))
        lines.append(f"  {name}: {counts[name]} of {len(ids)}; cause label: {cause_text or '-'}")
    return lines


def shares(
    name: str,
    cases: Sequence[CaseResult],
    outs: Mapping[str, Outcome],
    labels: Mapping[str, JudgeLabels],
    *,
    status: str,
) -> str:
    """One run's outcome shares, all cases and fatal / non-fatal."""
    judged = [c for c in cases if c.case_id in outs]
    lines = [f"## {name} -- outcomes ({status} narrative label, decision 0099)"]
    lines += _block("all", [c.case_id for c in judged], outs, labels)
    lines += _block("fatal", [c.case_id for c in judged if c.fatal], outs, labels)
    lines += _block("non-fatal", [c.case_id for c in judged if not c.fatal], outs, labels)
    return "\n".join(lines)


def movement(a: Mapping[str, Outcome], b: Mapping[str, Outcome]) -> tuple[int, int]:
    """(cases whose outcome differs, cases judged in both)."""
    shared = sorted(set(a) & set(b))
    return sum(a[i] != b[i] for i in shared), len(shared)


def _load(settings: Settings, run_id: str) -> tuple[list[CaseResult], dict[str, JudgeLabels]]:
    if "heldout" in run_id:
        raise SystemExit(f"judge_outcomes: {run_id} is a held-out run; development runs only")
    folder = settings.runs_dir / run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        raise SystemExit(f"judge_outcomes: {run_id} holds a case outside the dev split")
    return cases, read_labels(folder)


def main(argv: Sequence[str] | None = None) -> int:
    """Print each run's outcomes, then v1 against v2 and v1 against its repeat."""
    parser = argparse.ArgumentParser(prog="judge_outcomes")
    parser.add_argument("--runs", nargs="+", required=True, metavar="RUN_ID")
    parser.add_argument("--label-status", choices=("validated", "unvalidated"), default="unvalidated")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    loaded = [(run_id, *_load(settings, run_id)) for run_id in args.runs]
    per_run = [(run_id, cases, labels, outcomes(cases, labels)) for run_id, cases, labels in loaded]
    parts = [
        "judge outcomes (scripts/judge_outcomes.py; counts only, decision 0099)",
        *(shares(r, c, o, lab, status=args.label_status) for r, c, lab, o in per_run),
    ]
    if len(per_run) == 3:
        v1, repeat, v2 = (p[3] for p in per_run)
        moved_repeat, n_repeat = movement(v1, repeat)
        moved_v2, n_v2 = movement(v1, v2)
        parts += [
            "## movement between runs (label churn is the repeat's movement)",
            f"v1 against its repeat: {moved_repeat} of {n_repeat} cases change outcome",
            f"v1 against v2: {moved_v2} of {n_v2} cases change outcome",
        ]
    text = "\n\n".join(parts)
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_judge_outcomes.py -v`
Expected: PASS

- [ ] **Step 5: Run the full check and commit**

Run: `make check` (Expected: PASS)

```bash
git add scripts/judge_outcomes.py tests/test_judge_outcomes.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 5: the judge's four outcomes and their movement between runs"
```

---

### Task 6: Andy's hand-read, which validates the narrative label (spec §4.4, decision 0099 item 3; W7)

**Files:**
- Create: `scripts/round0_handread.py`
- Modify: `Makefile`
- Test: `tests/test_round0_handread.py` (create)

**Interfaces:**
- Consumes: `misses.miss_group`, `misses.MISS_GROUPS` (Task 4); `judge_outcomes.read_labels` (Task 5); `scripts.marking_page.Card`, `Choice`, `render`, `read_marks`; `samples.load_cases`; `records.split.split_record`; `codes.load_tables`.
- Produces: `SEED = 20260927`, `PER_GROUP = 8`, `HITS = 10`, `FOLDER = Path("handcheck") / "s27-round0"`; `draw_cards(cases, *, seed) -> list[tuple[str, str]]` (case id, group); `score(sheet, marks, labels) -> str`; `main(argv)` with subcommands `cards --run RUN_ID` and `score MARKS_CSV --run RUN_ID [--out PATH]`.

**What Andy sees.** One card per case: on the left, the model's evidence narrative and its first occurrence code with the code's words; on the right, the NTSB's probable-cause sentence and its defining code with the code's words; under the card, collapsed, the factual narrative for when he cannot tell without it. No case number, no docket. Two questions: *does the model's account contain the fact the NTSB's cause rests on?* (yes / no / can't tell) and, on misses only, *why did it miss?* (coding convention / wrong phase / misread or missing fact / NTSB code arguable / other). Example of a "yes" on a miss: the model's account says "the airplane stalled during a steep turn at low altitude and descended into trees", the NTSB's cause says "the pilot's failure to maintain airspeed during a low-altitude turn, which resulted in an aerodynamic stall", and the codes differ only because the NTSB flagged loss of control as defining — the fact is there, the code is the miss, so question 2 is "coding convention". The judge's label is never on the page.

- [ ] **Step 1: Write the failing tests** (`tests/test_round0_handread.py`)

```python
"""scripts/round0_handread.py: the cards, and the narrative-label validation (decision 0099)."""

import pytest
from scripts import round0_handread as rh

from ntsb_probable_cause.scoring.judge import JudgeLabels
from tests.test_occurrence_misses import _case


def _cases() -> list:
    cases = [_case(f"X{i:02d}", ("452240",), ("452240",)) for i in range(12)]  # hits
    cases += [_case(f"W{i:02d}", ("452240",), ("450240",)) for i in range(9)]  # right event, wrong phase
    cases += [_case(f"S{i:02d}", ("452240", "452241"), ("452241",)) for i in range(3)]  # in sequence
    return cases


def test_draw_cards_takes_eight_per_miss_group_or_all_and_ten_hits() -> None:
    drawn = rh.draw_cards(_cases(), seed=1)
    groups = [g for _id, g in drawn]
    assert groups.count("exact") == 10
    assert groups.count("right event, wrong phase") == 8
    assert groups.count("in sequence, not defining") == 3  # fewer than 8: all (plan W7)
    assert rh.draw_cards(_cases(), seed=1) == drawn


def _sheet(rows: list[tuple[str, str]]) -> list[dict[str, str]]:
    return [{"row": str(n), "case_id": c, "group": g} for n, (c, g) in enumerate(rows, start=1)]


def _labels(narratives: dict[str, str]) -> dict[str, JudgeLabels]:
    return {c: JudgeLabels(narrative=n, cause="related", lay="does_not") for c, n in narratives.items()}


def test_score_validates_at_75_percent_with_errors_both_ways() -> None:
    sheet = _sheet([(f"C{i}", "nothing in common") for i in range(8)])
    # Andy: yes on C0-C3, no on C4-C7. Judge: consistent on C0-C2 and C4 (one generous error),
    # not consistent on C3 (one harsh error) and C5-C7: 6 of 8 agree = 75%.
    marks = {n: {"key fact": "yes" if n <= 4 else "no", "why": "coding convention"} for n in range(1, 9)}
    labels = _labels({"C0": "consistent", "C1": "consistent", "C2": "consistent", "C3": "contradicts",
                      "C4": "consistent", "C5": "less_detailed", "C6": "contradicts", "C7": "contradicts"})
    text = rh.score(sheet, marks, labels)
    assert "agreement: 6 of 8" in text
    assert "outcome: validated" in text


def test_score_is_not_validated_when_errors_run_one_way() -> None:
    sheet = _sheet([(f"C{i}", "nothing in common") for i in range(4)])
    marks = {n: {"key fact": "yes", "why": "other"} for n in range(1, 5)}
    labels = _labels({"C0": "consistent", "C1": "consistent", "C2": "consistent", "C3": "contradicts"})
    text = rh.score(sheet, marks, labels)
    assert "outcome: not validated" in text


def test_score_refuses_an_unmarked_card() -> None:
    sheet = _sheet([("C0", "nothing in common")])
    with pytest.raises(SystemExit, match="unmarked"):
        rh.score(sheet, {1: {"key fact": "", "why": ""}}, _labels({"C0": "consistent"}))


def test_cards_refuses_a_held_out_run(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    with pytest.raises(SystemExit, match="development"):
        rh.main(["cards", "--run", "20260926T000000-abc1234-heldout-400-B"])
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_round0_handread.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `scripts/round0_handread.py`**

```python
"""Andy's Round 0 hand-read: about 50 cards, and the narrative-label validation.

Status
    Live for S2.7 (spec §4.4, decision 0099 item 3), free. ``cards`` draws a seeded sample from
    one development run (8 per miss group, or all of a smaller group, and 10 hits) and writes a
    private marking page under data/handcheck/s27-round0/; ``score`` reads Andy's marks and the
    judge's labels and prints counts only.

Why
    The judge's narrative label separates "understood, miscoded" from "misread" but was never
    validated. Andy judges whether the model's account holds the key fact; the rule, fixed in
    advance, compares that with the label. His second answer says why each miss happened.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.round0_handread cards --run RUN_ID
    NTSB_DATA_DIR=... uv run python -m scripts.round0_handread score MARKS.csv --run RUN_ID [--out PATH]
"""

import argparse
import csv
import html
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path

from scripts import marking_page
from scripts.judge_outcomes import read_labels

from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.judge import JudgeLabels
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.misses import MISS_GROUPS, miss_group
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.settings import Settings

SEED = 20260927
PER_GROUP = 8
HITS = 10
FOLDER = Path("handcheck") / "s27-round0"
KEY_FACT = ("yes", "no", "can't tell")
WHY = ("coding convention", "wrong phase", "misread or missing fact", "NTSB code arguable", "other")
# Decision 0099 item 3: validated at 75% agreement on decidable cards, errors both ways.
MIN_AGREEMENT = Fraction(3, 4)


def _guesses(case: CaseResult) -> tuple[str, ...]:
    return tuple(g.phase + g.event for g in case.steps[-1].hypothesis.occurrence)


def draw_cards(cases: Sequence[CaseResult], *, seed: int) -> list[tuple[str, str]]:
    """(case id, group): ``PER_GROUP`` per miss group (all of a smaller one) and ``HITS`` hits."""
    rng = random.Random(seed)  # noqa: S311 -- reproducible sampling, not security
    by_group: dict[str, list[str]] = {}
    for case in sorted((c for c in cases if c.scores is not None and c.steps), key=lambda c: c.case_id):
        group = miss_group(_guesses(case), case.verdict_occurrence, abstain=case.steps[-1].hypothesis.abstain)
        by_group.setdefault(group, []).append(case.case_id)
    drawn: list[tuple[str, str]] = []
    for group, size in (("exact", HITS), *((g, PER_GROUP) for g in MISS_GROUPS)):
        members = by_group.get(group, [])
        chosen = members if len(members) <= size else rng.sample(members, size)
        drawn.extend((case_id, group) for case_id in sorted(chosen))
    rng.shuffle(drawn)
    return drawn


def _code_words(code: str, tables: CodeTables) -> str:
    return f"{code} ({tables.phases.get(code[:3], '?')} / {tables.events.get(code[3:], '?')})"


def _card(row: int, case: CaseResult, raw: Mapping[str, object], group: str, tables: CodeTables) -> marking_page.Card:
    _evidence, synthesis, verdict = split_record(raw)
    hypothesis = case.steps[-1].hypothesis
    first = _guesses(case)[0]
    defining = case.verdict_occurrence[0] if case.verdict_occurrence else ""
    body = (
        "<div class='pair'>"
        f"<div><h4>The model's account</h4><p>{html.escape(hypothesis.evidence_narrative)}</p>"
        f"<p><b>Its first code:</b> {html.escape(_code_words(first, tables))}</p></div>"
        f"<div><h4>The NTSB's probable cause</h4><p>{html.escape(verdict.probable_cause or '(none)')}</p>"
        f"<p><b>Its defining code:</b> {html.escape(_code_words(defining, tables))}</p></div>"
        "</div>"
        "<details><summary>The investigators' factual narrative (open only if needed)</summary>"
        f"<p>{html.escape(synthesis.factual_narrative or '(none)')}</p></details>"
    )
    choices = [marking_page.Choice("key fact", KEY_FACT)]
    if group != "exact":
        choices.append(marking_page.Choice("why", WHY))
    return marking_page.Card(row=row, body_html=body, choices=tuple(choices), text_fields=(("notes", ""),))


def _run(settings: Settings, run_id: str) -> list[CaseResult]:
    if "heldout" in run_id or "-dev-" not in run_id:
        raise SystemExit(f"round0_handread: {run_id} is not a development run; development runs only")
    cases = read_jsonl(settings.runs_dir / run_id / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        raise SystemExit(f"round0_handread: {run_id} holds a case outside the dev split")
    return cases


def cmd_cards(settings: Settings, run_id: str) -> str:
    """Write the private page and sheet; return a one-line summary."""
    cases = {c.case_id: c for c in _run(settings, run_id)}
    drawn = draw_cards(list(cases.values()), seed=SEED)
    raws = samples.load_cases(settings.data_dir / "processed", [c for c, _g in drawn])
    tables = load_tables()
    cards = [_card(n, cases[c], raw, g, tables) for n, ((c, g), raw) in enumerate(zip(drawn, raws, strict=True), start=1)]
    folder = settings.data_dir / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    intro = (
        "<p>Each card: the model's account and first code beside the NTSB's probable cause and "
        "defining code. Question 1: does the model's account contain the fact the NTSB's cause "
        "rests on? Question 2 (misses only): why did it miss? Open the factual narrative only "
        "when you cannot tell without it.</p>"
    )
    (folder / "index.html").write_text(
        marking_page.render(title="S2.7 Round 0 hand-read", intro_html=intro, cards=cards,
                            storage_key="s27-round0-handread", csv_name="s27-round0-marks.csv")
    )
    with (folder / "sheet.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["row", "case_id", "group"])
        writer.writerows((n, c, g) for n, (c, g) in enumerate(drawn, start=1))
    counts = Counter(g for _c, g in drawn)
    return f"{len(drawn)} cards written to {folder}: " + ", ".join(f"{g} {n}" for g, n in counts.items())


def score(sheet: Sequence[Mapping[str, str]], marks: Mapping[int, Mapping[str, str]], labels: Mapping[str, JudgeLabels]) -> str:
    """The validation rule and the miss types, counts only."""
    unmarked = [r["row"] for r in sheet if not marks.get(int(r["row"]), {}).get("key fact")]
    if unmarked:
        raise SystemExit(f"round0_handread: {len(unmarked)} unmarked cards, e.g. row {unmarked[0]}")
    agree = generous = harsh = decidable = 0
    why: Counter[str] = Counter()
    cards_by_group = Counter(r["group"] for r in sheet)
    for row in sheet:
        mark = marks[int(row["row"])]
        if row["group"] != "exact" and mark.get("why"):
            why[mark["why"]] += 1
        andy = mark["key fact"]
        if andy == "can't tell":
            continue
        decidable += 1
        judge_yes = labels[row["case_id"]].narrative == "consistent"
        andy_yes = andy == "yes"
        agree += judge_yes == andy_yes
        generous += judge_yes and not andy_yes
        harsh += andy_yes and not judge_yes
    share = Fraction(agree, decidable) if decidable else Fraction(0)
    validated = decidable > 0 and share >= MIN_AGREEMENT and generous >= 1 and harsh >= 1
    low, high = wilson(agree, decidable) if decidable else (0.0, 0.0)
    lines = [
        "Round 0 hand-read (scripts/round0_handread.py; counts only, decision 0099)",
        "cards by group: " + ", ".join(f"{g} {n}" for g, n in sorted(cards_by_group.items())),
        f"decidable cards (not \"can't tell\"): {decidable} of {len(sheet)}",
        f"agreement: {agree} of {decidable} ({float(share):.1%} [{low:.1%}, {high:.1%}]); rule: at least 75%",
        f"judge errors: generous (judge consistent, Andy no) {generous}; harsh (judge not consistent, Andy yes) {harsh}; rule: at least 1 each way",
        f"outcome: {'validated' if validated else 'not validated'}",
        "why the misses happened (Andy): " + ", ".join(f"{w} {why[w]}" for w in WHY),
    ]
    return "\n".join(lines)


def main(argv: Sequence[str] | None = None) -> int:
    """``cards`` or ``score``."""
    parser = argparse.ArgumentParser(prog="round0_handread")
    commands = parser.add_subparsers(dest="command", required=True)
    cards_p = commands.add_parser("cards")
    cards_p.add_argument("--run", required=True)
    score_p = commands.add_parser("score")
    score_p.add_argument("marks", type=Path)
    score_p.add_argument("--run", required=True)
    score_p.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "cards":
        print(cmd_cards(settings, args.run))
        return 0
    _run(settings, args.run)
    with (settings.data_dir / FOLDER / "sheet.csv").open(newline="") as handle:
        sheet = list(csv.DictReader(handle))
    text = score(sheet, marking_page.read_marks(args.marks), read_labels(settings.runs_dir / args.run))
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

(`metrics.wilson(successes, n)` returns the interval as a pair of floats; if it returns a triple, unpack accordingly.)

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_round0_handread.py -v`
Expected: PASS

- [ ] **Step 5: Add the Makefile targets, run the full check, commit**

```make
s27-round0-cards:
	$(if $(RUN),,$(error RUN is required: the B-v1 run id))
	uv run python -m scripts.round0_handread cards --run $(RUN)
# S2.7 spec §4.4, free: writes Andy's private marking page under data/handcheck/s27-round0/.
```

Run: `make check` (Expected: PASS)

```bash
git add scripts/round0_handread.py tests/test_round0_handread.py Makefile docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 6: Round 0's hand-read cards and the narrative-label validation"
```

---

### Task 7: Round 0's runs and its results file (spec §4.2–§4.5; W4)

**Files:**
- Modify: `Makefile`
- Create (by running): `docs/results/s27-round0-dev.txt`

**Interfaces:**
- Consumes: Tasks 1, 4, 5, 6; `ntsb-eval run`, `ntsb-eval judge`.
- Produces: the noise-floor run id (written into this step's Deviations entry and read by Tasks 10–15 as `REPEAT`); `docs/results/s27-round0-dev.txt`.

The two S2.6 runs are `20260926T082427-d19aafa-dev-400-B` (B-v1) and `20260926T085904-d19aafa-dev-400-B` (B-v2).

- [ ] **Step 1: Add the targets**

```make
s27-noise-floor:
	$(if $(PER_CASE),,$(error PER_CASE is required: B-v1's cost per case rounded up, e.g. PER_CASE=0.0042))
	uv run python -m scripts.stage_spend --estimate 1.40
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version v1 --expected-cost-per-case-usd $(PER_CASE)
# S2.7 spec §4.2, paid (about $1.18, B-v1's cost): B-v1 again, identical settings, at S2.7's
# commit. The noise floor every round is read against.

s27-judge:
	$(if $(RUN),,$(error RUN is required: a development run id to judge))
	uv run python -m scripts.stage_spend --estimate 0.60
	uv run ntsb-eval judge $(RUN)
# S2.7 spec §4.3, paid (about $0.50 at the judge's conservative $0.00125 a case; standard
# price only): writes judge.jsonl into the run's folder and a <run>-judge cost row.

s27-round0-results:
	$(if $(REPEAT),,$(error REPEAT is required: the noise-floor run id))
	$(if $(MARKS),,$(error MARKS is required: Andy's downloaded marks CSV))
	$(if $(LABELS),,$(error LABELS is required: validated or unvalidated, from the score line))
	{ uv run python -m scripts.occurrence_misses --run 20260926T082427-d19aafa-dev-400-B --against $(REPEAT); \
	  echo; uv run python -m scripts.occurrence_misses --run 20260926T085904-d19aafa-dev-400-B --against 20260926T082427-d19aafa-dev-400-B; \
	  echo; uv run python -m scripts.occurrence_misses --run $(REPEAT); \
	  echo; uv run ntsb-eval report 20260926T082427-d19aafa-dev-400-B --against $(REPEAT); \
	  echo; uv run python -m scripts.judge_outcomes --runs 20260926T082427-d19aafa-dev-400-B $(REPEAT) 20260926T085904-d19aafa-dev-400-B --label-status $(LABELS); \
	  echo; uv run python -m scripts.round0_handread score $(MARKS) --run 20260926T082427-d19aafa-dev-400-B; } > docs/results/s27-round0-dev.txt
# S2.7 spec §4.5, free: Round 0's results file from committed scripts only.
```

Commit the Makefile (`S2.7 Task 7: Round 0 targets`).

- [ ] **Step 2: Check the S2.6 run folders hold no judge rows (W4)**

Run:
```bash
export NTSB_DATA_DIR=/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data
ls "$NTSB_DATA_DIR"/runs/20260926T082427-d19aafa-dev-400-B/ "$NTSB_DATA_DIR"/runs/20260926T085904-d19aafa-dev-400-B/
```
Expected: no `judge.jsonl` in either. If one exists, copy it to `$NTSB_DATA_DIR/s27/judge-before/<run id>.jsonl` before Step 4 and log it in Deviations.

- [ ] **Step 3: STOP — the noise-floor run (paid, about $1.18)**

Hand Andy: "Round 0's noise floor: B-v1 again on dev-400, identical settings, about $1.18 and 30–60 minutes on batch; start between 01:00 and 12:00 UTC. From the worktree, with the keys exported from `pass`: `make s27-noise-floor PER_CASE=0.0042`. Afterwards the tree is unchanged (development runs write no ledger row)." Record the printed run id in Deviations as `REPEAT`.

- [ ] **Step 4: STOP — the judge on three runs (paid, about $1.50)**

Hand Andy: "`make s27-judge RUN=20260926T082427-d19aafa-dev-400-B`, then `RUN=<REPEAT>`, then `RUN=20260926T085904-d19aafa-dev-400-B`; about $0.50 each, a few minutes each at the standard price." After each, read the printed `judge cost` line.

- [ ] **Step 5: Build the cards** (free)

Run: `make s27-round0-cards RUN=20260926T082427-d19aafa-dev-400-B`
Expected: about 50 cards; the printed group counts (a group under 8 is taken whole, W7).

- [ ] **Step 6: STOP — Andy's hand-read**

Hand Andy: "Open `$NTSB_DATA_DIR/handcheck/s27-round0/index.html`, mark every card (two clicks each, about an hour; it keeps progress), then download the marks CSV." When it is back:

Run: `uv run python -m scripts.round0_handread score <marks.csv> --run 20260926T082427-d19aafa-dev-400-B`
Read the `outcome:` line: `validated` or `not validated`.

- [ ] **Step 7: Write the results file** (free)

Run: `make s27-round0-results REPEAT=<REPEAT> MARKS=<marks.csv> LABELS=<validated|unvalidated>`
Expected: `docs/results/s27-round0-dev.txt` holds, in order, the misses and churn for B-v1 (against the repeat), B-v2 (against B-v1) and the repeat; the noise floor (`report --against`); the four outcomes with their movement; the hand-read's counts. Check that it names no case number: `grep -E '[A-Z]{3}[0-9]{2}[A-Z]{2}[0-9]{3}' docs/results/s27-round0-dev.txt` prints nothing.

- [ ] **Step 8: Commit, and report Round 0 to Andy**

```bash
git add docs/results/s27-round0-dev.txt docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 7: Round 0's results"
```

Report to Andy in plain English: the six groups' sizes, the noise floor (the paired top-1 difference of the two B-v1 runs and the churn), whether the narrative label was validated, the four outcomes, what transcription changed beyond label churn, and which miss group is largest and fixable — which sets the first guidance round (Task 15).

---

## Part C — Round 1: the ordering check (spec §5, decisions 0096, 0097)

### Task 8: The ordering check's pure parts (spec §5.1–§5.3, decision 0096)

**Files:**
- Create: `src/ntsb_probable_cause/scoring/ordering.py`
- Modify: `pyproject.toml` (import-linter source list: add `ntsb_probable_cause.scoring.ordering`)
- Test: `tests/test_ordering.py` (create)

**Interfaces:**
- Consumes: `coding_stats.CodingStats`, `NO_GROUP` (Task 3); `hypothesis.Hypothesis`, `OccurrenceGuess`; `codes.CodeTables`; `errors.SchemaError`.
- Produces: constants `MAX_CANDIDATES = 8`, `LINK_MIN_SHARE = Fraction(1, 4)`, `LINK_MIN_CASES = 20`, `GROUP_CODES = 2`, `PHASE_VARIANT_MIN_CASES = 10`, `RULE_MIN_CASES = 20`; `candidates(guesses: Sequence[str], group: str | None, stats: CodingStats) -> tuple[str, ...]`; `plain_rule(guesses, group, stats) -> tuple[str, ...]`; `CHECK_SYSTEM: str`; `RANKING_SCHEMA: dict[str, object]`; `check_text(guesses, options, group, narrative, stats, tables) -> str`; `parse_ranking(content: str, options: Sequence[str]) -> tuple[str, ...]`; `JEV_INSTRUCTIONS: str`; `jev_question(options, tables) -> dict[str, object]`; `ranking_from_probabilities(probabilities: Mapping[str, float]) -> tuple[str, ...]`; `reorder(hypothesis: Hypothesis, ranking: Sequence[str]) -> Hypothesis`.
- Task 10 consumes all of them.

**An example of the candidate list.** The model guessed `(452241, 452470, 450241)` — stall/spin at low altitude first — and the phase group is `Maneuvering`. The list starts with those three. If the pool shows that when `452241` appears, `452240` (loss of control in flight) is defining in at least a quarter of at least 20 cases, `452240` joins as a **linked code**. The two commonest defining codes for `Maneuvering` join as **group codes**. For every code so far, the same event under another prefix the pool uses for `Maneuvering` (for example `450` or `452`) joins as a **phase variant** if the pool shows it as defining in that group at least 10 times. Duplicates go; the guesses stay first; the rest are ordered by how often the pool flags them as defining; the list is cut at eight.

- [ ] **Step 1: Write the failing tests** (`tests/test_ordering.py`)

```python
"""scoring/ordering.py: the candidate list, the plain rule, the check text and reply (0096)."""

import json

import pytest

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import PoolCase, build
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring import ordering

LOC, STALL, LOC_450, CFIT = "452240", "452241", "450240", "452470"


def _stats():
    cases = (
        [PoolCase(2012, "Maneuvering", (LOC, STALL))] * 30  # stall appears: LOC defining 30 times
        + [PoolCase(2016, "Maneuvering", (STALL, LOC))] * 5  # ... stall defining 5 times
        + [PoolCase(2013, "Maneuvering", (LOC_450,))] * 12  # the 450 phase variant, 12 times
        + [PoolCase(2014, "Maneuvering", (CFIT,))] * 3
        + [PoolCase(2015, "Landing", ("552300",))] * 40
    )
    return build(cases, built_from="test")


def test_candidates_are_guesses_then_linked_group_and_phase_variants() -> None:
    options = ordering.candidates((STALL, CFIT), "Maneuvering", _stats())
    assert options[:2] == (STALL, CFIT)
    assert LOC in options  # linked (30 of 35) and a group code
    assert LOC_450 in options  # phase variant of LOC in Maneuvering (12 >= 10)
    assert len(options) == len(set(options)) <= ordering.MAX_CANDIDATES


def test_candidates_without_a_group_still_start_with_the_guesses() -> None:
    options = ordering.candidates(("552300",), None, _stats())
    assert options[0] == "552300"


def test_plain_rule_moves_the_pools_defining_code_first() -> None:
    assert ordering.plain_rule((STALL, CFIT), "Maneuvering", _stats()) == (LOC, STALL, CFIT)


def test_plain_rule_keeps_the_first_guess_on_thin_counts() -> None:
    assert ordering.plain_rule(("999999",), "Maneuvering", _stats())[0] == "999999"


def test_plain_rule_keeps_the_models_phase_on_a_tie() -> None:
    ranking = ordering.plain_rule((LOC,), "Maneuvering", _stats())
    assert ranking[0] == LOC  # 452 defining 30 times, 450 12 times: 452 stays


def test_check_text_holds_codes_counts_group_and_narrative_only() -> None:
    options = ordering.candidates((STALL,), "Maneuvering", _stats())
    text = ordering.check_text((STALL,), options, "Maneuvering", "The airplane stalled.", _stats(), load_tables())
    assert "Maneuvering" in text
    assert "The airplane stalled." in text
    assert STALL in text and LOC in text
    assert "defining in 30 of 35" in text


def test_parse_ranking_accepts_listed_codes_only() -> None:
    options = (STALL, LOC, CFIT)
    assert ordering.parse_ranking(json.dumps({"ranking": [LOC, STALL]}), options) == (LOC, STALL)
    with pytest.raises(SchemaError):
        ordering.parse_ranking(json.dumps({"ranking": ["111111"]}), options)
    with pytest.raises(SchemaError):
        ordering.parse_ranking(json.dumps({"ranking": [LOC, LOC]}), options)
    with pytest.raises(SchemaError):
        ordering.parse_ranking("not json", options)


def test_jev_question_and_ranking() -> None:
    question = ordering.jev_question((STALL, LOC), load_tables())
    assert question["type"] == "choice"
    assert set(question["criteria"]) == {STALL, LOC}
    assert ordering.ranking_from_probabilities({STALL: 0.2, LOC: 0.7, CFIT: 0.2}) == (LOC, CFIT, STALL)


def test_reorder_keeps_known_probabilities_and_gives_new_codes_zero() -> None:
    hypothesis = Hypothesis(
        evidence_narrative="n",
        occurrence=(OccurrenceGuess(phase="452", event="241", probability=0.6),),
        findings=(),
        probable_cause="p",
        lay_explanation="l",
        confidence=0.5,
        abstain=False,
        evidence_used=(),
    )
    out = ordering.reorder(hypothesis, (LOC, STALL))
    assert [(g.phase + g.event, g.probability) for g in out.occurrence] == [(LOC, 0.0), (STALL, 0.6)]
    assert out.evidence_narrative == "n"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_ordering.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `scoring/ordering.py`**

```python
"""The ordering check's pure parts (decision 0096; S2.7 spec §5).

The check takes a finished answer and re-orders its occurrence codes, choosing which code the
NTSB would flag as the defining event. It sees the model's guesses, a candidate list, the pool's
counts for those candidates (decision 0094), the phase group already given as evidence, and the
model's own narrative -- never the verdict, the synthesis or the docket. Every threshold here was
fixed in decision 0096 before any count was computed.
"""

import json
from collections.abc import Mapping, Sequence
from fractions import Fraction

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import NO_GROUP, CodingStats
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess

MAX_CANDIDATES = 8
LINK_MIN_SHARE = Fraction(1, 4)
LINK_MIN_CASES = 20
GROUP_CODES = 2
PHASE_VARIANT_MIN_CASES = 10
RULE_MIN_CASES = 20


def candidates(guesses: Sequence[str], group: str | None, stats: CodingStats) -> tuple[str, ...]:
    """The codes the check may choose among (decision 0096 item 3)."""
    name = group or NO_GROUP
    first = list(dict.fromkeys(guesses))
    extra: set[str] = set()
    for guess in first:
        n = stats.present_n(guess)
        if n >= LINK_MIN_CASES:
            extra.update(d for d, k in stats.defining_given(guess).items() if Fraction(k, n) >= LINK_MIN_SHARE)
    extra.update(stats.group_top(name, GROUP_CODES))
    phases = stats.group_phases(name)
    for code in sorted(set(first) | extra):
        for phase in phases:
            variant = phase + code[3:]
            if variant != code and stats.group_defining_n(name, variant) >= PHASE_VARIANT_MIN_CASES:
                extra.add(variant)
    rest = sorted(extra - set(first), key=lambda c: (-stats.defining_n(c), c))
    return tuple((first + rest)[:MAX_CANDIDATES])


def plain_rule(guesses: Sequence[str], group: str | None, stats: CodingStats) -> tuple[str, ...]:
    """The free way (spec §5.3 item 2): the pool's defining code, then its commonest phase."""
    chosen = guesses[0]
    if stats.present_n(chosen) >= RULE_MIN_CASES:
        given = stats.defining_given(chosen)
        options = candidates(guesses, group, stats)
        best = max(options, key=lambda c: (given.get(c, 0), -options.index(c)))
        if given.get(best, 0) > 0:
            chosen = best
    name = group or NO_GROUP
    by_phase = {p: stats.group_defining_n(name, p + chosen[3:]) for p in stats.group_phases(name)}
    top = max(by_phase.values(), default=0)
    if top > 0 and by_phase.get(chosen[:3], 0) < top:
        chosen = min(p for p, k in by_phase.items() if k == top) + chosen[3:]
    return tuple(dict.fromkeys((chosen, *guesses)))[:3]


CHECK_SYSTEM = """You are checking how the NTSB would code an accident that an analyst has \
already studied. The NTSB records each accident as an ordered sequence of occurrence codes and \
flags one of them as the defining event. You are given the analyst's own account of the \
evidence, the phase-of-flight group recorded as evidence, the analyst's first guesses, and a \
short list of candidate codes, each with how often the NTSB flagged it as the defining event in \
past cases. Past habits are a guide, not a rule: prefer the candidate the analyst's account \
supports. Rank the three candidates the NTSB would most likely flag as the defining event, most \
likely first. Choose only from the candidate list and copy each six-digit code exactly. Reply \
only with JSON matching the schema."""

RANKING_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "ranking": {
            "type": "array",
            "items": {"type": "string", "pattern": "^[0-9]{6}$"},
            "minItems": 1,
            "maxItems": 3,
        }
    },
    "required": ["ranking"],
    "additionalProperties": False,
}


def _words(code: str, tables: CodeTables) -> str:
    return f"{tables.phases.get(code[:3], '?')} / {tables.events.get(code[3:], '?')}"


def check_text(
    guesses: Sequence[str],
    options: Sequence[str],
    group: str | None,
    narrative: str,
    stats: CodingStats,
    tables: CodeTables,
) -> str:
    """The text the model-asked ways receive: codes, counts, the group and the narrative."""
    name = group or NO_GROUP
    lines = [f"Phase-of-flight group recorded as evidence: {group or 'not recorded'}", ""]
    lines.append("The analyst's guesses, in order: " + ", ".join(f"{g} ({_words(g, tables)})" for g in guesses))
    lines += ["", "Candidate codes:"]
    for code in options:
        n = stats.present_n(code)
        k = stats.defining_given(code).get(code, 0)
        lines.append(
            f"- {code} ({_words(code, tables)}): when it appears in a past case, defining in {k} of {n}; "
            f"defining in this phase group in {stats.group_defining_n(name, code)} past cases"
        )
        if code != guesses[0]:
            pair = stats.pair(code, guesses[0])
            if pair["both"]:
                lines.append(
                    f"  when it and {guesses[0]} both appear ({pair['both']} past cases): "
                    f"{code} defining in {pair.get(code, 0)}, {guesses[0]} defining in {pair.get(guesses[0], 0)}"
                )
    lines += ["", "The analyst's own account of the evidence:", narrative]
    return "\n".join(lines)


def parse_ranking(content: str, options: Sequence[str]) -> tuple[str, ...]:
    """The ranking, if every code is a listed candidate and none repeats; else ``SchemaError``."""
    try:
        ranking = json.loads(content)["ranking"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SchemaError(f"ranking reply is not the schema's JSON: {error}") from error
    if not isinstance(ranking, list) or not 1 <= len(ranking) <= 3:
        raise SchemaError("ranking must list one to three codes")
    codes = tuple(str(code) for code in ranking)
    if len(set(codes)) != len(codes):
        raise SchemaError(f"ranking repeats a code: {codes}")
    outside = [c for c in codes if c not in options]
    if outside:
        raise SchemaError(f"ranking names codes not in the candidate list: {outside}")
    return codes


JEV_INSTRUCTIONS = (
    "Which of these occurrence codes would the NTSB flag as the defining event of this "
    "accident? Each label is a six-digit NTSB occurrence code: phase, then event."
)


def jev_question(options: Sequence[str], tables: CodeTables) -> dict[str, object]:
    """One Choice over the candidates, labelled with their words (decision 0097)."""
    return {
        "type": "choice",
        "instructions": JEV_INSTRUCTIONS,
        "criteria": {code: _words(code, tables) for code in options},
    }


def ranking_from_probabilities(probabilities: Mapping[str, float]) -> tuple[str, ...]:
    """The three most probable codes; ties by code (Jev rounds to two decimals)."""
    return tuple(c for c, _p in sorted(probabilities.items(), key=lambda kv: (-kv[1], kv[0]))[:3])


def reorder(hypothesis: Hypothesis, ranking: Sequence[str]) -> Hypothesis:
    """The hypothesis with its occurrence guesses replaced by ``ranking``.

    A code the model gave keeps its probability; a code it did not give gets 0.0, so the
    probabilities still sum to at most 1. Nothing else changes.
    """
    given = {g.phase + g.event: g.probability for g in hypothesis.occurrence}
    occurrence = tuple(
        OccurrenceGuess(phase=code[:3], event=code[3:], probability=given.get(code, 0.0))
        for code in ranking
    )
    return hypothesis.model_copy(update={"occurrence": occurrence})
```

- [ ] **Step 4: Run the tests to verify they pass; add the import-linter entry**

Run: `uv run pytest tests/test_ordering.py -v && uv run lint-imports`
Expected: PASS; contracts kept after adding `"ntsb_probable_cause.scoring.ordering",` to the "Only the splitter…" source list.

- [ ] **Step 5: Run the full check and commit**

Run: `make check` (Expected: PASS)

```bash
git add src/ntsb_probable_cause/scoring/ordering.py pyproject.toml tests/test_ordering.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 8: the ordering check's candidate list, plain rule and check text"
```

---

### Task 9: The Jev client, ported from `typesafe-probe` (decision 0097)

**Files:**
- Create: `src/ntsb_probable_cause/model/typesafe.py` (from `origin/typesafe-probe`, commit `0c5d24c`)
- Modify: `src/ntsb_probable_cause/settings.py`, `src/ntsb_probable_cause/sources.py`, `.env.example`, `pyproject.toml` (typos)
- Create: `tests/fixtures/typesafe/README.md`, `choices.json`, `models.json`, `nouls.json` (from the branch)
- Create: `tests/test_typesafe_client.py` (from the branch)

**Interfaces:**
- Produces: `model.typesafe.TypeSafeClient(api_key, *, base_url, transport=None, sleep=time.sleep, clock=time.monotonic, max_attempts=5, backoff_seconds=2.0)` with `ask(payload, questions, *, model=DEFAULT_MODEL) -> Exchange` (refuses a payload carrying images) and `ask_state(state: str, questions, *, model=DEFAULT_MODEL) -> Exchange`; `Exchange(reply: SystemOneReply, attempts, retried_statuses, seconds)`; `SystemOneReply.choice(name) -> ChoiceAnswer` (`.probabilities: dict[str, float]`, `.model` on the reply); `Settings.typesafe_api_key`, `Settings.typesafe_base_url = "https://api.typesafe.ai"`, `Settings.require_typesafe_key() -> str`; `sources.JEV` (`ModelPrice("jev-latest", 0.042, 0.0, ...)`), `sources.TYPESAFE_SYSTEM_ONE = "/v1/systemone"`, `sources.TYPESAFE_MODELS`, `sources.TYPESAFE_MAX_CHOICE_LABELS = 255`.
- Task 10 consumes `TypeSafeClient.ask_state` and `sources.JEV`.

**Why a manual port.** The branch is 172 commits behind `main`; its `settings.py` and `sources.py` hunks no longer apply, and every comment that names its decision says 0060, which on `main` is an S2.5 record. The client module itself imports only `sources`, `errors` and `model.client`, so it satisfies every import-linter contract as it stands.

- [ ] **Step 1: Copy the module, fixtures and tests from the branch**

```bash
git show 0c5d24c:src/ntsb_probable_cause/model/typesafe.py > src/ntsb_probable_cause/model/typesafe.py
mkdir -p tests/fixtures/typesafe
for f in README.md choices.json models.json nouls.json; do git show 0c5d24c:tests/fixtures/typesafe/$f > tests/fixtures/typesafe/$f; done
git show 0c5d24c:tests/test_typesafe_client.py > tests/test_typesafe_client.py
```

- [ ] **Step 2: Renumber the decision in every copied file**

Every "decision 0060" and "(0060" in the four copied text files becomes 0097 (`typesafe.py`, the fixtures' `README.md`, `test_typesafe_client.py`). The module docstring's first line becomes: `"""TypeSafe's System One client, for the ordering check on development runs only (decision 0097)."""`. The JSON fixtures are not edited (they are saved replies).

Run: `grep -rn "0060\|0036" src/ntsb_probable_cause/model/typesafe.py tests/fixtures/typesafe tests/test_typesafe_client.py`
Expected: no output.

- [ ] **Step 3: Write the failing image test** (append to `tests/test_typesafe_client.py`)

```python
from ntsb_probable_cause.model.client import PageImage


def test_ask_refuses_a_payload_that_carries_images() -> None:
    payload = Payload.for_page(PageImage(media_type="image/jpeg", data=b"\xff\xd8"))
    with TypeSafeClient("k", base_url=BASE) as client, pytest.raises(ModelError, match="images"):
        client.ask(payload, QUESTIONS)
```

Run: `uv run pytest tests/test_typesafe_client.py -v`
Expected: this test FAILS (`ask` sends `payload.text` and drops the image); every ported test PASSES once Step 4's settings and sources exist — until then the module fails to import `sources.TYPESAFE_SYSTEM_ONE`, so run Step 4 first if the whole module errors.

- [ ] **Step 4: Port the settings and sources, and refuse images**

`settings.py`, after `openrouter_base_url`:

```python
    typesafe_api_key: SecretStr | None = Field(default=None, validation_alias="TYPESAFE_API_KEY")
    typesafe_base_url: str = "https://api.typesafe.ai"
```

and after `require_openrouter_key`:

```python
    def require_typesafe_key(self) -> str:
        """Return the TypeSafe key, or raise if it is not set (decision 0097)."""
        if self.typesafe_api_key is None or not self.typesafe_api_key.get_secret_value():
            raise ConfigurationError(
                "TYPESAFE_API_KEY is not set; export it or load it from the password store."
            )
        return self.typesafe_api_key.get_secret_value()
```

`sources.py`, beside the other price constants (and `JEV` added to `_PRICES`):

```python
# TypeSafe AI's launch post (typesafe.ai/blog/introducing-system-one-models-and-jev), read
# 2026-09-16: $0.042 per million input tokens, output unmetered. Self-reported and, in the
# vendor's words, not shown to be unsubsidised (decisions 0030, 0097). ``jev-latest`` is the
# SDK's default model name; every reply records the version it resolved to.
JEV = ModelPrice("jev-latest", 0.042, 0.0, "TypeSafe launch post, 2026-09-16, self-reported")
```

and at the end of the module:

```python
# https://api.typesafe.ai/openapi.json, as generated into ``typesafe-sdk`` 0.6.0 on PyPI (read
# 2026-09-17). The saved responses under tests/fixtures/typesafe/ confirm the shape (0097).
TYPESAFE_SYSTEM_ONE = "/v1/systemone"
TYPESAFE_MODELS = "/v1/models"
# The vendor's documented ceiling on labels in one Choice question.
TYPESAFE_MAX_CHOICE_LABELS = 255
```

`model/typesafe.py`, first lines of `TypeSafeClient.ask`:

```python
        if payload.images:
            raise ModelError(
                "Jev reads text only, and this payload carries images; it would send the text "
                "and silently drop them (decision 0097)"
            )
```

`.env.example`, after `OPENROUTER_API_KEY=`:

```
# TypeSafe System One (Jev): the S2.7 ordering check on development runs only (decision 0097).
TYPESAFE_API_KEY=
```

`pyproject.toml`: in `[tool.typos.default.extend-words]` add the NTSB's Anchorage case-number prefix (the three capitals A, N, C, as the typesafe branch's own `pyproject.toml` added it, `git show 0c5d24c:pyproject.toml`), mapped to itself, with the comment "the NTSB's Anchorage case-number prefix in the typesafe fixtures; not a misspelling" (it is not spelled out here because this plan is itself spell-checked); in `[tool.typos.files] extend-exclude` add `"tests/fixtures/typesafe/*.json",` with the comment `# The typesafe fixtures are saved replies that send the code-table labels verbatim (0097).`

- [ ] **Step 5: Run the tests to verify they pass**

Run: `uv run pytest tests/test_typesafe_client.py tests/test_sources_settings.py -v`
Expected: PASS (the ported tests and the image refusal)

- [ ] **Step 6: Run the full check and commit**

Run: `make check` (Expected: PASS. `vulture` runs at `min_confidence = 80` (`pyproject.toml`), below which unused classes and constants such as `ScoreAnswer`, `NoulAnswer` and `TYPESAFE_MODELS` are not reported; they stay, as part of the saved reply shape. If it does report one, log it in Deviations and keep the name.)

```bash
git add src/ntsb_probable_cause/model/typesafe.py src/ntsb_probable_cause/settings.py src/ntsb_probable_cause/sources.py .env.example pyproject.toml tests/fixtures/typesafe tests/test_typesafe_client.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 9: the Jev client, ported from typesafe-probe for the ordering check (0097)"
```

---

### Task 10: The check as a post-pass, and `ntsb-eval check` (spec §5.4–§5.5; W2, W3)

**Files:**
- Create: `src/ntsb_probable_cause/scoring/checkpass.py`
- Modify: `src/ntsb_probable_cause/scoring/metrics.py` (`rescore_occurrence`)
- Modify: `apps/eval/__main__.py` (the `check` subcommand; `resolve_latest` skips derived runs; `main` gains `jev_factory`)
- Test: `tests/test_checkpass.py` (create), `tests/test_metrics.py`, `tests/test_eval_app.py`

**Interfaces:**
- Consumes: Task 3 (`load_stats`), Task 8 (all of `ordering`), Task 9 (`TypeSafeClient`), `samples.refuse_sealed` (Task 2).
- Produces: `metrics.rescore_occurrence(scores: CaseScores, codes: Sequence[str], truth: Sequence[str], *, seen_pairs: AbstractSet[str]) -> CaseScores`; `checkpass.Way = Literal["rule", "luna", "jev"]`, `WAYS`, `CHECK_TOOL = "ordering_check"`, `EXPECTED_COST_PER_CASE_USD: Mapping[Way, float]`; `CheckOutcome(ranking, model, cost_usd, fingerprint, prompt_tokens=0, completion_tokens=0, note="")`; `Checker = Callable[[Hypothesis, str | None], CheckOutcome]`; `rule_checker(stats) -> Checker`; `luna_checker(client, stats, tables, *, model=sources.DEFAULT_MODEL, reasoning_effort=sources.DEFAULT_REASONING_EFFORT) -> Checker`; `jev_checker(client, stats, tables) -> Checker`; `checked_case(case, outcome, *, seen_pairs, commit) -> CaseResult`; `check_run(source: Path, way: Way, checker: Checker, *, runs_dir, groups, seen_pairs, commit, now) -> RunRecord`; `derived_id(run_id: str, way: Way) -> str` (`f"{run_id}-check-{way}"`). CLI: `ntsb-eval check RUN_ID --way {rule,luna,jev} [--budget-usd USD]`.
- Tasks 11, 12, 14, 15, 17 and 18 consume `ntsb-eval check` and `derived_id`.

**What a derived folder holds.** `<run id>-check-<way>/cases.jsonl`: each answered case with its original step and a second step (`step` = 1, `tool = "ordering_check"`, `arguments = {"ranking": [...]}`, the reordered hypothesis, the check's model, tokens, cost and input fingerprint); occurrence scores recomputed by `rescore_occurrence`; finding scores unchanged; an abstained or failed case copied unchanged. `run.jsonl`: the source's record with the derived id, `prompt_version` suffixed `+check-<way>`, S2.7's commit, and **`cost_usd` = the check's cost only** (the answers were paid for, and counted, in the source run; W2). Written in a `finally`, so an interrupted pass still records what it spent, with `finished` empty so the report calls it aborted.

- [ ] **Step 1: Write the failing `rescore_occurrence` test** (append to `tests/test_metrics.py`)

```python
from dataclasses import replace

from ntsb_probable_cause.records.verdict import Verdict
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.hypothesis import Hypothesis, OccurrenceGuess
from ntsb_probable_cause.scoring.metrics import rescore_occurrence, score_case


def _hyp(codes: tuple[str, ...]) -> Hypothesis:
    return Hypothesis(
        evidence_narrative="n",
        occurrence=tuple(OccurrenceGuess(phase=c[:3], event=c[3:], probability=0.2) for c in codes),
        findings=(),
        probable_cause="p",
        lay_explanation="l",
        confidence=0.5,
        abstain=False,
        evidence_used=(),
    )


def test_rescore_occurrence_equals_score_case_on_the_reordered_codes() -> None:
    tables = load_tables()
    verdict = Verdict(probable_cause=None, occurrence_codes=("452240", "452241"), finding_codes=(), finding_codes_in_cause=())
    seen = frozenset({"452240"})
    before = score_case(_hyp(("452241", "452240")), verdict, tables, seen_pairs=seen)
    after = rescore_occurrence(before, ("452240", "452241"), verdict.occurrence_codes, seen_pairs=seen)
    assert after == score_case(_hyp(("452240", "452241")), verdict, tables, seen_pairs=seen)
    assert rescore_occurrence(replace(before, abstained=True), ("452240",), ("452240",), seen_pairs=seen).occurrence_top1 is False
```

- [ ] **Step 2: Run it to verify it fails, then implement**

Run: `uv run pytest tests/test_metrics.py -v -k rescore` (Expected: FAIL, `ImportError`)

Add to `metrics.py` (with `from dataclasses import replace`):

```python
def rescore_occurrence(
    scores: CaseScores, codes: Sequence[str], truth: Sequence[str], *, seen_pairs: AbstractSet[str]
) -> CaseScores:
    """The occurrence scores after the codes are re-ordered; finding scores stand (0096).

    Exactly :func:`score_case`'s occurrence rules. An abstained case is returned unchanged.
    """
    if scores.abstained or not codes:
        return scores
    defining = truth[0] if truth else None
    return replace(
        scores,
        occurrence_top1=codes[0] == defining,
        occurrence_top3=defining in codes,
        event_match=defining is not None and codes[0][3:] == defining[3:],
        pair_unseen=codes[0] not in seen_pairs,
    )
```

Run: `uv run pytest tests/test_metrics.py -v` (Expected: PASS)

- [ ] **Step 3: Write the failing post-pass tests** (`tests/test_checkpass.py`)

```python
"""scoring/checkpass.py: the ordering check as a post-pass (decision 0096; plan W2)."""

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.model.client import RecordingFakeClient
from ntsb_probable_cause.scoring import checkpass
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import PoolCase, build
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl, write_jsonl
from tests.test_occurrence_misses import _case

NOW = datetime(2026, 9, 28, tzinfo=UTC)
LOC, STALL = "452240", "452241"
STATS = build(
    [PoolCase(2012, "Maneuvering", (LOC, STALL))] * 30 + [PoolCase(2016, "Maneuvering", (STALL, LOC))] * 5,
    built_from="test",
)


def _source(runs: Path, run_id: str = "20260926T000000-abc1234-dev-400-B") -> Path:
    folder = runs / run_id
    folder.mkdir(parents=True)
    record = RunRecord(
        run_id=run_id, sample="dev-400", arm="B", exclusions=(), includes=(), prompt_version="s1-v5",
        model="openai/gpt-6-luna", price_variant="batch", cap_usd=0.05, budget_usd=40.0,
        commit_sha="abc1234", dirty=False, started=NOW, finished=NOW, cases=2, cost_usd=1.0,
    )
    write_jsonl(folder / "run.jsonl", [record])
    write_jsonl(folder / "cases.jsonl", [
        _case("C1", (LOC, STALL), (STALL,)),  # stall first; LOC is defining
        _case("C2", (LOC, STALL), (LOC,), abstain=True),  # abstained: unchanged
    ])
    return folder


def test_the_rule_pass_writes_a_derived_run_with_a_check_step(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    source = _source(runs)
    record = checkpass.check_run(
        source, "rule", checkpass.rule_checker(STATS), runs_dir=runs,
        groups={"C1": "Maneuvering", "C2": "Maneuvering"}, seen_pairs=frozenset({LOC}),
        commit=("def5678", False), now=lambda: NOW,
    )
    assert record.run_id == "20260926T000000-abc1234-dev-400-B-check-rule"
    assert record.cost_usd == 0.0
    assert record.prompt_version == "s1-v5+check-rule"
    cases = {c.case_id: c for c in read_jsonl(runs / record.run_id / "cases.jsonl", CaseResult)}
    step = cases["C1"].steps[-1]
    assert step.tool == checkpass.CHECK_TOOL
    assert [g.phase + g.event for g in step.hypothesis.occurrence][0] == LOC
    assert cases["C1"].scores is not None and cases["C1"].scores.occurrence_top1
    assert len(cases["C2"].steps) == 1


def test_a_derived_run_is_refused_twice_and_a_held_out_source_is_refused(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    source = _source(runs)
    kwargs = dict(runs_dir=runs, groups={}, seen_pairs=frozenset(), commit=("d", False), now=lambda: NOW)
    checkpass.check_run(source, "rule", checkpass.rule_checker(STATS), **kwargs)
    with pytest.raises(ConfigurationError, match="exists"):
        checkpass.check_run(source, "rule", checkpass.rule_checker(STATS), **kwargs)
    held = _source(runs, "20260926T000000-abc1234-heldout-400-B")
    with pytest.raises(ConfigurationError, match="development"):
        checkpass.check_run(held, "rule", checkpass.rule_checker(STATS), **kwargs)


def test_the_luna_checker_sends_only_the_check_text_and_retries_a_bad_ranking() -> None:
    client = RecordingFakeClient([json.dumps({"ranking": ["111111"]}), json.dumps({"ranking": [LOC, STALL]})])
    checker = checkpass.luna_checker(client, STATS, load_tables())
    hypothesis = _case("C1", (LOC,), (STALL,)).steps[-1].hypothesis
    outcome = checker(hypothesis, "Maneuvering")
    assert outcome.ranking == (LOC, STALL)
    assert len(client.systems) == 2
    assert "rejected" in client.systems[1]
    assert client.payloads[0].text == ""  # everything is in the system text; no evidence payload
    assert client.settings[0].price_variant == "standard"


def test_the_luna_checker_leaves_the_answer_unchanged_when_both_replies_fail() -> None:
    client = RecordingFakeClient(["not json", "still not json"])
    checker = checkpass.luna_checker(client, STATS, load_tables())
    hypothesis = _case("C1", (LOC,), (STALL,)).steps[-1].hypothesis
    outcome = checker(hypothesis, "Maneuvering")
    assert outcome.ranking == (STALL,)
    assert outcome.note.startswith("check failed")
```

(`Payload.from_evidence` of an `Evidence` with no roles renders an empty text, as the judge's payload does; if it renders a placeholder, assert on that placeholder instead.)

- [ ] **Step 4: Run them to verify they fail**

Run: `uv run pytest tests/test_checkpass.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 5: Write `scoring/checkpass.py`**

```python
"""The ordering check as a post-pass over a finished run (decision 0096; plan walkthrough W2).

A finished arm B run is read; each answered case gets a second step whose hypothesis carries the
re-ordered occurrence codes; occurrence scores are recomputed and finding scores kept. The result
is a derived run folder ``<run id>-check-<way>`` that the report compares like any run. Its run
record's cost is the check's alone: the answers were paid for, and counted, in the source run.
Development runs only; the Jev way exists for this purpose alone (decision 0097).
"""

import hashlib
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError, SchemaError
from ntsb_probable_cause.model.client import ModelClient, ModelSettings, Payload, cost_usd
from ntsb_probable_cause.model.typesafe import TypeSafeClient
from ntsb_probable_cause.records.evidence import Evidence
from ntsb_probable_cause.scoring import ordering
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import CodingStats
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.scoring.metrics import rescore_occurrence
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl, write_jsonl

Way = Literal["rule", "luna", "jev"]
WAYS: tuple[Way, ...] = ("rule", "luna", "jev")
CHECK_TOOL = "ordering_check"
# Estimates for the budget guard (plan W3): GPT-6 Luna at the standard price, about 1,500
# prompt and 1,500 output tokens a case; Jev at its self-reported input price.
EXPECTED_COST_PER_CASE_USD: Mapping[Way, float] = {"rule": 0.0, "luna": 0.002, "jev": 0.0001}
MAX_OUTPUT_TOKENS = 4000


@dataclass(frozen=True)
class CheckOutcome:
    """One case's check: the ranking, who made it, and what it cost."""

    ranking: tuple[str, ...]
    model: str
    cost_usd: float
    fingerprint: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    note: str = ""


Checker = Callable[[Hypothesis, str | None], CheckOutcome]


def _codes(hypothesis: Hypothesis) -> tuple[str, ...]:
    return tuple(g.phase + g.event for g in hypothesis.occurrence)


def _fingerprint(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def rule_checker(stats: CodingStats) -> Checker:
    """The free way: :func:`ordering.plain_rule`."""

    def check(hypothesis: Hypothesis, group: str | None) -> CheckOutcome:
        guesses = _codes(hypothesis)
        return CheckOutcome(
            ranking=ordering.plain_rule(guesses, group, stats),
            model="rule",
            cost_usd=0.0,
            fingerprint=_fingerprint(f"{guesses}|{group}"),
        )

    return check


def luna_checker(
    client: ModelClient,
    stats: CodingStats,
    tables: CodeTables,
    *,
    model: str = sources.DEFAULT_MODEL,
    reasoning_effort: sources.ReasoningEffort | None = sources.DEFAULT_REASONING_EFFORT,
) -> Checker:
    """GPT-6 Luna asked, synchronously at the standard price (plan W3); one retry."""
    settings = ModelSettings(
        model=model,
        price_variant="standard",
        reasoning_effort=reasoning_effort,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        json_schema=ordering.RANKING_SCHEMA,
        schema_name="ranking",
    )
    empty = Payload.from_evidence(Evidence(case_id="check", docket_url=None))

    def check(hypothesis: Hypothesis, group: str | None) -> CheckOutcome:
        guesses = _codes(hypothesis)
        options = ordering.candidates(guesses, group, stats)
        text = ordering.check_text(guesses, options, group, hypothesis.evidence_narrative, stats, tables)
        system = f"{ordering.CHECK_SYSTEM}\n\n{text}"
        spent = 0.0
        prompt = completion = 0
        error: SchemaError | None = None
        for attempt in range(2):
            this_system = system if attempt == 0 else f"{system}\n\nYour previous reply was rejected: {error}"
            reply = client.complete(empty, settings, system=this_system)
            spent += cost_usd(reply, settings)[0]
            prompt += reply.usage.prompt_tokens
            completion += reply.usage.completion_tokens
            try:
                ranking = ordering.parse_ranking(reply.content or "", options)
            except SchemaError as caught:
                error = caught
                continue
            return CheckOutcome(ranking, model, spent, _fingerprint(system), prompt, completion)
        return CheckOutcome(
            guesses, model, spent, _fingerprint(system), prompt, completion,
            note=f"check failed, answer unchanged: {error}",
        )

    return check


def jev_checker(client: TypeSafeClient, stats: CodingStats, tables: CodeTables) -> Checker:
    """Jev asked, one Choice over the candidates (decision 0097)."""

    def check(hypothesis: Hypothesis, group: str | None) -> CheckOutcome:
        guesses = _codes(hypothesis)
        options = ordering.candidates(guesses, group, stats)
        text = ordering.check_text(guesses, options, group, hypothesis.evidence_narrative, stats, tables)
        exchange = client.ask_state(text, {"defining": ordering.jev_question(options, tables)})
        answer = exchange.reply.choice("defining")
        tokens = exchange.reply.usage.input_tokens
        return CheckOutcome(
            ranking=ordering.ranking_from_probabilities(answer.probabilities),
            model=exchange.reply.model,
            cost_usd=tokens * sources.JEV.input_usd_per_mtok / 1_000_000,
            fingerprint=_fingerprint(text),
            prompt_tokens=tokens,
        )

    return check


def checked_case(
    case: CaseResult, outcome: CheckOutcome, *, seen_pairs: AbstractSet[str], commit: tuple[str, bool]
) -> CaseResult:
    """The case with the check's step appended and its occurrence scores recomputed."""
    last = case.steps[-1]
    hypothesis = ordering.reorder(last.hypothesis, outcome.ranking)
    step = last.model_copy(
        update={
            "step": last.step + 1,
            "tool": CHECK_TOOL,
            "arguments": {"ranking": list(outcome.ranking)},
            "reason": outcome.note,
            "returned_roles": (),
            "documents_attached": (),
            "documents_not_read": (),
            "payload_fingerprint": outcome.fingerprint,
            "hypothesis": hypothesis,
            "model": outcome.model,
            "price_variant": "standard",
            "prompt_tokens": outcome.prompt_tokens,
            "completion_tokens": outcome.completion_tokens,
            "reasoning_tokens": None,
            "reply_completion_tokens": (),
            "reply_reasoning_tokens": (),
            "reply_finish_reasons": (),
            "cost_usd": outcome.cost_usd,
            "cumulative_cost_usd": last.cumulative_cost_usd + outcome.cost_usd,
            "commit_sha": commit[0],
            "dirty": commit[1],
        }
    )
    assert case.scores is not None  # the caller passes scored cases only
    scores = rescore_occurrence(case.scores, _codes(hypothesis), case.verdict_occurrence, seen_pairs=seen_pairs)
    return case.model_copy(update={"steps": (*case.steps, step), "scores": scores, "cost_usd": case.cost_usd + outcome.cost_usd})


def derived_id(run_id: str, way: Way) -> str:
    """The derived run's id."""
    return f"{run_id}-check-{way}"


def _refuse_unless_development(record: RunRecord, cases: Sequence[CaseResult]) -> None:
    if not record.sample.startswith("dev") or "heldout" in record.run_id or record.arm != "B":
        raise ConfigurationError(
            f"the ordering check runs on development arm B runs only; {record.run_id} is "
            f"{record.sample}, arm {record.arm} (decisions 0096, 0097)"
        )
    if any(c.split != "dev" for c in cases):
        raise ConfigurationError(f"{record.run_id} holds a case outside the development split")


def check_run(  # noqa: PLR0913 -- each argument is a separate input the tests vary.
    source: Path,
    way: Way,
    checker: Checker,
    *,
    runs_dir: Path,
    groups: Mapping[str, str | None],
    seen_pairs: AbstractSet[str],
    commit: tuple[str, bool],
    now: Callable[[], datetime],
) -> RunRecord:
    """Run the check over a finished run; write and return the derived run's record."""
    record = read_jsonl(source / "run.jsonl", RunRecord)[0]
    cases = read_jsonl(source / "cases.jsonl", CaseResult)
    _refuse_unless_development(record, cases)
    run_id = derived_id(record.run_id, way)
    folder = runs_dir / run_id
    try:
        folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError as error:
        raise ConfigurationError(f"{run_id} exists: a check is run once per source run") from error
    started = now()
    results: list[CaseResult] = []
    spent = 0.0
    finished: datetime | None = None
    try:
        for case in cases:
            if case.scores is None or not case.steps or case.steps[-1].hypothesis.abstain:
                results.append(case)
                continue
            outcome = checker(case.steps[-1].hypothesis, groups.get(case.case_id))
            spent += outcome.cost_usd
            results.append(checked_case(case, outcome, seen_pairs=seen_pairs, commit=commit))
        finished = now()
    finally:
        write_jsonl(folder / "cases.jsonl", results)
        derived = record.model_copy(
            update={
                "run_id": run_id,
                "prompt_version": f"{record.prompt_version}+check-{way}",
                "commit_sha": commit[0],
                "dirty": commit[1],
                "started": started,
                "finished": finished,
                "batch_ids": (),
                "cases": len(results),
                "cost_usd": spent,
                "reported_batch_cost_usd": None,
            }
        )
        write_jsonl(folder / "run.jsonl", [derived])
    return derived
```

(Replace the `assert` in `checked_case` with an explicit `if case.scores is None: raise ValueError(...)` if the lint config forbids `assert` in library code; `check_run` never passes an unscored case.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `uv run pytest tests/test_checkpass.py -v`
Expected: PASS (4 tests)

- [ ] **Step 7: Write the failing app tests** (append to `tests/test_eval_app.py`)

```python
def test_check_refuses_a_held_out_run_before_any_client_is_built(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    runs = tmp_path / "runs"
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("NTSB_RUNS_DIR", str(runs))
    run_id = "20260926T000000-abc1234-heldout-400-B"
    _write_judgeable_run(runs, run_id, "c1", sample="heldout-400", arm="B")

    def boom(_settings: object) -> object:
        raise AssertionError("no client may be built for a held-out run")

    assert main(["check", run_id, "--way", "jev"], client_factory=boom, jev_factory=boom) == 1
    assert "development" in capsys.readouterr().err


def test_resolve_latest_skips_derived_check_runs(tmp_path: Path) -> None:
    runs = tmp_path / "runs"
    _write_run(runs, "20260926T000000-abc1234-dev-400-B", finished=True, arm="B")
    _write_run(runs, "20260926T000000-abc1234-dev-400-B-check-rule", finished=True, arm="B")
    assert resolve_latest(runs, "B", "dev-400") == "20260926T000000-abc1234-dev-400-B"
```

(Use the real keyword names of `_write_judgeable_run` and `_write_run`; import `resolve_latest` from `apps.eval.__main__`.)

- [ ] **Step 8: Implement the command** in `apps/eval/__main__.py`

Imports: `from ntsb_probable_cause.model.typesafe import TypeSafeClient`, `from ntsb_probable_cause.scoring import checkpass`, `from ntsb_probable_cause.scoring.coding_stats import load_stats`, `from ntsb_probable_cause.scoring.budget import budget_lock, open_reservations`, `from ntsb_probable_cause.scoring.runner import refuse_over_budget` (skip any already imported).

```python
JevFactory = Callable[[Settings], TypeSafeClient]


def _default_jev_factory(settings: Settings) -> TypeSafeClient:
    return TypeSafeClient(settings.require_typesafe_key(), base_url=settings.typesafe_base_url)
```

In `_build_parser`:

```python
    check_p = commands.add_parser("check", help="the ordering check, as a post-pass over a finished run")
    check_p.add_argument("run_id")
    check_p.add_argument("--way", choices=checkpass.WAYS, required=True)
    check_p.add_argument("--budget-usd", type=float, default=None, help="default: NTSB_MONTHLY_BUDGET_USD")
```

```python
_GROUP_FIELD = next(f for f in fields.EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)


def _cmd_check(args: argparse.Namespace, settings: Settings, client_factory: ClientFactory, jev_factory: JevFactory) -> None:
    folder = settings.runs_dir / args.run_id
    record = answering_run_record(folder)
    samples.refuse_sealed(record.sample, is_committed=gitinfo.is_committed)
    if not record.sample.startswith("dev") or "heldout" in args.run_id or record.arm != "B":
        raise ConfigurationError(
            f"check: the ordering check runs on development arm B runs only; {args.run_id} is "
            f"{record.sample}, arm {record.arm} (decisions 0096, 0097)"
        )
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    processed = settings.data_dir / "processed"
    ids = [c.case_id for c in cases]
    groups = {
        case_id: (value if isinstance(value := _GROUP_FIELD.extract(raw), str) else None)
        for case_id, raw in zip(ids, samples.load_cases(processed, ids), strict=True)
    }
    stats, tables = load_stats(), load_tables()
    way: checkpass.Way = args.way
    if way == "rule":
        checker = checkpass.rule_checker(stats)
    else:
        budget = args.budget_usd if args.budget_usd is not None else settings.monthly_budget_usd
        projected = len(cases) * checkpass.EXPECTED_COST_PER_CASE_USD[way]
        with budget_lock(settings.runs_dir):
            reserved = sum(open_reservations(settings.runs_dir).values())
            spent = month_spent(settings.runs_dir, now=datetime.now(UTC))
            refuse_over_budget(projected, spent, budget, reserved=reserved)
        checker = (
            checkpass.luna_checker(client_factory(settings)[0], stats, tables)
            if way == "luna"
            else checkpass.jev_checker(jev_factory(settings), stats, tables)
        )
    derived = checkpass.check_run(
        folder, way, checker, runs_dir=settings.runs_dir, groups=groups,
        seen_pairs=samples.seen_pairs(processed), commit=ledger.commit_state(),
        now=lambda: datetime.now(UTC),
    )
    print(f"check {derived.run_id}: {derived.cases} cases, ${derived.cost_usd:.4f}")
```

`main` gains `jev_factory: JevFactory = _default_jev_factory` beside `client_factory`, and dispatches `"check"` to `_cmd_check(args, settings, client_factory, jev_factory)`. In `resolve_latest`, skip any candidate whose id contains `"-check-"`, with a comment: "a derived ordering-check run (S2.7, plan W2) is not a new answering run".

(`fields` and `EvidenceRole` imports: add if missing. If `open_reservations` returns a mapping of floats, `.values()` is right; match its real return type.)

- [ ] **Step 9: Run the tests to verify they pass**

Run: `uv run pytest tests/test_eval_app.py tests/test_checkpass.py -v`
Expected: PASS

- [ ] **Step 10: Add the boundary test for the check's payload** (append to `tests/test_boundary.py`)

```python
def test_the_ordering_check_sends_no_withheld_text(record_fixtures) -> None:
    """Layer 5 (0016) for the check: the body sent holds the check text and nothing withheld."""
    from ntsb_probable_cause.records.split import split_record
    from ntsb_probable_cause.scoring import checkpass
    from ntsb_probable_cause.scoring.coding_stats import PoolCase, build
    from ntsb_probable_cause.scoring.codes import load_tables
    from ntsb_probable_cause.model.client import RecordingFakeClient
    from tests.test_occurrence_misses import _case

    raw = record_fixtures[0]
    _evidence, synthesis, verdict = split_record(raw)
    stats = build([PoolCase(2012, "Landing", verdict.occurrence_codes or ("552300",))], built_from="t")
    client = RecordingFakeClient(['{"ranking": ["552300"]}'])
    hypothesis = _case("C1", ("552300",), ("552300",)).steps[-1].hypothesis
    checkpass.luna_checker(client, stats, load_tables())(hypothesis, "Landing")
    sent = client.systems[0] + client.payloads[0].text
    for withheld in (synthesis.factual_narrative, synthesis.analysis_narrative, verdict.probable_cause):
        if withheld:
            assert withheld[:80] not in sent
```

Then prove it can fail: temporarily append `+ (verdict.probable_cause or "")` to the narrative passed in (`hypothesis.model_copy(update={"evidence_narrative": verdict.probable_cause})`) and confirm the assertion fails; restore. Log the mutation check in the commit message.

(This test module may import `records.split`; `tests/` is outside the import allow-list, as the existing boundary tests already do.)

- [ ] **Step 11: Run the full check and commit**

Run: `make check` (Expected: PASS)

```bash
git add src/ntsb_probable_cause/scoring/checkpass.py src/ntsb_probable_cause/scoring/metrics.py apps/eval/__main__.py tests/test_checkpass.py tests/test_metrics.py tests/test_eval_app.py tests/test_boundary.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 10: the ordering check as a post-pass (ntsb-eval check), with its boundary test"
```

---

### Task 11: Round 1's reading rule (spec §5.4, decision 0096 item 5)

**Files:**
- Create: `scripts/round1_report.py`
- Test: `tests/test_round1_report.py` (create)

**Interfaces:**
- Consumes: derived folders `derived_id(source, way)` (Task 10); `misses.miss_group` (Task 4); `metrics.paired_difference`.
- Produces: `Paired(mean, low, high, n, fixes, breaks)` (frozen dataclass); `paired(a: Mapping[str, bool], b: Mapping[str, bool], ids: Sequence[str] | None = None) -> Paired`; `choose(results: Mapping[str, Mapping[str, tuple[Paired, Paired | None]]]) -> str` (returns a way or `"no check"`); `main(argv)` with `--answers RUN_A RUN_B`, `--out`.

**The rule, as code will apply it** (decision 0096 item 5). For each answer set and each way: *vs none* is the way's paired top-1 difference against the source run; *vs rule* is a model way's difference against the rule's derived run. A way **works** if *vs none*'s lower bound is above zero on both answer sets. A model way is **chosen** if *vs rule*'s lower bound is above zero on both sets; if both model ways qualify, the one with the larger mean gain over the rule, averaged over the two sets. Otherwise the rule is chosen if it works; otherwise no check is kept. A way whose derived folders are missing (for example Jev without access) is printed "not run" and cannot be chosen.

- [ ] **Step 1: Write the failing tests** (`tests/test_round1_report.py`)

```python
"""scripts/round1_report.py: Round 1's reading rule (decision 0096 item 5)."""

from scripts import round1_report as r1


def _p(low: float, mean: float = 0.05) -> r1.Paired:
    return r1.Paired(mean=mean, low=low, high=mean + 0.05, n=399, fixes=30, breaks=10)


def test_paired_counts_fixes_and_breaks() -> None:
    a = {"C1": True, "C2": False, "C3": True}
    b = {"C1": False, "C2": True, "C3": True, "C4": True}
    result = r1.paired(a, b)
    assert (result.n, result.fixes, result.breaks) == (3, 1, 1)


def test_the_rule_wins_when_no_model_beats_it() -> None:
    results = {
        "A": {"rule": (_p(0.01), None), "luna": (_p(0.02), _p(-0.01)), "jev": (_p(-0.01), _p(-0.03))},
        "B": {"rule": (_p(0.02), None), "luna": (_p(0.03), _p(0.00)), "jev": (_p(-0.02), _p(-0.04))},
    }
    assert r1.choose(results) == "rule"


def test_a_model_is_chosen_only_when_it_beats_the_rule_on_both_sets() -> None:
    results = {
        "A": {"rule": (_p(0.01), None), "luna": (_p(0.05, 0.10), _p(0.01, 0.04))},
        "B": {"rule": (_p(0.02), None), "luna": (_p(0.06, 0.11), _p(0.02, 0.05))},
    }
    assert r1.choose(results) == "luna"


def test_nothing_is_kept_when_nothing_works_on_both_sets() -> None:
    results = {"A": {"rule": (_p(0.01), None)}, "B": {"rule": (_p(-0.01), None)}}
    assert r1.choose(results) == "no check"
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_round1_report.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `scripts/round1_report.py`**

```python
"""Round 1's results: the four ways on two answer sets, and decision 0096's reading rule.

Status
    Live for S2.7 (spec §5.4), free: reads the source runs and their derived check folders
    (``ntsb-eval check``); counts only. Writes docs/results/s27-round1-dev.txt.

Why
    The rule was fixed before any check ran: a way works if it beats "no check" on both answer
    sets; a model must also beat the free rule on both, or the rule is kept.

Usage
    uv run python -m scripts.round1_report --answers RUN_A RUN_B [--out PATH]
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause.scoring.checkpass import WAYS, derived_id
from ntsb_probable_cause.scoring.metrics import paired_difference
from ntsb_probable_cause.scoring.misses import MISS_GROUPS, miss_group
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.settings import Settings

MODEL_WAYS = ("luna", "jev")


@dataclass(frozen=True)
class Paired:
    """A paired top-1 difference (a - b) with its interval, and fixes and breaks."""

    mean: float
    low: float
    high: float
    n: int
    fixes: int
    breaks: int


def paired(a: Mapping[str, bool], b: Mapping[str, bool], ids: Sequence[str] | None = None) -> Paired:
    """Paired over the shared ids (or ``ids``); fixes = right in a only, breaks = right in b only."""
    shared = sorted(set(a) & set(b)) if ids is None else [i for i in ids if i in a and i in b]
    if not shared:
        return Paired(0.0, 0.0, 0.0, 0, 0, 0)
    mean, low, high = paired_difference([a[i] for i in shared], [b[i] for i in shared])
    fixes = sum(a[i] and not b[i] for i in shared)
    breaks = sum(b[i] and not a[i] for i in shared)
    return Paired(mean, low, high, len(shared), fixes, breaks)


def choose(results: Mapping[str, Mapping[str, tuple[Paired, Paired | None]]]) -> str:
    """Decision 0096 item 5, over every answer set in ``results``."""
    sets = list(results.values())

    def everywhere(way: str, index: int) -> bool:
        return all(way in s and (p := s[way][index]) is not None and p.low > 0 for s in sets)

    winners = [w for w in MODEL_WAYS if everywhere(w, 1)]
    if winners:
        return max(winners, key=lambda w: sum(s[w][1].mean for s in sets if s[w][1] is not None))
    return "rule" if everywhere("rule", 0) else "no check"


def _top1(cases: Sequence[CaseResult]) -> dict[str, bool]:
    return {c.case_id: c.scores.occurrence_top1 for c in cases if c.scores is not None and c.steps}


def _line(label: str, p: Paired) -> str:
    return f"  {label}: {p.mean:+.1%} [{p.low:+.1%}, {p.high:+.1%}] on n={p.n}; fixes {p.fixes}, breaks {p.breaks}"


def main(argv: Sequence[str] | None = None) -> int:
    """Print every way on both answer sets, then the rule's outcome."""
    parser = argparse.ArgumentParser(prog="round1_report")
    parser.add_argument("--answers", nargs=2, required=True, metavar="RUN_ID")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    runs = Settings().runs_dir
    lines = ["Round 1: the ordering check (scripts/round1_report.py; counts only, decision 0096)"]
    results: dict[str, dict[str, tuple[Paired, Paired | None]]] = {}
    for source in args.answers:
        if "heldout" in source:
            raise SystemExit(f"round1_report: {source} is a held-out run; development runs only")
        base = read_jsonl(runs / source / "cases.jsonl", CaseResult)
        none = _top1(base)
        groups = {
            c.case_id: miss_group(
                tuple(g.phase + g.event for g in c.steps[-1].hypothesis.occurrence),
                c.verdict_occurrence,
                abstain=c.steps[-1].hypothesis.abstain,
            )
            for c in base
            if c.scores is not None and c.steps
        }
        fatal = {c.case_id for c in base if c.fatal}
        lines += ["", f"## answer set {source}"]
        loaded: dict[str, dict[str, bool]] = {}
        for way in WAYS:
            folder = runs / derived_id(source, way)
            if not (folder / "cases.jsonl").exists():
                lines.append(f"- {way}: not run")
                continue
            loaded[way] = _top1(read_jsonl(folder / "cases.jsonl", CaseResult))
        results[source] = {}
        for way, top1 in loaded.items():
            vs_none = paired(top1, none)
            vs_rule = paired(top1, loaded["rule"]) if way != "rule" and "rule" in loaded else None
            results[source][way] = (vs_none, vs_rule)
            lines.append(f"- {way}")
            lines.append(_line("against no check", vs_none))
            if vs_rule is not None:
                lines.append(_line("against the plain rule", vs_rule))
            lines.append(_line("fatal, against no check", paired(top1, none, sorted(fatal))))
            lines.append(_line("non-fatal, against no check", paired(top1, none, sorted(set(none) - fatal))))
            for group in ("exact", *MISS_GROUPS):
                members = sorted(i for i, g in groups.items() if g == group)
                p = paired(top1, none, members)
                lines.append(f"    {group}: fixes {p.fixes}, breaks {p.breaks} of {p.n}")
    outcome = choose(results)
    lines += ["", f"outcome (decision 0096 item 5): {outcome}"]
    text = "\n".join(lines)
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest tests/test_round1_report.py -v`
Expected: PASS

- [ ] **Step 5: Run the full check and commit**

Run: `make check` (Expected: PASS)

```bash
git add scripts/round1_report.py tests/test_round1_report.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 11: Round 1's reading rule"
```

---

### Task 12: Round 1's runs and results (spec §5)

**Files:**
- Modify: `Makefile`
- Create (by running): `docs/results/s27-round1-dev.txt`

**Interfaces:**
- Consumes: Tasks 10–11; the two answer sets: B-v1 `20260926T082427-d19aafa-dev-400-B` and Round 0's `REPEAT` (Task 7).
- Produces: the outcome line (a way, or "no check"), which every later round reads as `CHECK` (empty for "no check").

- [ ] **Step 1: Add the targets and commit them**

```make
s27-check:
	$(if $(RUN),,$(error RUN is required: the answer run id))
	$(if $(WAY),,$(error WAY is required: rule, luna or jev))
	uv run python -m scripts.stage_spend --estimate $(if $(filter luna,$(WAY)),0.90,0.05)
	uv run ntsb-eval check $(RUN) --way $(WAY)
# S2.7 spec §5, post-pass. rule: free. luna: about $0.36 per 400 cases at the standard price
# (plan W3). jev: a fraction of a cent (self-reported price); needs TYPESAFE_API_KEY.

s27-round1-results:
	$(if $(REPEAT),,$(error REPEAT is required: the noise-floor run id))
	uv run python -m scripts.round1_report --answers 20260926T082427-d19aafa-dev-400-B $(REPEAT) --out docs/results/s27-round1-dev.txt
```

- [ ] **Step 2: The plain rule on both answer sets** (free)

Run:
```bash
make s27-check RUN=20260926T082427-d19aafa-dev-400-B WAY=rule
make s27-check RUN=<REPEAT> WAY=rule
```
Expected: two derived folders; each prints `$0.0000`.

- [ ] **Step 3: STOP — GPT-6 Luna on both answer sets (paid, about $0.72)**

Hand Andy: "`make s27-check RUN=20260926T082427-d19aafa-dev-400-B WAY=luna`, then `RUN=<REPEAT>`; about $0.36 each, some minutes each, synchronous at the standard price (walkthrough W3)."

- [ ] **Step 4: STOP — Jev on both answer sets (paid, a fraction of a cent)**

Hand Andy: "With `TYPESAFE_API_KEY` exported from `pass`: `make s27-check RUN=… WAY=jev` for both answer sets." If Jev is unavailable, record it in Deviations; the report prints "not run" and Round 1 runs three ways (spec §17).

- [ ] **Step 5: The results** (free)

Run: `make s27-round1-results REPEAT=<REPEAT>`
Expected: `docs/results/s27-round1-dev.txt` ends with `outcome (decision 0096 item 5): <way or no check>`.

- [ ] **Step 6: Commit and report Round 1 to Andy**

```bash
git add docs/results/s27-round1-dev.txt Makefile docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 12: Round 1's results"
```

Report in plain English: each way's gain over no check on both answer sets, fixes against breaks, whether a model beat the free rule, and the outcome — which becomes `CHECK` for every later round.

---

## Part D — the guidance rounds (spec §6, decision 0098)

### Task 13: Guidance files, the prompt version, and the registration refusal (spec §6.1–§6.3; W5, W6)

**Files:**
- Create: `src/ntsb_probable_cause/scoring/guidance/__init__.py` (docstring only), `docs/rounds/README.md`
- Modify: `src/ntsb_probable_cause/scoring/prompt.py`, `scoring/runner.py` (`RunSpec`, `spec_json`, `_system_text`, `build_record`), `scoring/records.py` (`RunRecord`), `scoring/report.py` (`provenance`), `apps/eval/__main__.py` (`run --guidance`, `resolve_latest`)
- Create: `scripts/check_guidance.py`
- Modify: `Makefile`
- Test: `tests/test_prompt.py`, `tests/test_runner.py`, `tests/test_eval_app.py`, `tests/test_check_guidance.py` (create), `tests/test_guidance_files.py` (create)

**Interfaces:**
- Produces: `prompt.GUIDANCE_DIR: Traversable` (the `scoring/guidance` folder); `prompt.guidance_round(name: str) -> int` (names are `r<N>-<slug>`, lower case; `ConfigurationError` otherwise); `prompt.guidance_text(names: Sequence[str]) -> str`; `prompt.guidance_sha256(names) -> str | None`; `prompt.prompt_version(names) -> str` (`"s1-v5"` or `"s1-v5+" + "+".join(names)`); `prompt.registration_path(name) -> Path` (`docs/rounds/s27-round-<N>.md`); `RunSpec.guidance: tuple[str, ...] = ()`; `RunRecord.guidance: tuple[str, ...] = ()`, `RunRecord.guidance_sha256: str | None = None`; CLI `ntsb-eval run --guidance NAME` (repeatable, in stacking order). `scripts/check_guidance.py NAME...` exits 1 on any guidance sentence found in a development narrative or probable cause.
- Tasks 14, 15, 17, 18 consume these.

**Where guidance sits.** After the code tables, under its own heading: `SYSTEM_ANSWER`, the tables, then `## Coding guidance (how the NTSB codes)` and each file's text in stacking order. The evidence payload is untouched, so S0's provenance check and every boundary test read it unchanged (decision 0098 item 1).

- [ ] **Step 1: Write the failing prompt tests** (append to `tests/test_prompt.py`)

```python
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import prompt


@pytest.fixture
def guidance_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "r2-loc-stall.md").write_text("When a stall and a loss of control both occur...\n")
    (tmp_path / "r3-phase.md").write_text("Low-altitude maneuvering uses phase 452.\n")
    monkeypatch.setattr(prompt, "GUIDANCE_DIR", tmp_path)
    return tmp_path


def test_prompt_version_names_every_guidance_file_in_order(guidance_dir: Path) -> None:
    assert prompt.prompt_version(()) == prompt.PROMPT_VERSION
    assert prompt.prompt_version(("r2-loc-stall", "r3-phase")) == f"{prompt.PROMPT_VERSION}+r2-loc-stall+r3-phase"


def test_guidance_text_and_hash(guidance_dir: Path) -> None:
    text = prompt.guidance_text(("r2-loc-stall", "r3-phase"))
    assert text.index("stall") < text.index("452")
    assert prompt.guidance_sha256(()) is None
    assert prompt.guidance_sha256(("r2-loc-stall",)) != prompt.guidance_sha256(("r3-phase",))


def test_a_badly_named_or_missing_file_is_refused(guidance_dir: Path) -> None:
    with pytest.raises(ConfigurationError, match="r<N>-"):
        prompt.guidance_round("loc-stall")
    with pytest.raises(ConfigurationError, match="no guidance file"):
        prompt.guidance_text(("r9-missing",))


def test_registration_path() -> None:
    assert prompt.registration_path("r2-loc-stall") == Path("docs/rounds/s27-round-2.md")
```

- [ ] **Step 2: Run them to verify they fail, then implement in `prompt.py`**

Run: `uv run pytest tests/test_prompt.py -v` (Expected: FAIL, attributes missing)

Add to `prompt.py` (imports `hashlib`, `re`, `from importlib import resources`, `from importlib.resources.abc import Traversable`, `from pathlib import Path`, `from collections.abc import Sequence`, `from ntsb_probable_cause.errors import ConfigurationError`), and extend the module docstring: "From S2.7 (decision 0098) a run may add coding guidance files; `prompt_version` then names them."

```python
GUIDANCE_DIR: Traversable = resources.files("ntsb_probable_cause.scoring").joinpath("guidance")
_GUIDANCE_NAME = re.compile(r"^r(?P<round>[1-9][0-9]*)-[a-z0-9]+(?:-[a-z0-9]+)*$")
GUIDANCE_HEADING = "## Coding guidance (how the NTSB codes)"


def guidance_round(name: str) -> int:
    """The round a guidance file belongs to, from its name ``r<N>-<slug>``."""
    match = _GUIDANCE_NAME.match(name)
    if match is None:
        raise ConfigurationError(f"guidance {name!r}: names are r<N>-<slug>, lower case (decision 0098)")
    return int(match["round"])


def guidance_text(names: Sequence[str]) -> str:
    """The guidance files' text, in stacking order."""
    parts: list[str] = []
    for name in names:
        guidance_round(name)
        path = GUIDANCE_DIR.joinpath(f"{name}.md")
        if not path.is_file():
            raise ConfigurationError(f"no guidance file {name}.md in scoring/guidance")
        parts.append(path.read_text().strip())
    return "\n\n".join(parts)


def guidance_sha256(names: Sequence[str]) -> str | None:
    """The SHA-256 of the names and their text, or None with no guidance."""
    if not names:
        return None
    return hashlib.sha256(f"{list(names)}\n{guidance_text(names)}".encode()).hexdigest()


def prompt_version(names: Sequence[str]) -> str:
    """What elicits the answer: the base version, plus every guidance file in order (plan W5)."""
    return PROMPT_VERSION if not names else "+".join((PROMPT_VERSION, *names))


def registration_path(name: str) -> Path:
    """The round registration a guidance file needs committed before any run (0098 item 3)."""
    return Path("docs/rounds") / f"s27-round-{guidance_round(name)}.md"


def guidance_block(names: Sequence[str]) -> str:
    """The text appended to the system prompt after the tables; empty with no guidance."""
    return "" if not names else f"\n\n{GUIDANCE_HEADING}\n{guidance_text(names)}"
```

Create `src/ntsb_probable_cause/scoring/guidance/__init__.py` with only a docstring: `"""S2.7's coding guidance files (decision 0098): one r<N>-<slug>.md per round, read by scoring.prompt."""`.

Run: `uv run pytest tests/test_prompt.py -v` (Expected: PASS)

- [ ] **Step 3: Write the failing runner tests** (append to `tests/test_runner.py`, using its `runner`, `GOOD`, `REFINE` helpers and the `guidance_dir` idea)

```python
def test_guidance_reaches_the_system_text_and_the_records(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, record_fixtures) -> None:
    guidance = tmp_path / "guidance"
    guidance.mkdir()
    (guidance / "r2-loc-stall.md").write_text("GUIDANCE-MARKER sentence.\n")
    monkeypatch.setattr(prompt, "GUIDANCE_DIR", guidance)
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(sample="dev-400", arm="ceiling", sync=True, price_variant="standard", guidance=("r2-loc-stall",))
    record = runner(tmp_path, client).run(spec, record_fixtures[:1])
    assert "GUIDANCE-MARKER" in client.systems[0]
    assert "GUIDANCE-MARKER" not in client.payloads[0].text
    assert record.guidance == ("r2-loc-stall",)
    assert record.prompt_version.endswith("+r2-loc-stall")
    assert record.guidance_sha256 is not None
    written = json.loads((tmp_path / "runs" / record.run_id / "spec.json").read_text())
    assert written["guidance"] == ["r2-loc-stall"]


def test_a_run_without_guidance_writes_the_old_spec_keys(tmp_path: Path, record_fixtures) -> None:
    client = RecordingFakeClient([GOOD, REFINE])
    spec = RunSpec(sample="dev-400", arm="ceiling", sync=True, price_variant="standard")
    record = runner(tmp_path, client).run(spec, record_fixtures[:1])
    written = json.loads((tmp_path / "runs" / record.run_id / "spec.json").read_text())
    assert "guidance" not in written
    assert written["prompt_version"] == prompt.PROMPT_VERSION
```

(Use the arguments `tests/test_runner.py`'s other sync ceiling tests pass; the ceiling needs no docket.)

- [ ] **Step 4: Run them to verify they fail, then implement in the runner, records and report**

Run: `uv run pytest tests/test_runner.py -v -k guidance` (Expected: FAIL, `RunSpec` has no `guidance`)

- `RunSpec`: add `guidance: tuple[str, ...] = ()` after `expected_cost_per_case_usd`.
- `spec_json`: replace `"prompt_version": prompt.PROMPT_VERSION,` with `"prompt_version": prompt.prompt_version(spec.guidance),`; build the dict into a variable and, before returning, `if spec.guidance: recorded |= {"guidance": list(spec.guidance), "guidance_sha256": prompt.guidance_sha256(spec.guidance)}` inserted before `commit_sha` (keep `case_ids` last). A run without guidance writes exactly the old keys, so an older folder still resumes (W5).
- `_system_text`: return `f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(tables, case_number=case_number)}{prompt.guidance_block(spec.guidance)}"`.
- `build_record`: `prompt_version=prompt.prompt_version(spec.guidance)`, `guidance=spec.guidance`, `guidance_sha256=prompt.guidance_sha256(spec.guidance)`.
- `records.RunRecord`: add `guidance: tuple[str, ...] = ()` and `guidance_sha256: str | None = None` (defaults, so every older row still reads).
- `report.provenance`: after the `exclusions=` line, when `record.guidance`: `f"guidance={'+'.join(record.guidance)} sha256={(record.guidance_sha256 or '')[:12]}"`.

Run: `uv run pytest tests/test_runner.py tests/test_report.py tests/test_records.py -v` (Expected: PASS)

- [ ] **Step 5: The CLI and the registration refusal**

In `_build_parser`'s `run_p`: `run_p.add_argument("--guidance", action="append", default=[], metavar="NAME", help="a guidance file r<N>-<slug>, in stacking order (decision 0098)")`. In `_cmd_run`, after the sealed refusal:

```python
    for name in args.guidance:
        registration = prompt.registration_path(name)
        if not gitinfo.is_committed(registration):
            raise ConfigurationError(
                f"guidance {name}: its registration {registration} is not committed; a round is "
                "registered before it runs (decision 0098 item 3)"
            )
    prompt.guidance_text(args.guidance)  # a missing file is refused before any money moves
```

and pass `guidance=tuple(args.guidance)` to `RunSpec`. In `resolve_latest`, skip a candidate whose record has `guidance`, beside the ablation skip, with the comment "a guided run (S2.7) is not the plain arm".

Append to `tests/test_eval_app.py`:

```python
def test_run_refuses_guidance_whose_registration_is_not_committed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], record_fixtures
) -> None:
    _eval_env(tmp_path, monkeypatch, record_fixtures[0])
    monkeypatch.setattr(gitinfo, "is_committed", lambda path, repo=Path(): path.name != "s27-round-2.md")
    assert main(["run", "--arm", "ceiling", "--sample", "dev-400", "--guidance", "r2-loc-stall"],
                client_factory=lambda s: (RecordingFakeClient([]), None)) == 1
    assert "registration" in capsys.readouterr().err
```

Run: `uv run pytest tests/test_eval_app.py -v -k "guidance or resolve"` (Expected: PASS)

- [ ] **Step 6: The CI check on committed guidance, and the local sentence check (W6)**

`tests/test_guidance_files.py`:

```python
"""Every committed guidance file is named r<N>-<slug>, has a registration, and names no case."""

import re
from pathlib import Path

from ntsb_probable_cause.scoring import prompt

_CASE_NUMBER = re.compile(r"\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}[A-Z]?\b")
GUIDANCE = Path("src/ntsb_probable_cause/scoring/guidance")


def test_guidance_files_are_well_named_registered_and_name_no_case() -> None:
    for path in sorted(GUIDANCE.glob("*.md")):
        prompt.guidance_round(path.stem)
        assert prompt.registration_path(path.stem).is_file(), path
        assert not _CASE_NUMBER.search(path.read_text()), path
```

`scripts/check_guidance.py`:

```python
"""Check guidance files share no sentence with any development case's withheld text.

Status
    Live for S2.7 (spec §12, plan W6), free and local: streams every development case in the
    processed file and compares each guidance sentence of 30 or more characters, normalised,
    against the factual narrative, analysis narrative and probable cause. Prints counts and
    the offending guidance sentence only; exits 1 on any match. CI cannot run it (no data).

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.check_guidance r2-loc-stall [r3-...]
"""

import argparse
import json
import re
from collections.abc import Sequence

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.settings import Settings

MIN_CHARS = 30


def normalise(text: str) -> str:
    """Lower case, whitespace collapsed."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def sentences(text: str) -> list[str]:
    """The guidance's sentences of at least ``MIN_CHARS`` characters, normalised."""
    return [s for s in (normalise(p) for p in re.split(r"(?<=[.!?])\s+", text)) if len(s) >= MIN_CHARS]


def matches(needles: Sequence[str], haystacks: Sequence[str]) -> list[str]:
    """The needles found in any haystack."""
    return [n for n in needles if any(n in h for h in haystacks)]


def main(argv: Sequence[str] | None = None) -> int:
    """Exit 1 if any guidance sentence appears in a development case's withheld text."""
    parser = argparse.ArgumentParser(prog="check_guidance")
    parser.add_argument("names", nargs="+")
    args = parser.parse_args(argv)
    needles = sentences(prompt.guidance_text(args.names))
    found: set[str] = set()
    cases = 0
    columns = ["split", "raw_json"]
    path = Settings().data_dir / "processed" / "cases.parquet"
    with pq.ParquetFile(path) as parquet:
        for batch in parquet.iter_batches(batch_size=512, columns=columns):
            for split, raw_json in zip(*(batch.column(c).to_pylist() for c in columns), strict=True):
                if split != "dev":
                    continue
                raw = json.loads(raw_json)
                texts = [
                    normalise(t)
                    for t in (fields.factual_narrative(raw), fields.analysis_narrative(raw), fields.probable_cause(raw))
                    if isinstance(t, str)
                ]
                cases += 1
                found.update(matches(needles, texts))
    print(f"{len(needles)} guidance sentences checked against {cases} development cases; {len(found)} found")
    for sentence in sorted(found):
        print(f"- found: {sentence}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
```

`tests/test_check_guidance.py`:

```python
from scripts import check_guidance as cg


def test_sentences_and_matches() -> None:
    text = "Short one. When a loss of control and a stall both occur, code the first. Another."
    needles = cg.sentences(text)
    assert needles == ["when a loss of control and a stall both occur, code the first."]
    assert cg.matches(needles, ["... when a loss of control and a stall both occur, code the first. ..."]) == needles
    assert cg.matches(needles, ["nothing here"]) == []
```

(`fields.factual_narrative`, `analysis_narrative`, `probable_cause` exist on `main`; if a name differs, use the one in `fields.py`. Scripts are outside the import-linter contracts, as `analysis_handcheck.py` already is.)

- [ ] **Step 7: The rounds folder and its template** (`docs/rounds/README.md`)

```markdown
# S2.7 rounds

One file per guidance round, `s27-round-<N>.md` (decision 0098 item 3), committed **before** the
round's run; the runner refuses guidance whose registration is not committed. The result is
appended below the registration after the run, by `scripts/round_result.py`, and nothing above
it is edited. `s27-sealed.md` registers the final setup before the sealed sample is opened
(decision 0095).

## Template

    # S2.7 round <N>: <one-line change>

    - **Change:** adds `src/ntsb_probable_cause/scoring/guidance/r<N>-<slug>.md` (text quoted below).
    - **Stack:** the kept guidance before it, in order: <names or "none">.
    - **Source (decision 0098 item 2):** <the counts in docs/results/s27-coding-stats.txt it quotes,
      or the official definition it cites>.
    - **The miss group it should shrink:** <group>, from docs/results/s27-round0-dev.txt.
    - **Reading rule:** decision 0098 item 4, applied by scripts/round_result.py; with-check scores
      decide if Round 1 kept a check (<way or "no check">).
    - **Reference run:** <run id>; **noise pair:** <B-v1 run id> and <repeat run id>.
    - **Cost estimate:** <$, from the last run's cost per case>.
    - **Prediction:** <one line>.
    - **Local sentence check:** `scripts/check_guidance.py` passed on <date>.

    ## The guidance text

    <the file's text, verbatim>
```

- [ ] **Step 8: Makefile targets**

```make
s27-round:
	$(if $(PER_CASE),,$(error PER_CASE is required: the last run's cost per case rounded up))
	uv run python -m scripts.stage_spend --estimate $(or $(EST),1.40)
	uv run ntsb-eval run --arm B --sample dev-400 --evidence-version $(or $(EVIDENCE),v1) --expected-cost-per-case-usd $(PER_CASE) $(foreach g,$(GUIDANCE),--guidance $(g))
# S2.7 spec §6, paid (about $1.18 at v1): one guidance round's arm B run on dev-400. GUIDANCE
# lists every kept file and the new one, in stacking order; each needs its registration committed.

s27-check-guidance:
	$(if $(GUIDANCE),,$(error GUIDANCE is required))
	uv run python -m scripts.check_guidance $(GUIDANCE)
# S2.7 plan W6, free and local: no guidance sentence may appear in a development case's withheld text.
```

- [ ] **Step 9: Run the full check and commit**

Run: `make check` (Expected: PASS)

```bash
git add src/ntsb_probable_cause/scoring/prompt.py src/ntsb_probable_cause/scoring/guidance src/ntsb_probable_cause/scoring/runner.py src/ntsb_probable_cause/scoring/records.py src/ntsb_probable_cause/scoring/report.py apps/eval/__main__.py scripts/check_guidance.py docs/rounds/README.md Makefile tests/test_prompt.py tests/test_runner.py tests/test_eval_app.py tests/test_check_guidance.py tests/test_guidance_files.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 13: guidance files, the prompt version, and the registration refusal"
```

---

### Task 14: A round's reading rule (spec §6.4, decision 0098 item 4)

**Files:**
- Create: `scripts/round_result.py`
- Modify: `Makefile`
- Test: `tests/test_round_result.py` (create)

**Interfaces:**
- Consumes: `metrics.bootstrap_mean`; run folders.
- Produces: `Diff(mean, low, high, n)`; `diff(a: Mapping[str, float], b: Mapping[str, float]) -> Diff`; `Reading(primary, noise, secondary, kept, reason)`; `read(run, reference, noise_a, noise_b, *, finding_round: bool) -> Reading` over case lists; `main(argv)` with `--run`, `--reference`, `--noise A B`, `--finding-round`, `--append PATH`.

**The rule, as code applies it.** An occurrence round's **primary** score is top-1 and its **secondary** finding recall@10; a finding round swaps them. The **noise** is the absolute mean of the primary score's paired difference between the two identical Round 0 runs (or their derived check folders when a check is kept). The round is **kept** if the primary difference's lower bound is above zero, its mean is larger than the noise, and the secondary difference's upper bound is not below zero (do no harm). Example: top-1 +3.5% [+0.8%, +6.1%], noise 1.5%, finding recall@10 −0.4% [−1.9%, +1.1%] → kept. Top-1 +1.2% [+0.1%, +2.4%] with noise 1.5% → dropped: inside the noise.

- [ ] **Step 1: Write the failing tests** (`tests/test_round_result.py`)

```python
"""scripts/round_result.py: decision 0098 item 4."""

from dataclasses import replace

from scripts import round_result as rr

from tests.test_occurrence_misses import _SCORES, _case


def _cases(top1: list[bool], recall: list[float]):
    return [
        _case(f"C{i}", ("452240",), ("452240",)).model_copy(
            update={"scores": replace(_SCORES, occurrence_top1=t, finding_recall_10=r)}
        )
        for i, (t, r) in enumerate(zip(top1, recall, strict=True))
    ]


def test_a_round_is_kept_above_the_noise_with_no_harm() -> None:
    n = 200
    reference = _cases([False] * n, [0.1] * n)
    run = _cases([i < 40 for i in range(n)], [0.1] * n)  # +20 points, no finding change
    noise_a = _cases([False] * n, [0.1] * n)
    noise_b = _cases([i < 2 for i in range(n)], [0.1] * n)  # 1 point of noise
    reading = rr.read(run, reference, noise_a, noise_b, finding_round=False)
    assert reading.kept
    assert abs(reading.noise - 0.01) < 1e-9


def test_a_round_inside_the_noise_is_dropped() -> None:
    n = 200
    reference = _cases([False] * n, [0.1] * n)
    run = _cases([i < 4 for i in range(n)], [0.1] * n)  # +2 points
    noise_b = _cases([i < 10 for i in range(n)], [0.1] * n)  # 5 points of noise
    reading = rr.read(run, reference, reference, noise_b, finding_round=False)
    assert not reading.kept


def test_a_gain_that_harms_the_other_score_is_dropped() -> None:
    n = 200
    reference = _cases([False] * n, [0.5] * n)
    run = _cases([i < 40 for i in range(n)], [0.0] * n)  # top-1 up, finding recall down everywhere
    reading = rr.read(run, reference, reference, reference, finding_round=False)
    assert not reading.kept
    assert "harm" in reading.reason
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest tests/test_round_result.py -v`
Expected: FAIL with `ImportError`

- [ ] **Step 3: Write `scripts/round_result.py`**

```python
"""A guidance round's result, by decision 0098 item 4's rule; appended to its registration.

Status
    Live for S2.7 (spec §6.4), free: reads run folders; counts only.

Why
    The rule was fixed before the first round: kept only if the gain is real, larger than the
    difference between two identical runs, and costs the other score nothing clear.

Usage
    uv run python -m scripts.round_result --run RUN --reference REF --noise A B [--finding-round] [--append PATH]
"""

import argparse
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ntsb_probable_cause.scoring.metrics import bootstrap_mean
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.settings import Settings


@dataclass(frozen=True)
class Diff:
    """A paired mean difference (a - b) with its interval."""

    mean: float
    low: float
    high: float
    n: int


@dataclass(frozen=True)
class Reading:
    """A round's reading."""

    primary: Diff
    noise: float
    secondary: Diff
    kept: bool
    reason: str


def _top1(cases: Sequence[CaseResult]) -> dict[str, float]:
    return {c.case_id: float(c.scores.occurrence_top1) for c in cases if c.scores is not None and c.steps}


def _recall(cases: Sequence[CaseResult]) -> dict[str, float]:
    return {
        c.case_id: c.scores.finding_recall_10
        for c in cases
        if c.scores is not None and c.steps and c.scores.finding_recall_10 is not None
    }


def diff(a: Mapping[str, float], b: Mapping[str, float]) -> Diff:
    """Paired over the shared case ids."""
    shared = sorted(set(a) & set(b))
    if not shared:
        return Diff(0.0, 0.0, 0.0, 0)
    mean, low, high = bootstrap_mean([a[i] - b[i] for i in shared])
    return Diff(mean, low, high, len(shared))


def read(
    run: Sequence[CaseResult],
    reference: Sequence[CaseResult],
    noise_a: Sequence[CaseResult],
    noise_b: Sequence[CaseResult],
    *,
    finding_round: bool,
) -> Reading:
    """Decision 0098 item 4."""
    first, second = (_recall, _top1) if finding_round else (_top1, _recall)
    primary = diff(first(run), first(reference))
    noise = abs(diff(first(noise_a), first(noise_b)).mean)
    secondary = diff(second(run), second(reference))
    if secondary.high < 0:
        return Reading(primary, noise, secondary, False, "dropped: harm to the other score (interval wholly below zero)")
    if primary.low <= 0:
        return Reading(primary, noise, secondary, False, "dropped: the gain's interval includes zero")
    if primary.mean <= noise:
        return Reading(primary, noise, secondary, False, "dropped: the gain is inside the noise floor")
    return Reading(primary, noise, secondary, True, "kept")


def _load(run_id: str) -> list[CaseResult]:
    if "heldout" in run_id:
        raise SystemExit(f"round_result: {run_id} is a held-out run; development runs only")
    return read_jsonl(Settings().runs_dir / run_id / "cases.jsonl", CaseResult)


def _fmt(d: Diff) -> str:
    return f"{d.mean:+.1%} [{d.low:+.1%}, {d.high:+.1%}] on n={d.n}"


def main(argv: Sequence[str] | None = None) -> int:
    """Print the reading; with ``--append``, add it under the registration."""
    parser = argparse.ArgumentParser(prog="round_result")
    parser.add_argument("--run", required=True)
    parser.add_argument("--reference", required=True)
    parser.add_argument("--noise", nargs=2, required=True, metavar="RUN_ID")
    parser.add_argument("--finding-round", action="store_true")
    parser.add_argument("--append", default=None, type=Path)
    args = parser.parse_args(argv)
    reading = read(
        _load(args.run), _load(args.reference), _load(args.noise[0]), _load(args.noise[1]),
        finding_round=args.finding_round,
    )
    primary, secondary = ("finding recall@10", "occurrence top-1") if args.finding_round else ("occurrence top-1", "finding recall@10")
    text = "\n".join(
        [
            "## Result (scripts/round_result.py, decision 0098 item 4)",
            "",
            f"- run: {args.run}; reference: {args.reference}; noise pair: {args.noise[0]}, {args.noise[1]}",
            f"- {primary}: {_fmt(reading.primary)}",
            f"- noise floor ({primary}, the two identical runs): {reading.noise:.1%}",
            f"- {secondary} (do no harm): {_fmt(reading.secondary)}",
            f"- outcome: {reading.reason}",
        ]
    )
    print(text)
    if args.append is not None:
        with args.append.open("a") as handle:
            handle.write("\n" + text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the tests to verify they pass; add the target; commit**

Run: `uv run pytest tests/test_round_result.py -v` (Expected: PASS)

```make
s27-round-result:
	$(if $(N),,$(error N is required: the round number))
	$(if $(RUN),,$(error RUN is required))
	$(if $(REFERENCE),,$(error REFERENCE is required))
	$(if $(NOISE),,$(error NOISE is required: the two identical runs, space-separated, in quotes))
	uv run python -m scripts.round_result --run $(RUN) --reference $(REFERENCE) --noise $(NOISE) $(if $(FINDING),--finding-round,) --append docs/rounds/s27-round-$(N).md
# S2.7 spec §6.4, free: decision 0098 item 4's reading, appended to the round's registration.
```

Run: `make check` (Expected: PASS)

```bash
git add scripts/round_result.py tests/test_round_result.py Makefile docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 14: a guidance round's reading rule"
```

---

### Task 15: One guidance round (repeat until the stop rule) (spec §6, decision 0098)

This task is a procedure, repeated once per round. Rounds are numbered from 2 (Rounds 0 and 1 are the diagnosis and the check). Occurrence rounds come first; when two in a row are dropped, one or two finding rounds follow (`FINDING=1`); the $25 line ends everything (decision 0098 items 5–6).

**Variables for each round:** `N` (the round number), `SLUG`, `KEPT` (the kept guidance names before it, in order), `CHECK` (Round 1's outcome, empty for "no check"), `REFERENCE` (the last kept round's run, or its derived check folder when `CHECK` is set; for round 2, `REPEAT` or its derived folder), `NOISE` (`"20260926T082427-d19aafa-dev-400-B REPEAT"`, or their derived check folders when `CHECK` is set).

- [ ] **Step 1: Choose the change**

From `docs/results/s27-round0-dev.txt`: the largest miss group Andy's hand-read marked mostly "coding convention" or "wrong phase", not yet addressed. Write it down in the registration draft. One change per round (decision 0098 Why 1).

- [ ] **Step 2: Write the guidance file** `src/ntsb_probable_cause/scoring/guidance/r<N>-<SLUG>.md`

Rules: plain sentences for the model; every number quoted from `docs/results/s27-coding-stats.txt` (name the counts, e.g. "in 412 of 530 past cases"); an official definition quoted only with its source named in the registration; no case, no example taken from a `dev-400` case's text, no worked example from any real case (spec §6.2). An example of the form (the numbers come from the committed counts, never from this plan):

> When a loss of control in flight and an aerodynamic stall or spin both appear in an accident, the NTSB flagged the loss of control in flight as the defining event in N of M past cases. Put the stall or spin first only when the evidence shows the stall itself, not a loss of control, began the accident sequence; otherwise put loss of control in flight first and keep the stall among your guesses.

- [ ] **Step 3: The local sentence check** (free)

Run: `make s27-check-guidance GUIDANCE="<KEPT> r<N>-<SLUG>"`
Expected: `0 found`. If a sentence is found, reword it and re-run.

- [ ] **Step 4: Write and commit the registration** (`docs/rounds/s27-round-<N>.md`, from the template in `docs/rounds/README.md`)

```bash
git add src/ntsb_probable_cause/scoring/guidance/r<N>-<SLUG>.md docs/rounds/s27-round-<N>.md
git commit -m "S2.7 round <N>: registration and guidance (<one line>)"
```

The tree is clean now; the run records this commit.

- [ ] **Step 5: STOP — the round's run (paid, about $1.18 at v1)**

Hand Andy: "Round <N>: `make s27-round GUIDANCE="<KEPT> r<N>-<SLUG>" PER_CASE=<last cost per case rounded up>`; about $1.18, 30–60 minutes on batch; start between 01:00 and 12:00 UTC." Record the run id.

- [ ] **Step 6: The check, if Round 1 kept one**

If `CHECK` is set: `make s27-check RUN=<run id> WAY=<CHECK>` (free for `rule`; about $0.36 for `luna`). The derived id is `<run id>-check-<CHECK>`.

- [ ] **Step 7: Read the round** (free)

Run: `make s27-round-result N=<N> RUN=<run id, or its derived folder> REFERENCE=<REFERENCE> NOISE="<noise pair>" $(FINDING)`
The reading is appended to the registration. Commit it: `git commit -am "S2.7 round <N>: result (<kept|dropped>)"`.

- [ ] **Step 8: If kept — the judge (paid, about $0.50) and the outcomes**

`make s27-judge RUN=<the run that goes forward: the derived folder if CHECK is set>`; then
`uv run python -m scripts.judge_outcomes --runs <previous kept run> <this run> --label-status <validated|unvalidated> >> docs/rounds/s27-round-<N>.md` and commit. Read the misread share: if it moved beyond Round 0's label churn, say so in the registration (spec §6.4, last point).

- [ ] **Step 9: The stop rule**

`make stage-spend`. Two dropped rounds in a row ends the occurrence rounds (move to finding rounds with `FINDING=1`, one or two of them); the $25 line ends every round. Report the round to Andy in plain English (the change, the reading, kept or dropped, the spend) before starting the next.

---

## Part E — the meeting point, the sealed sample and the close (spec §7.5, §8, §9)

### Task 16: Merge track 2 back, and record the transcriber and page rule on v2 runs (spec §7.5)

**Files:**
- Modify: `scoring/runner.py` (`RunSpec`, `spec_json`, `Runner.run` refusals, `build_record`), `scoring/records.py` (`RunRecord`), `scoring/report.py` (`refuse_cross_version`, `provenance`), `apps/eval/__main__.py` (`run --transcriber --page-rule`, `_readings_for_run`)
- Test: `tests/test_runner.py`, `tests/test_report.py`, `tests/test_eval_app.py`

**Interfaces:**
- Consumes (from track 2, after the merge): `docket.transcribe.TRANSCRIBER: str`, `PAGE_RULE: PageRule`, `PAGE_RULES: tuple[PageRule, ...]`, `ReadingLookup(cache, *, model=TRANSCRIBER, instruction=TRANSCRIBE, dpi=RESOLUTION, page_rule=PAGE_RULE)` with `.model` and `.page_rule`.
- Produces: `RunSpec.transcriber: str | None = None`, `RunSpec.page_rule: str | None = None`; `RunRecord.transcriber`, `RunRecord.page_rule` (defaults None); `report.S26_V2_READING = ("qwen/qwen3.5-122b-a10b", "all")` (what a v2 record without the fields means: S2.6's transcriber and rule); CLI `run --transcriber MODEL --page-rule RULE` (defaults `TRANSCRIBER`, `PAGE_RULE`; used only at v2).

- [ ] **Step 1: STOP — track 2's merge back**

Track 2's last task merges `s27-transcriber` into this branch with a merge commit, on Andy's go-ahead. When it has: `git log --oneline -3` shows the merge; run `make check` (Expected: PASS). If `sources.py`, the `Makefile` or the decisions index conflicted, the resolution is in the merge commit; log it in Deviations.

- [ ] **Step 2: Write the failing tests**

`tests/test_runner.py`:

```python
def test_a_v2_run_records_its_transcriber_and_page_rule(tmp_path: Path, record_fixtures) -> None:
    reader = FakeDocketReader(_transcribed_docket(), version="v2")
    spec = replace(_arm_b("v2"), transcriber="qwen/qwen3.5-122b-a10b", page_rule="image-only")
    record = runner(tmp_path, RecordingFakeClient([GOOD, REFINE]), docket=reader).run(spec, record_fixtures[:1])
    assert (record.transcriber, record.page_rule) == ("qwen/qwen3.5-122b-a10b", "image-only")
    written = json.loads((tmp_path / "runs" / record.run_id / "spec.json").read_text())
    assert written["page_rule"] == "image-only"


def test_a_v2_run_without_its_reading_is_refused_and_a_v1_run_with_one_is_refused(tmp_path: Path, record_fixtures) -> None:
    reader = FakeDocketReader(_transcribed_docket(), version="v2")
    with pytest.raises(ConfigurationError, match="transcriber"):
        runner(tmp_path, RecordingFakeClient([GOOD, REFINE]), docket=reader).run(_arm_b("v2"), record_fixtures[:1])
    with pytest.raises(ConfigurationError, match="v1"):
        runner(tmp_path, RecordingFakeClient([GOOD, REFINE]), docket=FakeDocketReader(_transcribed_docket())).run(
            replace(_arm_b("v1"), transcriber="x", page_rule="all"), record_fixtures[:1]
        )
```

`tests/test_report.py`:

```python
def test_two_v2_runs_with_different_readings_are_refused_unless_labelled(run_record) -> None:
    a = run_record.model_copy(update={"evidence_version": "v2", "transcriber": "m1", "page_rule": "all"})
    b = run_record.model_copy(update={"evidence_version": "v2", "transcriber": "m2", "page_rule": "all"})
    with pytest.raises(ConfigurationError, match="transcriber"):
        refuse_cross_version(a, b, versions_compared=False)
    refuse_cross_version(a, b, versions_compared=True)
    s26 = run_record.model_copy(update={"evidence_version": "v2"})  # S2.6's record: no fields
    same_as_s26 = run_record.model_copy(update={"evidence_version": "v2", "transcriber": "qwen/qwen3.5-122b-a10b", "page_rule": "all"})
    refuse_cross_version(s26, same_as_s26, versions_compared=False)
```

(`_arm_b(version, *, sync=True)` and `_transcribed_docket()` are `tests/test_runner.py`'s own helpers; `replace` is `dataclasses.replace`, since `RunSpec` is a frozen dataclass. Match `refuse_cross_version`'s real exception type.)

Run: `uv run pytest tests/test_runner.py tests/test_report.py -v -k "reading or transcriber"` (Expected: FAIL)

- [ ] **Step 3: Implement**

- `RunSpec`: `transcriber: str | None = None`, `page_rule: str | None = None`.
- `Runner.run`, beside the v2/v3 refusals: a v2 arm B run with either field None raises `ConfigurationError("a v2 run records its transcriber and page rule (S2.7 spec §7.5)")`; a v1 run with either set raises `ConfigurationError("a v1 run reads no transcription; transcriber and page rule are for v2 runs")`.
- `spec_json`: when `spec.evidence_version == "v2"`, add `"transcriber"` and `"page_rule"` before `commit_sha` (v1 folders keep their keys).
- `RunRecord`: `transcriber: str | None = None`, `page_rule: str | None = None`; `build_record` sets both.
- `report.py`: `S26_V2_READING = ("qwen/qwen3.5-122b-a10b", "all")  # a v2 record from before S2.7 read S2.6's transcriber with every page (0087)`; in `refuse_cross_version`, when both records are v2 and `(t or S26[0], r or S26[1])` differ, raise unless `versions_compared`, naming both readings; `provenance` prints `transcriber=... page_rule=...` on a v2 record.
- `apps/eval`: `run --transcriber` (default `transcribe.TRANSCRIBER`) and `--page-rule` (choices `transcribe.PAGE_RULES`, default `transcribe.PAGE_RULE`); `_readings_for_run` builds `ReadingLookup(TranscriptionCache(settings.transcription_dir), model=args.transcriber, page_rule=args.page_rule)` (its `is_done` then checks the marker for that model and rule); `RunSpec` gets `transcriber`/`page_rule` only when `--evidence-version v2`.

Run: `uv run pytest tests/test_runner.py tests/test_report.py tests/test_eval_app.py -v` (Expected: PASS)

- [ ] **Step 4: Run the full check and commit**

Run: `make check` (Expected: PASS)

```bash
git add src/ntsb_probable_cause/scoring/runner.py src/ntsb_probable_cause/scoring/records.py src/ntsb_probable_cause/scoring/report.py apps/eval/__main__.py tests/test_runner.py tests/test_report.py tests/test_eval_app.py docs/plans/2026-09-26-s27-track1-coding-guidance.md
git commit -m "S2.7 Task 16: v2 runs record their transcriber and page rule (spec §7.5)"
```

---

### Task 17: The meeting point (spec §8)

**Files:**
- Modify: `Makefile`
- Create (by running): `docs/results/s27-meeting-dev.txt`
- Create: one decision record for Andy's v2 and v3 decisions (the next free number above 0100)

- [ ] **Step 1: Apply track 2's outcome to `dev-400`**

If track 2's decision kept Qwen with the rule `all`, nothing to do: S2.6's readings and marker stand. Otherwise run track 2's transcription targets for `dev-400` with the chosen `--model` and `--page-rule`: the dry run first (free; prints pages and projected cost), then — **STOP** for Andy — the paid run (estimate $1–7, spec §8).

- [ ] **Step 2: STOP — the v2 run under the final guidance (paid, about $1.33 plus the judge's $0.50)**

Hand Andy: `make s27-round GUIDANCE="<every kept name>" EVIDENCE=v2 PER_CASE=0.0042 EST=1.60` (the v2 run needs the transcriber and rule flags only if they differ from the defaults Task 16 set). Then, if `CHECK` is set, `make s27-check RUN=<v2 run> WAY=<CHECK>`; then `make s27-judge RUN=<the v2 run that goes forward>`.

- [ ] **Step 3: The comparison** (free)

```make
s27-meeting-results:
	$(if $(V1),,$(error V1 is required: the last kept v1 run (its derived folder if a check is kept)))
	$(if $(V2),,$(error V2 is required: the v2 run (its derived folder if a check is kept)))
	{ uv run ntsb-eval report $(V2) --against $(V1) --versions-compared; \
	  echo; uv run python -m scripts.judge_outcomes --runs $(V1) $(V2) --label-status $(or $(LABELS),unvalidated); } > docs/results/s27-meeting-dev.txt
```

Run it, commit the Makefile and the results file.

- [ ] **Step 4: STOP — Andy's decisions**

Report in plain English, one decision per message: (1) does v2 go forward (top-1, top-3, finding recall@10 and the outcomes, v2 against v1 under the final guidance)? (2) does the picture probe (v3) run in S2.7? Write one decision record holding both answers, with Andy's words, in the project's format; add it to `docs/decisions/README.md`; commit.

---

### Task 18: The sealed sample, and the prediction scored (spec §9, decisions 0095, 0098 item 7)

**Files:**
- Create: `docs/rounds/s27-sealed.md`, `scripts/sealed_report.py`
- Modify: `Makefile`
- Test: `tests/test_sealed_report.py` (create)
- Create (by running): `docs/results/s27-sealed-dev.txt`

**Interfaces:**
- Produces: `sealed_report.prediction_lines(dev_top1: float, sealed_top1: float, misread_moved: bool | None) -> list[str]`; `main(argv)` with `--dev RUN`, `--sealed RUN`, `--misread-moved {yes,no,unvalidated}`, `--out`.

- [ ] **Step 1: Write the failing tests** (`tests/test_sealed_report.py`)

```python
"""scripts/sealed_report.py: the prediction of decision 0098 item 7, scored."""

from scripts import sealed_report as sr


def test_prediction_lines_score_each_part() -> None:
    lines = sr.prediction_lines(dev_top1=0.33, sealed_top1=0.30, misread_moved=False)
    assert "top-1 on dev-400 between 30% and 36%: 33.0% -- met" in lines
    assert "sealed below dev-400 by less than 5 points: 3.0 points -- met" in lines
    assert "misread share did not move beyond label churn: met" in lines


def test_prediction_lines_report_a_miss_plainly() -> None:
    lines = sr.prediction_lines(dev_top1=0.25, sealed_top1=0.26, misread_moved=None)
    assert "top-1 on dev-400 between 30% and 36%: 25.0% -- not met" in lines
    assert "sealed below dev-400 by less than 5 points: -1.0 points -- not met" in lines
    assert "misread share: not scored (the narrative label was not validated)" in lines
```

- [ ] **Step 2: Run them to verify they fail, then write `scripts/sealed_report.py`**

```python
"""The sealed sample's result beside dev-400's, and the prediction of decision 0098 item 7.

Status
    Once, at S2.7's end (spec §9), free: reads two run folders (or their derived check
    folders); counts only. Writes docs/results/s27-sealed-dev.txt.

Why
    The sealed sample is the one clean check that guidance written from dev-400 generalises
    (decision 0095). The prediction was written before Round 1 and is published either way.

Usage
    uv run python -m scripts.sealed_report --dev RUN --sealed RUN --misread-moved {yes,no,unvalidated} [--out PATH]
"""

import argparse
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.records import CaseResult, read_jsonl
from ntsb_probable_cause.settings import Settings

PREDICTED_LOW, PREDICTED_HIGH = 0.30, 0.36
MAX_DROP_POINTS = 5.0


def prediction_lines(dev_top1: float, sealed_top1: float, misread_moved: bool | None) -> list[str]:
    """Each part of the prediction, scored plainly."""
    met = PREDICTED_LOW <= dev_top1 <= PREDICTED_HIGH
    drop = (dev_top1 - sealed_top1) * 100
    lines = [
        f"top-1 on dev-400 between 30% and 36%: {dev_top1:.1%} -- {'met' if met else 'not met'}",
        f"sealed below dev-400 by less than 5 points: {drop:.1f} points -- "
        f"{'met' if 0 < drop < MAX_DROP_POINTS else 'not met'}",
    ]
    if misread_moved is None:
        lines.append("misread share: not scored (the narrative label was not validated)")
    else:
        lines.append(f"misread share did not move beyond label churn: {'not met' if misread_moved else 'met'}")
    return lines


def _top1(run_id: str) -> tuple[float, int, int]:
    if "heldout" in run_id:
        raise SystemExit(f"sealed_report: {run_id} is a held-out run")
    cases = [c for c in read_jsonl(Settings().runs_dir / run_id / "cases.jsonl", CaseResult) if c.scores is not None and c.steps]
    hits = sum(c.scores.occurrence_top1 for c in cases if c.scores is not None)
    return (hits / len(cases) if cases else 0.0), hits, len(cases)


def main(argv: Sequence[str] | None = None) -> int:
    """Print both results and the prediction."""
    parser = argparse.ArgumentParser(prog="sealed_report")
    parser.add_argument("--dev", required=True)
    parser.add_argument("--sealed", required=True)
    parser.add_argument("--misread-moved", choices=("yes", "no", "unvalidated"), required=True)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    dev, dev_hits, dev_n = _top1(args.dev)
    sealed, sealed_hits, sealed_n = _top1(args.sealed)
    moved = None if args.misread_moved == "unvalidated" else args.misread_moved == "yes"
    low_d, high_d = wilson(dev_hits, dev_n)
    low_s, high_s = wilson(sealed_hits, sealed_n)
    text = "\n".join(
        [
            "the sealed sample (scripts/sealed_report.py; counts only, decisions 0095, 0098)",
            f"dev-400 ({args.dev}): top-1 {dev:.1%} [{low_d:.1%}, {high_d:.1%}], {dev_hits} of {dev_n}",
            f"dev-seal-400 ({args.sealed}): top-1 {sealed:.1%} [{low_s:.1%}, {high_s:.1%}], {sealed_hits} of {sealed_n}",
            "",
            "the prediction (decision 0098 item 7):",
            *prediction_lines(dev, sealed, moved),
        ]
    )
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

Run: `uv run pytest tests/test_sealed_report.py -v` (Expected: PASS); commit (`S2.7 Task 18: the sealed report`).

- [ ] **Step 3: Register the final setup** (`docs/rounds/s27-sealed.md`)

Name exactly: every kept guidance file in order and the `guidance_sha256` of the last kept run; the check way (or none); the evidence version and, at v2, the transcriber and page rule; model `openai/gpt-6-luna` at `medium`, batch, reply budget 8,000; the `dev-400` run it is compared with. Commit it alone: `git commit -m "S2.7: the sealed sample's registration (decision 0095)"`. From this commit, `dev-seal-400` opens.

- [ ] **Step 4: Verify the sealed list** (free)

Run: `uv run python -m scripts.draw_sealed --verify` (Expected: `identical: True`)

- [ ] **Step 5: STOP — fetch and, at v2, transcribe the sealed sample**

At v2, hand Andy track 2's transcription dry run for `dev-seal-400` (free; its live docket client fetches the dockets, about 3,500 documents at 2 seconds per request, a few hours), then the paid transcription (estimate $1–14, spec §9.1). At v1, the run of Step 6 fetches the dockets itself.

- [ ] **Step 6: STOP — the sealed run, once (paid, about $1.20–1.35 plus the judge)**

```make
s27-sealed-run:
	$(if $(PER_CASE),,$(error PER_CASE is required))
	uv run python -m scripts.stage_spend --estimate $(or $(EST),1.80)
	uv run ntsb-eval run --arm B --sample dev-seal-400 --evidence-version $(or $(EVIDENCE),v1) --expected-cost-per-case-usd $(PER_CASE) $(foreach g,$(GUIDANCE),--guidance $(g))
```

Hand Andy: `make s27-sealed-run GUIDANCE="<kept names>" EVIDENCE=<v1|v2> PER_CASE=<…>`; then the check (if kept) and `make s27-judge` on the run that goes forward. `ntsb-eval judge` refuses a sample other than `dev-400` without `--validated`: pass `--validated` only if Task 6's outcome was `validated`; otherwise skip the judge on the sealed run and record that.

- [ ] **Step 7: The results and the prediction** (free)

Run: `uv run python -m scripts.sealed_report --dev <final dev-400 run> --sealed <sealed run> --misread-moved <yes|no|unvalidated> --out docs/results/s27-sealed-dev.txt`
Commit. Report to Andy in plain English, with the prediction scored whichever way it came out; then **STOP** for his held-out decision (spec §9.3).

---

### Task 19: Close-out (decision 0017)

- [ ] **Step 1:** Update `CLAUDE.md` (this repository): S2.7's line in "What this repo is", the `make` targets added by both tracks in **Commands**, `ntsb-eval check` and `run --guidance/--transcriber/--page-rule` in the `ntsb-eval` paragraph, `TYPESAFE_API_KEY` in the settings paragraph, and the eval-bars section's pointer to S2.7's results. Commit.
- [ ] **Step 2:** Run the `close-stage` skill: the As-built record on the specification (every Deviations entry of both plans, grouped and rewritten plainly), specification status Implemented, the roadmap's S2.7 entry marked done, both plans deleted, `version` set in `pyproject.toml`.
- [ ] **Step 3:** `uv run python -m scripts.check_docs` and `make check`. Expected: both clean.
- [ ] **Step 4:** Push and open the pull request `S2.7: coding guidance` (merge commit, never squashed; decision 0033). Andy creates the release after the merge.

## Deviations

*Log every departure from the specification here, dated, with the reason. Moved into the As-built record at close-out (decision 0017).*
