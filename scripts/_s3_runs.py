"""Reading finished ``dev-400`` arm C runs, shared by the scripts that measure the noise floor.

Status
    Live helper (decision 0059), no model call. It holds what ``scripts/s3_noise_floor.py`` first
    wrote for itself and the S3.2 free readings (``s32_*.py``) need as well: the refusals made
    before a case is read, the run read whole, and the one place a result file is written from.
    Moved here without a change of behaviour: ``make s3-noise-report`` prints the same bytes.

Refusals, before any case or trail is read
    A held-out run id; a folder with no ``run.jsonl``, or whose record names another run (a
    copied or renamed folder); a run on any sample but ``dev-400``, of any arm but C, or not
    finished; a run on part of ``dev-400`` (a ``--limit`` run); a run from a tree with
    uncommitted changes (the noise floor is measured on one frozen commit); a run with no
    readable ``spec.json`` or no ``trail.jsonl``; and runs configured differently. Two runs are
    configured alike when their ``spec.json`` files are equal key for key, apart from
    ``budget_usd`` and ``expected_cost_per_case_usd``: those two only size the budget
    reservation and never reach a model call. Once the cases are read, a case outside the
    development split is refused too.

Writing a result
    :func:`write_result` refuses to write under ``docs/results/`` from a tree with uncommitted
    changes, so a committed number always names the commit that printed it. A file under
    ``docs/results/`` is the output of these scripts, so it does not count as a change: four
    scripts can run one after the other. The frozen curve file is the calibration script's output
    alone: for every other caller an uncommitted edit of it is a change and is refused.
"""

import json
import string
import subprocess
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, NoReturn

from ntsb_probable_cause.agent.run import TRAIL_FILE
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings

SAMPLE: Final = "dev-400"
# Settings that only size the budget reservation; they never reach a model call.
RESERVATION_ONLY: Final = ("budget_usd", "expected_cost_per_case_usd")
MISSING: Final = "(not recorded)"
RESULTS_DIR: Final = "docs/results"
# Files a free reading writes: their presence does not make the tree "dirty" for the next one.
# The curve file is the calibration script's output alone (``write_result(..., own_curve=True)``).
_RESULTS_PREFIX: Final = "docs/results/"
CURVE_PATH: Final = "src/ntsb_probable_cause/scoring/tables/calibration_s3.json"


@dataclass(frozen=True)
class Run:
    """One run, read whole: its label in the report, record, ``spec.json``, cases and trail."""

    label: str
    record: RunRecord
    spec: dict[str, object]
    cases: list[CaseResult]
    calls: list[AgentCall]


def refuse(prog: str, message: str) -> NoReturn:
    """Stop with ``<prog>: <message>``."""
    raise SystemExit(f"{prog}: {message}")


def _head(prog: str, run_id: str) -> tuple[RunRecord, dict[str, object]]:
    """A run's record and ``spec.json``, after every refusal that needs no case."""
    try:
        samples.refuse_unless_development(run_id, None)
    except ConfigurationError as error:
        refuse(prog, str(error))
    folder = Settings().runs_dir / run_id
    if not (folder / "run.jsonl").is_file():
        refuse(prog, f"{run_id}: no run.jsonl in {folder}")
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    if record.run_id != run_id:
        refuse(
            prog, f"{run_id}: its run.jsonl names run {record.run_id}: a copied or renamed folder"
        )
    if record.sample != SAMPLE:
        refuse(
            prog, f"{run_id} is on {record.sample}; the noise floor is measured on {SAMPLE} only"
        )
    if record.arm != "C":
        refuse(prog, f"{run_id} is arm {record.arm}, not arm C")
    if record.finished is None:
        refuse(prog, f"{run_id} has not finished: it did not complete a pass")
    spec = _spec(prog, folder, run_id)
    if record.dirty or spec.get("dirty"):
        refuse(
            prog,
            f"{run_id} ran from a tree with uncommitted changes; the noise floor is measured on "
            "one frozen commit, from a clean tree (plan Task 14)",
        )
    if spec.get("case_ids") != list(samples.sample_ids(SAMPLE)):
        refuse(
            prog,
            f"{run_id} is not the whole of {SAMPLE} (a --limit run?); decision 0130 measures the "
            "noise floor on the whole sample",
        )
    if not (folder / TRAIL_FILE).is_file():
        refuse(prog, f"{run_id}: no {TRAIL_FILE} in {folder}")
    return record, spec


def _spec(prog: str, folder: Path, run_id: str) -> dict[str, object]:
    path = folder / "spec.json"
    try:
        recorded = json.loads(path.read_text()) if path.is_file() else None
    except json.JSONDecodeError:
        recorded = None
    if not isinstance(recorded, dict):
        refuse(prog, f"{run_id}: no readable spec.json in {folder}")
    return recorded


def refuse_mismatched(prog: str, heads: Sequence[tuple[RunRecord, dict[str, object]]]) -> None:
    """Refuse runs whose ``spec.json`` differ at any key but the reservation-only ones."""
    (first, mine), *others = heads
    for other, theirs in others:
        for key in dict.fromkeys([*mine, *theirs]):
            if key in RESERVATION_ONLY:
                continue
            a, b = mine.get(key, MISSING), theirs.get(key, MISSING)
            if a != b:
                # A case list is case numbers: never repeated in a message.
                shown = (
                    "" if key == "case_ids" else f" ({first.run_id}: {a!r}; {other.run_id}: {b!r})"
                )
                refuse(
                    prog,
                    f"{other.run_id} is configured differently from {first.run_id}: spec.json "
                    f"differs at {key!r}{shown}; the noise floor compares identical runs "
                    "(spec §10.2)",
                )


def read_run(prog: str, label: str, run_id: str, head: tuple[RunRecord, dict[str, object]]) -> Run:
    """A run's cases and trail, after its head was accepted."""
    folder = Settings().runs_dir / run_id
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        refuse(prog, f"{run_id} holds a case outside the dev split")
    calls = read_jsonl(folder / TRAIL_FILE, AgentCall)
    record, spec = head
    return Run(label, record, spec, cases, calls)


def load_runs(prog: str, run_ids: Sequence[str]) -> list[Run]:
    """Refuse what must be refused, then read each run; labels are ``a``, ``b``, ``c``, ...

    Args:
        prog: the script's name, put first in a refusal.
        run_ids: finished ``dev-400`` arm C run ids, each named once.

    Raises:
        SystemExit: a run is named twice, or any refusal in the module's docstring applies.
    """
    if len(set(run_ids)) != len(run_ids):
        refuse(prog, "a run is named twice; these readings compare distinct runs")
    heads = [_head(prog, run_id) for run_id in run_ids]
    refuse_mismatched(prog, heads)
    return [
        read_run(prog, label, run_id, head)
        for label, run_id, head in zip(string.ascii_lowercase, run_ids, heads, strict=False)
    ]


def changed_files() -> list[str]:
    """The paths ``git status --porcelain`` lists, relative to the repository root."""
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],  # noqa: S607 -- git on PATH
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line[3:].split(" -> ")[-1] for line in out.splitlines() if line.strip()]


def refuse_unclean_results(prog: str, out: Path, *, own_curve: bool = False) -> None:
    """Refuse when ``out`` is under ``docs/results/`` and some other file has changed.

    Split out of :func:`write_result` so that a script can refuse before it reads anything. The
    rule is the same: a file under ``docs/results/`` is the proof of a number, so the number
    must come from a clean tree. A file under ``docs/results/`` (the free readings' own outputs)
    is not counted as a change. The frozen curve file is not counted either, but only for the
    calibration script (``own_curve=True``).

    Raises:
        SystemExit: ``out`` is under ``docs/results/`` and some other file has changed.
    """
    if out.resolve().is_relative_to(Path(RESULTS_DIR).resolve()):
        allowed = (_RESULTS_PREFIX, CURVE_PATH) if own_curve else (_RESULTS_PREFIX,)
        dirty = [path for path in changed_files() if not path.startswith(allowed)]
        if dirty:
            refuse(
                prog,
                f"the tree has {len(dirty)} uncommitted change(s) outside the results files; a "
                f"file under {RESULTS_DIR}/ is written from a clean tree only",
            )


def write_result(prog: str, out: Path, text: str, *, own_curve: bool = False) -> None:
    """Write ``text`` to ``out``; refuse a dirty tree when ``out`` is under ``docs/results/``.

    A file written under ``docs/results/`` is committed as the proof of a number, so the number
    must come from a clean tree (:func:`refuse_unclean_results`). The frozen curve file is not
    counted as a change for the calibration script alone (``own_curve=True``): for any other
    caller an uncommitted edit of the curve is a change and is refused.

    Args:
        prog: the script's name, put first in a refusal.
        out: where to write.
        text: the text; a newline is added.
        own_curve: True only for the script that writes the curve file.

    Raises:
        SystemExit: ``out`` is under ``docs/results/`` and some other file has changed.
    """
    refuse_unclean_results(prog, out, own_curve=own_curve)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(text + "\n")
