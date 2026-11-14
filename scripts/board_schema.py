"""Write the committed JSON Schema of the ``board/1`` export.

Status
    Live tooling (S4 Task 3). Free. Writes ``docs/schemas/board-1.schema.json`` from
    ``live.export``.

Usage:
    uv run --locked python -m scripts.board_schema [--out PATH]
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence
from pathlib import Path

from ntsb_probable_cause.live.export import board_json_schema

DEFAULT_OUT = Path("docs/schemas/board-1.schema.json")


def main(argv: Sequence[str] | None = None) -> int:
    """Write the schema file.

    Args:
        argv: Command-line arguments; defaults to ``sys.argv``.

    Returns:
        0.
    """
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(board_json_schema(), indent=2, sort_keys=True) + "\n")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
