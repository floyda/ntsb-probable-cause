"""Can personal names reach the public board through text the names rule would not catch?

Status
    Run once in S4 (spec §12.2, decision 0180 item 4). Free; development cases only; counts only.
    It reads the two finished ``dev-400`` arm C noise-floor runs, the development cases' raw
    records and their cached docket listings (cache only: no network), and makes no model call.
    ``make s4-names-probe`` writes ``docs/results/s4-names-dev.txt``; Andy chooses the names rule
    from it.

What it counts
    Five text kinds, over the cases the two runs share (both runs' texts are pooled per case):
    ``cause`` (every checkpoint's and the answer's ``probable_cause``), ``account``
    (``evidence_narrative``), ``note`` (each document decision's ``expected_effect``), ``reason``
    (each read choice's ``reason``) and ``ntsb_cause`` (the NTSB's own probable cause, from the
    verdict part of ``split_record``). A word is flagged when it is a capitalised word
    (``capitalised_words``) that ``known_title_words`` does not hold. For each kind:

    1. cases whose text holds a word flagged in that case's own document titles;
    2. cases whose text holds an owner or operator string (``owner_operator_values``, matched
       the way ``redact_known_names`` matches);
    3. cases whose text holds a flagged word outside the rule: not among the case's own flagged
       title words and not inside an owner or operator string;
    4. the total of those words in 3, each distinct word counted once per case.

    The rule fixed before the run: if count 3 is 0 for every kind the rule stands; otherwise
    Andy chooses. Output is counts and kind names only: never a word, a title or a case number.

Usage
    uv run python -m scripts.s4_names_probe [RUN_ID RUN_ID] [--out PATH]
"""

import argparse
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ntsb_probable_cause.agent.schemas import CODING_TOOLS, ChooseDocuments
from ntsb_probable_cause.agent.trail import AgentCall
from ntsb_probable_cause.docket.attach import owner_operator_values
from ntsb_probable_cause.docket.listing import parse_listing
from ntsb_probable_cause.docket.title_vocab import capitalised_words, known_title_words
from ntsb_probable_cause.errors import DocketError, LeakageError
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.samples import load_cases
from ntsb_probable_cause.settings import Settings
from scripts._s3_runs import load_runs, write_result

PROG: Final = "s4_names_probe"
DEFAULT_RUNS: Final = (
    "20261001T201506-fd6053f-dev-400-C",
    "20261001T201648-fd6053f-dev-400-C",
)
KINDS: Final = (
    "cause",
    "account",
    "note",
    "reason",
    "lookup_reason",
    "lookup_effect",
    "lookup_arg",
    "ntsb_cause",
)
_CHOICES: Final = frozenset({"choice1", "choice2"})


@dataclass(frozen=True)
class NameCase:
    """One case's titles, owner and operator strings, and texts by kind.

    Attributes:
        titles: the document titles of the case's cached docket listing.
        owner_operator: the record's owner and operator strings.
        texts: the texts to check, keyed by kind (``KINDS``).
    """

    titles: tuple[str, ...]
    owner_operator: tuple[str, ...]
    texts: Mapping[str, tuple[str, ...]]


@dataclass(frozen=True)
class KindCounts:
    """Counts 1 to 4 for one text kind."""

    in_titles: int = 0
    owner_operator: int = 0
    outside: int = 0
    outside_words: int = 0
    with_text: int = 0
    texts: int = 0
    words_scanned: int = 0


@dataclass(frozen=True)
class NameCounts:
    """Counts for every kind, and the cases counted."""

    cases: int
    by_kind: dict[str, KindCounts]


@dataclass(frozen=True)
class Loaded:
    """What a loader returns: the cases, the run ids read and cases without a cached listing."""

    cases: list[NameCase]
    run_ids: tuple[str, ...]
    no_listing: int = 0
    skipped: int = 0


Loader = Callable[[Sequence[str]], Loaded]


def _flagged(text: str, known: frozenset[str]) -> list[str]:
    return [w.lower() for w in capitalised_words(text) if w.lower() not in known]


def _owner_pattern(value: str) -> re.Pattern[str]:
    # The anchoring ``redact_known_names`` uses.
    return re.compile(rf"(?<!\w){re.escape(value)}(?!\w)", re.IGNORECASE)


def _count_kind(
    case: NameCase, kind: str, known: frozenset[str]
) -> tuple[bool, bool, set[str], int]:
    own = {w for title in case.titles for w in _flagged(title, known)}
    patterns = [
        _owner_pattern(v) for v in sorted(set(case.owner_operator), key=lambda v: (-len(v), v))
    ]
    in_titles = has_owner = False
    outside: set[str] = set()
    scanned = 0
    for original in case.texts.get(kind, ()):
        text = original
        for pattern in patterns:
            if pattern.search(text):
                has_owner = True
            text = pattern.sub(" ", text)
        scanned += len(capitalised_words(text))
        words = set(_flagged(text, known))
        in_titles |= bool(words & own)
        outside |= words - own
    return in_titles, has_owner, outside, scanned


def count_names(cases: Sequence[NameCase], known: frozenset[str]) -> NameCounts:
    """Counts 1 to 4 per text kind over ``cases`` (module docstring).

    Args:
        cases: the cases.
        known: the ordinary words, lower-cased; a capitalised word outside it is flagged.

    Returns:
        The counts. Owner and operator strings are masked before count 3's words are taken, so
        a name inside one is count 2 and never count 3.
    """
    by_kind: dict[str, KindCounts] = {}
    for kind in KINDS:
        titles = owners = outside = words = with_text = texts = scanned_total = 0
        for case in cases:
            in_titles, has_owner, loose, scanned = _count_kind(case, kind, known)
            n_texts = len(case.texts.get(kind, ()))
            texts += n_texts
            with_text += n_texts > 0
            scanned_total += scanned
            titles += in_titles
            owners += has_owner
            outside += bool(loose)
            words += len(loose)
        by_kind[kind] = KindCounts(titles, owners, outside, words, with_text, texts, scanned_total)
    return NameCounts(len(cases), by_kind)


def report_lines(counts: NameCounts, loaded: Loaded, *, dictionary: bool) -> list[str]:
    """The printed result: counts and kind names only."""
    lines = [
        "S4 names measurement on dev-400 (scripts/s4_names_probe.py; spec §12.2, decision 0180)",
        "Counts only: no word, title or case number is printed.",
        "The probe uses the same detector as the rule (a capitalised word not in the word list). "
        "So a zero in count (3) means no name that detector sees. It does not mean no names: "
        "names in capitals, short names, or names that are dictionary words are not counted.",
        *(f"run = {run_id}" for run_id in loaded.run_ids),
        f"cases counted: {counts.cases}; without a cached docket listing: {loaded.no_listing}; "
        f"skipped (record or docket unreadable): {loaded.skipped}",
        f"system dictionary found: {'yes' if dictionary else 'no'}",
        "",
        "per kind: (1) text holds a word flagged in the case's own titles; (2) text holds an "
        "owner or operator string; (3) text holds a flagged word outside the rule; (4) the "
        "words in (3), each distinct word once per case",
    ]
    for kind, c in counts.by_kind.items():
        lines.append(
            f"{kind}: (1) {c.in_titles}; (2) {c.owner_operator}; (3) {c.outside}; "
            f"(4) {c.outside_words}; cases with a text {c.with_text}; texts scanned {c.texts}; "
            f"capitalised words scanned {c.words_scanned}"
        )
    outside = {kind: c.outside for kind, c in counts.by_kind.items()}
    empty = [kind for kind, c in counts.by_kind.items() if c.texts == 0]
    stands = all(n == 0 for n in outside.values())
    lines += [
        "",
        "rule fixed before the run: if (3) is 0 for every kind, the rule stands; otherwise Andy "
        "chooses.",
        "result: "
        + (
            f"cannot conclude: kind {', '.join(empty)} has no texts"
            if empty
            else "the rule stands"
            if stands
            else "the rule does not stand for: "
            + ", ".join(k for k, n in outside.items() if n)
            + "; Andy chooses"
        ),
    ]
    return lines


def _collect(call: AgentCall, bucket: dict[str, list[str]]) -> None:  # pragma: no cover
    """Add one trail row's free text to a case's ``bucket``, by kind."""
    if call.hypothesis is not None:
        bucket["cause"].append(call.hypothesis.probable_cause)
        bucket["account"].append(call.hypothesis.evidence_narrative)
    if call.protocol_error:
        return
    if call.step in _CHOICES and call.tool == "choose_documents":
        chosen = ChooseDocuments.model_validate(call.arguments)
        bucket["reason"].append(chosen.reason)
        bucket["note"].extend(d.expected_effect for d in chosen.decisions)
    elif call.tool in CODING_TOOLS:
        # The four coding tools (S4 fix round 1): free-text fields, and the string arguments
        # (codes, an occurrence code), which a model could fill with anything.
        args = call.arguments
        for key, kind in (("reason", "lookup_reason"), ("expected_effect", "lookup_effect")):
            if isinstance(args.get(key), str):
                bucket[kind].append(str(args[key]))
        codes = args.get("codes")
        if isinstance(codes, list | tuple):
            bucket["lookup_arg"].extend(c for c in codes if isinstance(c, str))
        if isinstance(args.get("occurrence"), str):
            bucket["lookup_arg"].append(str(args["occurrence"]))


def load_dev_cases(run_ids: Sequence[str]) -> Loaded:  # pragma: no cover -- real data
    """Read the runs and the development cases they share; cache only, no network.

    Args:
        run_ids: finished ``dev-400`` arm C run ids (``load_runs`` refuses anything else).

    Returns:
        One ``NameCase`` per shared case with a readable record.
    """
    settings = Settings()
    runs = load_runs(PROG, run_ids)
    shared = sorted(set.intersection(*({c.case_id for c in run.cases} for run in runs)))
    texts: dict[str, dict[str, list[str]]] = {cid: {k: [] for k in KINDS} for cid in shared}
    for run in runs:
        for call in run.calls:
            if call.case_id in texts:
                _collect(call, texts[call.case_id])
    cases: list[NameCase] = []
    no_listing = skipped = 0
    for raw in load_cases(settings.data_dir / "processed", shared):
        case_id = str(raw.get("ntsbNumber"))
        try:
            cause = split_record(raw)[2].probable_cause
        except LeakageError:
            skipped += 1
            continue
        titles: tuple[str, ...] = ()
        mkey = raw.get("mKey")
        path = settings.docket_dir / str(mkey) / "listing.html"
        if isinstance(mkey, int) and path.is_file():
            try:
                page = path.read_text(encoding="utf-8", errors="replace")
                titles = tuple(e.title for e in parse_listing(page, mkey=mkey).entries)
            except DocketError:
                no_listing += 1
        else:
            no_listing += 1
        kinds = {k: tuple(v) for k, v in texts[case_id].items()}
        kinds["ntsb_cause"] = (cause,) if cause else ()
        cases.append(NameCase(titles, tuple(owner_operator_values(raw)), kinds))
    return Loaded(cases, tuple(run.record.run_id for run in runs), no_listing, skipped)


def main(argv: Sequence[str] | None = None, loader: Loader = load_dev_cases) -> int:
    """Print, and with ``--out`` also write, the names counts.

    Args:
        argv: arguments; ``RUN_ID`` twice overrides the two default noise-floor runs.
        loader: reads the runs and cases; a test passes a fake.

    Returns:
        0.
    """
    parser = argparse.ArgumentParser(prog=PROG)
    parser.add_argument("runs", nargs="*", metavar="RUN_ID", default=list(DEFAULT_RUNS))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    known, dictionary = known_title_words()
    loaded = loader(args.runs)
    text = "\n".join(report_lines(count_names(loaded.cases, known), loaded, dictionary=dictionary))
    print(text)
    if args.out is not None:
        write_result(PROG, Path(args.out), text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
