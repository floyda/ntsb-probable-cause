"""What elicits the agent's answer, as a label: the prompt version (decisions 0133, 0143, 0161).

A run records one label, computed once at its start (``agent/run.py``, ``agent/armb.py``): the
base version, ``+g`` and a short fingerprint of the coding guidance, then the text fingerprint,
then ``+r`` and a tuning round's number when there is one. The text fingerprint is ``+t`` and
twelve hex characters of :func:`~ntsb_probable_cause.agent.rendered.rendered_sha256`: it follows
what the model is sent, so a comment, a docstring or a rename moves nothing. S3.1 and S3.2 made
their runs under ``+p`` and twelve characters of the source fingerprint (decision 0133), which
this module no longer computes; their label is kept as :data:`SOURCE_LABEL_V1`.

Version 1 is the agent as S3.2 froze it. :data:`VERSION_1` is its label under the new
fingerprint, pinned: ``tests/test_s32_frozen.py`` fails when the text the agent sends changes
without a decision. The agent text contract (``pyproject.toml``) keeps this module apart from the
modules that build text, because it imports ``rendered``, which builds an invented case record.
"""

import re
from collections.abc import Sequence
from typing import Final

from ntsb_probable_cause.agent.rendered import rendered_sha256
from ntsb_probable_cause.scoring import prompt

# What elicits the loop: the base version, then ``+g`` and a short fingerprint of the coding
# guidance, then ``+t`` and a short fingerprint of the rendered text (decision 0143), then ``+r``
# and the tuning round's number when there is one (Task 13).
AGENT_PROMPT_VERSION: Final = "s3-v1"
# What version 1's runs recorded under the source fingerprint (decision 0133): S3.1's and S3.2's
# runs carry it, and ``is_plain`` still accepts it.
SOURCE_LABEL_V1: Final = "s3-v1+ge17fecdc66ec+p947fac1c86a4"
# Version 1 under the rendered-text fingerprint, pinned in S3.3 Task 2 and re-pinned in the
# final review (2026-10-08), before any live record carried the first value, when the renderer was
# extended to cover more of what a live run sends (decision 0161, note of 2026-10-08).
# ``tests/test_agent_version.py`` ties it to ``docs/results/s33-fingerprint-continuity.txt``,
# which proves the same value on ``fd6053f`` and on the current code. A new text is a new
# version (decision 0156, item 4), never a new value here.
VERSION_1: Final = "s3-v1+ge17fecdc66ec+te7811b387b31"

# The text fingerprint's place in a prompt version: ``+p`` (source, decision 0133) or ``+t``
# (rendered text, decision 0143), and twelve hex characters.
_TEXT_PART: Final = re.compile(rf"\+[pt][0-9a-f]{{{prompt.FINGERPRINT_CHARS}}}")


def prompt_version(guidance: Sequence[str], round_number: int | None = None) -> str:
    """What elicits the agent's answer, as recorded on a run.

    The text fingerprint (``+t``, :func:`text_mark`) follows what the model is sent (decision
    0143): a kept tuning round that changes the protocol, a step text, a tool's result wording or
    a tool description changes it, so later plain runs never share a version with runs made on
    the old text. A comment, a docstring or a rename does not. Nothing is bumped by hand.

    Args:
        guidance: the coding guidance names; a short fingerprint of them is appended.
        round_number: a tuning round's number, appended as ``+r<N>``, or None.

    Returns:
        ``AGENT_PROMPT_VERSION``, then ``+g`` and the first twelve characters of the guidance
        fingerprint when there is guidance, then ``+t`` and the first twelve characters of the
        text fingerprint, then ``+r<N>`` when there is a round. E.g.
        ``s3-v1+g0123456789ab+tba9876543210+r2``.
    """
    version = AGENT_PROMPT_VERSION
    fingerprint = prompt.guidance_sha256(guidance)
    if fingerprint is not None:
        version += f"+g{fingerprint[: prompt.FINGERPRINT_CHARS]}"
    version += text_mark()
    if round_number is not None:
        version += f"+r{round_number}"
    return version


def text_mark() -> str:
    """``+t`` and the first twelve characters of the rendered-text fingerprint.

    Arm C's prompt version carries it after the guidance, and arm B's tool post-pass label after
    ``+tools-<stats>`` (``agent/armb.py``): the post-pass sends the same tools and texts.
    """
    return f"+t{rendered_sha256()[: prompt.FINGERPRINT_CHARS]}"


def is_plain(version: str, guidance: Sequence[str]) -> bool:
    """Whether ``version`` is a run's with this guidance and no tuning round, on any agent text.

    The text fingerprint is not compared, and either kind is accepted (``+p``, S3.1 and S3.2's
    runs; ``+t``, from S3.3): a run made before a kept round changed the text is still a plain
    run of its day. ``resolve_latest`` (``apps/eval``) reads arm C's plain runs so.

    Args:
        version: a run's recorded prompt version.
        guidance: the guidance a plain run reads.

    Returns:
        True when ``version`` is ``prompt_version(guidance)`` with any text fingerprint.
    """
    stem = _TEXT_PART.sub("", prompt_version(guidance))
    return re.fullmatch(f"{re.escape(stem)}{_TEXT_PART.pattern}", version) is not None
