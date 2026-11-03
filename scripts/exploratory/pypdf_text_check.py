"""Does a new pypdf read dev-400's dockets as the old one did? Counts only (decision 0218).

Status
    Exploratory (decision 0059), free and offline: no model call, no network. It reads the
    dev-400 docket cache only. ``make pypdf-text-check`` runs ``read`` under pypdf 6.19.0 (every
    result before 2026-11-02) and under the locked version, then ``compare``, and writes
    ``docs/results/pypdf-text-dev.txt``.

Why
    pypdf extracts the text of every docket document the agent reads (decision 0047). Pull
    request #41 moved it from 6.19.0 to 6.21.4 to clear 18 security advisories, and the
    evidence text of a measured result is only what this library returned. This measures what
    the move changed, from the agent's side of the split: the docket as ``read_docket`` returns
    it, and the case as ``split_record`` screens it.

What it measures
    ``read``, once per pypdf version: for every dev-400 case, the docket through
    ``CachedDocketReader`` (as arm B and the loop read it), then every readable document
    attached and the case split, as ``scripts/docket_leak_scan.py`` does. Per document: its
    status, kind and readable pages, a SHA-256 of its text, and a SHA-256 of its text with every
    space and line break removed. Per case: the guard's outcome, the case marks, the narrative
    share and a SHA-256 of the docket text the agent would be sent. Hashes and counts only; the
    file names cases, so it is written under ``NTSB_DATA_DIR`` and never committed.
    ``compare``: two ``read`` files, as counts. A document whose text differs but whose
    no-space hash matches holds the same characters in the same order, laid out differently.

Run: ``uv run [--with pypdf==6.19.0] python -m scripts.exploratory.pypdf_text_check read``;
``uv run python -m scripts.exploratory.pypdf_text_check compare --old 6.19.0 --new 6.21.4
[--out PATH]``.
"""

import argparse
import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import httpx
import pypdf

from ntsb_probable_cause.docket.attach import attach_docket
from ntsb_probable_cause.docket.client import DocketClient
from ntsb_probable_cause.errors import DocketError, LeakageError
from ntsb_probable_cause.fields import EvidenceRole
from ntsb_probable_cause.records.split import split_record
from ntsb_probable_cause.scoring.runner import CachedDocketReader
from ntsb_probable_cause.scoring.samples import load_cases, sample_ids
from ntsb_probable_cause.settings import Settings

SAMPLE = "dev-400"
_SPACE = re.compile(r"\s+")


def _offline() -> httpx.BaseTransport:
    """A transport refusing every request, so a cache miss is loud and costs no fetch."""

    def refuse(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("offline: this measurement reads the cache only")

    return httpx.MockTransport(refuse)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def read_case(raw: Mapping[str, object]) -> dict[str, object]:
    """One case's docket and split, as hashes and counts."""
    settings = Settings()
    reader = CachedDocketReader(DocketClient(settings.docket_dir, transport=_offline()))
    row: dict[str, object] = {"case": str(raw["ntsbNumber"])}
    mkey = raw.get("mKey")
    if not isinstance(mkey, int):
        return row | {"outcome": "no docket"}
    try:
        docket = reader.read(mkey)
    except DocketError:
        return row | {"outcome": "no docket"}
    documents = {}
    for record in docket.documents:
        text = docket.texts.get(record.entry.index)
        documents[str(record.entry.index)] = {
            "status": record.status,
            "kind": record.kind,
            "readable_pages": record.readable_pages,
            "text": None if text is None else _sha(text),
            "no_space": None if text is None else _sha(_SPACE.sub("", text)),
        }
    row["documents"] = documents
    readable = [r.entry.index for r in docket.documents if r.status == "read"]
    context = attach_docket(raw, docket, documents=readable).context
    try:
        evidence, _, _ = split_record(context, exclude=frozenset())
    except LeakageError:
        return row | {"outcome": "refused"}
    sent = evidence.role_values().get(EvidenceRole.DOCKET_DOCUMENTS)
    return row | {
        "outcome": "ok",
        "marks": sorted([mark.kind, mark.count] for mark in evidence.marks),
        "share": evidence.narrative_share,
        "sent": _sha(json.dumps(sent, default=str)),
    }


def _path(settings: Settings, version: str) -> Path:
    return settings.data_dir / "pypdf-check" / f"pypdf-{version}.json"


def read(settings: Settings) -> Path:
    """Read every dev-400 case under the installed pypdf; write the private file."""
    records = load_cases(settings.data_dir / "processed", sample_ids(SAMPLE))
    with ProcessPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(read_case, records, chunksize=4))
    path = _path(settings, pypdf.__version__)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"pypdf": pypdf.__version__, "sample": SAMPLE, "rows": rows}))
    print(f"pypdf {pypdf.__version__}: {len(rows)} cases -> {path}")
    return path


def _load(path: Path) -> dict[str, dict[str, object]]:
    return {str(row["case"]): row for row in json.loads(path.read_text())["rows"]}


def _document_class(old: Mapping[str, object] | None, new: Mapping[str, object] | None) -> str:
    if old is None or new is None:
        return "listed by one version only"
    if old["text"] is None and new["text"] is None:
        return "not read by either version"
    if old["text"] is None:
        return "read only by the new version"
    if new["text"] is None:
        return "read only by the old version"
    if old["text"] == new["text"]:
        return "identical text"
    if old["no_space"] == new["no_space"]:
        return "same characters, spaces and line breaks differ"
    return "characters differ"


DOCUMENT_CLASSES = (
    "identical text",
    "same characters, spaces and line breaks differ",
    "characters differ",
    "read only by the new version",
    "read only by the old version",
    "not read by either version",
    "listed by one version only",
)


def compare(old_path: Path, new_path: Path, old_version: str, new_version: str) -> str:
    """The two reads, as counts."""
    old, new = _load(old_path), _load(new_path)
    if old.keys() != new.keys():
        raise SystemExit("the two files read different cases")
    classes: Counter[str] = Counter()
    cases_by_class: Counter[str] = Counter()
    status_or_kind = readable_pages = 0
    for case in old:
        old_docs = old[case].get("documents") or {}
        new_docs = new[case].get("documents") or {}
        assert isinstance(old_docs, dict) and isinstance(new_docs, dict)
        seen = set()
        for index in sorted(old_docs.keys() | new_docs.keys()):
            a, b = old_docs.get(index), new_docs.get(index)
            kind = _document_class(a, b)
            classes[kind] += 1
            seen.add(kind)
            if a is not None and b is not None:
                status_or_kind += (a["status"], a["kind"]) != (b["status"], b["kind"])
                readable_pages += a["readable_pages"] != b["readable_pages"]
        cases_by_class.update(seen)
    outcomes = Counter((old[c]["outcome"], new[c]["outcome"]) for c in old)
    both = [c for c in old if old[c]["outcome"] == new[c]["outcome"] == "ok"]
    marks = sum(old[c]["marks"] != new[c]["marks"] for c in both)
    shares = sum(old[c]["share"] != new[c]["share"] for c in both)
    sent = sum(old[c]["sent"] != new[c]["sent"] for c in both)
    width = max(map(len, DOCUMENT_CLASSES))
    lines = [
        f"# pypdf {old_version} against {new_version} on {SAMPLE}'s dockets -- counts only",
        "# scripts/exploratory/pypdf_text_check.py (decision 0218); exploratory (0059), free,",
        "# offline: the docket cache as CachedDocketReader reads it, then split_record",
        "",
        f"cases: {len(old)}; documents: {sum(classes.values())}",
        "",
        "## documents, by what the new version's text is",
        f"  {'class':<{width}} {'documents':>9} {'cases':>6}",
        *(
            f"  {kind:<{width}} {classes[kind]:9d} {cases_by_class[kind]:6d}"
            for kind in DOCUMENT_CLASSES
        ),
        "  (a case counts once in each class it holds a document of)",
        "  'same characters': with every space and line break removed, the texts are identical",
        "",
        "## documents, by what the classifier decides",
        f"  status or kind changed: {status_or_kind}",
        f"  readable pages changed (a page of 50 characters or more is readable): {readable_pages}",
        "",
        "## cases, through split_record with every readable document attached",
        *(f"  {a} -> {b}: {n}" for (a, b), n in sorted(outcomes.items())),
        f"  of {len(both)} cases split under both: case marks changed {marks}; "
        f"narrative share changed {shares}; docket text sent changed {sent}",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """Read under the installed pypdf, or compare two reads."""
    parser = argparse.ArgumentParser(prog="pypdf_text_check")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("read")
    comparing = sub.add_parser("compare")
    comparing.add_argument("--old", required=True)
    comparing.add_argument("--new", required=True)
    comparing.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "read":
        read(settings)
        return 0
    text = compare(_path(settings, args.old), _path(settings, args.new), args.old, args.new)
    print(text)
    if args.out:
        args.out.write_text(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
