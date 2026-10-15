"""The Claude API shape probe for the coding memory (decision 0202 item 5, rule 2).

Status
    One-shot probe (decision 0202 item 5, rule 2), paid: a few cents of plan credit. Invented
    text only; no case is read. Run once through ``make mem-shape-probe``, which supplies the
    keys from ``pass``; it refuses a dirty tree, so the result names a clean commit.

What it checks
    That both learner models are retrievable and what limits they report; that one synchronous
    Sonnet call and one two-request Haiku batch, each asking for strict structured output,
    return replies the learner's own schemas parse, stop on ``end_turn`` and are not truncated.
    A failed check exits 1.

Usage
    uv run python -m scripts.memory_shape_probe --out docs/results/memory-shape-probe.txt
"""

import argparse
import time
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ValidationError

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import ConfigurationError
from ntsb_probable_cause.memory import claude, prompts
from ntsb_probable_cause.scoring import budget
from ntsb_probable_cause.scoring.hypothesis import strict_schema
from ntsb_probable_cause.settings import Settings

PROJECTED_USD = 0.10
MEMORY = (
    "Lesson L1: when a cause names a loss of engine power with no mechanical fault found, "
    "the first occurrence is the power loss, not the landing that followed.\n"
    "Lesson L2: when a cause names a stall during a low-altitude turn, code the loss of "
    "control before the stall."
)
SONNET_USER = (
    "Cause: the pilot's failure to maintain airspeed during a low-altitude turn, which "
    "resulted in an aerodynamic stall."
)
HAIKU_USERS = (
    "Cause: a total loss of engine power due to fuel starvation, and the pilot's improper "
    "fuel management.",
    "Cause: the pilot's decision to continue a visual flight into instrument conditions.",
)


def _parses(model: type[BaseModel], text: str | None) -> bool:
    if text is None:
        return False
    try:
        model.model_validate_json(text)
    except ValidationError:
        return False
    return True


def _describe(
    label: str, reply: claude.Reply, model: type[BaseModel], max_tokens: int
) -> list[str]:
    return [
        f"{label}: stop_reason={reply.stop_reason} stop_category={reply.stop_category} "
        f"error={reply.error}",
        f"{label}: tokens input={reply.input_tokens} output={reply.output_tokens} "
        f"cache_write={reply.cache_write_tokens} cache_read={reply.cache_read_tokens} "
        f"of max {max_tokens}",
        f"{label}: cost_usd={reply.cost_usd:.6f} parses_as_{model.__name__}="
        f"{_parses(model, reply.text)}",
    ]


def main(argv: Sequence[str] | None = None) -> int:
    """Run the probe.

    Returns:
        0 when every check is ok, 1 when any check failed.

    Raises:
        ConfigurationError: the tree has uncommitted changes, the learning line would be
            passed, or the Anthropic key is not set.
    """
    parser = argparse.ArgumentParser(prog="memory_shape_probe")
    parser.add_argument("--out", type=Path, help="also write the printed text here")
    args = parser.parse_args(argv)
    settings = Settings()
    commit = gitinfo.commit_state()
    if commit[1]:
        raise ConfigurationError("the shape probe records a clean commit: commit first")
    now = datetime.now(UTC)
    budget.check_learning_budget(
        settings.runs_dir, PROJECTED_USD, settings.learning_monthly_budget_usd, now=now
    )
    sdk = claude.sdk_from_key(settings.require_anthropic_key())
    lines = [f"memory shape probe at commit {commit[0]}, {now:%Y-%m-%d}"]

    retrievable: dict[str, bool] = {}
    for model_id in (claude.SONNET, claude.HAIKU):
        try:
            info = sdk.models.retrieve(model_id)
        except Exception as exc:
            retrievable[model_id] = False
            lines.append(f"model {model_id}: {type(exc).__name__}: {exc}")
            continue
        retrievable[model_id] = True
        lines.append(
            f"model {model_id}: id={getattr(info, 'id', None)} "
            f"display_name={getattr(info, 'display_name', None)} "
            f"max_input_tokens={getattr(info, 'max_input_tokens', None)} "
            f"max_tokens={getattr(info, 'max_tokens', None)}"
        )

    client = claude.LearningClient(
        sdk,
        settings.runs_dir,
        f"memory-shape-probe-{now:%Y%m%dT%H%M%S}",
        commit=commit,
        forbidden=frozenset(),
    )
    sonnet_call = claude.Call(
        role="probe",
        model=claude.SONNET,
        effort="high",
        system=MEMORY,
        user=SONNET_USER,
        schema=strict_schema(prompts.ProposeReply),
        max_tokens=16000,
        case_ids=(),
    )
    sonnet = client.send(sonnet_call)
    lines += _describe("sonnet", sonnet, prompts.ProposeReply, sonnet_call.max_tokens)

    haiku_calls = [
        claude.Call(
            role="probe",
            model=claude.HAIKU,
            effort="low",
            system=MEMORY,
            user=user,
            schema=strict_schema(prompts.ApplyReply),
            max_tokens=2048,
            case_ids=(),
        )
        for user in HAIKU_USERS
    ]
    started = time.monotonic()
    batch = client.send_batch(haiku_calls)
    lines.append(f"haiku batch: wall clock {time.monotonic() - started:.1f} seconds")
    haikus = [batch[c.key()] for c in haiku_calls]
    for number, (call, reply) in enumerate(zip(haiku_calls, haikus, strict=True), start=1):
        lines += _describe(f"haiku {number}", reply, prompts.ApplyReply, call.max_tokens)

    replies = [(sonnet, sonnet_call), *zip(haikus, haiku_calls, strict=True)]
    checks = {
        "both model ids retrievable": all(retrievable.values()),
        "sonnet reply parses as ProposeReply": _parses(prompts.ProposeReply, sonnet.text),
        "both haiku replies parse as ApplyReply": all(
            _parses(prompts.ApplyReply, r.text) for r in haikus
        ),
        "every reply stopped on end_turn": all(r.stop_reason == "end_turn" for r, _ in replies),
        "no reply reached its max_tokens": all(r.output_tokens < c.max_tokens for r, c in replies),
    }
    lines += [f"check {name}: {'ok' if passed else 'FAILED'}" for name, passed in checks.items()]
    text = "\n".join(lines)
    print(text)
    if args.out is not None:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text + "\n")
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
