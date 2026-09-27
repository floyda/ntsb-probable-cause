"""The transcriber shortlist: newer vision models by a fixed filter, then probed (S2.7 §7.2).

Status
    Repeatable. Subcommands, in order:
      fetch        -- read OpenRouter's public model list and save it under
                      <data_dir>/s27/openrouter-models-<date>.json (free, no key)
      shortlist    -- apply decision 0100 item 1's filter to a saved list; write
                      docs/results/s27-transcriber-shortlist.txt (free)
      probe        -- one invented page to each shortlisted model, in order, until eight
                      pass; each reply saved under <data_dir>/s27/probe-replies/, and a
                      passed model's reply also under tests/fixtures/openrouter/transcription/
                      (paid, cents; Task 7 Step 6)
      batch-image  -- walkthrough W2: one batch request carrying the invented page's image,
                      for a passed candidate with a batch variant (paid, a fraction of a cent)
      batch-poll   -- that batch's status, and whether its one reply parses (free)
    The saved list, not memory, is the source of every id, price, date and reasoning level
    (rule 2). The recorded replies are of an invented page and hold no docket text.
"""

import argparse
import json
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from collections.abc import Set as AbstractSet
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import cast, get_args

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.docket.render import render_pages
from ntsb_probable_cause.docket.transcribe import TRANSCRIBE, parse_reply, request_for, settings_for
from ntsb_probable_cause.errors import ModelError, SchemaError
from ntsb_probable_cause.gitinfo import commit_state
from ntsb_probable_cause.model.batch import TERMINAL, BatchClient
from ntsb_probable_cause.model.client import ModelReply, cost_usd
from ntsb_probable_cause.model.openrouter import OpenRouterClient, request_body
from ntsb_probable_cause.scoring.budget import (
    SPEND_FILE,
    SpendRecord,
    reserve_within_budget,
    settle,
    write_spend,
)
from ntsb_probable_cause.scoring.preparation import openrouter_clients
from ntsb_probable_cause.settings import Settings
from scripts.transcriber_test import CANDIDATES as S26_CANDIDATES
from scripts.transcriber_test import FIXTURES, PROBE_LINES, probe_page

MODELS_URL = "https://openrouter.ai/api/v1/models"
RELEASED_FROM = datetime(2026, 6, 1, tzinfo=UTC)
SHORTLIST_SIZE = 8
RESULTS = Path("docs/results/s27-transcriber-shortlist.txt")
_LADDER: tuple[sources.ReasoningEffort, ...] = get_args(sources.ReasoningEffort)

# The results file's eligible models, in its order (Task 6): the first SHORTLIST_SIZE are the
# shortlist, the rest replace a failed probe in order. Every one is priced in sources.py.
S27_SHORTLIST: tuple[str, ...] = (
    "inclusionai/ling-3.0-flash-vl",
    "qwen/qwen3.7-flash",
    "deepseek/deepseek-v4.1-flash",
    "z-ai/glm-5.3-flash",
    "prism-ml/ternary-bonsai-2-27b",
    "meta/muse-spark-1.2-contributor",
    "meta/muse-spark-1.3-contributor",
    "openai/gpt-6-luna-pro",
    "xiaomi/mimo-v2.6-flash",
    "qwen/qwen3.8-flash",
    "qwen/qwen3.8-omni-flash",
    "openai/gpt-5.6-luna",
    "openai/gpt-5.6-luna-pro",
    "deepseek/deepseek-v4-flash-vision-exp",
)


@dataclass(frozen=True)
class Listed:
    """One eligible model, as the saved list gives it."""

    model_id: str
    slug: str
    created: datetime
    input_usd_per_mtok: float
    output_usd_per_mtok: float
    lowest_reasoning: sources.ReasoningEffort
    batch_variant: bool


def _map(value: object) -> Mapping[str, object]:
    return cast("Mapping[str, object]", value) if isinstance(value, Mapping) else {}


def _strings(value: object) -> tuple[str, ...]:
    return tuple(str(v) for v in value) if isinstance(value, list) else ()


def _price(pricing: Mapping[str, object], name: str) -> Decimal | None:
    """The listed per-token price as an exact ``Decimal``, or ``None`` if it is not a number."""
    try:
        return Decimal(str(pricing.get(name)))
    except InvalidOperation:
        return None


def _per_mtok(pricing: Mapping[str, object], name: str) -> float:
    """The per-million-token price, computed exactly and rounded once at the very end."""
    price = _price(pricing, name)
    return float("inf") if price is None else float(price * 1_000_000)


def _free_or_unpriced(pricing: Mapping[str, object]) -> bool:
    """True if either price is missing, not a number, or not strictly positive."""
    return any(
        (price := _price(pricing, name)) is None or price <= 0 for name in ("prompt", "completion")
    )


# One return per refusal, in the fixed order of decision 0100 item 1.
def refusal(entry: Mapping[str, object], *, ids: AbstractSet[str]) -> str | None:  # noqa: PLR0911
    """The first reason decision 0100 item 1 refuses this entry, or None if it is eligible.

    ``ids`` is every id in the list; it is unused by the rules above and kept so the batch
    check (``_has_batch``) and this function read the same list.
    """
    del ids
    model_id = str(entry.get("id", ""))
    architecture = _map(entry.get("architecture"))
    if model_id.endswith(":batch"):
        return "batch variant"
    if model_id.startswith("~") or entry.get("alias_target"):
        return "alias"
    if "image" not in _strings(architecture.get("input_modalities")):
        return "no image input"
    if _strings(architecture.get("output_modalities")) != ("text",):
        return "not text-only output"
    created = entry.get("created")
    if not isinstance(created, int) or datetime.fromtimestamp(created, UTC) < RELEASED_FROM:
        return "released before 2026-06-01"
    pricing = _map(entry.get("pricing"))
    if _free_or_unpriced(pricing):
        return "free or unpriced listing"  # Andy, 2026-09-27
    if _per_mtok(pricing, "prompt") > sources.QWEN_35_122B.input_usd_per_mtok:
        return "input price above Qwen3.5 122B's"
    if model_id in S26_CANDIDATES:
        return "an S2.6 candidate"
    if "response_format" not in _strings(entry.get("supported_parameters")):
        return "no structured output"  # walkthrough W6
    return None


def lowest_reasoning(entry: Mapping[str, object]) -> sources.ReasoningEffort:
    """Walkthrough W1: the lowest listed effort; else minimal if mandatory; else none."""
    reasoning = _map(entry.get("reasoning"))
    listed = [e for e in _LADDER if e in _strings(reasoning.get("supported_efforts"))]
    if listed:
        return listed[0]
    return "minimal" if reasoning.get("mandatory") is True else "none"


def shortlist(entries: Sequence[Mapping[str, object]]) -> tuple[list[Listed], Counter[str]]:
    """Eligible models, cheapest input first, one per canonical slug; and refusal counts."""
    ids = {str(e.get("id", "")) for e in entries}
    refused: Counter[str] = Counter()
    eligible: list[Listed] = []
    for entry in entries:
        reason = refusal(entry, ids=ids)
        if reason is not None:
            refused[reason] += 1
            continue
        pricing = _map(entry.get("pricing"))
        model_id = str(entry["id"])
        eligible.append(
            Listed(
                model_id=model_id,
                slug=str(entry.get("canonical_slug") or model_id),
                created=datetime.fromtimestamp(cast("int", entry["created"]), UTC),
                input_usd_per_mtok=_per_mtok(pricing, "prompt"),
                output_usd_per_mtok=_per_mtok(pricing, "completion"),
                lowest_reasoning=lowest_reasoning(entry),
                batch_variant=f"{model_id}:batch" in ids,
            )
        )
    eligible.sort(key=lambda x: (x.input_usd_per_mtok, x.output_usd_per_mtok, x.model_id))
    kept: list[Listed] = []
    slugs: set[str] = set()
    for listed_model in eligible:
        if listed_model.slug in slugs:
            refused["same model as a cheaper listing"] += 1
            continue
        slugs.add(listed_model.slug)
        kept.append(listed_model)
    return kept, refused


def render_shortlist(
    listed: Sequence[Listed], refused: Counter[str], *, source: Path, fetched: str
) -> str:
    """The results file: the filter's counts, the ordered eligible list, and sources.py lines."""
    lines = [
        "# the transcriber shortlist (S2.7 spec §7.2, decision 0100 item 1) -- model ids only",
        f"model list: {MODELS_URL}, read {fetched}, saved as {source.name}",
        f"eligible: {len(listed)}; refused: "
        + ", ".join(f"{reason} {n}" for reason, n in sorted(refused.items())),
        "",
        f"## eligible, cheapest input first (the first {SHORTLIST_SIZE} are the shortlist; the "
        "rest replace a failed probe, in order)",
    ]
    for rank, x in enumerate(listed, start=1):
        mark = "candidate" if rank <= SHORTLIST_SIZE else "reserve  "
        lines.append(
            f"{mark} {rank:2d} {x.model_id}  ${x.input_usd_per_mtok}/${x.output_usd_per_mtok}"
            f" per M tokens; created {x.created:%Y-%m-%d}; lowest reasoning {x.lowest_reasoning}; "
            f"batch variant {'yes' if x.batch_variant else 'no'}"
        )
    return "\n".join(lines)


def _saved(settings: Settings, fetched: str) -> Path:
    return settings.data_dir / "s27" / f"openrouter-models-{fetched}.json"


def cmd_fetch(settings: Settings, fetched: str) -> str:
    """Read the public model list (no key) and save it as read."""
    response = httpx.get(MODELS_URL, timeout=60.0)
    response.raise_for_status()
    path = _saved(settings, fetched)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(response.text)
    count = len(_entries(path))
    return f"saved {count} models to {path}"


def _entries(path: Path) -> list[Mapping[str, object]]:
    data = json.loads(path.read_text())["data"]
    return [cast("Mapping[str, object]", e) for e in data]


def cmd_shortlist(path: Path) -> str:
    """Apply the filter to a saved list."""
    fetched = path.stem.removeprefix("openrouter-models-")
    listed, refused = shortlist(_entries(path))
    return render_shortlist(listed, refused, source=path, fetched=fetched)


PROBE_WANTED = 8
# Expected cost of one probe call, for the reservation (S2.6's probe: under $0.005 a model).
PROBE_EXPECTED_USD = 0.005

# The shortlisted models that passed the probe (Task 7 Step 6, 2026-09-27), in shortlist
# order: the candidates of the re-test (decision 0100 item 2).
S27_CANDIDATES: tuple[str, ...] = (
    "inclusionai/ling-3.0-flash-vl",
    "qwen/qwen3.7-flash",
    "deepseek/deepseek-v4.1-flash",
    "z-ai/glm-5.3-flash",
    "prism-ml/ternary-bonsai-2-27b",
    "openai/gpt-6-luna-pro",
    "xiaomi/mimo-v2.6-flash",
    "qwen/qwen3.8-omni-flash",
)


def probe(
    models: Sequence[str],
    complete: Callable[[str], ModelReply],
    *,
    wanted: int = PROBE_WANTED,
) -> tuple[list[str], list[str]]:
    """Probe models in order until ``wanted`` pass; a failure is replaced by the next.

    A model passes if it answers and the reply parses under instruction t1 (spec §7.2). How
    many of ``PROBE_LINES`` it copies is printed, never judged here -- the re-test's answer
    keys judge reading (Task 9).
    """
    passed: list[str] = []
    lines: list[str] = []
    for model in models:
        if len(passed) == wanted:
            break
        try:
            reply = complete(model)
        except ModelError as error:
            lines.append(f"{model}: FAILED -- {type(error).__name__}: {str(error)[:200]}")
            continue
        try:
            text, kind = parse_reply(reply.content or "", TRANSCRIBE)
        except SchemaError as error:
            lines.append(f"{model}: the reply did not parse -- {error}")
            continue
        copied = sum(1 for line in PROBE_LINES if line in text)
        lines.append(f"{model}: ok, kind {kind}, {copied} of {len(PROBE_LINES)} lines copied")
        passed.append(model)
    return passed, lines


def cmd_probe(settings: Settings) -> str:
    """One invented page to each shortlisted model, in order, until eight pass (spec §7.2).

    Reserved, spent and settled as S2.6's probe was (``transcriber_test.cmd_probe``): the
    client factory is built (which raises if ``OPENROUTER_API_KEY`` is missing) before the
    reservation, and the spend row is written -- with ``settle`` -- in a ``finally``, so an
    exception partway through still records what was spent. Pre-flight 2.6-cmd_probe: kept as
    its own frame rather than calling ``transcriber_test.cmd_probe`` directly, which is fixed
    to S2.6's four ``CANDIDATES`` and its own per-page cost table -- both outside this task's
    files (``scripts/transcriber_test.py`` is not in Task 7's Files list) -- but it mirrors
    that frame's shape and order exactly.

    Pre-flight 1.3: every reply actually received (whether it parses or not) is saved first
    under the git-ignored data directory; only a model that passes has its reply copied into
    the committed fixtures folder, once the whole probe is done and ``passed`` is known.
    """
    (rendered,) = render_pages(probe_page())
    payload, system = request_for(rendered, TRANSCRIBE, text_layer=None)
    replies_dir = settings.data_dir / "s27" / "probe-replies"
    replies_dir.mkdir(parents=True, exist_ok=True)
    FIXTURES.mkdir(parents=True, exist_ok=True)
    sha, dirty = commit_state()
    started = datetime.now(UTC)
    job_id = f"{started:%Y%m%dT%H%M%S}-{sha}-s27-transcriber-probe"
    factory = openrouter_clients(settings)
    reserve_within_budget(
        settings.runs_dir,
        job_id,
        len(S27_SHORTLIST) * PROBE_EXPECTED_USD,
        settings.monthly_budget_usd,
        now=started,
    )
    spent = 0.0
    calls = 0
    replies: dict[str, ModelReply] = {}
    try:
        with ExitStack() as stack:
            make = factory(stack)

            def complete(model: str) -> ModelReply:
                nonlocal spent, calls
                model_settings = settings_for(model, TRANSCRIBE)
                reply = make().complete(payload, model_settings, system=system)
                calls += 1
                spent += cost_usd(reply, model_settings)[0]
                replies[model] = reply
                name = model.replace("/", "__") + ".json"
                (replies_dir / name).write_text(reply.model_dump_json(indent=1) + "\n")
                return reply

            passed, lines = probe(S27_SHORTLIST, complete)
    finally:
        write_spend(
            settings.runs_dir,
            SpendRecord(
                job_id=job_id,
                kind="transcriber-test",
                model="s27-shortlist",
                started=started,
                calls=calls,
                cost_usd=spent,
                commit_sha=sha,
                dirty=dirty,
            ),
        )
        settle(settings.runs_dir, job_id)
    for model in passed:
        name = model.replace("/", "__") + ".json"
        (FIXTURES / name).write_text(replies[model].model_dump_json(indent=1) + "\n")
    lines.append(f"passed ({len(passed)}): " + ", ".join(passed))
    return "\n".join(lines)


def cmd_batch_image(settings: Settings, model: str) -> str:
    """Walkthrough W2: does OpenRouter's batch service now accept one image part?

    ``BatchClient.submit`` refuses images by design (S2.6 decision W1) and must keep
    refusing them, so this call is sent by hand: the batch request body ``BatchClient.submit``
    would build, posted through ``OpenRouterClient.request_json`` directly.

    Pre-flight 1.2: reserved and settled like ``cmd_probe``. The monthly budget guard runs
    before the POST, and a ``SpendRecord`` (kind ``transcriber-test``) is written in a
    ``finally`` whether the batch service accepts or refuses the image, so ``stage_spend``
    always sees this call. The batch's own cost is not known until it is polled -- OpenRouter
    prices a batch once its requests complete -- so this row's ``cost_usd`` is 0.0; a real
    cost is recorded, in its own row, by ``cmd_batch_poll`` once ``reported_cost_usd`` is known.
    """
    (rendered,) = render_pages(probe_page())
    payload, system = request_for(rendered, TRANSCRIBE, text_layer=None)
    model_settings = settings_for(model, TRANSCRIBE).model_copy(update={"price_variant": "batch"})
    sha, dirty = commit_state()
    started = datetime.now(UTC)
    job_id = f"{started:%Y%m%dT%H%M%S}-{sha}-s27-batch-image"
    reserve_within_budget(
        settings.runs_dir, job_id, PROBE_EXPECTED_USD, settings.monthly_budget_usd, now=started
    )
    calls = 0
    result = ""
    try:
        body: dict[str, object] = {
            "endpoint": "/v1/chat/completions",
            "model": model_settings.model_id(),
            "requests": [
                {
                    "custom_id": "s27-probe",
                    "body": request_body(payload, model_settings, system=system, history=()),
                }
            ],
        }
        key = settings.require_openrouter_key()
        with OpenRouterClient(key, base_url=settings.openrouter_base_url) as http:
            try:
                submitted = http.request_json(
                    sources.BATCHES, method="POST", body=body, retry=False
                )
                calls = 1
                result = (
                    f"{model_settings.model_id()}: accepted as batch {submitted['id']}; "
                    "poll it with batch-poll"
                )
            except ModelError as error:
                result = f"{model_settings.model_id()}: refused -- {str(error)[:300]}"
        return result
    finally:
        write_spend(
            settings.runs_dir,
            SpendRecord(
                job_id=job_id,
                kind="transcriber-test",
                model=model_settings.model_id(),
                started=started,
                calls=calls,
                cost_usd=0.0,
                commit_sha=sha,
                dirty=dirty,
            ),
        )
        settle(settings.runs_dir, job_id)


def cmd_batch_poll(settings: Settings, batch_id: str) -> str:
    """The accepted batch's status, and whether its one reply parses.

    Fix round 1: once the batch is **terminal** (``TERMINAL``, ``model/batch.py``) and the
    provider reports a cost, that cost is written as its own spend row, under a distinct job
    id (the batch id, suffixed ``-poll``) so a batch counted once by ``cmd_batch_image`` and
    again here is never summed twice by ``stage_spend``. The row is written at most once per
    batch: ``write_spend``/``write_jsonl`` appends (``scoring/records.py``), and both
    ``month_spent`` and ``stage_spend`` sum every row under ``*/spend.jsonl``, so writing on
    every terminal poll would count the same cost again on a re-poll after completion. The
    row's own spend file's existence is the guard -- if it is already there, this poll writes
    nothing more. Before the batch is terminal, no row is written even if ``reported_cost_usd``
    is already reported (OpenRouter can report a partial ``usage.cost`` mid-batch,
    ``model/batch.py``'s ``poll``), since a later, terminal poll's cost would then double it.
    """
    key = settings.require_openrouter_key()
    with OpenRouterClient(key, base_url=settings.openrouter_base_url) as http:
        status = BatchClient(http).poll(batch_id)
    parsed = "no result yet"
    for result in status.results:
        if result.reply is None:
            parsed = f"error: {result.error}"
        else:
            try:
                parse_reply(result.reply.content or "", TRANSCRIBE)
                parsed = "the reply parses"
            except SchemaError as error:
                parsed = f"the reply did not parse: {error}"
    spend_path = settings.runs_dir / f"{batch_id}-poll" / SPEND_FILE
    if (
        status.status in TERMINAL
        and status.reported_cost_usd is not None
        and not spend_path.exists()
    ):
        sha, dirty = commit_state()
        write_spend(
            settings.runs_dir,
            SpendRecord(
                job_id=f"{batch_id}-poll",
                kind="transcriber-test",
                model=batch_id,
                started=datetime.now(UTC),
                calls=1,
                cost_usd=status.reported_cost_usd,
                commit_sha=sha,
                dirty=dirty,
            ),
        )
    return f"batch {batch_id}: {status.status}; {parsed}; cost {status.reported_cost_usd}"


def main(argv: list[str] | None = None) -> int:
    """Run one subcommand."""
    parser = argparse.ArgumentParser(prog="transcriber_shortlist")
    commands = parser.add_subparsers(dest="command", required=True)
    fetch_p = commands.add_parser("fetch")
    # pre-flight 2.8: the UTC date, so it always matches Step 6's `date -u` shell invocation.
    fetch_p.add_argument("--date", default=f"{datetime.now(UTC).date():%Y-%m-%d}")
    short_p = commands.add_parser("shortlist")
    short_p.add_argument("--models", type=Path, required=True)
    short_p.add_argument("--out", type=Path)
    commands.add_parser("probe")
    batch_image_p = commands.add_parser("batch-image")
    batch_image_p.add_argument("--model", required=True)
    batch_poll_p = commands.add_parser("batch-poll")
    batch_poll_p.add_argument("--batch-id", required=True)
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "fetch":
        text = cmd_fetch(settings, args.date)
    elif args.command == "shortlist":
        text = cmd_shortlist(args.models)
        if args.out is not None:
            args.out.write_text(text + "\n")
    elif args.command == "probe":
        text = cmd_probe(settings)
    elif args.command == "batch-image":
        text = cmd_batch_image(settings, args.model)
    else:
        text = cmd_batch_poll(settings, args.batch_id)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
