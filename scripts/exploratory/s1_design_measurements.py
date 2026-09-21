"""Measurements behind the S1 design (docs/specs/2026-09-14-s1-scoring-and-evaluation-design.md).

Status
    One-shot, complete (S1 design). Exploratory arithmetic behind the
    specification named above, kept so its figures can be re-derived. It produces no
    committed result and nothing imports it.

Exploratory and one-off, in the pattern of `s0_design_measurements.py`. It reads the frozen
spike's local data because this repository's `data/` is not in git. The S1 harness
supersedes every number here once it runs on `cases.parquet`.

No withheld text is read. Only codes, code labels, counts and field presence are used. The
held-out split is touched only through codes, injury level, class letter, report flavour
and narrative presence; the open split is not touched.

M10 reads the NTSB's public data dictionary, a table inside the downloadable dataset
`avall.zip` (https://www.ntsb.gov/safety/data/Pages/Data_Stats.aspx), which the spike holds at
`data/raw/avall.zip`. It is an Access database; the table is exported with mdbtools
(`brew install mdbtools`). The dictionary is a reference document: code, meaning, definition.

Usage (from the repository root, with the spike's virtual environment):
    ../ntsb-spike/.venv/bin/python scripts/exploratory/s1_design_measurements.py ../ntsb-spike
"""

from __future__ import annotations

import collections
import csv
import io
import json
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

DEV_MAX_YEAR = 2019
HELDOUT_YEARS = range(2020, 2024)
FACTUAL = "narratives[0].concatenatedFactualNarrative"


def section(title: str) -> None:
    print(f"\n== {title}")


def as_list(value: object) -> list[str]:
    if value is None or isinstance(value, str):
        return []
    return [str(v) for v in value]  # type: ignore[union-attr]


def _plain(value: object) -> object:
    """Turn parquet's nested numpy arrays into plain lists and dicts."""
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)) or hasattr(value, "tolist"):
        return [_plain(v) for v in (value.tolist() if hasattr(value, "tolist") else value)]  # type: ignore[union-attr]
    return value


def aircrafts(value: object) -> list[dict]:
    if value is None:
        return []
    if isinstance(value, str):
        return json.loads(value)
    plain = _plain(value)
    return [a for a in plain if isinstance(a, dict)] if isinstance(plain, list) else []


def est_tokens(text: str) -> int:
    return len(text) // 4


def main(spike: Path) -> None:
    df = pd.read_parquet(spike / "data/processed/filtered.parquet")
    df["cls"] = df.ntsbNumber.str[5]
    df["fatal"] = df.highestInjuryLevel == "Fatal"
    dev = df[df._event_year <= DEV_MAX_YEAR]
    held = df[df._event_year.isin(HELDOUT_YEARS)]
    print(f"filtered closed GA cases: {len(df)}; development {len(dev)}; held-out {len(held)}")

    # Code vocabularies and labels, from the development split only.
    occ_label: dict[str, str] = {}
    fin_label: dict[str, str] = {}
    tier_label: dict[str, str] = {}
    for _, row in dev.iterrows():
        for ac in aircrafts(row.aircrafts):
            for ev in ac.get("events") or []:
                code = str(ev.get("eventCode") or "")
                t1, t2 = (ev.get("eventTier1Name") or "").strip(), (ev.get("eventTier2Name") or "").strip()
                if code and (t1 or t2):
                    occ_label[code] = f"{t1} — {t2}" if t1 and t2 else (t1 or t2)
            for f in ac.get("findings") or []:
                code = str(f.get("findingCode") or "")
                desc = (f.get("findingDescription") or "").strip()
                if code and desc:
                    fin_label[code] = desc
                if len(code) == 10:
                    names = [(f.get(f"tier{i}Name") or "").strip() for i in (1, 2, 3)]
                    tier_label[code[:6]] = " — ".join(n for n in names if n)

    section("M1 occurrence codes: vocabulary from the development split, coverage of held-out")
    dev_primary = collections.Counter(as_list(v)[0] for v in dev["derived.eventCodes"] if as_list(v))
    held_primary = collections.Counter(as_list(v)[0] for v in held["derived.eventCodes"] if as_list(v))
    dev_all = {c for v in dev["derived.eventCodes"] for c in as_list(v)}
    print(f"distinct primary (defining-event) codes, development: {len(dev_primary)}; any position: {len(dev_all)}")
    print(f"labelled codes in development: {len(occ_label)}")
    print(f"distinct primary codes, held-out: {len(held_primary)}")
    covered = sum(n for c, n in held_primary.items() if c in dev_primary)
    print(f"held-out cases whose primary code is in the development vocabulary: {covered} of {sum(held_primary.values())} ({covered / sum(held_primary.values()):.1%})")
    top = held_primary.most_common(10)
    print(f"share of held-out cases in the 10 most common primary codes: {sum(n for _, n in top) / sum(held_primary.values()):.1%}")
    print(f"most common held-out primary code: {top[0][0]} ({occ_label.get(top[0][0], '?')}) {top[0][1] / sum(held_primary.values()):.1%}")
    print(f"development cases with no occurrence code: {int(sum(1 for v in dev['derived.eventCodes'] if not as_list(v)))}; held-out: {int(sum(1 for v in held['derived.eventCodes'] if not as_list(v)))}")

    section("M2 finding codes: vocabulary from the development split, coverage of held-out")
    dev_fin = collections.Counter(c for v in dev["derived.findingCodes"] for c in as_list(v))
    held_fin = collections.Counter(c for v in held["derived.findingCodes"] for c in as_list(v))
    print(f"distinct 10-digit finding codes, development: {len(dev_fin)}; held-out: {len(held_fin)}")
    print(f"distinct 8-digit prefixes (tiers 1-4), development: {len({c[:8] for c in dev_fin})}; 6-digit (tiers 1-3): {len({c[:6] for c in dev_fin})}; 4-digit (tiers 1-2): {len({c[:4] for c in dev_fin})}")
    cov_codes = sum(n for c, n in held_fin.items() if c in dev_fin)
    print(f"held-out finding-code instances in the development vocabulary: {cov_codes} of {sum(held_fin.values())} ({cov_codes / sum(held_fin.values()):.1%})")
    cov6 = sum(n for c, n in held_fin.items() if c[:6] in {d[:6] for d in dev_fin})
    print(f"  at 6 digits: {cov6 / sum(held_fin.values()):.1%}")
    full = sum(1 for v in held["derived.findingCodes"] if as_list(v) and all(c in dev_fin for c in as_list(v)))
    print(f"held-out cases whose every finding code is in the development vocabulary: {full} of {len(held)} ({full / len(held):.1%})")
    once = sum(1 for c, n in dev_fin.items() if n == 1)
    print(f"development finding codes seen once: {once} of {len(dev_fin)}; seen 5+ times: {sum(1 for n in dev_fin.values() if n >= 5)}")
    cov5 = sum(n for c, n in held_fin.items() if dev_fin.get(c, 0) >= 5)
    print(f"held-out finding-code instances covered by codes seen 5+ times in development: {cov5 / sum(held_fin.values()):.1%}")

    section("M3 findings per case and the in-probable-cause flag")
    for name, part in (("development", dev), ("held-out", held)):
        counts = [len(as_list(v)) for v in part["derived.findingCodes"]]
        s = pd.Series(counts)
        print(f"{name}: findings per case median {s.median():.0f}, p90 {s.quantile(0.9):.0f}, max {s.max()}, zero {(s == 0).sum()}")
    in_cause = total = cases_any = cases_all = cases_flagged = 0
    for _, row in df.iterrows():
        flags = [bool(f.get("inProbableCause")) for ac in aircrafts(row.aircrafts) for f in ac.get("findings") or []]
        if flags:
            cases_flagged += 1
            total += len(flags)
            in_cause += sum(flags)
            cases_any += any(flags)
            cases_all += all(flags)
    print(f"all splits: cases with findings {cases_flagged}; findings {total}; flagged in probable cause {in_cause} ({in_cause / total:.1%})")
    print(f"cases with at least one flagged finding: {cases_any} ({cases_any / cases_flagged:.1%}); with every finding flagged: {cases_all} ({cases_all / cases_flagged:.1%})")
    multi = int((df.aircrafts.map(lambda v: len(aircrafts(v))) > 1).sum())
    print(f"cases with more than one aircraft: {multi} ({multi / len(df):.1%})")

    section("M4 held-out: fatal / non-fatal by investigation class (the slices)")
    print(pd.crosstab(held.cls, held.fatal.map({True: "fatal", False: "non-fatal"}), margins=True).to_string())
    print("development, same table:")
    print(pd.crosstab(dev.cls, dev.fatal.map({True: "fatal", False: "non-fatal"}), margins=True).to_string())

    section("M5 held-out: report flavour and factual-narrative presence by class (S0 open question)")
    has_factual = held[FACTUAL].fillna("").str.len() > 0
    print(pd.crosstab(held.cls, held.factualFinalReportFlavor.fillna("(none)"), margins=True).to_string())
    print("factual narrative present, by class:")
    print(pd.crosstab(held.cls, has_factual.map({True: "present", False: "absent"}), margins=True).to_string())
    print("factual narrative present, by flavour:")
    print(pd.crosstab(held.factualFinalReportFlavor.fillna("(none)"), has_factual.map({True: "present", False: "absent"}), margins=True).to_string())

    section("M6 size of the code lists rendered for the model (characters / 4)")
    occ_text = "\n".join(f"{c} {occ_label.get(c, '')}" for c in sorted(dev_primary))
    print(f"occurrence list, primary codes with labels: {len(dev_primary)} lines, ~{est_tokens(occ_text)} tokens")
    fin_text = "\n".join(f"{c} {fin_label.get(c, '')}" for c in sorted(dev_fin))
    print(f"finding list, every 10-digit code with description: {len(dev_fin)} lines, ~{est_tokens(fin_text)} tokens")
    fin5 = [c for c, n in dev_fin.items() if n >= 5]
    fin5_text = "\n".join(f"{c} {fin_label.get(c, '')}" for c in sorted(fin5))
    print(f"finding list, codes seen 5+ times: {len(fin5)} lines, ~{est_tokens(fin5_text)} tokens")
    tier_text = "\n".join(f"{c} {tier_label.get(c, '')}" for c in sorted({d[:6] for d in dev_fin}))
    print(f"finding list at 6 digits (tiers 1-3) with names: {len(tier_label)} lines, ~{est_tokens(tier_text)} tokens")
    mods = collections.Counter(c[8:] for c in dev_fin)
    print(f"distinct modifiers (last 2 digits): {len(mods)}; most common: {mods.most_common(5)}")

    section("M7 the 40 like-for-like cases: slices they fall into")
    ids = pd.read_csv(spike / "labelling/decidability.filled.csv", dtype=str).case_id
    forty = df[df.ntsbNumber.isin(ids)]
    print(f"found {len(forty)} of {len(ids)}")
    print(pd.crosstab(forty.cls, forty.fatal.map({True: "fatal", False: "non-fatal"}), margins=True).to_string())

    section("M8 start-fact purity on the development split: does one value fix the occurrence code?")
    dev2 = dev[dev["derived.eventCodes"].map(lambda v: bool(as_list(v)))].copy()
    dev2["primary"] = dev2["derived.eventCodes"].map(lambda v: as_list(v)[0])
    for col in ("derived.phaseOfFlight", "highestInjuryLevel", "aircrafts[0].engines[0].engineType"):
        grp = dev2.groupby(col).primary
        top_share = grp.agg(lambda s: s.value_counts(normalize=True).iloc[0])
        sizes = grp.size()
        pure = sizes[(top_share >= 0.9) & (sizes >= 20)]
        best = top_share[sizes >= 20].max()
        print(f"{col}: values {len(sizes)}; values (n>=20) where one code takes 90%+: {len(pure)}; highest single-code share among values with n>=20: {best:.1%}")
    prefix_ok = (dev2["derived.phaseOfFlight"].fillna("") != "").sum()
    print(f"development cases with a phase of flight value: {int(prefix_ok)} of {len(dev2)}")

    section("M9 occurrence code = phase prefix + event suffix: the two tables")
    prefixes = collections.Counter(c[:3] for c in dev_primary.elements())
    suffixes = collections.Counter(c[3:] for c in dev_primary.elements())
    print(f"distinct 3-digit prefixes among development primary codes: {len(prefixes)}; distinct 3-digit suffixes: {len(suffixes)}")
    suffix_labels: dict[str, set[str]] = collections.defaultdict(set)
    prefix_labels: dict[str, set[str]] = collections.defaultdict(set)
    for code, label in occ_label.items():
        if len(code) == 6 and " — " in label:
            t1, t2 = label.split(" — ", 1)
            prefix_labels[code[:3]].add(t1)
            suffix_labels[code[3:]].add(t2)
    print(f"prefixes with exactly one tier-1 (phase) label: {sum(1 for v in prefix_labels.values() if len(v) == 1)} of {len(prefix_labels)}")
    print(f"suffixes with exactly one tier-2 (event) label: {sum(1 for v in suffix_labels.values() if len(v) == 1)} of {len(suffix_labels)}")
    combos = len(prefixes) * len(suffixes)
    print(f"possible prefix x suffix combinations: {combos}; seen as a primary code in development: {len(dev_primary)}")
    held_suffix_cov = sum(n for c, n in held_primary.items() if c[3:] in suffixes and c[:3] in prefixes)
    print(f"held-out cases whose primary code is composable from the development tables: {held_suffix_cov / sum(held_primary.values()):.1%}")
    pre_text = "\n".join(f"{p} {'/'.join(sorted(prefix_labels.get(p, {'?'})))}" for p in sorted(prefixes))
    suf_text = "\n".join(f"{s} {'/'.join(sorted(suffix_labels.get(s, {'?'})))}" for s in sorted(suffixes))
    print(f"phase table ~{est_tokens(pre_text)} tokens; event table ~{est_tokens(suf_text)} tokens")
    held_suffix = collections.Counter(c[3:] for c in held_primary.elements())
    print(f"share of held-out cases in the 10 most common event suffixes: {sum(n for _, n in held_suffix.most_common(10)) / sum(held_suffix.values()):.1%}")

    section("M10 the NTSB's public data dictionary as the source of the code tables")
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(spike / "data/raw/avall.zip") as z:
            z.extract("avall.mdb", tmp)
        out = subprocess.run(["mdb-export", f"{tmp}/avall.mdb", "eADMSPUB_DataDictionary"], capture_output=True, text=True, check=True).stdout
    rows = list(csv.DictReader(io.StringIO(out)))
    print(f"dictionary rows: {len(rows)}")
    items = {r["code_iaids"][:8]: r["meaning"] for r in rows if r["Table"] == "Findings" and r["Column"] == "findings_code" and r["code_iaids"].endswith("XX")}
    modifiers = {r["code_iaids"][-2:]: r["meaning"] for r in rows if r["Table"] == "Findings" and r["Column"] == "modifier_no"}
    events = {r["code_iaids"][-3:]: r["meaning"] for r in rows if r["Table"] == "Events_Sequence" and r["Column"] == "Occurrence_Code"}
    print(f"finding items (8 digits): {len(items)}; distinct 6-digit categories among them: {len({k[:6] for k in items})}; 4-digit: {len({k[:4] for k in items})}")
    print(f"modifiers: {len(modifiers)}; occurrence events (3-digit suffix): {len(events)}")
    per_cat = collections.Counter(k[:6] for k in items)
    median_items = sorted(per_cat.values())[len(per_cat) // 2]
    print(f"items per 6-digit category: median {median_items}, max {max(per_cat.values())}")
    dev8 = {c[:8] for c in dev_fin}
    print(f"development 8-digit items in the official list: {len(dev8 & set(items))} of {len(dev8)}")
    held_ok = sum(n for c, n in held_fin.items() if c[:8] in items and c[8:] in modifiers)
    print(f"held-out finding-code instances composable from official item + modifier: {held_ok / sum(held_fin.values()):.1%}")
    held_ev = sum(n for c, n in held_primary.items() if c[3:] in events)
    print(f"held-out primary occurrence codes whose event suffix is in the official list: {held_ev / sum(held_primary.values()):.1%}")
    dev_ev = {c[3:] for c in dev_primary}
    print(f"development event suffixes in the official list: {len(dev_ev & set(events))} of {len(dev_ev)}")
    item_text = "\n".join(f"{k} {v}" for k, v in sorted(items.items()))
    mod_text = "\n".join(f"{k} {v}" for k, v in sorted(modifiers.items()))
    ev_text = "\n".join(f"{k} {v}" for k, v in sorted(events.items()))
    print(f"official item list ~{est_tokens(item_text)} tokens; modifier list ~{est_tokens(mod_text)} tokens; event list ~{est_tokens(ev_text)} tokens")
    print(f"a stage-2 list for 3 chosen categories at the median: ~{3 * median_items} rows")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "../ntsb-spike"))
