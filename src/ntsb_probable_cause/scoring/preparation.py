"""A paid evidence-preparation job: reserved, spent row by row, settled (0045, 0081).

Transcription and the inventory are paid once per page and reused by every run (0081). They
count against the monthly budget like any run: the job reserves its projection before its
first call, appends a spend row as each chunk of pages returns, and settles the reservation
when it ends -- also when it is interrupted, since the spend rows already say what it cost.
"""

import re
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

_NOT_SLUG = re.compile(r"[^a-z0-9]+")


def _model_slug(model: str) -> str:
    """A short, filesystem-safe slug for a model id (fix round 1, I1).

    A command that starts one preparation job per model, one after another (the transcriber
    test's ``run``), can have its second job start in the same clock second as its first once
    every page is already cached -- the first job then returns in milliseconds. Without a
    per-model slug, two such jobs of the same kind in the same second at the same commit
    shared one folder name and the second was refused as a duplicate, so a re-run after an
    interruption could never get past its second model. A genuine duplicate -- same kind,
    same model, same second -- still refuses, unchanged.
    """
    return _NOT_SLUG.sub("-", model.lower()).strip("-") or "no-model"


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
    # The model slug (fix round 1, I1) keeps two jobs of the same kind, started one after
    # another in the same second at the same commit, from sharing a folder when they use
    # different models; a genuine duplicate -- same kind AND same model, same second -- still
    # collides and is refused below.
    job_id = f"{started:%Y%m%dT%H%M%S}-{sha}-{kind}-{_model_slug(model)}"
    # Claim the job's folder atomically, before anything else (fix round 3, M9; the same
    # pattern as scoring/runner.py's Task 9D): two preparation jobs of the same kind and model
    # started in the same second at the same commit would otherwise share one folder, each
    # overwriting the other's reservation and interleaving spend rows -- the exact collision
    # Task 9D records for evaluation runs. `mkdir` is atomic, so exactly one job claims it.
    job_folder = settings.runs_dir / job_id
    try:
        job_folder.mkdir(parents=True, exist_ok=False)
    except FileExistsError:
        raise ConfigurationError(
            f"preparation job folder {job_id} already exists: another job of kind {kind!r} "
            f"and model {model!r} was started in the same second at the same commit. Wait a "
            "second and start again."
        ) from None
    # Built before the reservation (fix round 1, I2): the default factory raises
    # ConfigurationError when OPENROUTER_API_KEY is missing, and building it after the
    # reservation would leave that reservation open with nothing left to settle it -- held
    # against the budget until someone ran `ntsb-eval release` by hand.
    factory = client_factory or openrouter_clients(settings)
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
