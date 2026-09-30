"""Build the statistics pool's coding counts, once (decision 0094).

Status
    One build per stage, free, chosen with ``--stage`` (default ``s27``): streams the processed
    file and writes that stage's counts, and only that stage's. ``s27`` (S2.7, built once)
    writes src/ntsb_probable_cause/scoring/tables/coding_stats.json (the counts the ordering
    check and the guidance read); ``s3`` (S3, decision 0129) writes
    src/ntsb_probable_cause/scoring/tables/coding_stats_s3.json from a pool that also leaves
    out dev-seal-s3-400. ``--out`` writes the same counts, readable (docs/results/
    s27-coding-stats.txt, docs/results/s3-coding-stats.txt). Counts and code labels only; no
    case number or text is written. S2.7's files are not rebuilt: its numbers stay citable.

Why
    The ordering check, the guidance and S3's coding tools need the NTSB's own coding habits.
    They come from development cases outside every sample, so no scored case helps answer
    itself; a guard refuses the build if a sample, held-out or open case reaches the pool. The
    ``s3`` stage needs dev-seal-s3-400 drawn first (scripts/draw_sealed.py), or it stops before
    writing anything.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.coding_stats [--stage {s27,s3}] [--out PATH]
"""

import argparse
import json
from collections.abc import Iterable, Iterator, Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.coding_stats import (
    HALVES,
    POOL_EXCLUDED,
    STATS_NAMES,
    CodingStats,
    PoolCase,
    StatsName,
    build,
)
from ntsb_probable_cause.settings import Settings

# `build` is re-exported (mypy --strict's implicit-reexport check) so the test module's
# `cs.build(...)` -- exercising the same function `main` calls -- resolves without a second
# import path; behaviour is unchanged.
__all__ = ["STAGES", "build", "check_pool", "main", "pool_cases", "processed_rows", "report"]

POOL_CLASSES = frozenset({"C", "F", "L"})
TABLES_DIR = Path("src/ntsb_probable_cause/scoring/tables")


@dataclass(frozen=True)
class Stage:
    """What one stage's counts are built from and where they are written."""

    excluded: tuple[str, ...]  # the samples whose cases stay out of the pool
    json_out: Path
    built_from: str  # recorded inside the JSON


STAGES: dict[StatsName, Stage] = {
    "s27": Stage(
        excluded=POOL_EXCLUDED["s27"],
        json_out=TABLES_DIR / "coding_stats.json",
        built_from=(
            "development split, classes C/F/L, excluding dev-400 and dev-seal-400 "
            "(scripts/coding_stats.py, decision 0094)"
        ),
    ),
    "s3": Stage(
        excluded=POOL_EXCLUDED["s3"],
        json_out=TABLES_DIR / "coding_stats_s3.json",
        built_from=(
            "development split, classes C/F/L, excluding dev-400, dev-seal-400 and "
            "dev-seal-s3-400 (scripts/coding_stats.py, decisions 0094, 129)"
        ),
    ),
}
TOP = 40
FINDING_EVENTS = 15
FINDINGS_EACH = 6
_GROUP = next(f for f in fields.EVIDENCE_FIELDS if f.role is EvidenceRole.PHASE_OF_FLIGHT)

Row = tuple[str, str, str, str, Mapping[str, object]]


def processed_rows(processed: Path) -> Iterator[Row]:
    """Stream (case, event date, split, class, raw) from the processed file.

    Final review, Minor 5: ``raw_json`` is parsed only for development rows. ``pool_cases``
    skips every held-out and open row (``split != "dev"``) before it ever touches ``raw``, so
    parsing their JSON bought nothing; a row outside the development split gets ``{}`` instead.
    """
    columns = ["ntsb_number", "event_date", "split", "investigation_class", "raw_json"]
    with pq.ParquetFile(processed / "cases.parquet") as parquet:
        for batch in parquet.iter_batches(batch_size=512, columns=columns):
            yield from (
                (str(n), str(d), str(s), str(c), json.loads(r) if s == "dev" else {})
                for n, d, s, c, r in zip(
                    *(batch.column(col).to_pylist() for col in columns), strict=True
                )
            )


def pool_cases(
    rows: Iterable[Row], *, excluded: AbstractSet[str]
) -> tuple[list[PoolCase], list[str]]:
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
                findings=fields.finding_codes_in_cause(raw),
            )
        )
        ids.append(case)
    return cases, ids


def check_pool(
    ids: Sequence[str], *, excluded: AbstractSet[str], splits: Mapping[str, str]
) -> None:
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
        "coding counts from the statistics pool (scripts/coding_stats.py; counts only, "
        "decision 0094)",
        f"built from: {stats.built_from}",
        "; ".join(f"{h}: {stats.cases.get(h, 0)} cases" for h in halves),
        "",
        f"## when a code appears, which code is defining (the {TOP} commonest codes; "
        "n = cases containing it)",
    ]
    commonest = sorted(
        {c for half in stats.present.values() for c in half},
        key=lambda c: (-stats.present_n(c), c),
    )[:TOP]
    for code in commonest:
        given = sorted(stats.defining_given(code).items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        by_half = ", ".join(f"{h} n={stats.present.get(h, {}).get(code, 0)}" for h in halves)
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
        lines.append(
            f"- {group}: phases "
            + ", ".join(f"{p} {tables.phases.get(p, '?')} {n}" for p, n in phases)
        )
        lines.extend(
            f"    {_label(c, tables)} {stats.group_defining_n(group, c)}"
            for c in stats.group_top(group, 3)
        )
    lines += [
        "",
        f"## flagged findings by defining event (the {FINDING_EVENTS} commonest defining events, "
        f"every phase; the {FINDINGS_EACH} commonest findings each; n = cases flagging it)",
    ]
    events = sorted(
        {c[3:] for half in stats.group_defining.values() for g in half.values() for c in g},
        key=lambda e: (-stats.findings_given_event(e)[0], e),
    )[:FINDING_EVENTS]
    for event in events:
        n, counts = stats.findings_given_event(event)
        lines.append(f"- {event} {tables.events.get(event, '?')}: {n} cases")
        lines.extend(
            f"    {code} {_finding_label(code, tables)} {k}"
            for code, k in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:FINDINGS_EACH]
        )
    return "\n".join(lines)


def _finding_label(code: str, tables: CodeTables) -> str:
    return f"{tables.items.get(code[:8], '?')} / {tables.modifiers.get(code[8:], '?')}"


def main(argv: Sequence[str] | None = None) -> int:
    """Build the chosen stage's pool, guard it, write that stage's JSON and the report."""
    parser = argparse.ArgumentParser(prog="coding_stats")
    parser.add_argument("--stage", choices=STATS_NAMES, default="s27")
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    stage = STAGES[args.stage]
    processed = Settings().data_dir / "processed"
    excluded = frozenset(i for name in stage.excluded for i in samples.sample_ids(name))
    # One streaming pass: holding every raw record at once costs about 600 MB (the note on
    # samples.seen_pairs); only each case's split is kept beside the pool.
    splits: dict[str, str] = {}

    def tapped() -> Iterator[Row]:
        for row in processed_rows(processed):
            splits[row[0]] = row[2]
            yield row

    cases, ids = pool_cases(tapped(), excluded=excluded)
    check_pool(ids, excluded=excluded, splits=splits)
    stats = build(cases, built_from=stage.built_from)
    stage.json_out.write_text(stats.to_json() + "\n")
    text = report(stats)
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
