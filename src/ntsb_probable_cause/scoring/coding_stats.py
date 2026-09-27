"""Counts of how the NTSB codes occurrences, from the statistics pool (decision 0094).

The pool is every development case in classes C, F and L outside ``dev-400`` and
``dev-seal-400``; ``scripts/coding_stats.py`` builds it and commits the counts beside the code
tables. This module holds the counts and reads them; it never reads a case, and nothing here
names one. Every count is kept per half of the decade so a habit that changed is visible.
"""

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
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


def _sorted_dict(tree: Mapping[str, object]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key in sorted(tree):
        value = tree[key]
        result[key] = _sorted_dict(value) if isinstance(value, Mapping) else value
    return result


def build(cases: Iterable[PoolCase], *, built_from: str) -> CodingStats:
    """Count ``cases``; a case with no occurrence codes is skipped."""
    counted: Counter[str] = Counter()
    present: defaultdict[str, Counter[str]] = defaultdict(Counter)
    given: defaultdict[str, defaultdict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    pairs: defaultdict[str, defaultdict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
    groups: defaultdict[str, defaultdict[str, Counter[str]]] = defaultdict(
        lambda: defaultdict(Counter)
    )
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
        _sorted_dict(
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
