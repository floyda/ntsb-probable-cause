"""Coding-memory snapshots on disk, and the refusal of any that is unchecked (decision 0201)."""

import hashlib
from pathlib import Path
from typing import Final

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import checks
from ntsb_probable_cause.memory.lessons import Memory

SNAPSHOT_DIR: Final = Path(__file__).parent / "snapshots"


def snapshot_path(name: str, directory: Path = SNAPSHOT_DIR) -> Path:
    """Where snapshot ``name`` lives."""
    return directory / f"{name}.json"


def stamp_path(name: str, directory: Path = SNAPSHOT_DIR) -> Path:
    """Where snapshot ``name``'s stamp lives."""
    return directory / f"{name}.stamp.json"


def sha256_of(path: Path) -> str:
    """The file's bytes, hashed."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def save(memory: Memory, directory: Path = SNAPSHOT_DIR) -> Path:
    """Write a new snapshot; never overwrite one.

    Raises:
        ConfigurationError: a snapshot of that name exists.
    """
    path = snapshot_path(memory.name, directory)
    if path.exists():
        raise ConfigurationError(f"snapshot {memory.name} exists; snapshots are never rewritten")
    path.write_text(memory.model_dump_json(indent=1) + "\n")
    return path


def load(name: str, directory: Path = SNAPSHOT_DIR) -> Memory:
    """Read a snapshot without checking it (the local check and the learner's draft only)."""
    return Memory.model_validate_json(snapshot_path(name, directory).read_text())


def load_checked(name: str, directory: Path = SNAPSHOT_DIR) -> Memory:
    """Read a snapshot only if its stamp matches it and it names no one.

    Raises:
        ConfigurationError: the stamp is missing, names another file or hash, or the identifier
            check finds anything.
    """
    stamp_file = stamp_path(name, directory)
    if not stamp_file.exists():
        raise ConfigurationError(
            f"snapshot {name} has no stamp: run make mem-check SNAPSHOT={name}"
        )
    stamp = checks.Stamp.model_validate_json(stamp_file.read_text())
    digest = sha256_of(snapshot_path(name, directory))
    if stamp.snapshot != name or stamp.sha256 != digest:
        raise ConfigurationError(f"snapshot {name} changed after its check; check it again")
    memory = load(name, directory)
    if found := checks.identifier_findings(memory):
        raise ConfigurationError(f"snapshot {name} fails the identifier check: {found}")
    return memory


def names(directory: Path = SNAPSHOT_DIR) -> list[str]:
    """Every snapshot in ``directory``, by name."""
    return sorted(
        p.name.removesuffix(".json")
        for p in directory.glob("*.json")
        if not p.name.endswith(".stamp.json")
    )
