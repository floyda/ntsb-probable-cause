"""Check guidance files share no sentence with any development case's withheld text.

Status
    Live for S2.7 (spec §12, plan W6), free and local: streams every development case in the
    processed file and compares each guidance sentence of 30 or more characters, normalised,
    against the factual narrative, analysis narrative and probable cause. Prints counts and
    the offending guidance sentence only; exits 1 on any match. CI cannot run it (no data).

Usage
    NTSB_DATA_DIR=... uv run python -m scripts.check_guidance r2-loc-stall [r3-...]
"""

import argparse
import json
import re
from collections.abc import Sequence

import pyarrow.parquet as pq

from ntsb_probable_cause import fields
from ntsb_probable_cause.scoring import prompt
from ntsb_probable_cause.settings import Settings

MIN_CHARS = 30


def normalise(text: str) -> str:
    """Lower case, whitespace collapsed."""
    return re.sub(r"\s+", " ", text.lower()).strip()


def sentences(text: str) -> list[str]:
    """The guidance's sentences of at least ``MIN_CHARS`` characters, normalised."""
    parts = (normalise(p) for p in re.split(r"(?<=[.!?])\s+", text))
    return [s for s in parts if len(s) >= MIN_CHARS]


def matches(needles: Sequence[str], haystacks: Sequence[str]) -> list[str]:
    """The needles found in any haystack."""
    return [n for n in needles if any(n in h for h in haystacks)]


def main(argv: Sequence[str] | None = None) -> int:
    """Exit 1 if any guidance sentence appears in a development case's withheld text."""
    parser = argparse.ArgumentParser(prog="check_guidance")
    parser.add_argument("names", nargs="+")
    args = parser.parse_args(argv)
    needles = sentences(prompt.guidance_text(args.names))
    found: set[str] = set()
    cases = 0
    columns = ["split", "raw_json"]
    path = Settings().data_dir / "processed" / "cases.parquet"
    with pq.ParquetFile(path) as parquet:
        for batch in parquet.iter_batches(batch_size=512, columns=columns):
            rows = zip(*(batch.column(c).to_pylist() for c in columns), strict=True)
            for split, raw_json in rows:
                if split != "dev":
                    continue
                raw = json.loads(raw_json)
                texts = [
                    normalise(t)
                    for t in (
                        fields.factual_narrative(raw),
                        fields.analysis_narrative(raw),
                        fields.probable_cause(raw),
                    )
                    if isinstance(t, str)
                ]
                cases += 1
                found.update(matches(needles, texts))
    print(
        f"{len(needles)} guidance sentences checked against {cases} development cases; "
        f"{len(found)} found"
    )
    for sentence in sorted(found):
        print(f"- found: {sentence}")
    return 1 if found else 0


if __name__ == "__main__":
    raise SystemExit(main())
