"""Guard statistics over the whole processed corpus (S0 spec §10). Counts only; no record text.

Usage:
    uv run python -m scripts.corpus_scan > docs/results/s0-corpus-scan.txt
"""

import json
import re
import sys
from collections import Counter, defaultdict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.errors import LeakageError
from ntsb_probable_cause.paths import resolve_path
from ntsb_probable_cause.records.guard import SENTENCE_CHECK_EXEMPTIONS, find_leaks, normalise_text
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.splits import Split

CANDIDATE_LENGTHS = (10, 20, 40, 80)
THRESHOLD_LINE = "chosen minimum sentence length: "
# A coded observation time, e.g. "121453Z" (day, hour, minute, "Z" for UTC): the fixed-format
# part of a METAR-style weather report (decision 0019's evidence field composition figure).
_WEATHER_TIME_GROUP = re.compile(r"\b\d{6}Z\b")
_WEATHER_METAR_FIELD = next(
    f for f in fields.EVIDENCE_FIELDS if f.role is fields.EvidenceRole.WEATHER_METAR
)
_NO_EXEMPTIONS: frozenset[tuple[str, str]] = frozenset()
# (label, exemption set) pairs the scan reports side by side, so decision 0019's figures can be
# checked against the results file both with and without the exemption in force.
_MODES: tuple[tuple[str, frozenset[tuple[str, str]]], ...] = (
    ("without", _NO_EXEMPTIONS),
    ("with", SENTENCE_CHECK_EXEMPTIONS),
)
# Copied from ../ntsb-spike/src/ntsb_spike/leakage.py (GIVEAWAY); the spike's 10.8% figure used
# this list.
GIVEAWAY = (
    r"\bfailed to\b",
    r"\bfailure to\b",
    r"\binadequate\b",
    r"\bimproper(ly)?\b",
    r"\bdid not maintain\b",
    r"\bdelayed\b",
    r"\bmisjudg",
    r"\bexceeded\b",
    r"\bpilot's decision\b",
    r"\bcontributing\b",
    r"\bprobable\b",
    r"\bresulted in\b",
)
_GIVEAWAY = re.compile("|".join(GIVEAWAY), re.IGNORECASE)
_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")
_DUPLICATION_THRESHOLD = 0.5

# Item F / decision 0019 context (b): `records/guard.py`'s `_SENTENCE_END` splits on ".", "!",
# "?" or ";" directly followed by whitespace, and also on ".", "!" or "?" directly followed by a
# letter with no space in between (a trivial edit that would otherwise hide a sentence). It still
# misses a break where sentence-final punctuation is immediately followed by a closing quote,
# "**" or ")" and then whitespace (the regex's lookbehind sees only the single character before
# the whitespace, and the letter-no-space rule does not cover a closing mark in between), and it
# misses a ";" directly followed by a letter (no space). This is a diagnostic pattern for
# counting how often that remaining gap is actually present in real withheld text — it does not
# change guard matching.
_MISSED_BREAK = re.compile(
    r"""[.!?]['"’”]\s(?=[A-Z0-9])"""  # noqa: RUF001 - closing quote (curly variants included)
    r"""|[.!?]\*\*\s(?=[A-Z0-9])"""  # sentence end, "**", space, new sentence
    r"""|[.!?]\)\s(?=[A-Z0-9])"""  # sentence end, ")", space, new sentence
    r"""|;(?=[A-Za-z])"""  # ";" with no following space
)
_MISSED_BREAK_SOURCES: tuple[tuple[str, Callable[[Mapping[str, object]], str | None]], ...] = (
    ("factual", fields.factual_narrative),
    ("analysis", fields.analysis_narrative),
    ("probable_cause", fields.probable_cause),
)
_SPLITS: tuple[str, ...] = tuple(s.value for s in Split)


def leak_kinds(raw: Mapping[str, object], min_sentence_chars: int) -> Counter[str]:
    """Count tripwire hits by kind for one record, mirroring split_record's check."""
    evidence = {f.role.value: f.extract(raw) for f in fields.EVIDENCE_FIELDS}
    withheld = {
        "factual_narrative": fields.factual_narrative(raw),
        "analysis_narrative": fields.analysis_narrative(raw),
        "probable_cause": fields.probable_cause(raw),
    }
    codes = fields.occurrence_codes(raw) + fields.finding_codes(raw)
    return Counter(
        leak.kind
        for leak in find_leaks(evidence, withheld, codes, min_sentence_chars=min_sentence_chars)
    )


def sentence_matches(
    raw: Mapping[str, object],
    min_sentence_chars: int,
    exemptions: frozenset[tuple[str, str]],
) -> list[tuple[str, str, int]]:
    """(role, source, matched fragment length) for every sentence-kind leak, given exemptions."""
    evidence = {f.role.value: f.extract(raw) for f in fields.EVIDENCE_FIELDS}
    withheld = {
        "factual_narrative": fields.factual_narrative(raw),
        "analysis_narrative": fields.analysis_narrative(raw),
        "probable_cause": fields.probable_cause(raw),
    }
    codes = fields.occurrence_codes(raw) + fields.finding_codes(raw)
    leaks = find_leaks(
        evidence, withheld, codes, min_sentence_chars=min_sentence_chars, exemptions=exemptions
    )
    return [
        (leak.evidence_role, leak.source, len(leak.fragment))
        for leak in leaks
        if leak.kind == "sentence"
    ]


def choose_threshold(hits_by_length: Mapping[int, int]) -> int | None:
    """The smallest candidate length with zero hits, or None."""
    return next((length for length in sorted(hits_by_length) if hits_by_length[length] == 0), None)


def duplication_share(analysis: str | None, factual: str | None, min_chars: int = 40) -> float:
    """Share of sentences at least ``min_chars`` long found verbatim in the factual narrative."""
    if not analysis or not factual:
        return 0.0
    haystack = normalise_text(factual)
    sentences = [s for s in _SENTENCE_END.split(normalise_text(analysis)) if len(s) >= min_chars]
    return sum(s in haystack for s in sentences) / len(sentences) if sentences else 0.0


def has_missed_break(text: str) -> bool:
    """True if ``text`` contains a sentence boundary the guard's ``_SENTENCE_END`` misses."""
    return bool(_MISSED_BREAK.search(text))


def missed_break_sources(raw: Mapping[str, object]) -> list[str]:
    """Which withheld texts (factual, analysis, probable_cause) carry a missed sentence break."""
    return [
        name
        for name, extract in _MISSED_BREAK_SOURCES
        if (text := extract(raw)) and has_missed_break(text)
    ]


def _narrative_entries(raw: Mapping[str, object]) -> list[Mapping[str, object]]:
    value = raw.get("narratives")
    return [n for n in value if isinstance(n, dict)] if isinstance(value, list) else []


def narratives_count(raw: Mapping[str, object]) -> int:
    """Number of entries in ``narratives[]`` (item F(b): the guard compares only entry 0)."""
    value = raw.get("narratives")
    return len(value) if isinstance(value, list) else 0


_MIN_NARRATIVES_TO_COMPARE = 2


def later_probable_cause_differs(raw: Mapping[str, object]) -> bool:
    """True if a ``narratives[]`` entry after the first carries a different, non-empty cause."""
    entries = _narrative_entries(raw)
    if len(entries) < _MIN_NARRATIVES_TO_COMPARE:
        return False
    first = normalise_text(str(entries[0].get("probableCause") or ""))
    return any(
        (later := normalise_text(str(entry.get("probableCause") or ""))) and later != first
        for entry in entries[1:]
    )


def _aircraft_carries_codes(aircraft: Mapping[str, object]) -> bool:
    events = aircraft.get("events")
    findings = aircraft.get("findings")
    has_event_code = isinstance(events, list) and any(
        isinstance(e, dict) and isinstance(e.get("eventCode"), str) and e.get("eventCode")
        for e in events
    )
    has_finding_code = isinstance(findings, list) and any(
        isinstance(f, dict) and isinstance(f.get("findingCode"), str) and f.get("findingCode")
        for f in findings
    )
    return has_event_code or has_finding_code


def multi_aircraft_with_codes(raw: Mapping[str, object]) -> bool:
    """True if more than one ``aircrafts[]`` entry carries an event or finding code.

    Item F(b): the guard compares only ``aircrafts[0]``'s codes.
    """
    aircrafts = raw.get("aircrafts")
    if not isinstance(aircrafts, list):
        return False
    carrying = sum(1 for a in aircrafts if isinstance(a, dict) and _aircraft_carries_codes(a))
    return carrying > 1


def has_nonempty_prelim_narrative(raw: Mapping[str, object]) -> bool:
    """True if any ``narratives[]`` entry has a non-blank ``prelimNarrative``.

    Item F(c): reported to confirm it is empty in every processed case.
    """
    return any(
        isinstance(v := e.get("prelimNarrative"), str) and v.strip()
        for e in _narrative_entries(raw)
    )


# --- amateur-built aircraft (decision 0020) — pure functions over the raw record ---

_AMATEUR_BUILT_FLAG = "aircrafts[0].aircraftAmateurBuilt"


def is_amateur_built(raw: Mapping[str, object]) -> bool:
    """True unless the amateur-built flag is `False` or absent/`None` (decision 0020).

    This is `fields.py`'s fail-closed rule: every real value is a JSON boolean, so this agrees
    with `fields.py` on the processed corpus, but does not repeat its narrower `is True` check.
    """
    flag = resolve_path(raw, _AMATEUR_BUILT_FLAG)
    return flag is not False and flag is not None


def raw_aircraft_make(raw: Mapping[str, object]) -> str | None:
    """The recorded make, before decision 0020's evidence-role substitution."""
    value = resolve_path(raw, "aircrafts[0].aircraftMake")
    return value if isinstance(value, str) and value.strip() else None


def raw_aircraft_model(raw: Mapping[str, object]) -> str | None:
    """The recorded model, before decision 0020's evidence-role substitution."""
    value = resolve_path(raw, "aircrafts[0].aircraftModel")
    return value if isinstance(value, str) and value.strip() else None


def model_contains_make(make: str | None, model: str | None) -> bool:
    """True if the recorded model text contains the recorded make text."""
    return bool(make and model and make.lower() in model.lower())


@dataclass
class ScanState:
    """Everything the scan accumulates across the corpus. Counts only; no record text."""

    hits: dict[int, Counter[str]] = field(
        default_factory=lambda: {length: Counter() for length in CANDIDATE_LENGTHS}
    )
    by_split: Counter[str] = field(default_factory=Counter)
    by_class: Counter[str] = field(default_factory=Counter)
    multi_aircraft: Counter[str] = field(default_factory=Counter)
    duplicated: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    whole_analysis: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    with_factual: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    giveaway: defaultdict[str, int] = field(default_factory=lambda: defaultdict(int))
    weather_nonempty: int = 0
    weather_coded: int = 0
    match_counts: dict[int, dict[str, Counter[str]]] = field(
        default_factory=lambda: {
            length: {mode: Counter() for mode, _ in _MODES} for length in CANDIDATE_LENGTHS
        }
    )
    case_sets: dict[int, dict[str, defaultdict[str, set[int]]]] = field(
        default_factory=lambda: {
            length: {mode: defaultdict(set) for mode, _ in _MODES} for length in CANDIDATE_LENGTHS
        }
    )
    # Item F: tripwire coverage limits (fixed in S2) — counts only.
    missed_break: Counter[str] = field(default_factory=Counter)
    multi_narrative: Counter[str] = field(default_factory=Counter)
    multi_narrative_pc_differs: Counter[str] = field(default_factory=Counter)
    multi_aircraft_codes: Counter[str] = field(default_factory=Counter)
    nonempty_prelim: Counter[str] = field(default_factory=Counter)
    # amateur-built aircraft (decision 0020) — counts only, no make/model values printed.
    amateur_built: Counter[str] = field(default_factory=Counter)
    amateur_built_makes: Counter[str] = field(default_factory=Counter)
    amateur_built_models: Counter[str] = field(default_factory=Counter)
    amateur_built_model_contains_make: int = 0


def _weather_label(raw: Mapping[str, object]) -> str | None:
    """Return coded/plain for a non-empty weather_metar value, or None if it is empty."""
    metar = _WEATHER_METAR_FIELD.extract(raw)
    if not (isinstance(metar, str) and metar.strip()):
        return None
    return "coded" if _WEATHER_TIME_GROUP.search(metar) else "plain"


def _accumulate_sentence_matches(
    state: ScanState, index: int, split: str, raw: Mapping[str, object]
) -> None:
    weather_label = _weather_label(raw)
    for length in CANDIDATE_LENGTHS:
        for mode, exemptions in _MODES:
            for role, source, matchlen in sentence_matches(raw, length, exemptions):
                key = f"{split}/{role}/{source}/{matchlen}"
                if role == fields.EvidenceRole.WEATHER_METAR.value and weather_label:
                    key = f"{key}/{weather_label}"
                state.match_counts[length][mode][key] += 1
                state.case_sets[length][mode][f"{split}/{role}/{source}"].add(index)


def _accumulate_row(state: ScanState, index: int, row: Mapping[str, object]) -> None:
    raw = json.loads(str(row["raw_json"]))
    split, cls = str(row["split"]), str(row["investigation_class"] or "?")
    state.by_split[split] += 1
    state.by_class[f"{split}/{cls}"] += 1
    aircraft_count = row["aircraft_count"]
    state.multi_aircraft[split] += isinstance(aircraft_count, int) and aircraft_count > 1
    for length in CANDIDATE_LENGTHS:
        kinds = leak_kinds(raw, length).items()
        state.hits[length].update({f"{split}/{kind}": n for kind, n in kinds})
    _accumulate_sentence_matches(state, index, split, raw)
    factual, analysis = fields.factual_narrative(raw), fields.analysis_narrative(raw)
    if factual:
        key = f"{split}/{cls}"
        state.with_factual[key] += 1
        state.duplicated[key] += duplication_share(analysis, factual) >= _DUPLICATION_THRESHOLD
        state.whole_analysis[key] += (
            normalise_text(analysis) in normalise_text(factual) if analysis else False
        )
        state.giveaway[key] += bool(_GIVEAWAY.search(factual))
    weather_label = _weather_label(raw)
    if weather_label is not None:
        state.weather_nonempty += 1
        state.weather_coded += weather_label == "coded"
    for source in missed_break_sources(raw):
        state.missed_break[f"{split}/{source}"] += 1
    if narratives_count(raw) > 1:
        state.multi_narrative[split] += 1
        if later_probable_cause_differs(raw):
            state.multi_narrative_pc_differs[split] += 1
    if multi_aircraft_with_codes(raw):
        state.multi_aircraft_codes[split] += 1
    if has_nonempty_prelim_narrative(raw):
        state.nonempty_prelim[split] += 1
    if is_amateur_built(raw):
        state.amateur_built[split] += 1
        make, model = raw_aircraft_make(raw), raw_aircraft_model(raw)
        # Counted case-insensitively: the same builder or kit name is sometimes recorded in a
        # different case, which would otherwise inflate the distinct-value counts.
        if make is not None:
            state.amateur_built_makes[make.strip().casefold()] += 1
        if model is not None:
            state.amateur_built_models[model.strip().casefold()] += 1
        state.amateur_built_model_contains_make += model_contains_make(make, model)


def _print_header(state: ScanState, case_count: int) -> None:
    print("# S0 corpus scan (scripts/corpus_scan.py) — counts only")
    print(f"cases: {case_count}; by split: {dict(sorted(state.by_split.items()))}")
    print(f"by split/class: {dict(sorted(state.by_class.items()))}")
    print(f"multi-aircraft cases by split: {dict(sorted(state.multi_aircraft.items()))}")


def _print_hits(state: ScanState, totals: Mapping[int, int]) -> None:
    print("\n## tripwire hits by minimum sentence length (split/kind)")
    for length in CANDIDATE_LENGTHS:
        print(f"{length}: total {totals[length]} {dict(sorted(state.hits[length].items()))}")


def _print_tripwire_coverage_limits(state: ScanState) -> None:
    print("\n## tripwire coverage limits (fixed in S2) — counts only")
    print("(a) cases whose withheld texts contain at least one missed sentence break, by split")
    print("    and source (every split x source shown, including zero):")
    for split in _SPLITS:
        for source, _ in _MISSED_BREAK_SOURCES:
            key = f"{split}/{source}"
            print(f"    {key}: {state.missed_break[key]}")
    print("(b) cases with more than one narratives[] entry, by split (every split shown):")
    for split in _SPLITS:
        print(f"    {split}: {state.multi_narrative[split]}")
    print(
        "    of those, cases whose later narratives[] entry carries a different probable"
        " cause, by split (every split shown):"
    )
    for split in _SPLITS:
        print(f"    {split}: {state.multi_narrative_pc_differs[split]}")
    print("(b) cases with more than one aircraft carrying codes, by split (every split shown):")
    for split in _SPLITS:
        print(f"    {split}: {state.multi_aircraft_codes[split]}")
    print("(c) cases with a non-empty prelim narrative, by split (every split shown):")
    for split in _SPLITS:
        print(f"    {split}: {state.nonempty_prelim[split]}")


def _print_weather_composition(state: ScanState) -> None:
    plain_english = state.weather_nonempty - state.weather_coded
    print(
        f"\n## weather_metar field composition (decision 0019): "
        f"{state.weather_nonempty} non-empty values, "
        f"{state.weather_coded} with a coded time group, {plain_english} plain-English"
    )


def _print_sentence_matches(state: ScanState) -> None:
    print(
        "\n## tripwire sentence matches by minimum sentence length (split/role/source/length),"
        " with and without decision 0019's exemption — counts only"
    )
    for length in CANDIDATE_LENGTHS:
        for mode, _ in _MODES:
            counter = state.match_counts[length][mode]
            total = sum(counter.values())
            print(f"{length} {mode} exemption: total {total} {dict(sorted(counter.items()))}")
    print(
        "\n## cases with a sentence match by minimum sentence length (split/role/source),"
        " with and without decision 0019's exemption — counts only, no case numbers"
    )
    for length in CANDIDATE_LENGTHS:
        for mode, _ in _MODES:
            sets = state.case_sets[length][mode]
            counts = {key: len(indices) for key, indices in sorted(sets.items())}
            distinct = {index for indices in sets.values() for index in indices}
            print(f"{length} {mode} exemption: total {len(distinct)} {counts}")


def _print_factual_narrative_stats(state: ScanState) -> None:
    print("\n## reported, not guarded: factual narrative statistics by split/class")
    print(
        "split/class: with factual narrative | >=50% analysis sentences verbatim"
        " | whole analysis contained | give-away phrase"
    )
    for key in sorted(state.with_factual):
        print(
            f"{key}: {state.with_factual[key]} | {state.duplicated[key]}"
            f" | {state.whole_analysis[key]} | {state.giveaway[key]}"
        )


def _print_amateur_built(state: ScanState) -> None:
    print("\n## amateur-built aircraft (decision 0020) — counts only, no make/model values")
    print("cases with the flag set, by split (every split shown):")
    for split in _SPLITS:
        print(f"    {split}: {state.amateur_built[split]}")
    make_counts = state.amateur_built_makes
    model_counts = state.amateur_built_models
    make_singletons = sum(1 for n in make_counts.values() if n == 1)
    model_singletons = sum(1 for n in model_counts.values() if n == 1)
    print(
        f"distinct make values: {len(make_counts)}; occurring in exactly one case:"
        f" {make_singletons}"
    )
    print(
        f"distinct model values: {len(model_counts)}; occurring in exactly one case:"
        f" {model_singletons}"
    )
    print(f"cases whose model contains the make: {state.amateur_built_model_contains_make}")


def _count_leakage_errors(rows: list[Mapping[str, object]], chosen: int) -> int:
    failures = 0
    for row in rows:
        try:
            split_record(json.loads(str(row["raw_json"])), min_sentence_chars=chosen)
        except LeakageError:
            failures += 1
    return failures


def main() -> int:
    """Scan every case and print the counts."""
    columns = ["split", "investigation_class", "aircraft_count", "raw_json"]
    table = pq.read_table(Settings().data_dir / "processed/cases.parquet", columns=columns)
    rows = table.to_pylist()
    state = ScanState()
    for index, row in enumerate(rows):
        _accumulate_row(state, index, row)

    totals = {length: sum(counter.values()) for length, counter in state.hits.items()}
    chosen = choose_threshold(totals)
    _print_header(state, len(rows))
    _print_hits(state, totals)
    _print_weather_composition(state)
    _print_sentence_matches(state)
    print(f"\n{THRESHOLD_LINE}{chosen if chosen is not None else 'NONE'}")
    _print_factual_narrative_stats(state)
    _print_tripwire_coverage_limits(state)
    _print_amateur_built(state)

    if chosen is None:
        print(
            "\nno candidate length has zero hits: investigate before choosing a threshold",
            file=sys.stderr,
        )
        return 1
    failures = _count_leakage_errors(rows, chosen)
    print(f"\nsplit_record at the chosen length: {failures} LeakageError across {len(rows)} cases")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
