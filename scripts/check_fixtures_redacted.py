"""Pre-commit hook: fail if a fixture JSON contains a redacted owner/operator field (0015)."""

import json
import sys
from pathlib import Path

from ntsb_probable_cause.data.redaction import find_redacted_fields


def main(paths: list[str]) -> int:
    """Check the given files, or every fixture JSON when none are given."""
    files = [Path(p) for p in paths] or sorted(Path("tests/fixtures").rglob("*.json"))
    failed = False
    for path in files:
        for found in find_redacted_fields(json.loads(path.read_text())):
            print(f"{path}: {found}")
            failed = True
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
