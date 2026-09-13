"""Resolve dotted JSON paths against nested case records."""

import re
from collections.abc import Mapping

_SEGMENT = re.compile(r"^([A-Za-z0-9_]+)(?:\[(\d+)\])?$")
_INDEX = re.compile(r"\[\d+\]")
_BRACKET_SUFFIX = re.compile(r"\[\d*\]$")
_SEGMENT_GRAMMAR = re.compile(r"^[A-Za-z0-9_]+(\[\d*\])?$")


def resolve_path(record: Mapping[str, object], path: str) -> object | None:
    """Return the value at ``path`` (``name`` or ``name[N]`` segments); None if a hop is missing."""
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


def is_well_formed(path: str) -> bool:
    """Return True if every dot-separated segment matches ``name``, ``name[N]`` or ``name[]``."""
    return all(_SEGMENT_GRAMMAR.match(segment) is not None for segment in path.split("."))


def _bare_parts(path: str) -> list[str]:
    """Segment names of ``path`` with any trailing ``[...]`` stripped (brackets ignored)."""
    return [_BRACKET_SUFFIX.sub("", segment) for segment in path.split(".")]


def is_under(path: str, subtree: str) -> bool:
    """Return True if ``path`` equals ``subtree`` or lies beneath it, ignoring brackets."""
    parts = _bare_parts(path)
    prefix = _bare_parts(subtree)
    return parts[: len(prefix)] == prefix


def overlaps(path: str, subtree: str) -> bool:
    """Return True if ``path`` lies under ``subtree`` or ``subtree`` lies under ``path``.

    A source that reads a parent of a withheld subtree reads the subtree too, so both
    directions of the ancestor relationship count as overlap (spec S7.3, guard layer 2).
    """
    return is_under(path, subtree) or is_under(subtree, path)
