"""Question 1's case on the public site (S5 spec §7.4): one closed case as the NTSB published it.

Status
    Repeatable, free: reads one committed, redacted development fixture
    (``tests/fixtures/records/``, decision 0015), makes no model call and writes
    ``site/data/example-case.json``. ``tests/test_site_example_case.py`` fails while the
    committed file differs from a fresh build, as the numbers file's test does.

Why
    The Path page's first question, "Is there an answer key nobody had to write?", is answered
    by showing one: a case's probable cause and its codes, exactly as the NTSB published them.
    §7.4 asks for a non-fatal development case, to keep the first example gentle; Andy chose
    ``ANC09CA020`` (2026-10-14).

What it reads
    The fixture's record goes through ``split_record`` (rule 1: the one place a record is
    split), and only the verdict is kept: the probable cause, the occurrence codes in the NTSB's
    order, the finding codes and which of them are in the probable cause. Codes are labelled
    from the code tables by S4's board rule (``live/board.py``): an occurrence as
    "phase / event", a finding as "item - modifier".

Refusals
    A case outside the development split, a fatal case, or a probable cause holding a
    capitalised word that is neither a sentence's first word nor on the allow list (a name could
    hide there; rule 6). Andy reads the cause before it is published (plan Task 6).

Usage
    uv run python -m scripts.site_example_case [--case ANC09CA020] [--check]
"""

import argparse
import json
import re
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.splits import Split, split_of

_REPO = Path(__file__).resolve().parents[1]
_FIXTURES = _REPO / "tests/fixtures/records"
_OUT = _REPO / "site/data/example-case.json"
_CHOSEN = "ANC09CA020"

# Capitalised words a probable cause may hold mid-sentence without naming anyone.
_ALLOWED = frozenset({"NTSB", "FAA", "VFR", "IFR", "VMC", "IMC"})
_WORD = re.compile("[A-Za-z][A-Za-z'\u2019-]*")  # straight or curly apostrophe


class Code(BaseModel):
    """One code and its label."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    code: str
    label: str


class Finding(Code):
    """A finding code, and whether it is in the probable cause."""

    in_cause: bool


class ExampleCase(BaseModel):
    """The file the site reads."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    format: Literal["example-case/1"] = "example-case/1"
    case_number: str
    mkey: int | None
    event_date: str
    injury: Literal["none", "minor", "serious"]
    cause: str | None
    occurrence: tuple[Code, ...]
    findings: tuple[Finding, ...]


def unexpected_capitals(text: str) -> list[str]:
    """Capitalised words that start no sentence and are not allowed: where a name could be."""
    found: list[str] = []
    for sentence in re.split(r"(?<=[.!?])\s+", text.strip()):
        words = _WORD.findall(sentence)
        found += [w for w in words[1:] if w[0].isupper() and w not in _ALLOWED]
    return found


def _occurrence(code: str, tables: CodeTables) -> Code:
    phase, event = tables.phases.get(code[:3]), tables.events.get(code[3:])
    label = f"{phase} / {event}" if phase is not None and event is not None else code
    return Code(code=code, label=label)


def _finding(code: str, in_cause: bool, tables: CodeTables) -> Finding:
    item, modifier = tables.items.get(code[:8]), tables.modifiers.get(code[8:])
    label = f"{item} - {modifier}" if item is not None and modifier is not None else code
    return Finding(code=code, label=label, in_cause=in_cause)


_INJURY = {"None": "none", "Minor": "minor", "Serious": "serious"}


def build(case: str, fixtures: Path = _FIXTURES) -> ExampleCase:
    """The example case from its fixture; refuses a non-development, fatal or named case."""
    raw = json.loads((fixtures / f"{case}.json").read_text())["record"]
    event_date = str(raw["eventDate"])
    if split_of(date.fromisoformat(event_date)) != Split.DEV:
        raise ConfigurationError(f"{case}: not a development case")
    injury = _INJURY.get(str(raw.get("highestInjuryLevel")))
    if injury is None:
        raise ConfigurationError(f"{case}: a fatal or unknown injury level; §7.4 asks non-fatal")
    _, _, verdict = split_record(raw)
    if verdict.probable_cause is not None and unexpected_capitals(verdict.probable_cause):
        raise ConfigurationError(
            f"{case}: its probable cause holds a capitalised word mid-sentence"
        )
    tables = load_tables()
    in_cause = set(verdict.finding_codes_in_cause)
    mkey = raw.get("mKey")
    return ExampleCase(
        case_number=case,
        mkey=mkey if isinstance(mkey, int) else None,
        event_date=event_date,
        injury=injury,
        cause=verdict.probable_cause,
        occurrence=tuple(_occurrence(c, tables) for c in verdict.occurrence_codes),
        findings=tuple(_finding(c, c in in_cause, tables) for c in verdict.finding_codes),
    )


def render(example: ExampleCase) -> str:
    """The file's text: two-space indent, a trailing newline."""
    return json.dumps(json.loads(example.model_dump_json()), indent=2) + "\n"


def main(argv: Sequence[str] | None = None) -> int:
    """Write the example case's file, or with ``--check`` exit 1 when it is stale."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0] if __doc__ else "")
    parser.add_argument("--case", default=_CHOSEN)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    text = render(build(args.case))
    if args.check:
        current = _OUT.is_file() and _OUT.read_text() == text
        if not current:
            print("stale: site/data/example-case.json (run: make site-example-case)")
        return 0 if current else 1
    _OUT.write_text(text)
    print(_OUT.relative_to(_REPO))
    return 0


if __name__ == "__main__":
    sys.exit(main())
