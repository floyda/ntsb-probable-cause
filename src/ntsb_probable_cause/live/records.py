"""The closure record and the run folder's integrity checks (S3.3 spec section 8.2).

A run folder is built to move: relative paths only, no secrets, and a manifest of every file's
size and SHA-256 so a copy can be verified.
"""

import hashlib
import json
import re
from collections.abc import Iterator
from datetime import date, datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

from ntsb_probable_cause.docket.manifest import Status

CLOSURE_FORMAT: Final = "live-closure/1"
BACKFILL_FORMAT: Final = "live-backfill/1"
MANIFEST_FORMAT: Final = "live-manifest/1"
CLOSURES_FILE: Final = "closures.jsonl"
BACKFILL_FILE: Final = "backfill.json"
INPUTS_FILE: Final = "inputs.jsonl"
MANIFEST_FILE: Final = "manifest.json"

CONTEXT_FAILURE: Final = "cap: context"
# The kinds a not-coded case's failure text can start with (the heads the runners write): the
# morning's summary and the report both say a failure by one of these or "other", never by the
# text, which can quote a case (decision 0024).
FAILURE_KINDS: Final = frozenset(
    {"schema", "model", "leak", "cap", "failed", "aborted", "missing result"}
)
_SECRET_VALUE = re.compile(r"sk-or-|AKIA[0-9A-Z]{16}")
_SECRET_KEYS: Final = frozenset({"aws_profile", "api_key"})


def failure_kind(failure: str | None) -> str:
    """A failure's kind, from a closed set; anything else is "other" (decision 0024).

    The kinds are the heads the runners write: ``schema``, ``model``, ``leak``, ``cap``,
    ``cap: context``, ``failed`` (the loop failed at a step), ``aborted``, and ``missing result``.
    """
    text = (failure or "").strip()
    if text.startswith(CONTEXT_FAILURE):
        return CONTEXT_FAILURE
    head = re.split(r"[:;(]", text, maxsplit=1)[0].strip()
    return head if head in FAILURE_KINDS else "other"


class DocumentLine(BaseModel, frozen=True):
    """One document of a case: its place, title and fate. Never its text."""

    position: int
    title: str
    status: Status  # the docket reader's five
    ellery: Literal["read", "skipped"] | None  # None when not on offer


class ClosureRecord(BaseModel, frozen=True):
    """What one coded closed case leaves behind (counts and provenance, no document text)."""

    format: Literal["live-closure/1"] = CLOSURE_FORMAT
    case_id: str
    mkey: int
    closed_on: date
    closure_run: int
    waited_days: int
    first_sent: datetime | None
    last_returned: datetime | None
    commit_sha: str
    dirty: bool
    prompt_version: str
    price_variant: Literal["batch", "standard"]
    model: str
    reasoning_effort: str | None
    training_cutoff: date
    training_cutoff_source: str
    uv_lock_sha256: str
    documents: tuple[DocumentLine, ...]
    prelim_present: bool
    outcome: Literal["coded", "not coded"]
    failure: str | None
    marks: tuple[str, ...]
    scored: bool  # False when the record held no verdict
    top1: bool | None
    top3: bool | None
    abstained: bool | None
    cost_usd: float


class Backfill(BaseModel, frozen=True):
    """The set of cases that closed before the queue began, fixed on one day."""

    format: Literal["live-backfill/1"] = BACKFILL_FORMAT
    fixed_on: date
    case_ids: tuple[str, ...]
    sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _listing(folder: Path) -> dict[str, Path]:
    """Every file under ``folder`` but the manifest, keyed by sorted relative POSIX path."""
    found = {
        path.relative_to(folder).as_posix(): path for path in folder.rglob("*") if path.is_file()
    }
    found.pop(MANIFEST_FILE, None)
    return dict(sorted(found.items()))


def write_manifest(folder: Path) -> None:
    """Write ``manifest.json``: each file's relative path, size and SHA-256, sorted."""
    files = [
        {"path": rel, "size": path.stat().st_size, "sha256": _sha256(path)}
        for rel, path in _listing(folder).items()
    ]
    manifest = {"format": MANIFEST_FORMAT, "files": files}
    (folder / MANIFEST_FILE).write_text(json.dumps(manifest, indent=2) + "\n")


def verify_manifest(folder: Path) -> list[str]:
    """Return what differs between the folder and its manifest; ``[]`` when sound."""
    manifest_path = folder / MANIFEST_FILE
    if not manifest_path.is_file():
        return [f"{MANIFEST_FILE} is missing"]
    listed = {entry["path"]: entry for entry in json.loads(manifest_path.read_text())["files"]}
    present = _listing(folder)
    problems: list[str] = []
    for rel in sorted(listed):
        path = present.get(rel)
        if path is None:
            problems.append(f"{rel}: missing")
        elif path.stat().st_size != listed[rel]["size"] or _sha256(path) != listed[rel]["sha256"]:
            problems.append(f"{rel}: changed")
    problems.extend(f"{rel}: extra, not in the manifest" for rel in present if rel not in listed)
    return problems


def _walk(value: object, key: str | None = None) -> Iterator[str]:
    """Yield a problem kind for each offending key or string under ``value``."""
    if isinstance(value, dict):
        for name, inner in value.items():
            if name in _SECRET_KEYS:
                yield f"key {name}"
            yield from _walk(inner, name)
    elif isinstance(value, list):
        for inner in value:
            yield from _walk(inner, key)
    elif isinstance(value, str):
        if _SECRET_VALUE.search(value):
            yield "secret-like value"
        elif Path(value).is_absolute():
            yield "absolute path"


def portability_problems(folder: Path) -> list[str]:
    """Report absolute paths and secrets in the folder's JSON, never the value itself."""
    problems: list[str] = []
    for path in sorted(folder.rglob("*")):
        if not path.is_file() or path.suffix not in {".json", ".jsonl"}:
            continue
        rel = path.relative_to(folder).as_posix()
        lines = path.read_text().splitlines() if path.suffix == ".jsonl" else [path.read_text()]
        for number, line in enumerate(lines, start=1):
            if path.suffix == ".jsonl" and not line.strip():
                continue
            where = f"{rel}:{number}" if path.suffix == ".jsonl" else rel
            try:
                parsed = json.loads(line)
            except json.JSONDecodeError:
                problems.append(f"{where}: not valid JSON")
                continue
            problems.extend(f"{where}: {kind}" for kind in _walk(parsed))
    return problems
