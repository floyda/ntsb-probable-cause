"""The coding memory's three checks and its stamp (decision 0201). Offline; made-up lessons."""

from datetime import date
from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import checks, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction


def _memory(statement: str, scope: str = "approach and landing") -> Memory:
    lesson = Lesson(
        lesson_id="L001",
        kind="convention",
        statement=statement,
        scope=scope,
        predicts=Prediction(first_occurrence=("550240",)),
        written_in=2009,
    )
    return Memory(name="t", periods=(2009,), lessons=(lesson,))


def test_digits_and_unlisted_capitals_are_identifiers() -> None:
    found = checks.identifier_findings(_memory("the pilot of N123AB lost control on 4 May"))
    assert any("digit" in f for f in found)
    found = checks.identifier_findings(
        _memory("when Smith stalls on approach, the NTSB codes loss of control")
    )
    assert any("capitalised word" in f for f in found)
    quiet = _memory("when the pilot stalls under VFR, the NTSB codes loss of control")
    assert checks.identifier_findings(quiet) == []


def test_a_shared_withheld_sentence_is_found() -> None:
    sentence = "did not maintain adequate airspeed during the approach, which resulted in a stall."
    memory = _memory(f"the pilot {sentence}")
    assert checks.withheld_findings(memory, [f"The pilot {sentence}"])


def test_eight_shared_words_are_a_copy_and_seven_are_not() -> None:
    cause = "the pilot's failure to maintain adequate airspeed during the approach"
    seven = _memory("a pilot's failure to maintain adequate airspeed during a flare")
    assert checks.copying_findings(seven, [cause]) == []
    eight = _memory("the pilot's failure to maintain adequate airspeed during the approach leads")
    assert checks.copying_findings(eight, [cause])


def test_a_snapshot_edited_after_its_stamp_is_refused(tmp_path: Path) -> None:
    memory = _memory("when the pilot stalls on approach, the NTSB codes loss of control first")
    path = snapshots.save(memory, tmp_path)
    stamp = checks.Stamp(
        snapshot="t",
        sha256=snapshots.sha256_of(path),
        withheld_texts_compared=3,
        causes_compared=2,
        checked_on=date(2026, 10, 14),
        commit="abc1234",
        dirty=False,
    )
    snapshots.stamp_path("t", tmp_path).write_text(stamp.model_dump_json(indent=1))
    assert snapshots.load_checked("t", tmp_path) == memory
    path.write_text(path.read_text().replace("first", "fist"))
    with pytest.raises(ConfigurationError):
        snapshots.load_checked("t", tmp_path)


def test_an_unstamped_snapshot_is_refused(tmp_path: Path) -> None:
    snapshots.save(
        _memory("when the pilot stalls on approach, the NTSB codes loss of control"), tmp_path
    )
    with pytest.raises(ConfigurationError):
        snapshots.load_checked("t", tmp_path)


def test_save_refuses_to_overwrite(tmp_path: Path) -> None:
    memory = _memory("when the pilot stalls on approach, the NTSB codes loss of control")
    snapshots.save(memory, tmp_path)
    with pytest.raises(ConfigurationError):
        snapshots.save(memory, tmp_path)


def test_curly_and_straight_apostrophes_match_both_ways() -> None:
    straight = "the pilot's failure to maintain adequate airspeed during the approach"
    curly = straight.replace("'", "\u2019")
    assert checks.copying_findings(_memory(straight), [curly])
    assert checks.copying_findings(_memory(curly), [straight])


def test_curly_quotes_in_a_withheld_sentence_are_found() -> None:
    sentence = 'the pilot said "go around" and did not maintain adequate airspeed on approach.'
    withheld = sentence.replace('"', "\u201c", 1).replace('"', "\u201d", 1)
    assert checks.withheld_findings(_memory(sentence), [withheld])


def test_a_possessive_of_an_allowed_word_passes_and_a_name_does_not() -> None:
    assert checks.identifier_findings(_memory("the NTSB's code is loss of control")) == []
    assert checks.identifier_findings(_memory("the NTSB\u2019s code is loss of control")) == []
    found = checks.identifier_findings(_memory("Smith's stall is coded loss of control"))
    assert any("capitalised word" in f for f in found)


def test_a_pushed_out_lesson_is_checked_too() -> None:
    memory = _memory("when the pilot stalls on approach, the NTSB codes loss of control")
    pushed = memory.lessons[0].model_copy(update={"lesson_id": "L002", "statement": "Smith stalls"})
    memory = memory.model_copy(update={"pushed_out": (pushed,)})
    assert any("L002" in f for f in checks.identifier_findings(memory))


def test_findings_name_the_lesson_and_the_kind_never_the_text() -> None:
    # Final review M3: a finding is printed and put in errors, so it quotes no lesson text.
    sentence = "did not maintain adequate airspeed during the approach, which resulted in a stall."
    memory = _memory("when Smith of N123AB stalls", scope=f"the pilot {sentence}")
    found = [
        *checks.identifier_findings(memory),
        *checks.withheld_findings(memory, [f"The pilot {sentence}"]),
        *checks.copying_findings(memory, [f"The pilot {sentence}"]),
    ]
    assert {f.partition(": ")[2] for f in found} == {
        "a digit",
        "a capitalised word not on the allowed list",
        "a sentence found in withheld text",
        "8 or more words shared with a probable-cause sentence",
    }
    assert all(f.startswith("L001: ") for f in found)
    for word in ("Smith", "N123AB", "airspeed"):
        assert word not in " ".join(found)


def test_lessons_failing_the_development_checks_are_named_with_their_checks() -> None:
    sentence = "did not maintain adequate airspeed during the approach, which resulted in a stall."
    copied = _memory(f"the pilot {sentence}")
    clean = copied.lessons[0].model_copy(update={"lesson_id": "L002", "statement": "quiet"})
    memory = copied.model_copy(update={"pushed_out": (clean,)})
    assert checks.development_failures(memory, [f"The pilot {sentence}"], [sentence]) == {
        "L001": ("copying", "withheld text")
    }
