"""The public site's numbers file (S5 spec §17.3): every figure the site prints, by key.

Status
    Repeatable, free: reads committed ``docs/results/*.txt`` files only, makes no model call
    and computes nothing (decision 0059). Each number is read from exactly one line of one
    results file by a fixed pattern, so the site never types a number and never quotes one
    that a re-run has moved: ``tests/test_site_numbers.py`` fails while the committed file
    differs from a fresh build.

Why
    Rule 3: every reported number comes from a script. The results files are that record;
    this script only carries their figures to the site, each with its interval, count,
    sample, model, run, results file and the script that wrote that file. Costs are billed
    costs only: the list price is a budgeting estimate, and what was charged is what the site
    reports (Andy, 2026-10-14).

Commits (S5 step 5; Andy, 2026-10-14, plan choice 2)
    Each entry names ``recorded_in``, the commit that last changed its results file, so the
    Methods page can link the file as it was; and, when it has a run, ``run_commit``, the
    commit in the run's name, which the run started from. A results file with uncommitted
    changes is refused (``UncommittedError``): every commit named must exist.

Failures
    A pattern that matches no line, or more than one, raises ``ExtractError`` naming the
    entry and the file, and nothing is written. A file that prints one block twice (S2.4's
    bars print arm B's report twice) is read through a source marked ``repeated``, which
    accepts several matches only when they read the same.

Usage
    uv run python -m scripts.site_numbers           # writes site/data/numbers.json
    uv run python -m scripts.site_numbers --check   # exit 1, naming the first stale key
"""

import argparse
import functools
import json
import re
import subprocess
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel, ConfigDict

_REPO = Path(__file__).resolve().parents[1]
_RESULTS = _REPO / "docs/results"
_REGISTRATION = _REPO / "docs/rounds/s3-registration.md"
_OUT = _REPO / "site/data/numbers.json"

_NUM = r"[+-]?\d+(?:\.\d+)?"
_V = rf"(?P<value>{_NUM})"
_L = rf"(?P<low>{_NUM})"
_H = rf"(?P<high>{_NUM})"
_N = r"(?P<n>\d+)"
# A rate with its interval and count, and a paired difference in points, as the files print them.
_PCT_CI = rf"{_V}% \[{_L}%, {_H}%\], n={_N}"
_PTS_CI = rf"{_V} points \[{_L}, {_H}\], n={_N}"
# The eval report's paired line: "+14.3% [+9.2%, +19.3%] on n=336 cases" (points, not a rate)
_PAIRED = rf"^- occurrence top-1: {_V}% \[{_L}%, {_H}%\] on n={_N} cases$"
# A section ends at a blank line, a "[name]" block or a heading once it holds a line. Another
# block's header line ("fatal: paired difference ... cases:") ends it at once: only the section's
# own "paired difference ...:" line may open it, so a missing overall block is never read from
# the fatal block beneath (review, 2026-10-14).
_SECTION_END = re.compile(r"^$|^\[|^#")
_BLOCK_HEADER = re.compile(r"^[^-].*:$")
_OPENING = re.compile(r"^paired difference ")

_LUNA = "openai/gpt-6-luna"
_EVAL = "apps/eval"
_CLAIMS = "scripts/s32_claims.py"
_DIAGNOSIS = "scripts/exploratory/s32_heldout_diagnosis.py"
_MISSES = "scripts/occurrence_misses.py"

Unit = Literal["percent", "points", "usd", "count"]


class Entry(BaseModel):
    """One printed figure and where it came from."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    value: float
    low: float | None
    high: float | None
    n: int | None
    unit: Unit
    sample: str
    model: str
    run: str | None
    run_commit: str | None
    results_file: str
    recorded_in: str
    script: str
    label: str


class Numbers(BaseModel):
    """The numbers file: entries by key, short lists, and texts (question 6's one sentence).

    Format 2 added ``texts`` (S5 step 4b): a figure's words read from a results file, never
    typed into a page. Format 3 (step 5) added each entry's ``run_commit`` and ``recorded_in``.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: Literal["site-numbers/3"] = "site-numbers/3"
    entries: dict[str, Entry]
    lists: dict[str, list[dict[str, str | int]]]
    texts: dict[str, str]


class ExtractError(Exception):
    """A pattern found no line, or more than one, in a results file."""

    def __init__(self, key: str, file: str, pattern: str, found: int) -> None:
        lines = "no line" if found == 0 else f"{found} lines"
        super().__init__(f"{key}: {lines} in {file} match {pattern!r}")


class UncommittedError(Exception):
    """A results file has uncommitted changes, or was never committed."""

    def __init__(self, path: str) -> None:
        super().__init__(f"{path} is not committed as it stands: commit it, then rebuild")


def recorded_in(path: str) -> str:
    """The commit that last changed ``path`` (repository-relative); refuses an uncommitted file."""

    def git(*args: str) -> str:
        return subprocess.run(  # noqa: S603 -- fixed argv, no shell
            ["git", *args],  # noqa: S607 -- git from PATH
            cwd=_REPO,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    if git("status", "--porcelain", "--", path):
        raise UncommittedError(path)
    sha = git("log", "-1", "--format=%H", "--", path)
    if not sha:
        raise UncommittedError(path)
    return sha


def first_recorded(path: str) -> tuple[str, str]:
    """The commit that added ``path`` (repository-relative), and its date: ``(sha, YYYY-MM-DD)``."""
    shown = subprocess.run(  # noqa: S603 -- fixed argv, no shell
        ["git", "log", "--diff-filter=A", "--format=%H %cs", "--", path],  # noqa: S607
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=True,
    ).stdout.split()
    match shown:  # one commit and its date; nothing when never added, more when added twice
        case [sha, date]:
            return sha, date
        case _:
            raise UncommittedError(path)


_RUN_COMMIT = re.compile(r"^\d{8}T\d{6}-(?P<sha>[0-9a-f]{7})-")


@dataclass(frozen=True)
class _Source:
    """Where in a results file a line is looked for: the whole file, or one section.

    ``until`` ends the section at a matching line instead of the default rule (blank lines then
    stay inside it); ``repeated`` accepts a section, or a line, found more than once when every
    copy reads the same.
    """

    file: str
    section: str | None = None
    until: str | None = None
    repeated: bool = False


@dataclass(frozen=True)
class _Spec:
    key: str
    source: _Source
    pattern: str
    unit: Unit
    sample: str
    model: str
    script: str
    label: str
    run: str | None = None  # a pattern whose group "run" is the run id
    run_source: _Source | None = None  # where to look for it; default: the number's source


def _lines(results_dir: Path, source: _Source, key: str) -> list[str]:
    path = results_dir / source.file
    lines = path.read_text().splitlines()
    if source.section is None:
        return lines
    starts = [i for i, line in enumerate(lines) if re.search(source.section, line)]
    bodies = [_body(lines[i + 1 :], source.until) for i in starts]
    if len(starts) != 1 and not (source.repeated and starts and _same(bodies)):
        raise ExtractError(key, source.file, source.section, len(starts))
    return bodies[0]


def _same(copies: Sequence[object]) -> bool:
    return all(copy == copies[0] for copy in copies)


def _body(lines: Sequence[str], until: str | None) -> list[str]:
    body: list[str] = []
    for line in lines:
        if until is not None:
            if re.search(until, line):
                break
        else:
            opening = not body and _OPENING.search(line)
            ended = _SECTION_END.search(line) and body
            if (_BLOCK_HEADER.search(line) and not opening) or ended:
                break
        body.append(line)
    return body


def _one(results_dir: Path, source: _Source, pattern: str, key: str) -> re.Match[str]:
    found = [m for line in _lines(results_dir, source, key) if (m := re.search(pattern, line))]
    if len(found) != 1 and not (source.repeated and found and _same([m.string for m in found])):
        raise ExtractError(key, source.file, pattern, len(found))
    return found[0]


def _float(m: re.Match[str], group: str) -> float | None:
    text = m.groupdict().get(group)
    return None if text is None else float(text)


def _entry(results_dir: Path, spec: _Spec, recorded: Callable[[str], str]) -> Entry:
    m = _one(results_dir, spec.source, spec.pattern, spec.key)
    value = _float(m, "value")
    if value is None:  # pragma: no cover -- every pattern names the group "value"
        raise ExtractError(spec.key, spec.source.file, spec.pattern, 0)
    n = m.groupdict().get("n")
    run = (
        None
        if spec.run is None
        else _one(results_dir, spec.run_source or spec.source, spec.run, spec.key).group("run")
    )
    run_commit = None if run is None else _RUN_COMMIT.search(run)
    if run is not None and run_commit is None:
        raise ExtractError(spec.key, spec.source.file, _RUN_COMMIT.pattern, 0)
    results_file = f"docs/results/{spec.source.file}"
    return Entry(
        value=value,
        low=_float(m, "low"),
        high=_float(m, "high"),
        n=None if n is None else int(n),
        unit=spec.unit,
        sample=spec.sample,
        model=spec.model,
        run=run,
        run_commit=None if run_commit is None else run_commit.group("sha"),
        results_file=results_file,
        recorded_in=recorded(results_file),
        script=spec.script,
        label=spec.label,
    )


_BASELINE = _Source("s1-baseline.txt")
_CLAIMS_FILE = _Source("s32-claims-heldout.txt")
_NO_DOCKET = _Source("s32-claims-heldout.txt", r"^\[the loop without the docket\]$")
_LOOP_BLOCK = _Source("s32-claims-heldout.txt", r"^\[the loop\]$")
_DIAG = _Source("s32-heldout-diagnosis.txt")
_PAGES = _Source("s26-page-kinds.txt", r"^## pages by kind$")
_MISS_FILE = _Source("s26-occurrence-misses-dev.txt")
_MISS_S3_FILE = _Source("s5-occurrence-misses-s3-dev.txt")
_ONE_FILE = _Source("s5-one-sentence-dev.txt")
_PATH_FILE = _Source("s5-belief-path-heldout.txt")
_PATH_SCRIPT = "scripts/exploratory/s5_belief_path.py"
_PATH_RUN = r"^the loop: (?P<run>\S+)$"

_RUN_LINE = r"^run (?P<run>\S+) \[complete\]$"
# The harness report's table row for all cases: its count, then occurrence top-1.
_ALL_ROW = rf"^\| all \| {_N} \| {_V}% \[{_L}%, {_H}%\] \|"
_S24_UNTIL = r"^(run |against |paired |model comparison )"
_S24_FIXED = _Source(
    "s24-bars.txt", r"^run \S+-heldout-400-B \[complete\]$", until=_S24_UNTIL, repeated=True
)
_S24_CEILING = _Source(
    "s24-bars.txt", r"^run \S+-heldout-400-ceiling \[complete\]$", until=_S24_UNTIL
)
_NOISE_FILE = _Source("s3-noise-floor-dev.txt", repeated=True)


def _page_kind(slug: str, words: str) -> _Spec:
    return _Spec(
        f"q4.pages.{slug}",
        _PAGES,
        rf"^  {words}\s+{_V}\s+\d+\s+\d+$",
        "count",
        "dev-400",
        "none",
        "scripts/page_kinds.py",
        f"pages in dev-400's dockets: {words}",
    )


def _misses(prefix: str, source: _Source, who: str) -> tuple[_Spec, _Spec]:
    """Question 5's two counts from one ``occurrence_misses`` results file."""
    return (
        _Spec(
            f"{prefix}.first_right",
            source,
            rf"^first guess = the NTSB's first code: {_V} of {_N} \(",
            "count",
            "dev-400",
            _LUNA,
            _MISSES,
            f"{who}: the first guess is the NTSB's first code",
            run=_RUN_LINE,
        ),
        _Spec(
            f"{prefix}.in_sequence",
            source,
            rf"^first guess anywhere in the NTSB's sequence: {_V} of {_N} \(",
            "count",
            "dev-400",
            _LUNA,
            _MISSES,
            f"{who}: the first guess is somewhere in the NTSB's sequence",
            run=_RUN_LINE,
        ),
    )


def _path_count(key: str, pattern: str, label: str) -> _Spec:
    """One of question 7's counts from decision 0186's reading."""
    return _Spec(
        f"q7.path.{key}",
        _PATH_FILE,
        pattern,
        "count",
        "heldout-400",
        _LUNA,
        _PATH_SCRIPT,
        f"the loop's beliefs against the NTSB's first code: {label}",
        run=_PATH_RUN,
    )


_MOVES: Final = ("stayed right", "fixed", "broken", "stayed wrong")


def _path_moves(key: str, words: str) -> tuple[_Spec, ...]:
    """The four ways a case moved between two checkpoints, one entry each."""
    specs: list[_Spec] = []
    for move in _MOVES:
        parts = [rf"{m} {_V if m == move else r'\d+'}" for m in _MOVES]
        specs.append(
            _path_count(
                f"{key}.{move.replace(' ', '_')}",
                rf"^{words}: {', '.join(parts)}$",
                f"{words}, {move}",
            )
        )
    return tuple(specs)


_SPECS: tuple[_Spec, ...] = (
    _Spec(
        "ladder.baseline.top1",
        _BASELINE,
        rf"^Honest baseline \(fit on development, scored on all held-out, n={_N}\): "
        rf"top-1 {_V}% \[{_L}%, {_H}%\]",
        "percent",
        "held-out (all)",
        "none",
        f"{_EVAL} (ntsb-eval baseline)",
        "always guess the commonest code: occurrence top-1",
    ),
    _Spec(
        "ladder.no_docket.top1",
        _CLAIMS_FILE,
        rf"^the loop without the docket top-1: {_PCT_CI} ",
        "percent",
        "heldout-400",
        _LUNA,
        _CLAIMS,
        "the loop without the docket: occurrence top-1",
        run=_RUN_LINE,
        run_source=_NO_DOCKET,
    ),
    _Spec(
        "ladder.fixed.top1",
        _DIAG,
        rf"^arm B check top-1: {_PCT_CI} ",
        "percent",
        "heldout-400",
        _LUNA,
        _DIAGNOSIS,
        "the fixed pipeline (arm B): occurrence top-1",
        run=r"^arm B check: (?P<run>\S+)$",
    ),
    _Spec(
        "ladder.loop.top1",
        _DIAG,
        rf"^the loop top-1: {_PCT_CI} ",
        "percent",
        "heldout-400",
        _LUNA,
        _DIAGNOSIS,
        "the loop, version 1: occurrence top-1",
        run=r"^the loop: (?P<run>\S+)$",
    ),
    _Spec(
        "ladder.fixed.billed",
        _CLAIMS_FILE,
        rf"^arm B billed {_V} USD \(",
        "usd",
        "heldout-400",
        _LUNA,
        _CLAIMS,
        "the fixed pipeline (arm B): cost billed, its three parts",
    ),
    _Spec(
        "ladder.loop.billed",
        _CLAIMS_FILE,
        rf"^cost, billed \(spec §6\): loop billed {_V} USD, computed {_NUM} USD$",
        "usd",
        "heldout-400",
        _LUNA,
        _CLAIMS,
        "the loop, version 1: cost billed",
        run=_RUN_LINE,
        run_source=_LOOP_BLOCK,
    ),
    _Spec(
        "q3.docket_gain",
        _Source("s24-bars.txt", r"^against \S+-heldout-400-ceiling:$"),
        _PAIRED,
        "points",
        "heldout-400",
        _LUNA,
        f"{_EVAL} (ntsb-eval report)",
        "S2.4's fixed pipeline, before its coding tools, against S2.4's one-shot ceiling: "
        "occurrence top-1, paired",
    ),
    _Spec(
        "q4.v2_gain",
        _Source(
            "s26-armB-v2-dev.txt",
            r"^evidence-version comparison \(decision 0076\): v2 against v1",
        ),
        _PAIRED,
        "points",
        "dev-400",
        _LUNA,
        f"{_EVAL} (ntsb-eval report)",
        "words read from page images (v2) against text layers only (v1): top-1, paired",
    ),
    _page_kind("text_only", "text only"),
    _page_kind("image_only", "image only"),
    _page_kind("text_and_image", "text and image"),
    _page_kind("blank", "blank"),
    _page_kind("total", "total"),
    # Question 5: S2.6's misses, which led to coding guidance, and the rerun on S3's fixed
    # pipeline after it (Andy, 2026-10-14: keep the history and add S3).
    *_misses("q5", _MISS_FILE, "S2.6's fixed pipeline"),
    *_misses("q5.s3", _MISS_S3_FILE, "S3's fixed pipeline"),
    _Spec(
        "q6.twins",
        _Source("s3-coding-consistency-dev.txt"),
        rf"^Headline: exact twins, all years, leave-one-out agreement on the six-digit "
        rf"first code: \d+ of {_N} \({_V}%\) \[{_L}%, {_H}%\]$",
        "percent",
        "development pool",
        "none",
        "scripts/exploratory/s3_coding_consistency.py",
        "identical NTSB cause sentences that share the first code",
    ),
    _Spec(
        "q6.one.distinct",
        _ONE_FILE,
        rf"^different first codes: {_V}$",
        "count",
        "development pool",
        "none",
        "scripts/exploratory/s5_one_sentence.py",
        "the chosen sentence's cases: how many different first codes they received",
    ),
    _Spec(
        "q6.one.cases",
        _ONE_FILE,
        rf"^cases: {_V}$",
        "count",
        "development pool",
        "none",
        "scripts/exploratory/s5_one_sentence.py",
        "the chosen sentence: how many cases it was written for",
    ),
    # Question 7's figure (decision 0186): three checkpoints and the moves between them.
    _path_count("cases", rf"^cases: the {_V} the loop answered;", "the cases counted"),
    _path_count(
        "no_belief_after",
        rf"^cases with no belief after a read choice \(after reading is before reading\): {_V}$",
        "cases with no belief after a read choice",
    ),
    _path_count("before", rf"^- before reading: {_V}$", "right before reading"),
    _path_count("after", rf"^- after reading: {_V}$", "right after reading"),
    _path_count("answer", rf"^- the answer: {_V}$", "right at the answer"),
    *_path_moves("reading", "before reading -> after reading"),
    *_path_moves("coding", "after reading -> the answer"),
    _Spec(
        "q7.loop_vs_fixed",
        _DIAG,
        rf"^top-1, loop - arm B check: {_PTS_CI}$",
        "points",
        "heldout-400",
        _LUNA,
        _DIAGNOSIS,
        "the loop against the fixed pipeline: occurrence top-1, paired",
    ),
    _Spec(
        "q7.loop_vs_answer",
        _DIAG,
        rf"^top-1, loop - arm B answer: {_PTS_CI}$",
        "points",
        "heldout-400",
        _LUNA,
        _DIAGNOSIS,
        "the loop against the fixed pipeline's answer alone: occurrence top-1, paired",
    ),
    _Spec(
        "q7.no_docket_loss",
        _CLAIMS_FILE,
        rf"^no-docket - loop, top-1: {_PTS_CI};",
        "points",
        "heldout-400",
        _LUNA,
        _CLAIMS,
        "the loop without the docket against the loop: occurrence top-1, paired",
    ),
    _Spec(
        "q7.read_all",
        _CLAIMS_FILE,
        rf"^- read every document on offer: {_V} of {_N} \(",
        "count",
        "heldout-400",
        _LUNA,
        _CLAIMS,
        "cases where the loop read every document on offer, of those with documents on offer",
    ),
    _Spec(
        "q7.noise_band",
        _Source("s3-noise-floor-dev.txt", r"^paired difference \(a - b\) on \d+ shared"),
        _PAIRED,
        "points",
        "dev-400",
        _LUNA,
        "scripts/s3_noise_floor.py",
        "the loop run twice, identically: occurrence top-1, paired",
    ),
    # History (spec §9 item 6): the bars the ladder replaced.
    _Spec(
        "history.s1_ceiling.top1",
        _Source("s1-bars.txt"),
        _ALL_ROW,
        "percent",
        "heldout-400",
        "openai/gpt-5.6-luna",
        f"{_EVAL} (ntsb-eval report)",
        "S1's one-shot ceiling, on an earlier model and stack: occurrence top-1",
        run=_RUN_LINE,
    ),
    _Spec(
        "history.s24_fixed.top1",
        _S24_FIXED,
        _ALL_ROW,
        "percent",
        "heldout-400",
        _LUNA,
        f"{_EVAL} (ntsb-eval report)",
        "S2.4's fixed pipeline, reading the docket, before coding tools: occurrence top-1",
        run=r"^run (?P<run>\S+-heldout-400-B) \[complete\]$",
        run_source=_Source("s24-bars.txt", repeated=True),
    ),
    _Spec(
        "history.s24_ceiling.top1",
        _S24_CEILING,
        _ALL_ROW,
        "percent",
        "heldout-400",
        _LUNA,
        f"{_EVAL} (ntsb-eval report)",
        "S2.4's one-shot ceiling, no docket: occurrence top-1",
        run=r"^run (?P<run>\S+-heldout-400-ceiling) \[complete\]$",
        run_source=_Source("s24-bars.txt"),
    ),
    # Limits (spec §9 item 7): the cost cap and the failure counts.
    _Spec(
        "limits.cap",
        _Source("s32-cap-check-dev.txt"),
        rf"-> the \${_V} cap stands",
        "usd",
        "every S3.2 run",
        "none",
        "scripts/s32_cap_check.py",
        "the cost cap per case, the same for every arm and part (decision 0144)",
    ),
    _Spec(
        "limits.loop.failed",
        _CLAIMS_FILE,
        rf"^- the loop: {_V} of {_N} failed:",
        "count",
        "heldout-400",
        _LUNA,
        _CLAIMS,
        "the loop's cases that failed, for any reason, counted as wrong",
        run=_RUN_LINE,
        run_source=_LOOP_BLOCK,
    ),
    _Spec(
        "limits.loop.format",
        _CLAIMS_FILE,
        rf"^format gate, run loop: PASS -- {_V} of {_N} cases failed for format or tool reasons",
        "count",
        "heldout-400",
        _LUNA,
        _CLAIMS,
        "the loop's cases that failed for format or tool reasons (prediction 9)",
        run=_RUN_LINE,
        run_source=_LOOP_BLOCK,
    ),
    *(
        _Spec(
            f"limits.noise_{run}.format",
            _NOISE_FILE,
            rf"^format gate, run {run}: PASS -- {_V} of {_N} cases failed for format or tool",
            "count",
            "dev-400",
            _LUNA,
            "scripts/s3_noise_floor.py",
            f"the loop's noise-floor run {run}: cases that failed for format or tool reasons",
            run=rf"^run {run} = (?P<run>\S+)$",
            run_source=_Source("s3-noise-floor-dev.txt"),
        )
        for run in ("a", "b")
    ),
)

_PAIR_LINE = r"^- (?P<count>\d+)  (?P<ntsb>.+?) -> (?P<agent>.+)$"
_PAIRS_SHOWN = 5


def _pairs(results_dir: Path, key: str, file: _Source) -> list[dict[str, str | int]]:
    source = _Source(file.file, r"^most common misses by event, ")
    rows = [m for line in _lines(results_dir, source, key) if (m := re.search(_PAIR_LINE, line))]
    if len(rows) < _PAIRS_SHOWN:
        raise ExtractError(key, source.file, _PAIR_LINE, len(rows))
    # A pair tied with the fifth is shown too, so file order never decides which (review).
    cut = int(rows[_PAIRS_SHOWN - 1].group("count"))
    return [
        {"count": int(m.group("count")), "ntsb": m.group("ntsb"), "agent": m.group("agent")}
        for m in rows
        if int(m.group("count")) >= cut
    ]


_ONE_CODE = r"^- (?P<count>\d+)  (?P<code>\d{6})  (?P<label>.+)$"


def _one_sentence_codes(results_dir: Path) -> list[dict[str, str | int]]:
    key = "q6.one.codes"
    source = _Source(_ONE_FILE.file, r"^first codes, most common first ")
    rows = [m for line in _lines(results_dir, source, key) if (m := re.search(_ONE_CODE, line))]
    if not rows:
        raise ExtractError(key, source.file, _ONE_CODE, 0)
    return [
        {"count": int(m.group("count")), "code": m.group("code"), "label": m.group("label")}
        for m in rows
    ]


_PREDICTIONS: Final = "s32.predictions"
# The registration's items: "1. **Top-1** (held-out): the loop ...", wrapped onto lines indented
# three spaces. Item 8 has no colon after its scope.
_ITEM = re.compile(
    r"^(?P<number>\d+)\. \*\*(?P<title>[^*]+)\*\* \((?P<scope>[^)]+)\):? (?P<text>.+)$"
)
_OUTCOME = re.compile(r"^P(?P<number>\d+): (?P<outcome>met|not met) -- (?P<result>.+)$")


def _plain(markdown: str) -> str:
    """The words of a markdown line: emphasis and code marks removed, spaces collapsed."""
    return " ".join(markdown.replace("*", "").replace("`", "").split())


def _predictions(results_dir: Path, registration: Path) -> list[dict[str, str | int]]:
    """S3.2's nine predictions as registered, each with its outcome (plan step 5 choice 3).

    The words are the registration's, copied, never retyped; the outcome and the line of what
    was measured are ``s32-claims-heldout.txt``'s. Both must hold items 1 to 9.
    """
    lines = registration.read_text().splitlines()
    start = lines.index("## The predictions")
    items: list[list[str]] = []
    for line in lines[start + 1 :]:
        if line.startswith(("## ", "Not predicted")):
            break
        if re.match(r"^\d+\. ", line):
            items.append([line])
        elif line.startswith("   ") and items:
            items[-1].append(line.strip())
    parsed = [m for item in items if (m := _ITEM.match(" ".join(item)))]
    claims = _lines(
        results_dir, _Source(_CLAIMS_FILE.file, r"^## 8\. The predictions"), _PREDICTIONS
    )
    outcomes = {m["number"]: m for line in claims if (m := _OUTCOME.match(line))}
    nine = [str(n) for n in range(1, 10)]
    if [m["number"] for m in parsed] != nine or len(parsed) != len(items):
        raise ExtractError(_PREDICTIONS, registration.name, _ITEM.pattern, len(parsed))
    if sorted(outcomes, key=int) != nine:
        raise ExtractError(_PREDICTIONS, _CLAIMS_FILE.file, _OUTCOME.pattern, len(outcomes))
    return [
        {
            "number": int(m["number"]),
            "title": _plain(m["title"]),
            "scope": _plain(m["scope"]),
            "text": _plain(m["text"]),
            "outcome": outcomes[m["number"]]["outcome"],
            "result": outcomes[m["number"]]["result"],
        }
        for m in parsed
    ]


def build(
    results_dir: Path,
    *,
    recorded: Callable[[str], str] = recorded_in,
    registration: Path = _REGISTRATION,
    added: Callable[[str], tuple[str, str]] = first_recorded,
) -> Numbers:
    """Read every entry from the results files under ``results_dir``.

    Args:
        results_dir: where the results files are read from.
        recorded: the commit that last changed a repository-relative path; ``recorded_in``
            unless a test reads copies outside the repository.
        registration: S3.2's registration, the predictions' words.
        added: the commit that added a path, and its date; the registration's is printed
            beside the predictions, to show they were written before the held-out run.
    """
    once = functools.cache(recorded)  # one git lookup per results file, not per entry
    entries = {spec.key: _entry(results_dir, spec, once) for spec in _SPECS}
    lists = {
        "q5.pairs": _pairs(results_dir, "q5.pairs", _MISS_FILE),
        "q5.s3.pairs": _pairs(results_dir, "q5.s3.pairs", _MISS_S3_FILE),
        "q6.one.codes": _one_sentence_codes(results_dir),
        _PREDICTIONS: _predictions(results_dir, registration),
    }
    sentence = _one(results_dir, _ONE_FILE, r"^sentence: (?P<text>.+)$", "q6.one.sentence")
    registered_in, registered_on = added(_REGISTRATION.relative_to(_REPO).as_posix())
    texts = {
        "q6.one.sentence": sentence.group("text"),
        "s32.registered_in": registered_in,
        "s32.registered_on": registered_on,
    }
    codes = lists["q6.one.codes"]
    if entries["q6.one.distinct"].value != len(codes) or entries["q6.one.cases"].value != sum(
        int(row["count"]) for row in codes
    ):
        raise ExtractError("q6.one.codes", _ONE_FILE.file, "the counts add up", 0)
    return Numbers(entries=entries, lists=lists, texts=texts)


def render(numbers: Numbers) -> str:
    """The file's text: sorted keys, two-space indent, a trailing newline."""
    return json.dumps(json.loads(numbers.model_dump_json()), indent=2, sort_keys=True) + "\n"


def first_difference(path: Path, numbers: Numbers) -> str | None:
    """The first key at which the file at ``path`` differs from ``numbers``, or None."""
    if not path.is_file():
        return "(no file)"
    committed: object = json.loads(path.read_text())
    fresh: object = json.loads(numbers.model_dump_json())
    # An entry's key holds dots, so it is compared as one key, not split.
    if isinstance(committed, dict) and isinstance(fresh, dict):
        for section in sorted(set(committed) | set(fresh), key=str):
            a, b = committed.get(section), fresh.get(section)
            if isinstance(a, dict) and isinstance(b, dict):
                for k in sorted(set(a) | set(b), key=str):
                    if a.get(k) != b.get(k):
                        return f"{section}.{k}"
            elif a != b:
                return str(section)
        return None
    return None if committed == fresh else "(the whole file)"


def main(argv: Sequence[str] | None = None) -> int:
    """Write the numbers file, or with ``--check`` report the first stale key."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else "")
    parser.add_argument("--check", action="store_true", help="exit 1 if the file is stale")
    args = parser.parse_args(argv)
    numbers = build(_RESULTS)
    if args.check:
        stale = first_difference(_OUT, numbers)
        if stale is not None:
            print(f"stale: {stale} (run: make site-numbers)")
            return 1
        return 0
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(render(numbers))
    print(_OUT.relative_to(_REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
