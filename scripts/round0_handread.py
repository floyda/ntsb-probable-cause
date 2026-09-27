"""Andy's Round 0 hand-read: about 50 cards, and the narrative-label validation.

Status
    Live for S2.7 (spec §4.4, decision 0099 item 3), free. ``cards`` draws a seeded sample from
    one development run (8 per miss group, or all of a smaller group, and 10 hits) and writes a
    private marking page under data/handcheck/s27-round0/; ``score`` reads Andy's marks and the
    judge's labels and prints counts only.

Why
    The judge's narrative label separates "understood, miscoded" from "misread" but was never
    validated. Andy judges whether the model's account holds the key fact; the rule, fixed in
    advance, compares that with the label. His second answer says why each miss happened.

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.round0_handread cards --run RUN_ID
    NTSB_DATA_DIR=... uv run python -m scripts.round0_handread score MARKS.csv --run RUN_ID \
        [--out PATH]
"""

import argparse
import csv
import html
import random
from collections import Counter
from collections.abc import Mapping, Sequence
from fractions import Fraction
from pathlib import Path

from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring import samples
from ntsb_probable_cause.scoring.codes import CodeTables, load_tables
from ntsb_probable_cause.scoring.judge import JudgeLabels
from ntsb_probable_cause.scoring.metrics import wilson
from ntsb_probable_cause.scoring.misses import MISS_GROUPS, miss_group
from ntsb_probable_cause.scoring.records import CaseResult, RunRecord, read_jsonl
from ntsb_probable_cause.settings import Settings
from scripts import marking_page
from scripts.judge_outcomes import read_labels

SEED = 20260927
PER_GROUP = 8
HITS = 10
FOLDER = Path("handcheck") / "s27-round0"
KEY_FACT = ("yes", "no", "can't tell")
WHY = ("coding convention", "wrong phase", "misread or missing fact", "NTSB code arguable", "other")
# Decision 0099 item 3: validated at 75% agreement on decidable cards, errors both ways.
MIN_AGREEMENT = Fraction(3, 4)


def _guesses(case: CaseResult) -> tuple[str, ...]:
    return tuple(g.phase + g.event for g in case.steps[-1].hypothesis.occurrence)


def draw_cards(cases: Sequence[CaseResult], *, seed: int) -> list[tuple[str, str]]:
    """(case id, group): ``PER_GROUP`` per miss group (all of a smaller one) and ``HITS`` hits."""
    rng = random.Random(seed)  # noqa: S311 -- reproducible sampling, not security
    by_group: dict[str, list[str]] = {}
    for case in sorted(
        (c for c in cases if c.scores is not None and c.steps), key=lambda c: c.case_id
    ):
        group = miss_group(
            _guesses(case), case.verdict_occurrence, abstain=case.steps[-1].hypothesis.abstain
        )
        by_group.setdefault(group, []).append(case.case_id)
    drawn: list[tuple[str, str]] = []
    for group, size in (("exact", HITS), *((g, PER_GROUP) for g in MISS_GROUPS)):
        members = by_group.get(group, [])
        chosen = members if len(members) <= size else rng.sample(members, size)
        drawn.extend((case_id, group) for case_id in sorted(chosen))
    rng.shuffle(drawn)
    return drawn


def _code_words(code: str, tables: CodeTables) -> str:
    return f"{code} ({tables.phases.get(code[:3], '?')} / {tables.events.get(code[3:], '?')})"


def _card(
    row: int, case: CaseResult, raw: Mapping[str, object], group: str, tables: CodeTables
) -> marking_page.Card:
    _evidence, synthesis, verdict = split_record(raw)
    hypothesis = case.steps[-1].hypothesis
    first = _guesses(case)[0]
    defining = case.verdict_occurrence[0] if case.verdict_occurrence else ""
    body = (
        "<div class='pair'>"
        f"<div><h4>The model's account</h4><p>{html.escape(hypothesis.evidence_narrative)}</p>"
        f"<p><b>Its first code:</b> {html.escape(_code_words(first, tables))}</p></div>"
        f"<div><h4>The NTSB's probable cause</h4>"
        f"<p>{html.escape(verdict.probable_cause or '(none)')}</p>"
        f"<p><b>Its defining code:</b> {html.escape(_code_words(defining, tables))}</p></div>"
        "</div>"
        "<details><summary>The investigators' factual narrative (open only if needed)</summary>"
        f"<p>{html.escape(synthesis.factual_narrative or '(none)')}</p></details>"
    )
    choices = [marking_page.Choice("key fact", KEY_FACT)]
    if group != "exact":
        choices.append(marking_page.Choice("why", WHY))
    return marking_page.Card(
        row=row, body_html=body, choices=tuple(choices), text_fields=(("notes", ""),)
    )


def _run(settings: Settings, run_id: str) -> list[CaseResult]:
    """A development run's cases, after every refusal (held-out, then split).

    Mirrors ``judge_outcomes._load``: run.jsonl's recorded sample is checked before
    cases.jsonl is read at all, so a run whose id looks like development but was recorded on
    a held-out sample is refused before any per-case data is touched.
    """
    if "heldout" in run_id or "-dev-" not in run_id:
        raise SystemExit(
            f"round0_handread: {run_id} is not a development run; development runs only"
        )
    folder = settings.runs_dir / run_id
    record = read_jsonl(folder / "run.jsonl", RunRecord)[0]
    if not record.sample.startswith("dev"):
        raise SystemExit(
            f"round0_handread: {run_id} is a held-out run ({record.sample}); development runs only"
        )
    cases = read_jsonl(folder / "cases.jsonl", CaseResult)
    if any(c.split != "dev" for c in cases):
        raise SystemExit(f"round0_handread: {run_id} holds a case outside the dev split")
    return cases


def cmd_cards(settings: Settings, run_id: str) -> str:
    """Write the private page and sheet; return a one-line summary."""
    cases = {c.case_id: c for c in _run(settings, run_id)}
    drawn = draw_cards(list(cases.values()), seed=SEED)
    raws = samples.load_cases(settings.data_dir / "processed", [c for c, _g in drawn])
    tables = load_tables()
    cards = [
        _card(n, cases[c], raw, g, tables)
        for n, ((c, g), raw) in enumerate(zip(drawn, raws, strict=True), start=1)
    ]
    folder = settings.data_dir / FOLDER
    folder.mkdir(parents=True, exist_ok=True)
    intro = (
        "<p>Each card: the model's account and first code beside the NTSB's probable cause and "
        "defining code. Question 1: does the model's account contain the fact the NTSB's cause "
        "rests on? Question 2 (misses only): why did it miss? Open the factual narrative only "
        "when you cannot tell without it.</p>"
    )
    (folder / "index.html").write_text(
        marking_page.render(
            title="S2.7 Round 0 hand-read",
            intro_html=intro,
            cards=cards,
            storage_key="s27-round0-handread",
            csv_name="s27-round0-marks.csv",
        )
    )
    with (folder / "sheet.csv").open("w", newline="") as handle:
        writer = csv.writer(handle, lineterminator="\n")
        writer.writerow(["row", "case_id", "group", "run_id"])
        writer.writerows((n, c, g, run_id) for n, (c, g) in enumerate(drawn, start=1))
    counts = Counter(g for _c, g in drawn)
    return f"{len(drawn)} cards written to {folder}: " + ", ".join(
        f"{g} {n}" for g, n in counts.items()
    )


def score(
    sheet: Sequence[Mapping[str, str]],
    marks: Mapping[int, Mapping[str, str]],
    labels: Mapping[str, JudgeLabels],
) -> str:
    """The validation rule and the miss types, counts only."""
    unmarked = [r["row"] for r in sheet if not marks.get(int(r["row"]), {}).get("key fact")]
    if unmarked:
        raise SystemExit(f"round0_handread: {len(unmarked)} unmarked cards, e.g. row {unmarked[0]}")
    agree = generous = harsh = decidable = 0
    why: Counter[str] = Counter()
    cards_by_group = Counter(r["group"] for r in sheet)
    for row in sheet:
        mark = marks[int(row["row"])]
        if row["group"] != "exact" and mark.get("why"):
            why[mark["why"]] += 1
        andy = mark["key fact"]
        if andy == "can't tell":
            continue
        decidable += 1
        label = labels.get(row["case_id"])
        if label is None:
            raise SystemExit(f"round0_handread: row {row['row']} has no judge label")
        judge_yes = label.narrative == "consistent"
        andy_yes = andy == "yes"
        agree += judge_yes == andy_yes
        generous += judge_yes and not andy_yes
        harsh += andy_yes and not judge_yes
    share = Fraction(agree, decidable) if decidable else Fraction(0)
    validated = decidable > 0 and share >= MIN_AGREEMENT and generous >= 1 and harsh >= 1
    low, high = wilson(agree, decidable) if decidable else (0.0, 0.0)
    lines = [
        "Round 0 hand-read (scripts/round0_handread.py; counts only, decision 0099)",
        "cards by group: " + ", ".join(f"{g} {n}" for g, n in sorted(cards_by_group.items())),
        f'decidable cards (not "can\'t tell"): {decidable} of {len(sheet)}',
        f"agreement: {agree} of {decidable} ({float(share):.1%} [{low:.1%}, {high:.1%}]); "
        "rule: at least 75%",
        "judge errors: generous (judge consistent, Andy no) "
        f"{generous}; harsh (judge not consistent, Andy yes) {harsh}; rule: at least 1 each way",
        f"outcome: {'validated' if validated else 'not validated'}",
        "why the misses happened (Andy): " + ", ".join(f"{w} {why[w]}" for w in WHY),
    ]
    return "\n".join(lines)


def _refuse_mismatched_run(sheet: Sequence[Mapping[str, str]], run_id: str) -> None:
    """Refuse a sheet drawn from a different run than the one now being scored (review fix)."""
    mismatched = {row.get("run_id", "") for row in sheet} - {run_id}
    if mismatched:
        raise SystemExit(
            f"round0_handread: sheet.csv was drawn from {sorted(mismatched)[0]}, not {run_id}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    """``cards`` or ``score``."""
    parser = argparse.ArgumentParser(prog="round0_handread")
    commands = parser.add_subparsers(dest="command", required=True)
    cards_p = commands.add_parser("cards")
    cards_p.add_argument("--run", required=True)
    score_p = commands.add_parser("score")
    score_p.add_argument("marks", type=Path)
    score_p.add_argument("--run", required=True)
    score_p.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "cards":
        print(cmd_cards(settings, args.run))
        return 0
    _run(settings, args.run)
    with (settings.data_dir / FOLDER / "sheet.csv").open(newline="") as handle:
        sheet = list(csv.DictReader(handle))
    _refuse_mismatched_run(sheet, args.run)
    text = score(
        sheet, marking_page.read_marks(args.marks), read_labels(settings.runs_dir / args.run)
    )
    print(text)
    if args.out is not None:
        Path(args.out).write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
