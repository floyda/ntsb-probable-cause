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
    assert any("Smith" in f for f in found)
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
