"""Check guidance files share no sentence with any development case's withheld text.

Status
    Live for S2.7 (spec §12, plan W6), free and local: streams every development case in the
    processed file and compares each guidance sentence of 30 or more characters, normalised,
    against the factual narrative, analysis narrative and probable cause. Prints counts and
    the offending guidance sentence only; exits 1 on any match. CI cannot run it (no data).
    From S3.1 (final review), ``--agent-texts`` checks the agent's own fixed texts the same way
    (``agent_texts``): the protocol and every fixed string of ``agent/texts.py`` and
    ``agent/steps.py`` (their templates rendered with listing numbers and placeholder words),
    the coding tools' fixed result sentences (``agent/tools.py``, each tool run on a small
    placeholder pool: ``tool_texts``), and every string of the tool definitions
    (``agent/schemas.py``). The rule is S2.7's.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.check_guidance r2-loc-stall [r3-...]
    NTSB_DATA_DIR=... uv run python -m scripts.check_guidance --agent-texts
"""

import argparse
import json
import re
from collections.abc import Sequence
from typing import cast

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.agent import schemas, steps, texts, tools
from ntsb_probable_cause.agent.facts import DocumentFacts
from ntsb_probable_cause.agent.schemas import DescribeKind
from ntsb_probable_cause.agent.trail import Prior
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.scoring.codes import CodeTables
from ntsb_probable_cause.scoring.coding_stats import PoolCase, build
from ntsb_probable_cause.scoring.hypothesis import Hypothesis
from ntsb_probable_cause.settings import Settings

MIN_CHARS = 30
# A hypothesis for rendering the prior summary's fixed lines; its own words are not checked.
_PLACEHOLDER = Hypothesis.model_validate(
    {
        "evidence_narrative": "n",
        "occurrence": [{"phase": "551", "event": "092", "probability": 0.5}],
        "findings": [],
        "probable_cause": "p",
        "lay_explanation": "l",
        "confidence": 0.5,
        "abstain": False,
        "evidence_used": [],
    }
)


def normalise(text: str) -> str:
    """Lower case, whitespace collapsed."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def sentences(text: str) -> list[str]:
    """The guidance's sentences of at least ``MIN_CHARS`` characters, normalised."""
    parts = (normalise(p) for p in re.split(r"(?<=[.!?])\s+", text))
    return [s for s in parts if len(s) >= MIN_CHARS]


def matches(needles: Sequence[str], haystacks: Sequence[str]) -> list[str]:
    """The needles found in any haystack."""
    return [n for n in needles if any(n in h for h in haystacks)]


def _strings(value: object) -> list[str]:
    """Every string in a value: itself, or those inside a mapping's values or a collection."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for child in value.values() for s in _strings(child)]
    if isinstance(value, list | tuple | set | frozenset):
        return [s for child in value for s in _strings(child)]
    return []


def tool_texts() -> list[str]:
    """The coding tools' fixed result words, one line each, for ``sentences`` to split.

    Decision 0133 names a tool's result wording as text a tuning round may change, so each of the
    four tools (``agent/tools.py``) is run, every branch of its wording once, over placeholder
    code tables and a three-case placeholder pool. What comes out is the tools' own fixed
    sentences and layout around placeholder labels ("phase label", "event label") and small
    counts: no label of the real code tables and no count of the real statistics. A sentence a
    tool adds later is checked without a change here.

    Returns:
        The lines of every result, in the order the tools were run.
    """
    tables = CodeTables(
        phases={"100": "phase label", "200": "other phase label"},
        events={"010": "event label", "020": "other event label", "030": "third event label"},
        categories={"010101": "category label"},
        items={f"010101{n:02d}": "item label" for n in range(1, 22)},  # 21: the list is cut at 20
        modifiers={"10": "modifier label"},
    )
    pool = build(
        [
            PoolCase(2010, "Landing", ("100010", "200020"), findings=("0101010110",)),
            PoolCase(2011, "Landing", ("200020",)),
            PoolCase(2016, "Landing", ("100010",), findings=("0101010210",)),
        ],
        built_from="check_guidance",
    )
    results = [
        tools.describe_codes(tables, "occurrence", ["100010", "999999"]),
        tools.describe_codes(tables, "finding_category", ["010101", "999999"]),
        tools.describe_codes(tables, "item", ["01010101", "99999999"]),
        tools.describe_codes(tables, cast(DescribeKind, "other"), ["100010"]),
        tools.describe_codes(tables, "occurrence", []),
        tools.occurrence_usage(tables, pool, []),
        tools.occurrence_usage(tables, pool, ["100010", "200020", "999999"]),
        tools.occurrence_usage(tables, pool, ["100030"]),  # valid, in no pool case
        tools.past_findings(tables, pool, "999999"),
        tools.past_findings(tables, pool, "100010"),  # findings, and fewer than 20 cases
        tools.past_findings(tables, pool, "200020"),  # cases, no findings
        tools.suggest_codes(tables, pool, "Landing"),
        tools.suggest_codes(tables, pool, "Takeoff"),  # a group the pool holds no case of
    ]
    return [line for result in results for line in result.text.splitlines()]


def agent_texts() -> list[str]:
    """The agent's fixed model-facing texts, one part each, for ``sentences`` to split.

    Every module-level string of ``agent/texts.py`` and ``agent/steps.py`` (the protocol, the
    step texts, the summary's fixed lines; strings inside a table too), every string of the
    tool definitions (names, descriptions, enum values), the templates those modules build,
    rendered with listing numbers and placeholder words so their fixed words are checked, and
    the coding tools' fixed result sentences (:func:`tool_texts`).
    """
    parts: list[str] = []
    for module in (texts, steps, tools):
        for name, value in vars(module).items():
            if not name.startswith("__"):
                parts.extend(_strings(value))
    parts.extend(_strings(json.loads(json.dumps(list(schemas.TOOL_DEFINITIONS)))))
    one = DocumentFacts(1, 1, 1, 10, "born-digital", "read")
    two = DocumentFacts(2, 2, 0, 0, None, "fetch failed")
    prior = Prior(trigger=1, last_hypothesis=_PLACEHOLDER, reads=(), read=())
    parts += [
        texts.menu([one, two], [two], already_read=[3]),
        texts.read_summary([1], [2]),
        texts.not_accepted("an error"),
        texts.prior_summary(prior),
        steps.wrong_tool(("describe_codes", "submit_answer"), "another"),
        steps.wrong_tool(("submit_answer",), "describe_codes"),
    ]
    parts += tool_texts()
    return parts


def main(argv: Sequence[str] | None = None) -> int:
    """Exit 1 if any guidance sentence appears in a development case's withheld text."""
    parser = argparse.ArgumentParser(prog="check_guidance")
    parser.add_argument("names", nargs="*", help="guidance files r<N>-<slug>")
    parser.add_argument(
        "--agent-texts",
        action="store_true",
        help="check the agent's fixed texts and tool definitions as well (S3.1)",
    )
    args = parser.parse_args(argv)
    if not args.names and not args.agent_texts:
        parser.error("name a guidance file, or pass --agent-texts")
    needles = sentences(prompt.guidance_text(args.names)) if args.names else []
    if args.agent_texts:
        needles += [s for part in agent_texts() for s in sentences(part)]
    needles = list(dict.fromkeys(needles))
    found: set[str] = set()
    cases = 0
    columns = ["split", "raw_json"]
    path = Settings().data_dir / "processed" / "cases.parquet"
    with pq.ParquetFile(path) as parquet:
        for batch in parquet.iter_batches(batch_size=512, columns=columns):
            rows = zip(*(batch.column(c).to_pylist() for c in columns), strict=True)
            for split, raw_json in rows:
                if split != "dev":
                    continue
                raw = json.loads(raw_json)
                texts = [
                    normalise(t)
                    for t in (
                        fields.factual_narrative(raw),
                        fields.analysis_narrative(raw),
                        fields.probable_cause(raw),
                    )
                    if isinstance(t, str)
                ]
                cases += 1
                found.update(matches(needles, texts))
    what = "guidance sentences"  # S2.7's line, unchanged for a guidance-only check
    if args.agent_texts:
        what = "guidance and agent text sentences" if args.names else "agent text sentences"
    print(f"{len(needles)} {what} checked against {cases} development cases; {len(found)} found")
    for sentence in sorted(found):
        print(f"- found: {sentence}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
