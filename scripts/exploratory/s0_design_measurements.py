"""Measurements behind the S0 design (docs/specs/2026-09-13-s0-foundation-design.md).

Exploratory and one-off. It reads the frozen spike's local data rather than this
repository's, because this repository has no ingestion yet. S0's
`scripts/corpus_scan.py` supersedes it once `cases.parquet` exists; the numbers it
prints are quoted in the S0 spec and in decision records 0013-0016.

Answer and synthesis text is read here only to count overlaps. Every text
measurement is restricted to the development split (event year <= 2019); the
held-out and open splits are touched only through case numbers, event dates and
field presence.

Usage (from the repository root, with the spike's virtual environment):
    ../ntsb-spike/.venv/bin/python scripts/exploratory/s0_design_measurements.py ../ntsb-spike
"""

from __future__ import annotations

import collections
import glob
import json
import re
import sys
from pathlib import Path

import pandas as pd

FACTUAL = "narratives[0].concatenatedFactualNarrative"
ANALYSIS = "narratives[0].analysisNarrative"
CAUSE = "narratives[0].probableCause"
PRELIM = "narratives[0].prelimNarrative"
METAR = "weatherConditions[0].metar"
DEV_MAX_YEAR = 2019
DUPLICATED_SHARE = 0.5
MIN_SENTENCE = 40


def norm(text: object) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip().lower()


def sentences(text: object) -> list[str]:
    return [s.strip() for s in re.split(r"(?<=[.!?])\s+", norm(text)) if s.strip()]


def codes(value: object) -> list[str]:
    return list(value) if value is not None and not isinstance(value, str) else []  # type: ignore[call-overload]


def section(title: str) -> None:
    print(f"\n== {title}")


def main(spike: Path) -> None:
    df_all = pd.read_parquet(spike / "data/processed/filtered.parquet")

    section("M1 raw fetch: does GetCasesByDateRangeV2 filter on eventDate?")
    total = outside = 0
    for fp in sorted(glob.glob(str(spike / "data/raw/fetched=*/cases_*.json"))):
        m = re.search(r"cases_(\d{4}-\d{2}-\d{2})_(\d{4}-\d{2}-\d{2})", fp)
        assert m is not None
        start, end = m.groups()
        for rec in json.load(open(fp)):
            total += 1
            if not start <= (rec.get("eventDate") or "")[:10] <= end:
                outside += 1
    print(f"raw records: {total}; eventDate outside requested range: {outside}")

    section("M2 case number year vs event year (filtered closed GA cases, all splits)")
    id_year = df_all.ntsbNumber.str[3:5].astype(int) + 2000
    print(f"filtered cases: {len(df_all)}; case-number year != event year: {int((id_year != df_all._event_year).sum())}")
    labelled = pd.concat(
        [
            pd.read_csv(spike / "labelling/decidability.filled.csv").case_id,
            pd.read_csv(spike / "labelling/leakage.filled.csv").case_id,
        ]
    )
    lab = df_all[df_all.ntsbNumber.isin(labelled)]
    lab_mismatch = int((lab.ntsbNumber.str[3:5].astype(int) + 2000 != lab._event_year).sum())
    print(f"labelled cases: {len(labelled)} (found {len(lab)}); event years {lab._event_year.value_counts().sort_index().to_dict()}; "
          f"case-number year != event year: {lab_mismatch}")

    section("M3 personal-data fields present in raw records (one month sample, 2016-08)")
    sample = sorted(glob.glob(str(spike / "data/raw/fetched=*/cases_2016-08*.json")))[0]
    paths: collections.Counter[str] = collections.Counter()

    def walk(obj: object, prefix: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                walk(v, f"{prefix}.{k}")
        elif isinstance(obj, list):
            for v in obj:
                walk(v, f"{prefix}[]")
        else:
            paths[prefix] += 1

    records = json.load(open(sample))
    for rec in records:
        walk(rec)
    personal = sorted(p for p in paths if re.search(r"(owner|operator)(Name|Individual|Address|Zip|DoingBusinessAs)|registeredOwner|CertificateNumber", p))
    print(f"distinct leaf paths: {len(paths)}; mean bytes/record: {len(json.dumps(records)) // len(records)}")
    print("personal-data paths:", personal)

    dev = df_all[df_all._event_year <= DEV_MAX_YEAR].copy()
    dev["cls"] = dev.ntsbNumber.str[5]

    section("M4 dev split: investigation class")
    print(f"dev cases: {len(dev)}")
    print("cases by class:", dev.cls.value_counts().to_dict())
    print("share fatal by class:", dev.groupby("cls").highestInjuryLevel.apply(lambda s: round(float((s == "Fatal").mean()), 3)).to_dict())
    print(f"dev cases with preliminary narrative text: {int((dev[PRELIM].fillna('').str.len() > 0).sum())}")

    narr = dev[dev[FACTUAL].fillna("").str.len() > 0].copy()
    print(f"dev cases with factual narrative: {len(narr)}")

    section("M5 dev split: synthesis and verdict text found verbatim in the factual narrative")
    long_hits = 0
    long_hit_cases: set[str] = set()
    whole_analysis = 0
    cause_hits: list[str] = []
    token_hits = 0
    rows = []
    for _, r in narr.iterrows():
        factual = norm(r[FACTUAL])
        analysis = norm(r[ANALYSIS])
        a_sents = sentences(r[ANALYSIS])
        for s in a_sents + sentences(r[CAUSE]):
            if len(s) >= MIN_SENTENCE and s in factual:
                long_hits += 1
                long_hit_cases.add(r.ntsbNumber)
        for s in sentences(r[CAUSE]):
            if len(s) >= 20 and s in factual:
                cause_hits.append(s[:60])
        if analysis and analysis in factual:
            whole_analysis += 1
        a_long = [s for s in a_sents if len(s) >= MIN_SENTENCE]
        found = sum(s in factual for s in a_long)
        rows.append({"cls": r.cls, "year": r._event_year, "any": found > 0,
                     "share": found / len(a_long) if a_long else 0.0})
        text = " ".join(str(r[c]) for c in (FACTUAL, PRELIM, METAR) if pd.notna(r[c]))
        for c in codes(r["derived.eventCodes"]) + codes(r["derived.findingCodes"]):
            if re.search(rf"\b{c}\b", text):
                token_hits += 1
    print(f"sentences >= {MIN_SENTENCE} chars (analysis + cause) found verbatim: {long_hits} across {len(long_hit_cases)} cases")
    print(f"whole analysis text contained in factual narrative: {whole_analysis}")
    print(f"probable-cause sentences (>= 20 chars) found verbatim: {len(cause_hits)} -> {cause_hits}")
    print(f"occurrence/finding code whole-token hits in factual, prelim or METAR text: {token_hits}")

    o = pd.DataFrame(rows)
    c = o[o.cls == "C"]
    print(f"C-class cases sharing >= 1 analysis sentence: {int(c['any'].sum())} of {len(c)}; "
          f"median share of analysis sentences found: {c.share.median():.2f}")

    section(f"M6 dev split: duplicated narratives (>= {DUPLICATED_SHARE:.0%} of analysis sentences verbatim in factual)")
    o["dup"] = o.share >= DUPLICATED_SHARE
    print(f"duplicated: {int(o.dup.sum())} of {len(o)}; by class: {o[o.dup].cls.value_counts().to_dict()}")
    print(pd.crosstab(o.year, o.cls, values=o.dup, aggfunc="mean").round(2)[["C", "L", "F"]].to_string())

    sys.path.insert(0, str(spike / "src"))
    from ntsb_spike.leakage import GIVEAWAY  # the spike's own phrase list

    pattern = re.compile("|".join(GIVEAWAY), re.I)
    o["giveaway"] = [bool(pattern.search(str(t))) for t in narr[FACTUAL]]
    print("\ngive-away phrase rate in factual narrative, by class and duplication:")
    print(o.groupby(["cls", "dup"]).giveaway.agg(["size", "mean"]).round(3).loc[["C", "L", "F"]].to_string())

    section("M7 dev split: report flavour, investigationClass and richNarratives")
    print("factualFinalReportFlavor by case-number class letter:")
    print(pd.crosstab(dev["factualFinalReportFlavor"].fillna("<null>"), dev.cls)[["C", "L", "F"]].to_string())
    print(f"investigationClass non-null: {int(dev['investigationClass'].notna().sum())} of {len(dev)}")
    o["flavour"] = narr["factualFinalReportFlavor"].fillna("<null>").to_numpy()
    print("duplicated share by report flavour:", o.groupby("flavour").dup.mean().round(2).to_dict())
    rich = 0
    for fp in sorted(glob.glob(str(spike / "data/raw/fetched=*/cases_*.json"))):
        rich += sum(1 for rec in json.load(open(fp)) if rec.get("richNarratives"))
    print(f"raw records (all splits) with non-empty richNarratives: {rich}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    main(Path(sys.argv[1]).resolve())
