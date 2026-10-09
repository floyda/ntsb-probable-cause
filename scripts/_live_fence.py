"""The open-split fence for report scripts that read a run's cases (decision 0024).

Status
    Live helper, no model call, reads one line of ``run.jsonl`` (or ``spec.json``). A report
    script that opens a run's ``cases.jsonl`` without going through ``ntsb-eval`` calls
    :func:`refuse_live` first, so a live run (open-split cases) is refused before any case is
    read. A run killed after ``cases.jsonl`` and before ``run.jsonl`` is still caught: the check
    falls back to ``spec.json``, and a folder that has neither readable but is named for a live
    run (``-live-``) is refused too.
"""

import json
from pathlib import Path
from typing import Final

# Held equal to ``live.local.LIVE_SAMPLE`` by tests/test_live_fence.py (scripts may not import it
# without widening the import contract, and the string is the whole fence).
LIVE_SAMPLE: Final = "live"


def _sample_of(path: Path, *, first_line_only: bool) -> str | None:
    """The ``sample`` a JSON file records, or ``None`` if it is missing or unreadable."""
    try:
        text = path.read_text()
        if first_line_only:
            text = text.split("\n", 1)[0]
        loaded = json.loads(text)
    except OSError, ValueError:
        return None
    sample = loaded.get("sample") if isinstance(loaded, dict) else None
    return sample if isinstance(sample, str) else None


def refuse_live(prog: str, folder: Path) -> None:
    """Exit if ``folder`` is, or may be, a live run.

    Raises:
        SystemExit: the run's first record (or, without one, its ``spec.json``) has
            ``sample == "live"``, or neither names a sample and the folder is named for a live run.
    """
    sample = _sample_of(folder / "run.jsonl", first_line_only=True)
    if sample is None:
        sample = _sample_of(folder / "spec.json", first_line_only=False)
    if sample == LIVE_SAMPLE or (sample is None and f"-{LIVE_SAMPLE}-" in folder.name):
        raise SystemExit(
            f"{prog}: {folder.name} is a live run on the open split; this script does not read "
            "it (decision 0024)"
        )
