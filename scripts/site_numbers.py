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

Failures
    A pattern that matches no line, or more than one, raises ``ExtractError`` naming the
    entry and the file, and nothing is written.

Usage
    uv run python -m scripts.site_numbers           # writes site/data/numbers.json
    uv run python -m scripts.site_numbers --check   # exit 1, naming the first stale key
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

_REPO = Path(__file__).resolve().parents[1]
_RESULTS = _REPO / "docs/results"
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
# A section ends at a blank line, a "[name]" block, a heading, or the next block's own header
# line ("fatal: paired difference ... cases:"), once it holds a line.
_SECTION_END = re.compile(r"^$|^\[|^#|^[^-].*:$")

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
    results_file: str
    script: str
    label: str


class Numbers(BaseModel):
    """The numbers file: entries by key, and short lists (the commonest miss pairs)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: Literal["site-numbers/1"] = "site-numbers/1"
    entries: dict[str, Entry]
    lists: dict[str, list[dict[str, str | int]]]


class ExtractError(Exception):
    """A pattern found no line, or more than one, in a results file."""

    def __init__(self, key: str, file: str, pattern: str, found: int) -> None:
        lines = "no line" if found == 0 else f"{found} lines"
        super().__init__(f"{key}: {lines} in {file} match {pattern!r}")


@dataclass(frozen=True)
class _Source:
    """Where in a results file a line is looked for: the whole file, or one section."""

    file: str
    section: str | None = None


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
    if len(starts) != 1:
        raise ExtractError(key, source.file, source.section, len(starts))
    body: list[str] = []
    for line in lines[starts[0] + 1 :]:
        if _SECTION_END.search(line) and body:
            break
        body.append(line)
    return body


def _one(results_dir: Path, source: _Source, pattern: str, key: str) -> re.Match[str]:
    found = [m for line in _lines(results_dir, source, key) if (m := re.search(pattern, line))]
    if len(found) != 1:
        raise ExtractError(key, source.file, pattern, len(found))
    return found[0]


def _float(m: re.Match[str], group: str) -> float | None:
    text = m.groupdict().get(group)
    return None if text is None else float(text)


def _entry(results_dir: Path, spec: _Spec) -> Entry:
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
    return Entry(
        value=value,
        low=_float(m, "low"),
        high=_float(m, "high"),
        n=None if n is None else int(n),
        unit=spec.unit,
        sample=spec.sample,
        model=spec.model,
        run=run,
        results_file=f"docs/results/{spec.source.file}",
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

_RUN_LINE = r"^run (?P<run>\S+) \[complete\]$"


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
        "reading the docket (arm B) against the one-shot ceiling: occurrence top-1, paired",
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
    _Spec(
        "q5.first_right",
        _MISS_FILE,
        rf"^first guess = the NTSB's first code: {_V} of {_N} \(",
        "count",
        "dev-400",
        _LUNA,
        _MISSES,
        "the first guess is the NTSB's first code",
        run=_RUN_LINE,
    ),
    _Spec(
        "q5.in_sequence",
        _MISS_FILE,
        rf"^first guess anywhere in the NTSB's sequence: {_V} of {_N} \(",
        "count",
        "dev-400",
        _LUNA,
        _MISSES,
        "the first guess is somewhere in the NTSB's sequence",
        run=_RUN_LINE,
    ),
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
)

_PAIR_LINE = r"^- (?P<count>\d+)  (?P<ntsb>.+?) -> (?P<agent>.+)$"
_PAIRS_SHOWN = 5


def _pairs(results_dir: Path) -> list[dict[str, str | int]]:
    key = "q5.pairs"
    source = _Source(_MISS_FILE.file, r"^most common misses by event, ")
    rows = [m for line in _lines(results_dir, source, key) if (m := re.search(_PAIR_LINE, line))]
    if len(rows) < _PAIRS_SHOWN:
        raise ExtractError(key, source.file, _PAIR_LINE, len(rows))
    return [
        {"count": int(m.group("count")), "ntsb": m.group("ntsb"), "agent": m.group("agent")}
        for m in rows[:_PAIRS_SHOWN]
    ]


def build(results_dir: Path) -> Numbers:
    """Read every entry from the results files under ``results_dir``."""
    entries = {spec.key: _entry(results_dir, spec) for spec in _SPECS}
    return Numbers(entries=entries, lists={"q5.pairs": _pairs(results_dir)})


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
