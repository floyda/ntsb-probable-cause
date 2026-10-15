"""The learner's transport: the Claude API, for learning calls only (decisions 0202, 0207).

Not a ``model.client.ModelClient``: it carries no ``Payload`` and serves no answering call. Every
call states its effort and asks for structured output; thinking stays at the model's default.
Every reply is recorded under the run folder before it is used, so a repeated call is answered
from the record and never paid for twice. A refused or truncated reply is a failed reply.
"""

import hashlib
import json
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final, Literal

import anthropic
from pydantic import BaseModel, ConfigDict

from ntsb_probable_cause import sources
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory.lessons import estimated_tokens
from ntsb_probable_cause.scoring.budget import SpendRecord, write_spend

SONNET: Final = "claude-sonnet-5-5"
HAIKU: Final = "claude-haiku-5-5"
ROLES: Final = frozenset({"propose", "apply", "revise", "agreement", "probe"})
CALLS_FILE: Final = "calls.jsonl"
BATCHES_FILE: Final = "batches.jsonl"
FAILED_STOPS: Final = frozenset({"refusal", "max_tokens"})
Effort = Literal["low", "medium", "high"]


def sdk_from_key(api_key: str) -> anthropic.Anthropic:
    """The only place a Claude client is constructed (decision 0207 item 1); scripts call it."""
    return anthropic.Anthropic(api_key=api_key)


@dataclass(frozen=True)
class Call:
    """One learner request, exactly as sent."""

    role: str
    model: str
    effort: Effort
    system: str
    user: str
    schema: dict[str, object]
    max_tokens: int
    case_ids: tuple[str, ...]

    def params(self) -> dict[str, object]:
        """The Messages API parameters; the system text is cached (the memory repeats)."""
        return {
            "model": self.model,
            "max_tokens": self.max_tokens,
            "system": [
                {"type": "text", "text": self.system, "cache_control": {"type": "ephemeral"}}
            ],
            "messages": [{"role": "user", "content": self.user}],
            "output_config": {
                "effort": self.effort,
                "format": {"type": "json_schema", "schema": self.schema},
            },
        }

    def key(self) -> str:
        """The request's hash: its record key, and its batch ``custom_id``."""
        body = json.dumps(self.params(), sort_keys=True, ensure_ascii=False)
        return hashlib.sha256(body.encode()).hexdigest()[:32]


class Reply(BaseModel):
    """One recorded reply, failed or not, with its usage and what its price needs."""

    model_config = ConfigDict(frozen=True, extra="forbid")
    key: str
    role: str
    model: str
    effort: str
    batch: bool
    text: str | None
    stop_reason: str | None
    stop_category: str | None
    error: str | None
    input_tokens: int
    output_tokens: int
    cache_write_tokens: int
    cache_read_tokens: int
    cost_usd: float

    @property
    def ok(self) -> bool:
        """A usable reply: text, and no failure."""
        return self.text is not None and self.error is None


def cost_usd(
    input_tokens: int,
    output_tokens: int,
    cache_write_tokens: int,
    cache_read_tokens: int,
    price: sources.ClaudePrice,
) -> float:
    """A reply's price: each kind of token at its own rate (thinking is billed as output)."""
    return (
        input_tokens * price.input_usd_per_mtok
        + output_tokens * price.output_usd_per_mtok
        + cache_write_tokens * price.cache_write_usd_per_mtok
        + cache_read_tokens * price.cache_read_usd_per_mtok
    ) / 1e6


def _reply(call: Call, message: object | None, *, batch: bool, error: str | None = None) -> Reply:
    usage = getattr(message, "usage", None)
    counts = [
        int(getattr(usage, name, 0) or 0)
        for name in (
            "input_tokens",
            "output_tokens",
            "cache_creation_input_tokens",
            "cache_read_input_tokens",
        )
    ]
    stop = getattr(message, "stop_reason", None)
    # A refusal's category (decision 0207 item 4): ``stop_details.category``, which may be null.
    category = getattr(getattr(message, "stop_details", None), "category", None)
    text = next(
        (b.text for b in getattr(message, "content", []) if getattr(b, "type", None) == "text"),
        None,
    )
    if stop in FAILED_STOPS:
        error, text = error or f"stopped: {stop}", None
    price = sources.claude_price(call.model, batch=batch)
    return Reply(
        key=call.key(),
        role=call.role,
        model=call.model,
        effort=call.effort,
        batch=batch,
        text=text,
        stop_reason=stop,
        stop_category=category,
        error=error,
        input_tokens=counts[0],
        output_tokens=counts[1],
        cache_write_tokens=counts[2],
        cache_read_tokens=counts[3],
        cost_usd=cost_usd(counts[0], counts[1], counts[2], counts[3], price),
    )


class LearningClient:
    """Learner calls, sync or in batches, refused outside their role and the learning part."""

    def __init__(
        self,
        sdk: anthropic.Anthropic,
        runs_dir: Path,
        run_id: str,
        *,
        commit: tuple[str, bool],
        forbidden: frozenset[str],
    ) -> None:
        self._sdk = sdk
        self._runs_dir = runs_dir
        self._run_id = run_id
        self._commit = commit
        self._forbidden = forbidden
        self._folder = runs_dir / run_id
        self._folder.mkdir(parents=True, exist_ok=True)
        self._replies: dict[str, Reply] = {}
        calls = self._folder / CALLS_FILE
        if calls.exists():
            for line in calls.read_text().splitlines():
                reply = Reply.model_validate_json(line)
                if reply.ok:
                    self._replies[reply.key] = reply

    def _check(self, call: Call) -> None:
        if call.role not in ROLES:
            raise ConfigurationError(
                f"the Claude transport serves learning calls only, not {call.role!r} (0202)"
            )
        if hit := set(call.case_ids) & self._forbidden:
            raise ConfigurationError(f"{len(hit)} case(s) outside the learning part (0200)")
        prompt = estimated_tokens(call.system + call.user)
        if call.model == HAIKU and prompt > sources.HAIKU_55_PROMPT_LIMIT:
            raise ConfigurationError(
                f"a Haiku prompt of about {prompt} tokens passes its price limit"
            )

    def _record(self, replies: Sequence[Reply], *, model: str) -> None:
        with (self._folder / CALLS_FILE).open("a") as out:
            for reply in replies:
                out.write(reply.model_dump_json() + "\n")
        for reply in replies:
            if reply.ok:
                self._replies[reply.key] = reply
        sha, dirty = self._commit
        write_spend(
            self._runs_dir,
            SpendRecord(
                job_id=self._run_id,
                kind="learning",
                model=model,
                started=datetime.now(UTC),
                calls=len(replies),
                cost_usd=sum(r.cost_usd for r in replies),
                commit_sha=sha,
                dirty=dirty,
            ),
        )

    def _batch_rows(self) -> list[dict[str, object]]:
        path = self._folder / BATCHES_FILE
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]

    def _append_batch(self, batch_id: str, keys: Sequence[str], *, finished: bool) -> None:
        row = {"batch_id": batch_id, "keys": sorted(keys), "finished": finished}
        with (self._folder / BATCHES_FILE).open("a") as out:
            out.write(json.dumps(row) + "\n")

    def _submit(self, calls: Sequence[Call]) -> str:
        """Send one batch, and record its id before waiting so a crash resumes on it."""
        batch = self._sdk.messages.batches.create(
            requests=[{"custom_id": c.key(), "params": c.params()} for c in calls]  # type: ignore[typeddict-item]
        )
        self._append_batch(batch.id, [c.key() for c in calls], finished=False)
        return batch.id

    def _open_batch(self, keys: set[str]) -> str | None:
        """The last unfinished recorded batch holding exactly these keys, if any."""
        rows = self._batch_rows()
        closed = {r["batch_id"] for r in rows if r["finished"]}
        found: str | None = None
        for row in rows:
            if set(row["keys"]) == keys and row["batch_id"] not in closed:  # type: ignore[call-overload]
                found = str(row["batch_id"])
        return found

    def _mark_finished(self, batch_id: str) -> None:
        keys = next(
            (r["keys"] for r in reversed(self._batch_rows()) if r["batch_id"] == batch_id), []
        )
        self._append_batch(batch_id, keys, finished=True)  # type: ignore[arg-type]

    def _failed(self, call: Call) -> Reply:
        """The last recorded failed reply for a call, so its caller sees why it failed."""
        path = self._folder / CALLS_FILE
        found: Reply | None = None
        if path.exists():
            for line in path.read_text().splitlines():
                reply = Reply.model_validate_json(line)
                if reply.key == call.key():
                    found = reply
        if found is None:
            raise ConfigurationError(f"no recorded reply for call {call.key()}")
        return found

    def send(self, call: Call) -> Reply:
        """One call now, at the standard price; a recorded usable reply is returned instead."""
        self._check(call)
        if (known := self._replies.get(call.key())) is not None:
            return known
        try:
            message = self._sdk.messages.create(**call.params())  # type: ignore[call-overload]
            reply = _reply(call, message, batch=False)
        except anthropic.APIError as exc:
            reply = _reply(call, None, batch=False, error=f"{type(exc).__name__}: {exc}")
        self._record([reply], model=call.model)
        return reply

    def send_batch(
        self,
        calls: Sequence[Call],
        *,
        every_seconds: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> dict[str, Reply]:
        """Calls in one batch at the batch price; a recorded unfinished batch is waited on."""
        for call in calls:
            self._check(call)
        if len({c.model for c in calls}) > 1:
            raise ConfigurationError("one batch holds one model, so its spend row names one")
        todo = {c.key(): c for c in calls if c.key() not in self._replies}
        if todo:
            batch_id = self._open_batch(set(todo)) or self._submit(list(todo.values()))
            while self._sdk.messages.batches.retrieve(batch_id).processing_status != "ended":
                sleep(every_seconds)
            got: list[Reply] = []
            for result in self._sdk.messages.batches.results(batch_id):
                call = todo[result.custom_id]
                kind = result.result.type
                message = getattr(result.result, "message", None) if kind == "succeeded" else None
                got.append(_reply(call, message, batch=True, error=None if message else kind))
            missing = set(todo) - {r.key for r in got}
            got.extend(
                _reply(todo[k], None, batch=True, error="no result") for k in sorted(missing)
            )
            self._record(got, model=calls[0].model)
            self._mark_finished(batch_id)
        return {c.key(): self._replies.get(c.key()) or self._failed(c) for c in calls}
