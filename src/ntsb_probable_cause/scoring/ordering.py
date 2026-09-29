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
# Decision 0101: the plain rule follows the NTSB's most common choice only on a clear habit.
CLEAR_HABIT_SHARE = Fraction(3, 5)
CLEAR_HABIT_MIN_CASES = 20


def candidates(guesses: Sequence[str], group: str | None, stats: CodingStats) -> tuple[str, ...]:
    """The codes the check may choose among (decision 0096 item 3)."""
    name = group or NO_GROUP
    first = list(dict.fromkeys(guesses))
    extra: set[str] = set()
    for guess in first:
        n = stats.present_n(guess)
        if n >= LINK_MIN_CASES:
            extra.update(
                d
                for d, k in stats.defining_given(guess).items()
                if Fraction(k, n) >= LINK_MIN_SHARE
            )
    extra.update(stats.group_top(name, GROUP_CODES))
    phases = stats.group_phases(name)
    for code in sorted(set(first) | extra):
        for phase in phases:
            variant = phase + code[3:]
            if variant != code and stats.group_defining_n(name, variant) >= PHASE_VARIANT_MIN_CASES:
                extra.add(variant)
    rest = sorted(extra - set(first), key=lambda c: (-stats.defining_n(c), c))
    return tuple((first + rest)[:MAX_CANDIDATES])


def clear_habit(counts: Mapping[str, int]) -> str | None:
    """The option holding at least 60% of at least 20 cases, or None (decision 0101)."""
    total = sum(counts.values())
    if total < CLEAR_HABIT_MIN_CASES:
        return None
    best, n = max(sorted(counts.items()), key=lambda kv: kv[1])
    return best if Fraction(n, total) >= CLEAR_HABIT_SHARE else None


def plain_rule(guesses: Sequence[str], group: str | None, stats: CodingStats) -> tuple[str, ...]:
    """The free way (spec §5.3 item 2, as amended by decision 0101).

    Event step: among pool cases containing the model's first guess, if one code is defining in
    a clear habit and it is a candidate, it goes first. Phase step: among pool cases with this
    phase group and that event, if one phase is a clear habit, it is used. At either step,
    without a clear habit the model's own choice stands.
    """
    chosen = guesses[0]
    habit = clear_habit(stats.defining_given(chosen))
    if habit is not None and habit in candidates(guesses, group, stats):
        chosen = habit
    name = group or NO_GROUP
    by_phase = {p: stats.group_defining_n(name, p + chosen[3:]) for p in stats.group_phases(name)}
    phase = clear_habit({p: k for p, k in by_phase.items() if k})
    if phase is not None:
        chosen = phase + chosen[3:]
    return tuple(dict.fromkeys((chosen, *guesses)))[:3]


def toward_more_common(before: str, after: str, group: str | None, stats: CodingStats) -> bool:
    """Whether a change of first code moved toward a more common option in the group (0101)."""
    name = group or NO_GROUP
    return after != before and stats.group_defining_n(name, after) > stats.group_defining_n(
        name, before
    )


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


def check_text(  # noqa: PLR0913, PLR0917 -- one parameter per fact the check-text prompt shows.
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
    lines.append(
        "The analyst's guesses, in order: "
        + ", ".join(f"{g} ({_words(g, tables)})" for g in guesses)
    )
    lines += ["", "Candidate codes:"]
    for code in options:
        n = stats.present_n(code)
        k = stats.defining_given(code).get(code, 0)
        lines.append(
            f"- {code} ({_words(code, tables)}): when it appears in a past case, "
            f"defining in {k} of {n}; "
            f"defining in this phase group in {stats.group_defining_n(name, code)} past cases"
        )
        if code != guesses[0]:
            pair = stats.pair(code, guesses[0])
            if pair["both"]:
                lines.append(
                    f"  when it and {guesses[0]} both appear ({pair['both']} past cases): "
                    f"{code} defining in {pair.get(code, 0)}, "
                    f"{guesses[0]} defining in {pair.get(guesses[0], 0)}"
                )
    lines += ["", "The analyst's own account of the evidence:", narrative]
    return "\n".join(lines)


_MAX_RANKING = 3


def parse_ranking(content: str, options: Sequence[str]) -> tuple[str, ...]:
    """The ranking, if every code is a listed candidate and none repeats; else ``SchemaError``."""
    try:
        ranking = json.loads(content)["ranking"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise SchemaError(f"ranking reply is not the schema's JSON: {error}") from error
    if not isinstance(ranking, list) or not 1 <= len(ranking) <= _MAX_RANKING:
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


# --- jev2: the registered second Jev check (decision 0103) ----------------------------------
#
# Built exactly as ``docs/rounds/s27-round1-jev2.md`` registers it, before any call: an object
# state with four named fields, every count written as words (``jev-1.13`` is weak at counting),
# each option described with ``what`` and, from the other candidates only, ``not_for``, and a
# ``none_of_these`` option. No example text anywhere: it would have to come from real cases.

NONE_OF_THESE = "none_of_these"

JEV2_QUESTION = (
    "Which of these occurrence codes would the NTSB flag as the defining event of this accident?"
)
# The same guidance GPT-6 Luna's check receives in CHECK_SYSTEM.
JEV2_FOCUS = (
    "Judge from the analyst's account which event began the accident sequence. Past habits are "
    "a guide, not a rule: prefer the option the account supports."
)
_NONE_OF_THESE_CRITERION: dict[str, str] = {
    "what": "The defining event is none of the codes listed",
    "not_for": "any listed code",
}


def habit_words(share_k: int, base_n: int) -> str:
    """A count as words, by the registration's five rules, applied in their order (0103).

    ``share_k`` of ``base_n`` past cases had the code as the defining event. The thresholds are
    decision 0101's clear habit and decision 0096 item 3's link; no new number is introduced.
    """
    if base_n < min(CLEAR_HABIT_MIN_CASES, LINK_MIN_CASES):
        return "too few past cases to say"
    share = Fraction(share_k, base_n)
    if share >= CLEAR_HABIT_SHARE:
        return "usually the defining event (a clear habit)"
    if share >= LINK_MIN_SHARE:
        return "often the defining event"
    if share > 0:
        return "seldom the defining event"
    return "never the defining event in past cases"


def jev2_state(  # noqa: PLR0913, PLR0917 -- one parameter per fact the state holds, as check_text.
    guesses: Sequence[str],
    options: Sequence[str],
    group: str | None,
    narrative: str,
    stats: CodingStats,
    tables: CodeTables,
) -> dict[str, object]:
    """The registered state: four named fields, and no count or share written as a number."""
    name = group or NO_GROUP
    first = guesses[0]
    group_base = stats.group_n(name)
    rows: list[dict[str, str]] = []
    for code in options:
        row = {
            "code": code,
            "meaning": _words(code, tables),
            "past_cases_when_it_appears": habit_words(
                stats.defining_given(code).get(code, 0), stats.present_n(code)
            ),
            "past_cases_in_this_phase_group": habit_words(
                stats.group_defining_n(name, code), group_base
            ),
        }
        if code != first:
            pair = stats.pair(code, first)
            row["past_cases_with_the_first_guess"] = habit_words(pair.get(code, 0), pair["both"])
        rows.append(row)
    return {
        "phase_of_flight_group": group or "not recorded",
        "analyst_guesses": [{"code": g, "meaning": _words(g, tables)} for g in guesses],
        "candidates": rows,
        "analyst_account": narrative,
    }


def _not_for(code: str, options: Sequence[str], tables: CodeTables) -> str:
    """What ``code`` is not for, written from the other candidates only (0103)."""
    parts: list[str] = []
    for other in options:
        if other == code:
            continue
        same_phase, same_event = other[:3] == code[:3], other[3:] == code[3:]
        if same_event and not same_phase:
            parts.append(
                f"the same event in the {tables.phases.get(other[:3], '?')} phase ({other})"
            )
        elif same_phase and not same_event:
            parts.append(
                f"{tables.events.get(other[3:], '?')}, which is listed separately ({other})"
            )
    return "; ".join(parts)


def jev2_question(options: Sequence[str], tables: CodeTables) -> dict[str, object]:
    """One Choice named ``defining``: object instructions, object criteria, ``none_of_these``."""
    criteria: dict[str, object] = {}
    for code in options:
        criterion = {"what": _words(code, tables)}
        if not_for := _not_for(code, options, tables):
            criterion["not_for"] = not_for
        criteria[code] = criterion
    criteria[NONE_OF_THESE] = dict(_NONE_OF_THESE_CRITERION)
    return {
        "type": "choice",
        "instructions": {"question": JEV2_QUESTION, "focus": JEV2_FOCUS},
        "criteria": criteria,
    }


def jev2_order(
    probabilities: Mapping[str, float], guesses: Sequence[str], options: Sequence[str]
) -> tuple[str, ...]:
    """Every option, highest probability first; ties by the model's own order (0103).

    ``none_of_these`` wins any tie it is part of: the registration's clarification (2026-09-27,
    before any call; Andy: option A) ranks it first whenever no code has a strictly higher
    probability, so a tie at the top leaves the answer unchanged. Among codes, ties go by the
    model's own order: its guesses first, in its order, then the other candidates in the
    candidate list's order -- never by code number. A label Jev was not asked about is a
    ``SchemaError``.
    """
    tie_order = [NONE_OF_THESE, *dict.fromkeys([*(g for g in guesses if g in options), *options])]
    if set(probabilities) != set(tie_order):
        raise SchemaError(
            f"Jev's labels {sorted(probabilities)} are not the options asked {sorted(tie_order)}"
        )
    return tuple(sorted(tie_order, key=lambda label: -probabilities[label]))


def jev2_ranking(
    probabilities: Mapping[str, float], guesses: Sequence[str], options: Sequence[str]
) -> tuple[str, ...]:
    """The top three codes, ``none_of_these`` left out; ``()`` when it ranks first (unchanged)."""
    order = jev2_order(probabilities, guesses, options)
    if order[0] == NONE_OF_THESE:
        return ()
    return tuple(label for label in order if label != NONE_OF_THESE)[:3]
