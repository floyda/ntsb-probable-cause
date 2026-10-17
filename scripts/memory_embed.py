"""Embeddings for the coding memory's embedding lookup: model list, shape probe (decision 0213).

Status
    Live tool for decision 0213, on OpenRouter's embeddings service (the product's transport,
    decision 0009). ``models`` is free: it saves OpenRouter's public embedding model list. ``probe``
    is paid, cents, ONCE: one request per candidate model with two invented texts, no case read.
    It refuses a dirty tree and runs only once ``docs/rounds/memory-embed-lookup.md`` is committed.
    Its spend row is kind ``probe``: the $40 monthly guard counts it, and so does the side track's
    $10 line (``make mem-spend``, decision 0207).

What it sends
    ``probe``: ``POST /api/v1/embeddings`` with ``{"model": ..., "input": PROBE_TEXTS}`` for each
    of ``CANDIDATES``, the key as a bearer token. No case text and no lesson.

What it writes
    ``models``: the list, verbatim, at ``<data_dir>/mem/openrouter-embedding-models.json`` (never
    committed). ``probe``: each reply body, verbatim, at ``<fixtures>/<slug>.json`` (the test
    fixtures the client is written against, rule 2); one ``spend.jsonl`` row under
    ``<runs>/<job id>/``; and, counts only, ``docs/results/memory-embed-probe.txt``.

Usage
    uv run python -m scripts.memory_embed models
    uv run python -m scripts.memory_embed probe [--fixtures DIR] [--out PATH]
"""

import argparse
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import httpx

from ntsb_probable_cause import gitinfo
from ntsb_probable_cause.errors import BudgetError, ConfigurationError
from ntsb_probable_cause.scoring import budget
from ntsb_probable_cause.settings import Settings
from scripts._live_fence import refuse_live
from scripts._s3_runs import write_result

PROG: Final = "memory_embed"
REGISTRATION: Final = Path("docs/rounds/memory-embed-lookup.md")
CANDIDATES: Final = (
    "qwen/qwen3-embedding-8b",
    "openai/text-embedding-3-small",
    "openai/text-embedding-3-large",
)
MODELS_FILE: Final = "mem/openrouter-embedding-models.json"
MODELS_PATH: Final = "/api/v1/embeddings/models"
EMBEDDINGS_PATH: Final = "/api/v1/embeddings"
FIXTURES: Final = Path("tests/fixtures/openrouter/embeddings")
PROBE_TEXTS: Final = (
    "a single-engine aeroplane lost power after takeoff",
    "the pilot did not maintain airspeed in the turn",
)
VECTORS_FILE: Final = "vectors.json"
PROBE_PROJECTED_USD: Final = 0.01
CHARS_PER_TOKEN: Final = 4
TIMEOUT_SECONDS: Final = 60.0
_USER_AGENT: Final = "ntsb-probable-cause (https://github.com/floyda/ntsb-probable-cause)"

Clock = Callable[[], datetime]


def slug(model: str) -> str:
    """A model id as a file or folder name: ``qwen/qwen3-embedding-8b`` -> ``qwen-qwen3-...``."""
    return model.replace("/", "-").replace(":", "-")


def refuse_without_registration() -> None:
    """Refuse every paid step until the embedding lookup's registration is committed.

    Raises:
        ConfigurationError: ``docs/rounds/memory-embed-lookup.md`` is not committed (0213 item 11).
    """
    if not gitinfo.is_committed(REGISTRATION):
        raise ConfigurationError(
            f"{REGISTRATION} is not committed: the embedding lookup waits for its registration "
            "(decision 0213 item 11)"
        )


def require_clean(dirty: bool) -> None:
    """Refuse a paid step from a tree with uncommitted changes, so its rows name a clean commit.

    Raises:
        ConfigurationError: ``dirty`` is True.
    """
    if dirty:
        raise ConfigurationError("the tree has uncommitted changes: commit first")


@dataclass(frozen=True)
class EmbedRun:
    """A finished embedding run's ``vectors.json``: one model's vectors for a snapshot and sample.

    Attributes:
        run_id: the run folder's name.
        model: the embedding model.
        lessons: lesson id to vector, for every lesson of the snapshot that embedded.
        cases: case id to its cause sentence's vector; a case that failed is absent.
        failed_cases: the cases whose cause sentence did not embed.
    """

    run_id: str
    model: str
    lessons: dict[str, tuple[float, ...]]
    cases: dict[str, tuple[float, ...]]
    failed_cases: tuple[str, ...]


def _vectors(raw: object) -> dict[str, tuple[float, ...]]:
    if not isinstance(raw, dict):
        raise TypeError("not a mapping of vectors")
    return {str(key): tuple(float(x) for x in value) for key, value in raw.items()}


def read_vectors(folder: Path, *, snapshot: str, sha: str, sample: str) -> EmbedRun:
    """An embedding run, refused unless it embedded this snapshot (and file) and sample.

    Raises:
        SystemExit: the folder is, or may be, a live run (``refuse_live``).
        ConfigurationError: no readable ``vectors.json``; a run of another sample, snapshot or
            snapshot file; or a model that is not a candidate.
    """
    refuse_live(PROG, folder)
    try:
        body = json.loads((folder / VECTORS_FILE).read_text())
        run = EmbedRun(
            run_id=folder.name,
            model=str(body["model"]),
            lessons=_vectors(body["lessons"]),
            cases=_vectors(body["cases"]),
            failed_cases=tuple(map(str, body["failed_cases"])),
        )
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ConfigurationError(
            f"{folder.name}: not a finished embedding run ({type(error).__name__})"
        ) from None
    wanted = {"sample": sample, "snapshot": snapshot, "snapshot_sha256": sha}
    differing = [key for key, value in wanted.items() if body.get(key) != value]
    if differing:
        raise ConfigurationError(f"{folder.name} differs in {', '.join(differing)}")
    if run.model not in CANDIDATES:
        raise ConfigurationError(f"{folder.name}: {run.model} is not a registered candidate")
    return run


def load_prices(data_dir: Path) -> dict[str, float]:
    """Each candidate's list price in dollars per input token, from the saved model list.

    Raises:
        ConfigurationError: no saved list (run ``make mem-embed-models``), one that cannot be read,
            or a candidate missing from it or without a numeric prompt price.
    """
    path = data_dir / MODELS_FILE
    try:
        rows = json.loads(path.read_text())["data"]
        found = {str(row["id"]): row for row in rows}
    except (OSError, ValueError, KeyError, TypeError) as error:
        raise ConfigurationError(
            f"no readable model list at {path} ({type(error).__name__}): run make mem-embed-models"
        ) from None
    prices: dict[str, float] = {}
    for model in CANDIDATES:
        try:
            prices[model] = float(found[model]["pricing"]["prompt"])
        except KeyError, TypeError, ValueError:
            raise ConfigurationError(f"{model} has no prompt price in {path}") from None
    return prices


def _client(settings: Settings, transport: httpx.BaseTransport | None) -> httpx.Client:
    return httpx.Client(
        base_url=settings.openrouter_base_url,
        transport=transport,
        timeout=TIMEOUT_SECONDS,
        headers={"User-Agent": _USER_AGENT},
    )


def models(settings: Settings, transport: httpx.BaseTransport | None) -> int:
    """Save OpenRouter's public embedding model list, verbatim, and print the candidates' prices."""
    with _client(settings, transport) as http:
        response = http.get(MODELS_PATH)
    if response.status_code != httpx.codes.OK:
        raise ConfigurationError(f"the model list answered HTTP {response.status_code}")
    path = settings.data_dir / MODELS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(response.content)
    for model, price in load_prices(settings.data_dir).items():
        print(f"{model}: ${price * 1_000_000:.4f} per million input tokens")
    print(f"saved {path}")
    return 0


def _reply_cost(body: object, price: float, texts: Sequence[str]) -> float:
    """The reply's own ``usage.cost``; else the price times its prompt tokens; else characters/4."""
    usage = body.get("usage") if isinstance(body, dict) else None
    if isinstance(usage, dict):
        cost = usage.get("cost")
        if isinstance(cost, int | float):
            return float(cost)
        tokens = usage.get("prompt_tokens")
        if isinstance(tokens, int):
            return tokens * price
    return sum(len(text) for text in texts) / CHARS_PER_TOKEN * price


def _vector_shape(body: object, wanted: int) -> tuple[int, int | None, bool]:
    """How many vectors a reply holds, their length, and whether it is one per text, one length."""
    data = body.get("data") if isinstance(body, dict) else None
    if not isinstance(data, list):
        return 0, None, False
    lengths = {
        len(item["embedding"])
        for item in data
        if isinstance(item, dict) and isinstance(item.get("embedding"), list)
    }
    indexes = sorted(
        index
        for item in data
        if isinstance(item, dict) and isinstance(index := item.get("index"), int)
    )
    ok = len(data) == wanted and len(lengths) == 1 and indexes == list(range(wanted))
    return len(data), (next(iter(lengths)) if len(lengths) == 1 else None), ok


def _describe(model: str, status: int, body: object, cost: float) -> tuple[str, bool]:
    keys = sorted(body) if isinstance(body, dict) else []
    usage = body.get("usage") if isinstance(body, dict) else None
    usage_keys = sorted(usage) if isinstance(usage, dict) else []
    count, length, ok = _vector_shape(body, len(PROBE_TEXTS))
    line = (
        f"{model}: status={status} keys={','.join(keys)} vectors={count} length={length} "
        f"usage={','.join(usage_keys)} cost_usd={cost:.8f}"
    )
    return line, ok and status == httpx.codes.OK


def probe(  # noqa: PLR0913 -- the parsed arguments and the injectable seams
    args: argparse.Namespace,
    settings: Settings,
    *,
    transport: httpx.BaseTransport | None,
    commit: tuple[str, bool],
    now: Clock,
    prices: Mapping[str, float],
) -> int:
    """One request per candidate; save each reply; report its shape. 0 if every shape is right."""
    started = now()
    job_id = f"{started:%Y%m%dT%H%M%SZ}-{commit[0]}-memory-embed-probe"
    budget.reserve_within_budget(
        settings.runs_dir, job_id, PROBE_PROJECTED_USD, settings.monthly_budget_usd, now=started
    )
    lines = [f"embeddings shape probe at commit {commit[0]}, {started:%Y-%m-%d} (decision 0213)"]
    total, oks = 0.0, []
    fixtures: Path = args.fixtures
    fixtures.mkdir(parents=True, exist_ok=True)
    headers = {"Authorization": f"Bearer {settings.require_openrouter_key()}"}
    try:
        with _client(settings, transport) as http:
            for model in CANDIDATES:
                payload = {"model": model, "input": list(PROBE_TEXTS)}
                response = http.post(EMBEDDINGS_PATH, json=payload, headers=headers)
                (fixtures / f"{slug(model)}.json").write_bytes(response.content)
                try:
                    body: object = response.json()
                except ValueError:
                    body = None
                cost = (
                    _reply_cost(body, prices[model], PROBE_TEXTS)
                    if response.status_code == httpx.codes.OK
                    else 0.0
                )
                total += cost
                line, ok = _describe(model, response.status_code, body, cost)
                lines.append(line)
                oks.append(ok)
    finally:
        budget.write_spend(
            settings.runs_dir,
            budget.SpendRecord(
                job_id=job_id,
                kind="probe",
                model=",".join(CANDIDATES),
                started=started,
                calls=len(oks),
                cost_usd=total,
                commit_sha=commit[0],
                dirty=commit[1],
            ),
        )
        budget.settle(settings.runs_dir, job_id)
    passed = len(oks) == len(CANDIDATES) and all(oks)
    lines.append(
        "check every reply holds one vector per text, of one length: "
        f"{'ok' if passed else 'FAILED'}"
    )
    text = "\n".join(lines)
    print(text)
    if args.out is not None:
        write_result(PROG, args.out, text)
    return 0 if passed else 1


def _utc_now() -> datetime:
    return datetime.now(UTC)


def main(
    argv: Sequence[str] | None = None,
    *,
    settings: Settings | None = None,
    transport: httpx.BaseTransport | None = None,
    now: Clock = _utc_now,
) -> int:
    """Run one command. 0 on success; 1 on a refusal or a failed probe check."""
    parser = argparse.ArgumentParser(prog=PROG)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("models", help="save OpenRouter's embedding model list (free)")
    p = sub.add_parser("probe", help="the shape probe, ONCE (paid, cents)")
    p.add_argument("--fixtures", type=Path, default=FIXTURES)
    p.add_argument("--out", type=Path)
    args = parser.parse_args(argv)
    settings = settings or Settings()
    try:
        if args.command == "models":
            return models(settings, transport)
        commit = gitinfo.commit_state()
        require_clean(commit[1])
        refuse_without_registration()
        prices = load_prices(settings.data_dir)
        return probe(args, settings, transport=transport, commit=commit, now=now, prices=prices)
    except (ConfigurationError, BudgetError) as exc:
        print(f"refused: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
