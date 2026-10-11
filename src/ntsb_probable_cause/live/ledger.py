"""The ledger of manifest hashes (S4 specification section 11, decision 0178).

Each day a continuous-integration job lists the live bucket's run and night manifests and
appends one line per new or rewritten manifest to ``ledger.jsonl``. A line holds the manifest's
key, its SHA-256 and size, and, for a night, the manifest's flat counts; never a file's contents.
:func:`verify` checks a local copy of the bucket against that ledger and reports problems by
key and kind only.
"""

import hashlib
import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final, Literal

from pydantic import BaseModel

from ntsb_probable_cause.live.records import MANIFEST_FILE, verify_manifest

LEDGER_FORMAT: Final = "ledger/1"
_NIGHT_RECORD: Final = "night.json"


class LedgerLine(BaseModel, frozen=True):
    """One manifest's hash at one moment.

    Attributes:
        format: The line format.
        appended_at: When the job appended the line.
        key: ``runs/<run id>/manifest.json`` or ``nights/<date>/manifest.json``.
        sha256: SHA-256 of the manifest's bytes.
        size: The manifest's size in bytes.
        counts: A night manifest's counts; None for a run manifest.
    """

    format: Literal["ledger/1"] = LEDGER_FORMAT
    appended_at: datetime
    key: str
    sha256: str
    size: int
    counts: dict[str, int] | None


def _counts(key: str, body: bytes) -> dict[str, int] | None:
    """A night manifest's integer counts; None for a run manifest or an unreadable one."""
    if not key.startswith("nights/"):
        return None
    try:
        counts = json.loads(body).get("counts")
    except ValueError, AttributeError:
        return None
    if not isinstance(counts, dict):
        return None
    return {str(k): v for k, v in counts.items() if isinstance(v, int) and not isinstance(v, bool)}


def _latest(ledger: Sequence[LedgerLine]) -> dict[str, LedgerLine]:
    return {line.key: line for line in ledger}  # later lines win


def new_lines(
    ledger: Sequence[LedgerLine], manifests: Mapping[str, bytes], now: datetime
) -> list[LedgerLine]:
    """One line per manifest not in the ledger or whose hash differs from its latest line.

    A rewritten manifest is appended, never hidden: the earlier line stays.

    Args:
        ledger: The lines so far, oldest first.
        manifests: Manifest bytes by bucket key.
        now: The time the new lines carry.

    Returns:
        The new lines, sorted by key.
    """
    latest = _latest(ledger)
    lines: list[LedgerLine] = []
    for key in sorted(manifests):
        body = manifests[key]
        digest = hashlib.sha256(body).hexdigest()
        known = latest.get(key)
        if known is not None and known.sha256 == digest:
            continue
        lines.append(
            LedgerLine(
                appended_at=now, key=key, sha256=digest, size=len(body), counts=_counts(key, body)
            )
        )
    return lines


def render_line(line: LedgerLine) -> str:
    """The line as one JSON text line, newline included."""
    return line.model_dump_json() + "\n"


def read_ledger(path: Path) -> list[LedgerLine]:
    """The ledger file's lines; an absent file is an empty ledger."""
    if not path.is_file():
        return []
    return [LedgerLine.model_validate_json(t) for t in path.read_text().splitlines() if t.strip()]


def _check_listed(folder: Path, mirror: Path, label: str) -> list[str]:
    """A night manifest's ``night_files`` (bucket paths) against the mirror."""
    manifest = json.loads((folder / MANIFEST_FILE).read_text())
    problems: list[str] = []
    for entry in manifest.get("night_files", []):
        path = mirror / entry["path"]
        if not path.is_file():
            problems.append(f"{label}: {entry['path']}: missing")
        elif (
            path.stat().st_size != entry["size"]
            or hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]
        ):
            problems.append(f"{label}: {entry['path']}: changed")
    return problems


def _check_folder(key: str, mirror: Path) -> list[str]:
    folder = (mirror / key).parent
    label = folder.relative_to(mirror).as_posix()
    if key.startswith("nights/") and not (folder / _NIGHT_RECORD).is_file():
        return [f"{label}: unfinished night"]
    try:
        problems = [f"{label}: {p}" for p in verify_manifest(folder)]
        if key.startswith("nights/"):
            problems += _check_listed(folder, mirror, label)
    except ValueError, KeyError, TypeError:
        return [f"{label}: manifest unreadable"]
    return problems


def verify(ledger: Sequence[LedgerLine], mirror: Path) -> list[str]:
    """Problems between the ledger and a local copy of the bucket; ``[]`` when sound.

    For each key's latest line: the manifest is present, its SHA-256 is the line's, and the
    folder it lists matches it (``records.verify_manifest``). A night folder with no
    ``night.json`` is an unfinished night, not a mismatch. Problems name keys and kinds, never
    contents.
    """
    problems: list[str] = []
    for key, line in sorted(_latest(ledger).items()):
        path = mirror / key
        if not path.is_file():
            problems.append(f"{key}: manifest is missing")
        elif hashlib.sha256(path.read_bytes()).hexdigest() != line.sha256:
            problems.append(f"{key}: manifest differs from the ledger")
        else:
            problems += _check_folder(key, mirror)
    return problems
