"""scripts/s3_probe/budget.py: the probe's cost caps, model settings and spend accounting.

Status
    One-shot learning probe for S3 (2026-09-29). Output is not a result; it sets no bar and
    tunes nothing.

Cost is checked before every call (``constraints.md``, "Cost limits"): a call's estimate is
all its input text at four characters a token plus the full reply budget, priced at the
standard variant. :class:`RunBudget` is shared by every case thread and holds both caps;
:class:`CaseBudget` is one case's spend on it. :func:`call_settings` is the one place the
probe's model settings are written.
"""

import threading
from collections.abc import Sequence

from ntsb_probable_cause import sources
from ntsb_probable_cause.model.client import ModelSettings, Payload, Turn

CASE_CAP_USD = 0.15
RUN_CAP_USD = 3.00
# Held back for the coding checks and the final answer when deciding whether H_all runs.
CODING_RESERVE_USD = 0.03
MAX_OUTPUT_TOKENS = 8000  # decision 0084
_CHARS_PER_TOKEN = 4


def call_settings(schema: dict[str, object], name: str) -> ModelSettings:
    """The settings every probe call uses; only the reply schema and its name vary."""
    return ModelSettings(
        model=sources.DEFAULT_MODEL,
        price_variant="standard",
        reasoning_effort=sources.DEFAULT_REASONING_EFFORT,
        max_output_tokens=MAX_OUTPUT_TOKENS,
        temperature=0.0,
        json_schema=schema,
        schema_name=name,
    )


class RunBudget:
    """The run-wide spend, shared by every case thread, and both caps.

    A call reserves its estimate before it is made and settles to its actual cost after, all
    under one lock, so threads checking at the same moment cannot together pass the run cap.
    """

    def __init__(
        self, *, run_cap_usd: float = RUN_CAP_USD, case_cap_usd: float = CASE_CAP_USD
    ) -> None:
        """Start a run with nothing spent."""
        self.run_cap_usd = run_cap_usd
        self.case_cap_usd = case_cap_usd
        self._lock = threading.Lock()
        self._spent = 0.0
        self._reserved = 0.0

    @property
    def spent(self) -> float:
        """Actual dollars spent by settled calls."""
        with self._lock:
            return self._spent

    def reserve(self, estimate: float) -> bool:
        """Hold ``estimate`` against the run cap; ``False`` (nothing held) if it would pass it."""
        with self._lock:
            if self._spent + self._reserved + estimate > self.run_cap_usd:
                return False
            self._reserved += estimate
            return True

    def settle(self, estimate: float, actual: float) -> None:
        """Release a reservation and add the call's actual cost."""
        with self._lock:
            self._reserved -= estimate
            self._spent += actual


class CapReached(Exception):  # noqa: N818 -- a signal, not an error
    """A cap refused the next call; ``reason`` is ``"cap"`` or ``"run_cap"``.

    Raised by :meth:`CaseBudget.check`; ``loop.run_case`` catches it and ends the case.
    """

    def __init__(self, reason: str) -> None:
        """Carry the stop reason."""
        super().__init__(reason)
        self.reason = reason


class CaseBudget:
    """One case's spend, checked with the run's before every call."""

    def __init__(self, run: RunBudget) -> None:
        """Start a case with nothing spent, against ``run``'s caps."""
        self.run = run
        self.spent = 0.0

    @staticmethod
    def estimate(
        system: str, payload: Payload, history: Sequence[Turn], settings: ModelSettings
    ) -> float:
        """Estimated dollars: all input text at 4 characters a token, plus the full reply budget."""
        chars = len(system) + len(payload.text) + sum(len(t.content or "") for t in history)
        price = sources.price_of(settings.model_id())
        return (
            chars / _CHARS_PER_TOKEN * price.input_usd_per_mtok
            + settings.max_output_tokens * price.output_usd_per_mtok
        ) / 1e6

    def fits(self, estimate: float, *, reserve: float = 0.0) -> bool:
        """Whether a call of ``estimate``, with ``reserve`` held back, stays under the case cap."""
        return self.spent + estimate + reserve <= self.run.case_cap_usd

    def check(self, estimate: float) -> None:
        """Reserve ``estimate`` or stop the case: the case cap first, then the run cap."""
        if not self.fits(estimate):
            raise CapReached("cap")
        if not self.run.reserve(estimate):
            raise CapReached("run_cap")

    def settle(self, estimate: float, actual: float) -> None:
        """Record a finished (or failed) call's actual cost, here and on the run."""
        self.spent += actual
        self.run.settle(estimate, actual)
