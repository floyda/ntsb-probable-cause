"""Every committed guidance file is named r<N>-<slug>, has a registration, and names no case."""

import re
from pathlib import Path

from ntsb_probable_cause.scoring import prompt

_CASE_NUMBER = re.compile(r"\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}[A-Z]?\b")
GUIDANCE = Path("src/ntsb_probable_cause/scoring/guidance")


def test_guidance_files_are_well_named_registered_and_name_no_case() -> None:
    for path in sorted(GUIDANCE.glob("*.md")):
        prompt.guidance_round(path.stem)
        assert prompt.registration_path(path.stem).is_file(), path
        assert not _CASE_NUMBER.search(path.read_text()), path
