"""Resolve dotted JSON paths against nested case records."""

import re
from collections.abc import Mapping

_SEGMENT = re.compile(r"^([A-Za-z0-9_]+)(?:\[(\d+)\])?$")
_INDEX = re.compile(r"\[\d+\]")


def resolve_path(record: Mapping[str, object], path: str) -> object | None:
    """Return the value at ``path`` (segments ``name`` or ``name[N]``); None if a hop is missing."""
    current: object = record
    for segment in path.split("."):
        match = _SEGMENT.match(segment)
        if match is None or not isinstance(current, Mapping) or match.group(1) not in current:
            return None
        current = current[match.group(1)]
        if match.group(2) is not None:
            index = int(match.group(2))
            if not isinstance(current, list) or index >= len(current):
                return None
            current = current[index]
    return current


def normalise_path(path: str) -> str:
    """Replace every concrete index with ``[]`` so paths compare by shape."""
    return _INDEX.sub("[]", path)


def is_under(path: str, subtree: str) -> bool:
    """Return True if ``path`` equals ``subtree`` or lies beneath it, comparing whole segments."""
    parts = normalise_path(path).split(".")
    prefix = normalise_path(subtree).split(".")
    return parts[: len(prefix)] == prefix
