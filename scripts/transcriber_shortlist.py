"""The transcriber shortlist: newer vision models by a fixed filter, then probed (S2.7 §7.2).

Status
    Repeatable. Subcommands, in order:
      fetch      -- read OpenRouter's public model list and save it under
                    <data_dir>/s27/openrouter-models-<date>.json (free, no key)
      shortlist  -- apply decision 0100 item 1's filter to a saved list; write
                    docs/results/s27-transcriber-shortlist.txt (free)
    Later tasks add ``probe`` (one invented page to each shortlisted model, paid) and
    ``batch-image``/``batch-poll`` (one batch request carrying an image, paid).
    The saved list, not memory, is the source of every id, price, date and reasoning level
    (rule 2). The recorded replies are of an invented page and hold no docket text.
"""

import argparse
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from collections.abc import Set as AbstractSet
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import cast, get_args

import httpx

from ntsb_probable_cause import sources
from ntsb_probable_cause.settings import Settings
from scripts.transcriber_test import CANDIDATES as S26_CANDIDATES

MODELS_URL = "https://openrouter.ai/api/v1/models"
RELEASED_FROM = datetime(2026, 6, 1, tzinfo=UTC)
SHORTLIST_SIZE = 8
RESULTS = Path("docs/results/s27-transcriber-shortlist.txt")
_LADDER: tuple[sources.ReasoningEffort, ...] = get_args(sources.ReasoningEffort)


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


def _per_mtok(pricing: Mapping[str, object], name: str) -> float:
    return float(str(pricing.get(name, "inf"))) * 1_000_000


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
    if _per_mtok(_map(entry.get("pricing")), "prompt") > sources.QWEN_35_122B.input_usd_per_mtok:
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
    args = parser.parse_args(argv)
    settings = Settings()
    if args.command == "fetch":
        text = cmd_fetch(settings, args.date)
    else:
        text = cmd_shortlist(args.models)
        if args.out is not None:
            args.out.write_text(text + "\n")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
