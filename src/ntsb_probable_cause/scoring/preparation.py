"""A paid evidence-preparation job: reserved, spent row by row, settled (0045, 0081).

Transcription and the inventory are paid once per page and reused by every run (0081). They
count against the monthly budget like any run: the job reserves its projection before its
first call, appends a spend row as each chunk of pages returns, and settles the reservation
when it ends -- also when it is interrupted, since the spend rows already say what it cost.
"""

from collections.abc import Callable, Sequence
from contextlib import ExitStack
from datetime import UTC, datetime
from typing import Literal

from ntsb_probable_cause.docket.transcribe import (
    Instruction,
    PageJob,
    Transcription,
    TranscriptionCache,
    transcribe_all,
)
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.model.client import ModelClient
from ntsb_probable_cause.model.openrouter import OpenRouterClient
from ntsb_probable_cause.scoring.budget import (
    SpendRecord,
    reserve_within_budget,
    settle,
    write_spend,
)
from ntsb_probable_cause.settings import Settings

Kind = Literal["inventory", "transcriber-test", "transcription"]


def openrouter_clients(settings: Settings) -> Callable[[ExitStack], Callable[[], ModelClient]]:
    """A factory of OpenRouter clients, each closed when the job's exit stack unwinds."""
    key = settings.openrouter_api_key
    if key is None or not key.get_secret_value():
        raise ConfigurationError("OPENROUTER_API_KEY is not set")
    secret = key.get_secret_value()

    def per_job(stack: ExitStack) -> Callable[[], ModelClient]:
        def make() -> ModelClient:
            return stack.enter_context(
                OpenRouterClient(secret, base_url=settings.openrouter_base_url)
            )

        return make

    return per_job


def run_preparation(  # noqa: PLR0913 -- one keyword per fact the job records.
    *,
    kind: Kind,
    jobs: Sequence[PageJob],
    instruction: Instruction,
    settings: Settings,
    commit: tuple[str, bool],
    expected_cost_per_page_usd: float,
    workers: int = 8,
    retry_failed: bool = False,
    client_factory: Callable[[ExitStack], Callable[[], ModelClient]] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> list[Transcription]:
    """Read the jobs' pages not yet cached, within the month's budget, recording the spend."""
    models = {job.key.model for job in jobs}
    if len(models) > 1:
        raise ConfigurationError(f"one model per preparation job, not {sorted(models)}")
    model = next(iter(models), "")
    cache = TranscriptionCache(settings.transcription_dir)
    pending = sum(
        1
        for job in jobs
        if (hit := cache.get(job.key)) is None or (retry_failed and hit.status == "failed")
    )
    started = now()
    sha, dirty = commit
    job_id = f"{started:%Y%m%dT%H%M%S}-{sha}-{kind}"
    reserve_within_budget(
        settings.runs_dir,
        job_id,
        pending * expected_cost_per_page_usd,
        settings.monthly_budget_usd,
        now=started,
    )

    def on_chunk(records: Sequence[Transcription]) -> None:
        write_spend(
            settings.runs_dir,
            SpendRecord(
                job_id=job_id,
                kind=kind,
                model=model,
                started=started,
                calls=len(records),
                cost_usd=sum(r.cost_usd for r in records),
                commit_sha=sha,
                dirty=dirty,
            ),
        )

    factory = client_factory or openrouter_clients(settings)
    try:
        with ExitStack() as stack:
            return transcribe_all(
                jobs,
                factory(stack),
                cache,
                instruction,
                workers=workers,
                on_chunk=on_chunk,
                retry_failed=retry_failed,
                now=now,
            )
    finally:
        settle(settings.runs_dir, job_id)
