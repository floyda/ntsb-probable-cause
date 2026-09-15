"""Allow-list import test (spec §7.4): who MAY import synthesis/verdict, not who is forbidden.

A forbidden list (the import-linter contracts in pyproject.toml) silently misses new modules
added later; this test instead names the modules allowed to import synthesis or verdict and
fails if any other library module does.
"""

import grimp

# Decision 0025: the scoring modules that grade against the verdict, and the judge that also
# reads synthesis. Everything else in scoring stays outside.
ALLOWED_TO_IMPORT_SYNTHESIS_OR_VERDICT = frozenset(
    {
        "ntsb_probable_cause.records.split",
        "ntsb_probable_cause.scoring.metrics",
        "ntsb_probable_cause.scoring.runner",
        "ntsb_probable_cause.scoring.judge",
        "ntsb_probable_cause.scoring.report",
    }
)


def test_only_the_splitter_imports_synthesis_or_verdict() -> None:
    graph = grimp.build_graph("ntsb_probable_cause")
    importers: set[str] = set()
    for withheld in (
        "ntsb_probable_cause.records.synthesis",
        "ntsb_probable_cause.records.verdict",
    ):
        importers |= graph.find_modules_that_directly_import(withheld) - {withheld}
    assert importers <= ALLOWED_TO_IMPORT_SYNTHESIS_OR_VERDICT, (
        f"modules importing synthesis/verdict outside the allow-list: "
        f"{sorted(importers - ALLOWED_TO_IMPORT_SYNTHESIS_OR_VERDICT)}"
    )


def test_synthesis_is_imported_only_by_split_and_judge() -> None:
    graph = grimp.build_graph("ntsb_probable_cause")
    importers = graph.find_modules_that_directly_import("ntsb_probable_cause.records.synthesis") - {
        "ntsb_probable_cause.records.synthesis"
    }
    allowed = frozenset({"ntsb_probable_cause.records.split", "ntsb_probable_cause.scoring.judge"})
    assert importers <= allowed, (
        f"modules importing records.synthesis outside split/judge: {sorted(importers - allowed)}"
    )
