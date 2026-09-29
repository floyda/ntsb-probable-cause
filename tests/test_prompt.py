"""``scoring/prompt.py``: coding guidance files, the prompt version, and registration paths
(S2.7, decision 0098, plan W5)."""

from pathlib import Path

import pytest

from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.scoring import prompt


@pytest.fixture
def guidance_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    (tmp_path / "r2-loc-stall.md").write_text("When a stall and a loss of control both occur...\n")
    (tmp_path / "r3-phase.md").write_text("Low-altitude maneuvering uses phase 452.\n")
    monkeypatch.setattr(prompt, "GUIDANCE_DIR", tmp_path)
    return tmp_path


def test_prompt_version_carries_a_short_fingerprint_of_the_stack(guidance_dir: Path) -> None:
    assert prompt.prompt_version(()) == prompt.PROMPT_VERSION
    stack = ("r2-loc-stall", "r3-phase")
    fingerprint = prompt.guidance_sha256(stack)
    assert fingerprint is not None
    assert prompt.prompt_version(stack) == f"{prompt.PROMPT_VERSION}+g{fingerprint[:12]}"
    assert prompt.prompt_version(stack) != prompt.prompt_version(tuple(reversed(stack)))
    (guidance_dir / "r3-phase.md").write_text("Edited text.\n")
    assert prompt.prompt_version(stack) != f"{prompt.PROMPT_VERSION}+g{fingerprint[:12]}"


def test_guidance_text_and_hash(guidance_dir: Path) -> None:
    text = prompt.guidance_text(("r2-loc-stall", "r3-phase"))
    assert text.index("stall") < text.index("452")
    assert prompt.guidance_sha256(()) is None
    assert prompt.guidance_sha256(("r2-loc-stall",)) != prompt.guidance_sha256(("r3-phase",))


def test_a_badly_named_or_missing_file_is_refused(guidance_dir: Path) -> None:
    with pytest.raises(ConfigurationError, match="r<N>-"):
        prompt.guidance_round("loc-stall")
    with pytest.raises(ConfigurationError, match="no guidance file"):
        prompt.guidance_text(("r9-missing",))


def test_registration_path() -> None:
    assert prompt.registration_path("r2-loc-stall") == Path("docs/rounds/s27-round-2.md")
