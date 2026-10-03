"""Allow-list import test (spec §7.4): who MAY import synthesis/verdict, not who is forbidden.

A forbidden list (the import-linter contracts in pyproject.toml) silently misses new modules
added later; this test instead names the modules allowed to import synthesis or verdict and
fails if any other library module does.

S3.1 Task 10 adds two contracts for the agent package, and the tests below hold them: the
agent's tools, schemas and texts reach no case record by any chain (the ``ToolText`` they build
is case-free), with ``agent.documents`` as the positive control that the check can fail; and
the "nothing imports the agent" contract names every top-level library module, so a package
added later cannot slip past it.
"""

import tomllib
from pathlib import Path

import grimp
import pytest

_ROOT = "ntsb_probable_cause"
_PYPROJECT = Path(__file__).resolve().parent.parent / "pyproject.toml"


def _contract(name: str) -> dict[str, object]:
    contracts = tomllib.loads(_PYPROJECT.read_text())["tool"]["importlinter"]["contracts"]
    (found,) = [c for c in contracts if c["name"] == name]
    assert isinstance(found, dict)
    return found


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


def _chains(module: str, package: str) -> set[tuple[str, ...]]:
    """Every shortest chain from one agent module into any module of a library package.

    ``as_packages=True``: the singular ``find_shortest_chain`` looks for the package's
    ``__init__`` only and finds nothing even where a chain exists (the plan's Task 7 Deviations).
    """
    graph = grimp.build_graph(_ROOT)
    return graph.find_shortest_chains(
        importer=f"{_ROOT}.agent.{module}", imported=f"{_ROOT}.{package}", as_packages=True
    )


# The modules that build model-facing tool text: the coding tools, the tool definitions, the
# fixed texts, the step table (menus, refusals, step texts) and the document facts they read.
_TOOL_TEXT_MODULES = ("tools", "schemas", "texts", "steps", "facts")


@pytest.mark.parametrize("module", _TOOL_TEXT_MODULES)
@pytest.mark.parametrize("package", ["records", "docket", "data"])
def test_the_agents_tools_schemas_and_texts_reach_no_case_record(module: str, package: str) -> None:
    """The contract "The agent's tools and texts see no case record", chain by chain."""
    assert _chains(module, package) == set()


@pytest.mark.parametrize("package", ["records", "docket", "data"])
def test_the_chain_check_can_fail_documents_reaches_each_package(package: str) -> None:
    """The positive control: ``agent.documents`` builds payloads, so it reaches all three."""
    assert _chains("documents", package)


def test_the_agent_contract_names_the_tool_text_modules() -> None:
    contract = _contract("The agent's tools and texts see no case record")
    assert contract["type"] == "forbidden"
    assert set(contract["source_modules"]) == {  # type: ignore[call-overload]
        f"{_ROOT}.agent.{module}" for module in _TOOL_TEXT_MODULES
    }
    assert set(contract["forbidden_modules"]) == {  # type: ignore[call-overload]
        f"{_ROOT}.records",
        f"{_ROOT}.docket",
        f"{_ROOT}.data",
    }
    assert "ignore_imports" not in contract
    assert "allow_indirect_imports" not in contract


def test_nothing_in_the_library_imports_the_agent() -> None:
    """The contract's sources are every top-level library module but the agent itself.

    A forbidden list misses what it does not name, so the list is held to the package's own
    children: a top-level module added later fails here until the contract names it.
    """
    contract = _contract("Nothing in the library imports the agent")
    graph = grimp.build_graph(_ROOT)
    children = set(graph.find_children(_ROOT)) - {f"{_ROOT}.agent"}
    assert set(contract["source_modules"]) == children  # type: ignore[call-overload]
    assert contract["forbidden_modules"] == [f"{_ROOT}.agent"]
    outside = {
        importer
        for module in graph.find_descendants(f"{_ROOT}.agent") | {f"{_ROOT}.agent"}
        for importer in graph.find_modules_that_directly_import(module)
        if not importer.startswith(f"{_ROOT}.agent")
    }
    assert outside == set()
