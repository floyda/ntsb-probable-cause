"""How many cases carry an owner or operator name, and what shape those names are (0046).

Counts only. No name is printed, written or returned: the point of the measurement is to decide
whether searching document text for the names the record already holds is worth doing, and at
what granularity, not to look at anybody's name.

Run: ``uv run python -m scripts.name_coverage`` (add ``--out PATH`` to save the text).
"""

import argparse
from collections import Counter
from pathlib import Path

from ntsb_probable_cause.data.redaction import REDACTED_FIELDS
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings

# Name-bearing fields, as opposed to the addresses, postcodes and certificate number that
# REDACTED_FIELDS also holds. Only these decide "does this case name a person at all".
NAME_FIELDS = (
    "registeredOwner",
    "ownerIndividual",
    "operatorName",
    "operatorIndividual",
    "operatorDoingBusinessAs",
)
# Tokens that mark a name as an organisation rather than an individual. A judgement, and the
# report says so: it separates "77% look like people" from a claim that they are.
ORGANISATION_TOKENS = (
    "INC",
    "LLC",
    "L.L.C",
    "CORP",
    "CLUB",
    "COMPANY",
    "CO.",
    "AVIATION",
    "SERVICE",
    "LTD",
    "TRUST",
    "LEASING",
    "PARTNERS",
    "ASSOC",
    "SCHOOL",
    "UNIVERSITY",
    "FLYING",
    "AIRWAYS",
    "CHARTER",
    "AIRLINES",
    "HOLDINGS",
    "ENTERPRISES",
)
WORDS_FILE = Path("/usr/share/dict/words")
MIN_WORD_LEN = 3
MIN_NAME_WORDS = 2


def looks_like_an_organisation(name: str) -> bool:
    """True if the name carries a token that marks it as a company rather than a person."""
    upper = name.upper()
    return any(token in upper for token in ORGANISATION_TOKENS)


def owner_operator_values(record: dict[str, object], fields: tuple[str, ...]) -> list[str]:
    """Every non-empty value of ``fields`` under this record's owner/operator entries."""
    found: list[str] = []
    aircrafts = record.get("aircrafts")
    for aircraft in aircrafts if isinstance(aircrafts, list) else []:
        operators = aircraft.get("ownerOperators") if isinstance(aircraft, dict) else None
        for operator in operators if isinstance(operators, list) else []:
            if not isinstance(operator, dict):
                continue
            for field in fields:
                value = operator.get(field)
                if isinstance(value, str) and value.strip():
                    found.append(value.strip())
    return found


def ordinary_words() -> frozenset[str]:
    """The system word list, lowercased; empty if the platform has none."""
    if not WORDS_FILE.is_file():
        return frozenset()
    with WORDS_FILE.open() as handle:
        return frozenset(w.strip().lower() for w in handle if len(w.strip()) >= MIN_WORD_LEN)


def report(records: list[dict[str, object]]) -> str:
    """The measurement, as the text decision 0046 quotes. Counts only, never a name."""
    cases_with_a_name = sum(1 for r in records if owner_operator_values(r, NAME_FIELDS))
    names = [v for r in records for v in owner_operator_values(r, NAME_FIELDS)]
    organisations = sum(1 for n in names if looks_like_an_organisation(n))
    shortest = min((len(n) for n in names), default=0)
    lengths = Counter(len(n.split()) for n in names)
    surnames = {
        n.split()[-1].lower()
        for n in names
        if not looks_like_an_organisation(n) and len(n.split()) >= MIN_NAME_WORDS
    }
    words = ordinary_words()
    collisions = {s for s in surnames if s in words}
    per_field = {
        f: sum(1 for r in records for _ in owner_operator_values(r, (f,)))
        for f in sorted(REDACTED_FIELDS)
    }
    # Decision 0046 item 5: a value that is nothing but digits cannot be told apart from the
    # many numbers a docket legitimately holds -- serials, weights, readings -- so replacing it
    # would corrupt evidence and add non-name hits to a count published as a floor on names.
    numeric = {
        f: sum(1 for r in records for v in owner_operator_values(r, (f,)) if v.isdigit())
        for f in sorted(REDACTED_FIELDS)
    }
    # Fix finding 3: 0046's justification (no recorded name under five characters, the 28%
    # surname collision) rests on ``NAME_FIELDS`` alone, but the docket replacement it
    # justifies (``attach.redact_known_names``) reaches every ``REDACTED_FIELDS`` value --
    # addresses, zip codes, a certificate number too. Both scopes are reported below, by
    # name rather than left for a reader to infer from the code.
    further_fields = sorted(REDACTED_FIELDS - set(NAME_FIELDS))

    lines = [
        "owner and operator names in the development split (decision 0046)",
        "counts only; no name is printed, saved or returned",
        "",
        f"cases                                     {len(records)}",
        f"cases naming an owner or operator         {cases_with_a_name}"
        f" ({100 * cases_with_a_name / len(records):.1f}%)",
        f"name strings in total                     {len(names)}",
        f"  carrying an organisation token          {organisations}"
        f" ({100 * organisations / len(names):.0f}%)",
        f"  not carrying one (person-looking)       {len(names) - organisations}"
        f" ({100 * (len(names) - organisations) / len(names):.0f}%)",
        f"shortest name string                      {shortest} characters",
        "words per name                            "
        + ", ".join(f"{w}: {c}" for w, c in sorted(lengths.items())),
        "",
        f"distinct person-looking surnames          {len(surnames)}",
        f"  also ordinary dictionary words          {len(collisions)}"
        + (f" ({100 * len(collisions) / len(surnames):.0f}%)" if surnames else "")
        + ("" if words else "   [no system word list; not measured]"),
        "",
        "name-bearing fields -- everything above (shortest string, words per name, surname",
        "collisions) is counted over these five fields only:",
        "  " + ", ".join(sorted(NAME_FIELDS)),
        "further owner/operator fields the docket replacement (decision 0046) also covers --",
        "addresses, zip codes, a certificate number; not name-bearing, no claim above is",
        "measured over these:",
        "  " + ", ".join(further_fields),
        "",
        "non-empty values per redacted field, and how many are bare digits",
        "(name-bearing fields marked *; the rest are the further fields above):",
        *(
            f"  {f:28s} {n:5d}{' *' if f in NAME_FIELDS else '  '}"
            + (f"   ({numeric[f]} all digits)" if numeric[f] else "")
            for f, n in per_field.items()
        ),
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Print the measurement, optionally saving it."""
    parser = argparse.ArgumentParser(prog="name_coverage")
    parser.add_argument("--sample", default="dev-400")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    records = load_cases(settings.data_dir / "processed", sample_ids(args.sample))
    text = report(records)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
