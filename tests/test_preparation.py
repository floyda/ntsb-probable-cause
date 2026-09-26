"""A paid preparation job: reserved, spent in rows, settled (decisions 0045, 0081)."""

import json
from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from pathlib import Path

import pytest
from tests.pdf_builder import PageSpec, build_pdf

from ntsb_probable_cause.docket.transcribe import (
    TRANSCRIBE,
    PageJob,
    TranscriptionCache,
    TranscriptionKey,
)
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.model.client import (
    ModelReply,
    ModelSettings,
    Payload,
    RecordingFakeClient,
    Turn,
    Usage,
)
from ntsb_probable_cause.scoring.budget import month_spent, open_reservations
from ntsb_probable_cause.scoring.preparation import PreparationStoppedError, run_preparation
from ntsb_probable_cause.settings import Settings

NOW = datetime(2026, 10, 2, tzinfo=UTC)
DOC = build_pdf([PageSpec(text="Engine sputtered at 800 ft. Switched tanks.")] * 3)
DOC6 = build_pdf([PageSpec(text="Engine sputtered at 800 ft. Switched tanks.")] * 6)


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
    calls = 0

    def factory(_stack: ExitStack) -> Callable[[], RecordingFakeClient]:
        def make() -> RecordingFakeClient:
            nonlocal calls
            calls += 1
            return _factory(_stack)

        return make

    with pytest.raises(BudgetError):
        run_preparation(
            kind="transcription",
            jobs=_jobs(),
            instruction=TRANSCRIBE,
            settings=settings,
            commit=("abc1234", False),
            expected_cost_per_page_usd=0.01,
            workers=1,
            client_factory=factory,
            now=lambda: NOW,
        )
    # Fix round 1, M10: the refusal happens before any model client is even built.
    assert calls == 0
    assert open_reservations(settings.runs_dir) == {}


def test_a_missing_key_leaves_no_reservation_and_makes_no_call(tmp_path: Path) -> None:
    """Fix round 1, I2: the default factory's ConfigurationError must not leak a reservation."""
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0, openrouter_api_key=None)
    with pytest.raises(ConfigurationError, match="OPENROUTER_API_KEY"):
        run_preparation(
            kind="transcription",
            jobs=_jobs(),
            instruction=TRANSCRIBE,
            settings=settings,
            commit=("abc1234", False),
            expected_cost_per_page_usd=0.01,
            workers=1,
            now=lambda: NOW,
        )
    assert open_reservations(settings.runs_dir) == {}
    assert month_spent(settings.runs_dir, now=NOW) == 0.0


class _BoomClient:
    """Answers correctly for ``fail_after`` calls, then raises ``exc`` (M10)."""

    def __init__(
        self, fail_after: int, exc: BaseException, *, calls: list[int] | None = None
    ) -> None:
        self._calls = calls if calls is not None else []
        self._inner = RecordingFakeClient(
            [json.dumps({"text": "words", "page_kind": "typed text"})],
            usage=[Usage(prompt_tokens=1000, completion_tokens=100)],
        )
        self._fail_after = fail_after
        self._exc = exc
        self._n = 0

    def complete(
        self,
        payload: Payload,
        settings: ModelSettings,
        *,
        system: str = "",
        history: Sequence[Turn] = (),
    ) -> ModelReply:
        self._n += 1
        self._calls.append(1)
        if self._n > self._fail_after:
            raise self._exc
        return self._inner.complete(payload, settings, system=system, history=history)


def test_settle_on_an_unexpected_exception_mid_run(tmp_path: Path) -> None:
    """Fix round 1, M10: the reservation is settled even when a call raises part-way through."""
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)
    client = _BoomClient(1, RuntimeError("boom"))
    done = run_preparation(
        kind="transcription",
        jobs=_jobs(),
        instruction=TRANSCRIBE,
        settings=settings,
        commit=("abc1234", False),
        expected_cost_per_page_usd=0.01,
        workers=1,
        client_factory=lambda stack: lambda: client,
        now=lambda: NOW,
    )
    assert len(done) == 3
    assert open_reservations(settings.runs_dir) == {}


def test_settle_on_a_keyboard_interrupt(tmp_path: Path) -> None:
    """Fix round 1, M10: an interruption still settles the reservation."""
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)
    client = _BoomClient(1, KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        run_preparation(
            kind="transcription",
            jobs=_jobs(),
            instruction=TRANSCRIBE,
            settings=settings,
            commit=("abc1234", False),
            expected_cost_per_page_usd=0.01,
            workers=1,
            client_factory=lambda stack: lambda: client,
            now=lambda: NOW,
        )
    assert open_reservations(settings.runs_dir) == {}


def test_a_second_job_with_the_same_id_is_refused(tmp_path: Path) -> None:
    """Fix round 3, M9: two jobs of the same kind claim one folder atomically, so the second
    one refuses rather than mixing its reservation and spend rows into the first's."""
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
    with pytest.raises(ConfigurationError, match="already exists"):
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
    # The first job's own reservation is unaffected by the second's refusal.
    assert open_reservations(settings.runs_dir) == {}


def test_two_models_in_the_same_second_do_not_collide(tmp_path: Path) -> None:
    """Fix round 1, I1: a command that runs one job per model, one after another, must not
    have its second job refused as a duplicate of the first just because both started in the
    same clock second (every page already cached makes the first job return in milliseconds).
    """
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)
    for model in ("google/gemini-3.1-flash-lite", "openai/gpt-6-luna"):
        done = run_preparation(
            kind="transcriber-test",
            jobs=_jobs(model),
            instruction=TRANSCRIBE,
            settings=settings,
            commit=("abc1234", False),
            expected_cost_per_page_usd=0.01,
            workers=1,
            client_factory=lambda stack: lambda: _factory(stack),
            now=lambda: NOW,
        )
        assert len(done) == 3
    assert open_reservations(settings.runs_dir) == {}


def test_a_second_job_with_the_same_model_still_collides(tmp_path: Path) -> None:
    """Fix round 1, I1: the model slug narrows the collision, it does not remove it."""
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)
    run_preparation(
        kind="transcriber-test",
        jobs=_jobs(),
        instruction=TRANSCRIBE,
        settings=settings,
        commit=("abc1234", False),
        expected_cost_per_page_usd=0.01,
        workers=1,
        client_factory=lambda stack: lambda: _factory(stack),
        now=lambda: NOW,
    )
    with pytest.raises(ConfigurationError, match="already exists"):
        run_preparation(
            kind="transcriber-test",
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


# --- S2.6 final review, I1: the spend is bounded in code ---


def _many_jobs(n: int) -> list[PageJob]:
    """``n`` distinct pages of one document of six pages (each page its own key)."""
    return [
        PageJob(
            TranscriptionKey(
                document_sha256="e" * 64,
                page=page,
                model="google/gemini-3.1-flash-lite",
                instruction="t1",
                dpi=150,
            ),
            lambda: DOC6,
            mixed=False,
        )
        for page in range(1, n + 1)
    ]


@pytest.mark.parametrize("expected", [0.0, -0.01, float("nan")])
def test_an_expected_cost_of_zero_or_less_is_refused_before_anything(
    tmp_path: Path, expected: float
) -> None:
    """A $0 estimate would reserve nothing and so bound nothing."""
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)

    def factory(_stack: ExitStack) -> Callable[[], RecordingFakeClient]:
        raise AssertionError("no client is built for a refused job")

    with pytest.raises(ConfigurationError, match="above zero"):
        run_preparation(
            kind="transcription",
            jobs=_jobs(),
            instruction=TRANSCRIBE,
            settings=settings,
            commit=("abc1234", False),
            expected_cost_per_page_usd=expected,
            client_factory=factory,
            now=lambda: NOW,
        )
    assert not settings.runs_dir.exists() or not any(settings.runs_dir.iterdir())


def test_a_job_stops_once_its_reservation_is_spent_and_reports_every_paid_page(
    tmp_path: Path,
) -> None:
    """Each page really costs $0.0004; the job expected $0.0001 a page, so it reserved $0.0006
    for six pages and must stop after the second page, not read all six."""
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)
    calls: list[int] = []

    def factory(_stack: ExitStack) -> Callable[[], _BoomClient]:
        def make() -> _BoomClient:
            return _BoomClient(10**6, RuntimeError("never"), calls=calls)

        return make

    jobs = _many_jobs(6)
    with pytest.raises(PreparationStoppedError) as stopped:
        run_preparation(
            kind="transcription",
            jobs=jobs,
            instruction=TRANSCRIBE,
            settings=settings,
            commit=("abc1234", False),
            expected_cost_per_page_usd=0.0001,
            workers=1,
            client_factory=factory,
            now=lambda: NOW,
        )
    error = stopped.value
    assert isinstance(error, BudgetError)  # `ntsb-eval` exits non-zero on a BudgetError
    read = error.read
    # Two pages reach the reservation; at most one more was already in flight.
    assert 2 <= len(read) <= 3
    assert error.unread == 6 - len(read)
    assert f"{error.unread} were left unread" in str(error)
    # Every paid page is recorded exactly once, and nothing more was paid for.
    assert len(calls) == len(read)
    assert month_spent(settings.runs_dir, now=NOW) == pytest.approx(sum(r.cost_usd for r in read))
    assert open_reservations(settings.runs_dir) == {}
    # The pages never started stay unread, so a later job reads them.
    cache = TranscriptionCache(settings.transcription_dir)
    assert sum(1 for job in jobs if cache.get(job.key) is None) == error.unread

    later = datetime(2026, 10, 2, 0, 0, 1, tzinfo=UTC)
    done = run_preparation(
        kind="transcription",
        jobs=jobs,
        instruction=TRANSCRIBE,
        settings=settings,
        commit=("abc1234", False),
        expected_cost_per_page_usd=0.01,
        workers=1,
        client_factory=factory,
        now=lambda: later,
    )
    assert len(done) == error.unread
    assert all(cache.get(job.key) is not None for job in jobs)
    assert all(r.status == "transcribed" for r in done)
    assert month_spent(settings.runs_dir, now=later) == pytest.approx(6 * 0.0004)


def test_a_job_that_spends_exactly_its_reservation_on_its_last_page_is_not_stopped(
    tmp_path: Path,
) -> None:
    """Reaching the reservation with nothing left to read is a finished job, not a stop."""
    settings = Settings(data_dir=tmp_path, monthly_budget_usd=40.0)
    done = run_preparation(
        kind="transcription",
        jobs=_jobs(),
        instruction=TRANSCRIBE,
        settings=settings,
        commit=("abc1234", False),
        expected_cost_per_page_usd=0.0004,
        workers=1,
        client_factory=lambda stack: lambda: _factory(stack),
        now=lambda: NOW,
    )
    assert len(done) == 3
