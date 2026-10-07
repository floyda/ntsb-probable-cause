"""Tests for ``agent/version.py``: the prompt version and its rendered-text fingerprint (0143)."""

import pytest

from ntsb_probable_cause.agent import armb, run, version
from ntsb_probable_cause.agent.rendered import rendered_sha256
from ntsb_probable_cause.agent.tools import run_coding_tool
from ntsb_probable_cause.agent.version import (
    AGENT_PROMPT_VERSION,
    SOURCE_LABEL_V1,
    VERSION_1,
    is_plain,
    prompt_version,
    text_mark,
)
from ntsb_probable_cause.scoring import prompt

GUIDANCE = ("r3-loc-stall", "r6-aircraft-control")


class TestPromptVersion:
    """Decision 0143: the version fingerprints the text the agent sends (``+t``)."""

    def test_is_the_base_version_and_the_text_fingerprint_with_no_guidance(self) -> None:
        assert AGENT_PROMPT_VERSION == "s3-v1"
        assert prompt_version(()) == "s3-v1+t" + rendered_sha256()[:12]

    def test_carries_twelve_characters_of_the_guidance_then_the_text_fingerprint(self) -> None:
        sha = prompt.guidance_sha256(GUIDANCE)
        assert sha is not None
        text = rendered_sha256()
        assert prompt_version(GUIDANCE) == f"s3-v1+g{sha[:12]}+t{text[:12]}"
        assert text_mark() == f"+t{text[:12]}"

    def test_a_tuning_round_adds_its_number_last(self) -> None:
        sha = prompt.guidance_sha256(GUIDANCE)
        assert sha is not None
        text = rendered_sha256()[:12]
        assert prompt_version(GUIDANCE, 2) == f"s3-v1+g{sha[:12]}+t{text}+r2"
        assert prompt_version((), 2) == f"s3-v1+t{text}+r2"
        assert prompt_version(GUIDANCE, None) == prompt_version(GUIDANCE)

    def test_a_different_guidance_changes_the_guidance_part_only(self) -> None:
        mine, other = prompt_version(GUIDANCE), prompt_version(("r3-loc-stall",))
        assert mine != other
        assert mine.partition("+t")[2] == other.partition("+t")[2], "guidance is not in +t"

    def test_a_changed_text_changes_the_text_part_only(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        before = prompt_version(GUIDANCE)
        monkeypatch.setattr(version, "rendered_sha256", lambda: "e" * 64)
        after = prompt_version(GUIDANCE)
        assert after != before
        assert after.partition("+t")[0] == before.partition("+t")[0]
        assert after.endswith("+t" + "e" * 12)

    def test_version_1_is_pinned_and_its_source_label_is_kept(self) -> None:
        assert VERSION_1.startswith("s3-v1+ge17fecdc66ec+t")
        assert SOURCE_LABEL_V1 == "s3-v1+ge17fecdc66ec+p947fac1c86a4"
        assert VERSION_1.partition("+t")[0] == SOURCE_LABEL_V1.partition("+p")[0]


class TestIsPlain:
    def test_a_plain_version_is_the_guidance_with_no_round_on_any_agent_text(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        current = prompt_version(GUIDANCE)
        with monkeypatch.context() as patched:
            patched.setattr(version, "rendered_sha256", lambda: "e" * 64)
            earlier = prompt_version(GUIDANCE)
        assert earlier != current
        assert prompt_version(GUIDANCE) == current
        assert is_plain(current, GUIDANCE)
        assert is_plain(earlier, GUIDANCE), "the text fingerprint is not compared"
        assert not is_plain(prompt_version(GUIDANCE, 1), GUIDANCE)
        assert not is_plain(prompt_version(("r3-loc-stall",)), GUIDANCE)
        assert not is_plain(current.partition("+t")[0], GUIDANCE), "the text part is required"
        assert not is_plain(f"{current}x", GUIDANCE)
        assert is_plain(prompt_version(()), ())

    def test_runs_made_under_the_source_fingerprint_are_still_plain(self) -> None:
        """S3.1's and S3.2's runs carry ``+p`` (decision 0133); ``resolve_latest`` finds them."""
        assert is_plain(SOURCE_LABEL_V1, GUIDANCE)
        assert is_plain(VERSION_1, GUIDANCE)
        assert not is_plain(f"{SOURCE_LABEL_V1}+r1", GUIDANCE)
        assert not is_plain(SOURCE_LABEL_V1.replace("+p", "+x"), GUIDANCE)


class TestLabelDoesNotDependOnTestOrder:
    """The label hashes live module state once per process; a patched test must not freeze it."""

    def test_a_patched_scenario_global_does_not_move_the_frozen_label(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        real = run_coding_tool

        def leaky(*args: object, **kwargs: object) -> object:
            result = real(*args, **kwargs)  # type: ignore[arg-type]
            return type(result)(f"{result.text}\nleak", result.argument_errors)

        monkeypatch.setattr(armb, "run_coding_tool", leaky)
        assert version.prompt_version(run.GUIDANCE) == VERSION_1
