"""S2.7 track 2, Task 4: the page-value counts and the page-rule choice."""

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scripts import page_value
from scripts.page_value import PageRow, choose_rule, rows_for_document, tally
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.transcribe import (
    TRANSCRIBE,
    TRANSCRIBER,
    ReadingLookup,
    Transcription,
    TranscriptionCache,
    TranscriptionKey,
    key_instruction,
    pages_to_read,
)

TYPED = "Engine sputtered at 800 ft. Switched tanks, no change."


def _row(kind: str, layer: int, chars: int, *, cost: float = 0.001) -> PageRow:
    return PageRow(
        fatal=True,
        kind=kind,  # type: ignore[arg-type]
        layer_chars=layer,
        image_share=0.9,
        status="transcribed",
        chars=chars,
        cost_usd=cost,
    )


def test_tally_counts_only_the_pages_a_rule_sends() -> None:
    rows = [
        _row("image only", 0, 1000),
        _row("text and image", 60, 300),
        _row("text and image", 900, 5),
    ]
    assert tally(rows, "all").pages == 3
    assert tally(rows, "all").chars == 1305
    assert tally(rows, "image-only").pages == 1
    assert tally(rows, "image-only+thin-layer").chars == 1300


def test_choose_rule_takes_image_only_when_it_keeps_nine_tenths() -> None:
    rows = [_row("image only", 0, 950), _row("text and image", 900, 50)]
    rule, _notes = choose_rule(rows)
    assert rule == "image-only"


def test_choose_rule_takes_the_thin_layer_rule_when_image_only_falls_short() -> None:
    rows = [
        _row("image only", 0, 800),
        _row("text and image", 60, 150),
        _row("text and image", 900, 50),
    ]
    rule, _notes = choose_rule(rows)
    assert rule == "image-only+thin-layer"


def test_choose_rule_keeps_all_when_no_narrower_rule_keeps_enough() -> None:
    rows = [_row("image only", 0, 500), _row("text and image", 900, 500)]
    rule, _notes = choose_rule(rows)
    assert rule == "all"


def test_rows_for_document_joins_facts_and_readings(tmp_path: Path) -> None:
    document = build_pdf(
        [
            PageSpec(images=("/CCITTFaxDecode",)),
            PageSpec(text=TYPED, images=("/DCTDecode",)),
            PageSpec(text=TYPED),
        ]
    )
    cache = TranscriptionCache(tmp_path)
    sha = hashlib.sha256(document).hexdigest()
    for page, mixed in pages_to_read(document, page_rule="all"):
        cache.put(
            Transcription(
                key=TranscriptionKey(
                    document_sha256=sha,
                    page=page,
                    model=TRANSCRIBER,
                    instruction=key_instruction(TRANSCRIBE, mixed=mixed),
                    dpi=150,
                ),
                status="transcribed",
                text="x" * (40 if page == 1 else 3),
                mixed=mixed,
                cost_usd=0.002,
                created=datetime(2026, 9, 27, tzinfo=UTC),
            ),
            instruction=TRANSCRIBE,
        )

    rows = rows_for_document(document, ReadingLookup(cache).for_document(document), fatal=False)
    assert [(r.kind, r.chars) for r in rows] == [("image only", 40), ("text and image", 3)]
    assert rows[1].layer_chars >= len(TYPED) - 1
    assert all(r.cost_usd == pytest.approx(0.002) for r in rows)


def test_main_refuses_a_sample_that_is_not_dev_400() -> None:
    with pytest.raises(SystemExit, match="dev-400 only"):
        page_value.main(["--sample", "heldout-400"])
