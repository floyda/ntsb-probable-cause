"""Exception hierarchy for the library."""

from collections.abc import Sequence


class NtsbError(Exception):
    """Base class for every error this library raises."""


class ConfigurationError(NtsbError):
    """A required setting, such as an API key, is missing or invalid."""


class ApiError(NtsbError):
    """The NTSB API returned an unusable response after retries.

    ``status`` is the HTTP status code that caused the failure (an ``int``), or the class name
    of a transport exception that exhausted every retry (a ``str``, e.g. ``"ConnectError"``),
    or ``None`` for a failure with no status to report at all (a malformed body, a missing
    pagination marker). It exists so a caller can log *what kind* of failure this was --
    ``401``/``403`` (an expired or revoked key) reads very differently from a transport outage
    -- without logging ``message``, which can embed up to 200 characters of the response body
    (Task 9 fix round 1, Important 2).
    """

    def __init__(self, message: str, *, status: int | str | None = None) -> None:
        super().__init__(message)
        self.status = status


class ManifestError(NtsbError):
    """The raw-data manifest is missing, malformed, or disagrees with the files."""


class FixtureError(NtsbError):
    """A fixture would break the fixture policy (decision 0015)."""


class LeakageError(NtsbError):
    """Withheld synthesis or verdict content reached evidence (decision 0016).

    ``message`` must never contain the withheld text itself — only role, kind and source. Callers
    that need the structured detail (tests, an audit trail) can read ``leaks``, typed loosely here
    (``Sequence[object]``) so this foundational module never depends on ``records.guard.Leak``.
    """

    def __init__(self, message: str, *, leaks: Sequence[object] = ()) -> None:
        super().__init__(message)
        self.leaks: Sequence[object] = tuple(leaks)


class ModelError(NtsbError):
    """The model provider returned an unusable response after retries."""


class BatchNotFoundError(ModelError):
    """A batch id the provider no longer recognises, after the not-found grace."""


class SchemaError(NtsbError):
    """A model reply did not parse as the requested schema, or named a code not in the tables."""


class BudgetError(NtsbError):
    """A run or call would exceed the per-case cap or the monthly budget (decision 0030)."""


class DocketError(NtsbError):
    """The docket site returned an unusable page or file, or a listing did not parse."""
