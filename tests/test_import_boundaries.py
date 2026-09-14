"""Allow-list import test (spec §7.4): who MAY import synthesis/verdict, not who is forbidden.

A forbidden list (the import-linter contracts in pyproject.toml) silently misses new modules
added later; this test instead names the modules allowed to import synthesis or verdict and
fails if any other library module does.
"""

import grimp

# S1's `scoring` module will be added to this allow-list by decision, when it needs verdict for
# grading a model's answer against the NTSB's published cause.
ALLOWED_TO_IMPORT_SYNTHESIS_OR_VERDICT = frozenset({"ntsb_probable_cause.records.split"})


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
