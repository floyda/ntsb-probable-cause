"""The open-split fence for report scripts that read a run's cases (decision 0024).

Status
    Live helper, no model call, reads one line of ``run.jsonl``. A report script that opens a
    run's ``cases.jsonl`` without going through ``ntsb-eval`` calls :func:`refuse_live` first, so
    a live run (open-split cases) is refused before any case is read.
"""

import json
from pathlib import Path


def refuse_live(prog: str, folder: Path) -> None:
    """Exit unless ``folder`` is not a live run; reads only the first line of ``run.jsonl``.

    Raises:
        SystemExit: the run's first record has ``sample == "live"``.
    """
    path = folder / "run.jsonl"
    if not path.is_file():
        return
    first = path.read_text().split("\n", 1)[0]
    try:
        sample = json.loads(first).get("sample") if first else None
    except ValueError, AttributeError:
        return
    if sample == "live":
        raise SystemExit(
            f"{prog}: {folder.name} is a live run on the open split; this script does not read "
            "it (decision 0024)"
        )
