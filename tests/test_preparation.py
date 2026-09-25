"""A paid preparation job: reserved, spent in rows, settled (decisions 0045, 0081)."""

import json
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.transcribe import TRANSCRIBE, PageJob, TranscriptionKey
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.model.client import RecordingFakeClient, Usage
from ntsb_probable_cause.scoring.budget import month_spent, open_reservations
from ntsb_probable_cause.scoring.preparation import run_preparation
from ntsb_probable_cause.settings import Settings

NOW = datetime(2026, 10, 2, tzinfo=UTC)
DOC = build_pdf([PageSpec(text="Engine sputtered at 800 ft. Switched tanks.")] * 3)


def _jobs(model: str = "google/gemini-3.1-flash-lite") -> list[PageJob]:
    return [
        PageJob(
            TranscriptionKey(
                document_sha256="d" * 64, page=n, model=model, instruction="t1", dpi=150
            ),
            lambda: DOC,
            mixed=False,
        )
        for n in (1, 2, 3)
    ]


def _factory(_stack: ExitStack) -> RecordingFakeClient:
    return RecordingFakeClient(
        [json.dumps({"text": "words", "page_kind": "typed text"})],
        usage=[Usage(prompt_tokens=1000, completion_tokens=100)],
    )


def test_spend_is_recorded_and_the_reservation_settled(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)
    done = run_preparation(
        kind="transcription",
        jobs=_jobs(),
        instruction=TRANSCRIBE,
        settings=settings,
        commit=("abc1234", False),
        expected_cost_per_page_usd=0.01,
        workers=1,
        client_factory=lambda stack: lambda: _factory(stack),
        now=lambda: NOW,
    )
    assert len(done) == 3
    assert month_spent(settings.runs_dir, now=NOW) == pytest.approx(3 * (250 + 150) / 1e6)
    assert open_reservations(settings.runs_dir) == {}


def test_a_job_over_the_budget_is_refused_before_any_call(tmp_path: Path) -> None:
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=0.01)
    with pytest.raises(BudgetError):
        run_preparation(
            kind="transcription",
            jobs=_jobs(),
            instruction=TRANSCRIBE,
            settings=settings,
            commit=("abc1234", False),
            expected_cost_per_page_usd=0.01,
            workers=1,
            client_factory=lambda stack: lambda: _factory(stack),
            now=lambda: NOW,
        )


def test_one_job_one_model(tmp_path: Path) -> None:
    jobs = [*_jobs(), *_jobs("google/gemini-3.6-flash")]
    with pytest.raises(ConfigurationError, match="one model"):
        run_preparation(
            kind="transcription",
            jobs=jobs,
            instruction=TRANSCRIBE,
            settings=Settings(data_dir=tmp_path),
            commit=("abc1234", False),
            expected_cost_per_page_usd=0.01,
            client_factory=lambda s: lambda: _factory(s),
        )
