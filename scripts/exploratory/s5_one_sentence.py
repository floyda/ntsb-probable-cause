"""Question 6's figure on the public site (S5 spec §7.4): one cause sentence, many first codes.

Status
    Exploratory (decision 0059), free and offline: no model call, no run. It decides nothing. It
    reads S3's statistics pool (development only, guarded as ``s3_coding_consistency`` reads it)
    and writes ``docs/results/s5-one-sentence-dev.txt``. Counts and code labels only, with one
    exception the specification asks for: the one sentence the figure shows (§7.4, question 6).
    No case number, and no other text from any record.

The rule (fixed before the data was read; Andy, 2026-10-14, plan step 4b choice 3)
    Among the exact-twin groups of all years (two or more pool cases whose NTSB probable-cause
    sentences match word for word, as ``s3_coding_consistency`` forms them), take the group
    whose cases received the most different first occurrence codes. A tie goes to the group
    with more cases, then to the group whose shown sentence sorts first. The sentence shown is
    the group's commonest exact text, a tie to the text that sorts first. The page says how the
    sentence was chosen, so it is never read as typical.

Refusals
    A pool case outside the development split (the pool reader's own guard), and a sentence
    holding a capitalised word that starts no sentence and is not on the allow list
    (``scripts.site_example_case.unexpected_capitals``; rule 6). Andy reads the sentence before
    it is published (plan Task 6).

Usage
    uv run python -m scripts.exploratory.s5_one_sentence [--out PATH]
"""

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from scripts.exploratory import s3_coding_consistency as cc
from scripts.exploratory import s3_precedent_probe as pp
from scripts.site_example_case import unexpected_capitals

from ntsb_probable_cause.settings import Settings
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables

RULE: Final = (
    "The rule (fixed before the data was read; Andy, 2026-10-14): among groups of two or more "
    "cases whose NTSB probable-cause sentences match word for word (exact twins, all years), the "
    "group whose cases received the most different first codes; a tie goes to the group with "
    "more cases, then to the sentence that sorts first."
)


@dataclass(frozen=True)
class Chosen:
    """The chosen group: its sentence, its size, and its first codes with their counts."""

    sentence: str
    cases: int
    codes: tuple[tuple[str, int], ...]  # (first code, cases), most common first, ties by code
    groups: int  # exact-twin groups in the pool, for the reader's context


def _sentence(group: cc.Group) -> str:
    texts = Counter(case.text.strip() for case in group)
    return min(texts, key=lambda t: (-texts[t], t))


def _first_codes(group: cc.Group) -> tuple[tuple[str, int], ...]:
    counts = Counter(case.sequence[0] for case in group)
    return tuple(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def choose(cases: Sequence[pp.PoolText]) -> Chosen:
    """The group the rule picks, whatever the order of ``cases``."""
    groups = cc.form_groups(cases, "exact")
    if not groups:
        raise SystemExit("s5_one_sentence: the pool holds no exact twins")
    best = min(
        groups,
        key=lambda g: (-len(_first_codes(g)), -len(g), _sentence(g)),
    )
    sentence = _sentence(best)
    named = unexpected_capitals(sentence)
    if named:
        raise SystemExit(
            f"s5_one_sentence: the chosen sentence holds {len(named)} capitalised word(s) "
            "mid-sentence; nothing is written (rule 6)"
        )
    return Chosen(sentence=sentence, cases=len(best), codes=_first_codes(best), groups=len(groups))


def _label(code: str, tables: CodeTables) -> str:
    phase, event = tables.phases.get(code[:3]), tables.events.get(code[3:])
    return f"{phase} / {event}" if phase is not None and event is not None else code


def report(chosen: Chosen, tables: CodeTables) -> str:
    """The results file's text."""
    lines = [
        "S5 question 6: one cause sentence and its first codes "
        "(scripts/exploratory/s5_one_sentence.py; decision 0059)",
        "Exploratory: free and offline, no model call; it decides nothing. S3's statistics pool, "
        "development only. Counts and code labels only, but for the one sentence the S5 "
        "specification §7.4 publishes; no case number.",
        RULE,
        "",
        f"exact-twin groups, all years: {chosen.groups}",
        f"sentence: {chosen.sentence}",
        f"cases: {chosen.cases}",
        f"different first codes: {len(chosen.codes)}",
        "first codes, most common first (cases, code, label):",
    ]
    lines += [f"- {n}  {code}  {_label(code, tables)}" for code, n in chosen.codes]
    return "\n".join(lines) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Print, and with ``--out`` also write, the chosen sentence and its first codes."""
    parser = argparse.ArgumentParser(prog="s5_one_sentence")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    cases, _dates, _counts = pp.read_pool_texts(Settings().data_dir / "processed")
    text = report(choose(cases), load_tables())
    print(text, end="")
    if args.out is not None:
        args.out.write_text(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
