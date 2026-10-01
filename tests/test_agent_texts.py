"""Tests for ``agent/texts.py`` and ``agent/facts.py``: the agent's fixed texts (S3.1 Task 7).

The texts are plain strings and never hold case text: the system text and the protocol are the
same for every case of a run (the provider's prompt cache depends on it), and the menu holds
numbers keyed by listing index, never a title.
"""

import copy
import hashlib
import importlib
import json
import os
import subprocess
import sys
from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import Any

import grimp
import pytest

from ntsb_probable_cause.agent import schemas, texts
from ntsb_probable_cause.agent.facts import DocumentFacts
from ntsb_probable_cause.agent.schemas import TOOL_DEFINITIONS
from ntsb_probable_cause.agent.texts import (
    AGENT_PROMPT_VERSION,
    ANSWER_NOW,
    CHOOSE,
    CHOOSE_AGAIN,
    CODE_NOW,
    NO_DOCUMENTS,
    NONE_READABLE,
    ONE_CALL,
    PROTOCOL,
    RECORD_NOW,
    TEXT_SOURCES,
    agent_text_sha256,
    is_plain,
    menu,
    not_accepted,
    prompt_version,
    read_summary,
    source_text,
    system_text,
    text_mark,
)
from ntsb_probable_cause.agent.tools import describe_codes, occurrence_usage
from ntsb_probable_cause.scoring import hypothesis, prompt
from ntsb_probable_cause.scoring.codes import load_tables
from ntsb_probable_cause.scoring.coding_stats import load_stats
from ntsb_probable_cause.scoring.hypothesis import REFINEMENT_SCHEMA

TABLES = load_tables()
GUIDANCE = ("r3-loc-stall", "r6-aircraft-control")
# The titles of the small docket the document tests use (tests/test_attach.py's ``_docket``).
TITLES = (
    "Powerplant Examination Report",
    "Party Submission - engine manufacturer",
    "Pilot Operator Report 6120",
)


def _facts(index: int, **changes: Any) -> DocumentFacts:
    """A readable born-digital document's facts, with any field changed."""
    fields: dict[str, Any] = {
        "index": index,
        "pages": 3,
        "readable_pages": 3,
        "estimated_tokens": 700,
        "kind": "born-digital",
        "status": "read",
    }
    return DocumentFacts(**(fields | changes))


def _flat(text: str) -> str:
    """``text`` with every run of whitespace, line breaks included, as one space."""
    return " ".join(text.split())


class TestDocumentFacts:
    def test_is_a_frozen_record_of_six_plain_fields(self) -> None:
        facts = _facts(4, pages=11, readable_pages=4, estimated_tokens=1200, kind=None)
        assert (facts.index, facts.pages, facts.readable_pages) == (4, 11, 4)
        assert (facts.estimated_tokens, facts.kind, facts.status) == (1200, None, "read")
        with pytest.raises(FrozenInstanceError):
            facts.pages = 2  # type: ignore[misc]


class TestSystemText:
    def test_starts_with_arm_bs_system_text_and_ends_with_the_protocol(self) -> None:
        text = system_text(TABLES, GUIDANCE)
        arm_b = (
            f"{prompt.SYSTEM_ANSWER}\n\n{prompt.tables_block(TABLES)}"
            f"{prompt.guidance_block(GUIDANCE)}"
        )
        assert text.startswith(arm_b.rstrip())
        assert text.endswith(PROTOCOL)
        assert text.index(prompt.GUIDANCE_HEADING) < text.index(PROTOCOL)

    def test_without_guidance_there_is_no_guidance_heading(self) -> None:
        text = system_text(TABLES, ())
        assert prompt.GUIDANCE_HEADING not in text
        assert text.endswith(PROTOCOL)

    def test_is_identical_for_two_different_cases(
        self, record_fixtures: list[dict[str, object]]
    ) -> None:
        """No record reaches the function: the same call gives the same bytes for any case."""
        first, second = record_fixtures[0], record_fixtures[1]
        assert first["ntsbNumber"] != second["ntsbNumber"]
        text_for_first = system_text(TABLES, GUIDANCE)
        text_for_second = system_text(TABLES, GUIDANCE)
        assert text_for_first == text_for_second
        assert text_for_first.encode() == text_for_second.encode()
        for raw in (first, second):
            assert str(raw["ntsbNumber"]) not in text_for_first

    def test_holds_no_case_number_section(self) -> None:
        """``tables_block`` is called without its ``case_number`` keyword."""
        assert "## Case number" not in system_text(TABLES, GUIDANCE)


class TestProtocol:
    def test_holds_the_steps_the_agent_works_through(self) -> None:
        for phrase in (
            "You work through one case in steps, using tools.",
            "First record your hypothesis from the evidence given.",
            "decide for each whether to read it and what you expect it to show",
            "reading costs time and money, so read what your hypothesis needs",
            "Record your hypothesis again after reading.",
            "give for each call why you make it and what you expect",
            "they are not evidence about this one",
            "Keep a less usual code when this case's evidence supports it.",
            "before the findings",
            "Submit your answer when your coding is settled.",
            "Make one tool call at a time.",
        ):
            assert phrase in _flat(PROTOCOL)

    def test_says_the_limits_of_the_coding_tools(self) -> None:
        flat = _flat(PROTOCOL)
        assert "describe_codes takes up to six codes in one call" in flat
        assert "occurrence_usage takes up to three" in flat
        assert "as they appear in the code tables" in flat

    def test_states_the_limits_the_tools_enforce(self) -> None:
        """The sentence is held to the tools: six codes are accepted, a seventh is an error."""
        phase = next(iter(TABLES.phases))
        codes = [f"{phase}{event}" for event in list(TABLES.events)[:7]]
        stats = load_stats("s3")
        assert describe_codes(TABLES, "occurrence", codes[:6]).argument_errors == 0
        assert describe_codes(TABLES, "occurrence", codes[:7]).argument_errors == 1
        assert occurrence_usage(TABLES, stats, codes[:3]).argument_errors == 0
        assert occurrence_usage(TABLES, stats, codes[:4]).argument_errors == 1

    def test_is_in_the_second_person_and_plain_ascii(self) -> None:
        assert PROTOCOL.startswith("## ")
        assert " you " in f" {PROTOCOL.lower()} "
        assert PROTOCOL.isascii()


class TestPromptVersion:
    """Andy, 2026-10-01: the version fingerprints the model-facing text (``+p``)."""

    def test_is_the_base_version_and_the_text_fingerprint_with_no_guidance(self) -> None:
        assert AGENT_PROMPT_VERSION == "s3-v1"
        assert prompt_version(()) == "s3-v1+p" + agent_text_sha256()[:12]

    def test_carries_twelve_characters_of_the_guidance_then_the_text_fingerprint(self) -> None:
        sha = prompt.guidance_sha256(GUIDANCE)
        assert sha is not None
        text = agent_text_sha256()
        assert prompt_version(GUIDANCE) == f"s3-v1+g{sha[:12]}+p{text[:12]}"

    def test_a_tuning_round_adds_its_number_last(self) -> None:
        sha = prompt.guidance_sha256(GUIDANCE)
        assert sha is not None
        text = agent_text_sha256()[:12]
        assert prompt_version(GUIDANCE, 2) == f"s3-v1+g{sha[:12]}+p{text}+r2"
        assert prompt_version((), 2) == f"s3-v1+p{text}+r2"
        assert prompt_version(GUIDANCE, None) == prompt_version(GUIDANCE)

    def test_a_different_guidance_changes_the_guidance_part_only(self) -> None:
        mine, other = prompt_version(GUIDANCE), prompt_version(("r3-loc-stall",))
        assert mine != other
        assert mine.partition("+p")[2] == other.partition("+p")[2], "guidance is not in +p"

    @pytest.mark.parametrize("name", ["texts.py", "tools.py", "prompt.py"])
    def test_an_edited_text_module_changes_the_text_part_only(
        self, monkeypatch: pytest.MonkeyPatch, name: str
    ) -> None:
        """A kept tuning round that edits the protocol or a tool's wording shows in later plain
        runs' version (decision 0133)."""
        before = prompt_version(GUIDANCE)
        _edit_source(monkeypatch, name)
        after = prompt_version(GUIDANCE)
        assert after != before
        assert after.partition("+p")[0] == before.partition("+p")[0]

    def test_a_plain_version_is_the_guidance_with_no_round_on_any_agent_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = prompt_version(GUIDANCE)
        with monkeypatch.context() as patched:
            _edit_source(patched, "texts.py")
            earlier = prompt_version(GUIDANCE)
        assert earlier != current
        assert prompt_version(GUIDANCE) == current
        assert is_plain(current, GUIDANCE)
        assert is_plain(earlier, GUIDANCE), "the text fingerprint is not compared"
        assert not is_plain(prompt_version(GUIDANCE, 1), GUIDANCE)
        assert not is_plain(prompt_version(("r3-loc-stall",)), GUIDANCE)
        assert not is_plain(current.partition("+p")[0], GUIDANCE), "the text part is required"
        assert not is_plain(f"{current}x", GUIDANCE)
        assert is_plain(prompt_version(()), ())


def _edit_source(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """Make the fingerprint read one covered file with a comment line added to it."""
    original = texts.source_text

    def edited(package: str, file: str) -> str:
        return original(package, file) + ("# an edit\n" if file == name else "")

    monkeypatch.setattr(texts, "source_text", edited)


_EXPECTED_SOURCES = (
    ("ntsb_probable_cause.scoring", "prompt.py"),
    ("ntsb_probable_cause.scoring", "hypothesis.py"),
    ("ntsb_probable_cause.scoring", "codes.py"),
    ("ntsb_probable_cause.agent", "texts.py"),
    ("ntsb_probable_cause.agent", "steps.py"),
    ("ntsb_probable_cause.agent", "tools.py"),
    ("ntsb_probable_cause.agent", "schemas.py"),
    ("ntsb_probable_cause.agent", "later.py"),
    ("ntsb_probable_cause.agent", "loop.py"),
    ("ntsb_probable_cause.agent", "armb.py"),
)


class TestAgentTextFingerprint:
    """``agent_text_sha256``: the source of the modules that hold or compose the agent's text.

    Decision 0133: any edit to a covered file changes the version, a comment included; a false
    change only separates runs, it never merges two different prompts.
    """

    def test_covers_the_modules_that_hold_or_compose_the_text_in_a_fixed_order(self) -> None:
        assert TEXT_SOURCES == _EXPECTED_SOURCES

    def test_reads_each_module_as_its_file(self) -> None:
        for package, name in TEXT_SOURCES:
            module = importlib.import_module(f"{package}.{name.removesuffix('.py')}")
            assert module.__file__ is not None
            assert source_text(package, name) == Path(module.__file__).read_text(encoding="utf-8")

    def test_is_the_sha256_of_the_sources_and_the_schemas_as_sent(self) -> None:
        parts = [[f"{p}/{n}", source_text(p, n)] for p, n in TEXT_SOURCES]
        parts.append(["TOOL_DEFINITIONS", json.dumps(TOOL_DEFINITIONS, sort_keys=True)])
        parts.append(["REFINEMENT_SCHEMA", json.dumps(REFINEMENT_SCHEMA, sort_keys=True)])
        digest = agent_text_sha256()
        assert digest == hashlib.sha256(json.dumps(parts).encode()).hexdigest()
        assert len(digest) == 64
        assert text_mark() == f"+p{digest[:12]}"

    @pytest.mark.parametrize(
        ("package", "name"), _EXPECTED_SOURCES, ids=[n for _, n in _EXPECTED_SOURCES]
    )
    def test_an_edit_to_any_covered_file_changes_it_even_a_comment(
        self, tmp_path: Path, package: str, name: str
    ) -> None:
        """Hashed over a copy of the files, with one of them edited by a comment line."""
        for p, n in TEXT_SOURCES:
            copy_of = tmp_path / p / n
            copy_of.parent.mkdir(parents=True, exist_ok=True)
            copy_of.write_text(source_text(p, n), encoding="utf-8")

        def read(p: str, n: str) -> str:
            return (tmp_path / p / n).read_text(encoding="utf-8")

        before = agent_text_sha256(read)
        assert before == agent_text_sha256(), "the copy hashes as the package does"
        edited = tmp_path / package / name
        edited.write_text(f"{edited.read_text(encoding='utf-8')}# an edit\n", encoding="utf-8")
        assert agent_text_sha256(read) != before

    def test_a_file_is_read_once_per_process_so_a_later_edit_is_not_seen(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A covered file edited while a run is in flight must not change what any other caller
        in the process reads (decision 0133): the first reading is the text that was imported."""
        package = tmp_path / "read_once_probe"
        package.mkdir()
        module = package / "a.py"
        module.write_text("one\n", encoding="utf-8")
        monkeypatch.setattr("importlib.resources.files", lambda name: tmp_path / str(name))
        assert source_text("read_once_probe", "a.py") == "one\n"
        module.write_text("two\n", encoding="utf-8")
        assert source_text("read_once_probe", "a.py") == "one\n"
        source_text.cache_clear()  # what a fresh interpreter starts with
        assert source_text("read_once_probe", "a.py") == "two\n"
        source_text.cache_clear()

    def test_the_tool_definitions_as_sent_are_in_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        before = agent_text_sha256()
        changed = copy.deepcopy(TOOL_DEFINITIONS)
        function = changed[0]["function"]
        assert isinstance(function, dict)
        function["description"] = f"{function['description']} (changed)"
        monkeypatch.setattr(schemas, "TOOL_DEFINITIONS", changed)
        assert agent_text_sha256() != before

    def test_the_refinement_schema_as_sent_is_in_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        before = agent_text_sha256()
        monkeypatch.setattr(hypothesis, "REFINEMENT_SCHEMA", {"changed": True})
        assert agent_text_sha256() != before

    def test_no_data_or_guidance_file_is_in_it(self) -> None:
        """Tables and statistics are data (the commit SHA); guidance has its own ``+g``."""
        assert all(name.endswith(".py") for _, name in TEXT_SOURCES)
        assert prompt.guidance_text(GUIDANCE) not in json.dumps(
            [source_text(*s) for s in TEXT_SOURCES]
        )

    def test_is_stable_across_two_fresh_interpreters(self) -> None:
        code = (
            "from ntsb_probable_cause.agent.texts import agent_text_sha256\n"
            "print(agent_text_sha256())"
        )
        seen: set[str] = set()
        for seed in ("0", "1"):
            env = {**os.environ, "PYTHONHASHSEED": seed}
            done = subprocess.run(  # noqa: S603 -- the interpreter running these tests, fixed code
                [sys.executable, "-c", code], capture_output=True, text=True, check=True, env=env
            )
            seen.add(done.stdout.strip())
        assert seen == {agent_text_sha256()}


class TestMenu:
    def test_lists_an_offered_document_in_the_fixed_format(self) -> None:
        text = menu([_facts(3, pages=6, readable_pages=5, estimated_tokens=2100)], [])
        assert text == "[3] 6 pages, 5 with a text layer, about 2100 tokens"

    def test_lists_offered_documents_in_the_order_given_one_per_line(self) -> None:
        offered = [_facts(4, estimated_tokens=100), _facts(2, estimated_tokens=900)]
        lines = menu(offered, []).splitlines()
        assert lines == [
            "[4] 3 pages, 3 with a text layer, about 100 tokens",
            "[2] 3 pages, 3 with a text layer, about 900 tokens",
        ]

    def test_lists_not_readable_documents_by_index_and_pages(self) -> None:
        scan = _facts(5, pages=14, readable_pages=0, kind="scan", status="unreadable: scan")
        text = menu([_facts(1)], [scan])
        assert text.splitlines()[-1] == "Not readable: [5] 14 pages"

    def test_each_not_readable_document_has_its_own_line_in_the_fixed_format(self) -> None:
        first = _facts(2, pages=1, readable_pages=0, kind="scan", status="unreadable: scan")
        second = _facts(6, pages=9, readable_pages=0, kind=None, status="skipped: photo-only")
        assert menu([], [first, second]).splitlines() == [
            "Not readable: [2] 1 page",
            "Not readable: [6] 9 pages",
        ]

    @pytest.mark.parametrize(
        "status",
        ["unreadable: scan", "fetch failed", "unreadable: not a pdf", "skipped: photo-only"],
    )
    def test_the_not_readable_line_names_no_cause_for_any_status(self, status: str) -> None:
        """The cause is not measured for every status (a fetch that failed, a file that is not a
        PDF), so the line says only that the document cannot be read."""
        document = _facts(4, pages=2, readable_pages=0, kind=None, status=status)
        assert menu([], [document]) == "Not readable: [4] 2 pages"

    def test_one_page_is_one_page_as_the_attached_documents_header_says(self) -> None:
        """``docket/attach.py`` writes ``1 page`` for a one-page document; so does the menu."""
        one = _facts(3, pages=1, readable_pages=1, estimated_tokens=40)
        assert menu([one], []) == "[3] 1 page, 1 with a text layer, about 40 tokens"
        two = _facts(3, pages=2, readable_pages=1, estimated_tokens=40)
        assert menu([two], []) == "[3] 2 pages, 1 with a text layer, about 40 tokens"

    def test_names_what_was_already_read_by_index(self) -> None:
        text = menu([_facts(3)], [], already_read=[1, 2])
        assert "Already read: [1], [2]" in text
        assert "Already read" not in menu([_facts(3)], [])

    def test_holds_the_three_parts_in_order(self) -> None:
        scan = _facts(5, pages=14, readable_pages=0, kind="scan", status="unreadable: scan")
        lines = menu([_facts(3)], [scan], already_read=[1]).splitlines()
        assert lines[0].startswith("[3] ")
        assert lines[1].startswith("Already read")
        assert lines[2].startswith("Not readable")

    def test_nothing_offered_and_nothing_unreadable_is_empty(self) -> None:
        assert menu([], []) == ""

    def test_holds_no_title_and_no_status_or_kind_word(self) -> None:
        scan = _facts(3, pages=2, readable_pages=0, kind="scan", status="unreadable: scan")
        text = menu([_facts(1), _facts(2)], [scan], already_read=[2])
        for title in TITLES:
            assert title not in text
        for word in ("Report", "Submission", "born-digital", "scan", "unreadable"):
            assert word not in text


class TestReadSummary:
    def test_lists_listing_indices_only(self) -> None:
        assert read_summary([1, 3], [2]) == "You read: [1], [3]. You skipped: [2]."

    def test_says_none_for_an_empty_side(self) -> None:
        assert read_summary([], [2, 4]) == "You read: none. You skipped: [2], [4]."
        assert read_summary([2], []) == "You read: [2]. You skipped: none."
        assert read_summary([], []) == "You read: none. You skipped: none."


class TestFixedStrings:
    def test_are_as_the_plan_gives_them(self) -> None:
        assert CHOOSE == "Choose read or skip for every document listed above."
        assert CHOOSE_AGAIN == "You may read more. Choose read or skip for every document listed."
        assert RECORD_NOW == "Record your hypothesis now."
        assert CODE_NOW == "Check your coding with the coding tools, then submit your answer."
        assert NO_DOCUMENTS == "No docket documents are available for this case."
        assert ONE_CALL == "Only one tool call is run per turn; this call was not run."

    def test_none_readable_is_andys_text_and_names_no_cause(self) -> None:
        """Andy, 2026-10-01: the text that follows an unreadable docket's listing."""
        assert NONE_READABLE == "None of the documents listed can be read."
        assert "scan" not in NONE_READABLE
        assert "text layer" not in NONE_READABLE

    def test_the_coding_ablation_names_no_coding_tool(self) -> None:
        """Task 8: the ``without={"coding"}`` run sends no coding tools, so its text names none."""
        assert ANSWER_NOW == "Submit your answer now."
        assert "coding" not in ANSWER_NOW

    def test_not_accepted_names_the_error(self) -> None:
        assert (
            not_accepted("document 9 is not on offer")
            == "That call was not accepted: document 9 is not on offer"
        )

    def test_every_text_is_a_plain_str(self) -> None:
        for value in (
            PROTOCOL,
            CHOOSE,
            CHOOSE_AGAIN,
            RECORD_NOW,
            CODE_NOW,
            ANSWER_NOW,
            NO_DOCUMENTS,
            NONE_READABLE,
            ONE_CALL,
            system_text(TABLES, GUIDANCE),
            menu([_facts(1)], []),
            read_summary([1], []),
            not_accepted("x"),
            prompt_version(GUIDANCE),
        ):
            assert type(value) is str


def _chains(module: str, package: str) -> set[tuple[str, ...]]:
    """Every shortest import chain from an agent module into any module of ``package``."""
    graph = grimp.build_graph("ntsb_probable_cause")
    return graph.find_shortest_chains(
        importer=f"ntsb_probable_cause.agent.{module}",
        imported=f"ntsb_probable_cause.{package}",
        as_packages=True,
    )


@pytest.mark.parametrize("module", ["texts", "facts"])
@pytest.mark.parametrize("package", ["records", "docket", "data"])
def test_no_import_chain_from_texts_or_facts_to_records_docket_or_data(
    module: str, package: str
) -> None:
    """Indirect chains count too: Task 10's contract forbids them, so the texts keep clear."""
    assert _chains(module, package) == set()


@pytest.mark.parametrize("package", ["records", "docket", "data"])
def test_the_chain_check_can_fail_documents_does_reach_each_package(package: str) -> None:
    """The positive control: ``agent.documents`` imports all three, and the check sees it."""
    assert _chains("documents", package)
