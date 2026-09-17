"""The code tables the model chooses from, and composition of its choices (decision 0025)."""

import csv
from collections.abc import Mapping
from dataclasses import dataclass
from functools import cache
from importlib import resources
from typing import Literal

from ntsb_probable_cause.errors import SchemaError

TableName = Literal["phases", "events", "categories", "items", "modifiers"]


@dataclass(frozen=True)
class CodeTables:
    """Five code → label maps, from the NTSB data dictionary."""

    phases: Mapping[str, str]
    events: Mapping[str, str]
    categories: Mapping[str, str]
    items: Mapping[str, str]
    modifiers: Mapping[str, str]

    def items_under(self, category6: str) -> Mapping[str, str]:
        """The eight-digit items whose first six digits are the category."""
        return {k: v for k, v in self.items.items() if k.startswith(category6)}

    def compose_occurrence(self, phase: str, event: str) -> str:
        """Join a phase prefix and an event suffix; both must be in the tables."""
        if phase not in self.phases:
            raise SchemaError(f"unknown phase prefix {phase!r}")
        if event not in self.events:
            raise SchemaError(f"unknown event suffix {event!r}")
        return f"{phase}{event}"

    def compose_finding(self, item8: str, modifier: str) -> str:
        """Join an eight-digit item and a two-digit modifier; both must be in the tables."""
        if item8 not in self.items:
            raise SchemaError(f"unknown finding item {item8!r}")
        if modifier not in self.modifiers:
            raise SchemaError(f"unknown modifier {modifier!r}")
        return f"{item8}{modifier}"

    def render(self, which: TableName) -> str:
        """One line per code, ``code  label``, sorted by code; what the prompt shows."""
        table: Mapping[str, str] = getattr(self, which)
        return "\n".join(f"{code}  {label}" for code, label in sorted(table.items()))


def _read(name: TableName) -> dict[str, str]:
    text = resources.files("ntsb_probable_cause.scoring").joinpath(f"tables/{name}.csv").read_text()
    return {row["code"]: row["label"] for row in csv.DictReader(text.splitlines())}


@cache
def load_tables() -> CodeTables:
    """Load the committed tables once."""
    return CodeTables(
        phases=_read("phases"),
        events=_read("events"),
        categories=_read("categories"),
        items=_read("items"),
        modifiers=_read("modifiers"),
    )
