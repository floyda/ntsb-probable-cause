"""Every committed snapshot passes the identifier check and has a matching stamp (decision 0201).

Runs in continuous integration, which has no case data: the withheld-text and copying checks
run locally (``make mem-check``) and their result is the stamp.
"""

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq
import pytest
from scripts import memory_check

from ntsb_probable_cause.memory import checks, snapshots
from ntsb_probable_cause.memory.lessons import Lesson, Memory, Prediction


@pytest.mark.parametrize("name", snapshots.names())
def test_every_committed_snapshot_is_stamped_and_names_no_one(name: str) -> None:
    memory = snapshots.load_checked(name)
    assert checks.identifier_findings(memory) == []


CAUSE = "the pilot's failure to maintain adequate airspeed during the approach"


def _memory(statement: str) -> Memory:
    lesson = Lesson(
        lesson_id="L001",
        kind="convention",
        statement=statement,
        scope="approach and landing",
        predicts=Prediction(first_occurrence=("550240",)),
        written_in=2009,
    )
    return Memory(name="t", periods=(2009,), lessons=(lesson,))


def _setup(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """A three-row processed file, one row held out, and an empty snapshot directory."""

    def raw(factual: str, analysis: str, cause: str) -> str:
        narrative = {
            "concatenatedFactualNarrative": factual,
            "analysisNarrative": analysis,
            "probableCause": cause,
        }
        return json.dumps({"narratives": [narrative]})

    table = pa.table(
        {
            "split": ["dev", "dev", "heldout"],
            "raw_json": [
                raw("Factual one.", "Analysis one.", CAUSE),
                raw("Factual two.", "", "a second cause"),
                raw("Held out factual.", "Held out analysis.", "held out words stay out"),
            ],
        }
    )
    processed = tmp_path / "cases.parquet"
    pq.write_table(table, processed)
    monkeypatch.setattr(memory_check, "processed_path", lambda: processed)
    monkeypatch.setattr(snapshots, "SNAPSHOT_DIR", tmp_path / "snaps")
    (tmp_path / "snaps").mkdir()
    return tmp_path / "snaps"


def test_main_stamps_a_clean_memory(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    directory = _setup(tmp_path, monkeypatch)
    clean = _memory("when the pilot stalls on approach, the NTSB codes loss of control")
    snapshots.save(clean, directory)
    assert memory_check.main(["--snapshot", "t"]) == 0
    stamp = checks.Stamp.model_validate_json(snapshots.stamp_path("t", directory).read_text())
    assert stamp.withheld_texts_compared == 5
    assert stamp.causes_compared == 2
    assert snapshots.load_checked("t", directory).name == "t"


def test_main_writes_no_stamp_for_a_copying_memory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = _setup(tmp_path, monkeypatch)
    snapshots.save(
        _memory("the pilot's failure to maintain adequate airspeed during the approach leads"),
        directory,
    )
    assert memory_check.main(["--snapshot", "t"]) == 1
    assert not snapshots.stamp_path("t", directory).exists()
