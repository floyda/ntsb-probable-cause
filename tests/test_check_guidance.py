import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts import check_guidance as cg

from ntsb_probable_cause.agent import schemas, steps, texts
from ntsb_probable_cause.scoring.codes import load_tables


def test_sentences_and_matches() -> None:
    text = "Short one. When a loss of control and a stall both occur, code the first. Another."
    needles = cg.sentences(text)
    assert needles == ["when a loss of control and a stall both occur, code the first."]
    haystack = "... when a loss of control and a stall both occur, code the first. ..."
    assert cg.matches(needles, [haystack]) == needles
    assert cg.matches(needles, ["nothing here"]) == []


def test_agent_texts_hold_the_protocol_the_tool_definitions_and_every_fixed_string() -> None:
    """S3.1 final review: the agent's model-facing texts go through S2.7's sentence check."""
    parts = cg.agent_texts()
    joined = "\n".join(parts)
    for constant in (
        texts.PROTOCOL,
        texts.CHOOSE,
        texts.CHOOSE_AGAIN,
        texts.RECORD_NOW,
        texts.CODE_NOW,
        texts.ANSWER_NOW,
        texts.NO_DOCUMENTS,
        texts.NONE_READABLE,
        texts.ALL_READ,
        texts.ONE_CALL,
        texts.PRIOR_HEADING,
        texts.PRIOR_HYPOTHESIS,
    ):
        assert constant in parts
    for tool in schemas.TOOL_DEFINITIONS:
        function = tool["function"]
        assert isinstance(function, dict)
        assert function["description"] in parts
    # The templates' fixed words, rendered with numbers and placeholder words.
    assert "Not readable: [2] 2 pages" in joined
    assert "[1] 1 page, 1 with a text layer, about 10 tokens" in joined
    assert "That call was not accepted: an error" in joined
    assert "Documents you read: none." in joined
    # Decision 0134's three lines for a decision on a document not on offer, rendered.
    rendered = [s for part in parts for s in cg.sentences(part)]
    for line in (
        "Document [1] cannot be read; skipped.",
        "Document [2] was already read; skipped.",
        "There is no document [3]; skipped.",
    ):
        assert cg.normalise(line) in rendered, line
    assert steps.wrong_tool(("describe_codes", "submit_answer"), "another") in parts
    needles = [s for part in parts for s in cg.sentences(part)]
    assert cg.normalise(
        "Check the occurrence (which event defines the accident, and its phase)"
    ) in (" ".join(needles))


def test_agent_texts_hold_the_coding_tools_fixed_result_sentences() -> None:
    """Decision 0133 names the tools' result wording as text a round may change, so the check
    covers it: each tool is run on a small placeholder pool, so its fixed words come out and
    no code label or count of the real tables or statistics does."""
    parts = cg.agent_texts()
    needles = [s for part in parts for s in cg.sentences(part)]
    for sentence in (
        "Fewer than 20 past cases with this defining event; the counts are unreliable.",
        "no findings recorded for this event.",
        "These are counts, not evidence about this accident.",
        "No past Takeoff accidents in the pool.",
        "describe_codes: no codes given.",
        "occurrence_usage: no codes given.",
    ):
        assert cg.normalise(sentence) in needles, sentence
    joined = "\n".join(parts)
    assert "no pool cases present" in joined
    assert "... and 1 more" in joined  # a finding category's item list is cut at 20
    tables = load_tables()
    for label in (*tables.phases.values(), *tables.events.values(), *tables.items.values()):
        if len(label) >= 15:
            assert label not in joined, f"a real code label reached the check: {label}"


def _processed(data_dir: Path, rows: list[tuple[str, dict[str, object]]]) -> None:
    folder = data_dir / "processed"
    folder.mkdir(parents=True)
    table = pa.table(
        {
            "split": [split for split, _ in rows],
            "raw_json": [json.dumps(raw) for _, raw in rows],
        }
    )
    pq.write_table(table, folder / "cases.parquet")


def _raw(probable_cause: str) -> dict[str, object]:
    return {
        "narratives": [
            {
                "concatenatedFactualNarrative": "The pilot reported a hard landing.",
                "analysisNarrative": "The pilot did not flare.",
                "probableCause": probable_cause,
            }
        ]
    }


def test_main_with_agent_texts_finds_a_protocol_sentence_in_a_development_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    sentence = "Keep a less usual code when this case's evidence supports it."
    assert sentence in texts.PROTOCOL
    _processed(
        tmp_path,
        [
            ("dev", _raw(f"Something. {sentence} More.")),
            ("heldout", _raw(texts.PROTOCOL)),  # held-out cases are not read
        ],
    )
    assert cg.main(["--agent-texts"]) == 1
    out = capsys.readouterr().out
    assert "agent text sentences checked against 1 development cases; 1 found" in out
    assert f"- found: {cg.normalise(sentence)}" in out


def test_main_with_agent_texts_passes_on_clean_cases_and_keeps_s27s_line(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("NTSB_DATA_DIR", str(tmp_path))
    _processed(tmp_path, [("dev", _raw("The pilot's failure to flare."))])
    assert cg.main(["--agent-texts"]) == 0
    assert "agent text sentences checked against 1 development cases; 0 found" in (
        capsys.readouterr().out
    )
    assert cg.main(["r3-loc-stall"]) == 0
    line = capsys.readouterr().out.splitlines()[0]
    assert line.endswith(" guidance sentences checked against 1 development cases; 0 found")
    assert cg.main(["r3-loc-stall", "--agent-texts"]) == 0
    assert "guidance and agent text sentences checked" in capsys.readouterr().out


def test_main_needs_a_guidance_file_or_agent_texts(capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stopped:
        cg.main([])
    assert stopped.value.code == 2
    assert "--agent-texts" in capsys.readouterr().err
