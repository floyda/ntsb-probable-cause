"""The per-literal mutation sweep of the rendered-text fingerprint (S3.3 final review, A1).

Status
    Live tooling (decisions 0143 and 0161). Free and local: no model, no network, no secret. It
    reads the package source and writes nothing in the repository; every mutation is made in a
    fresh copy of ``src`` under a temporary folder, run with ``PYTHONDONTWRITEBYTECODE=1``.

What it checks
    The reach test (``tests/test_agent_rendered.py``) shows that a scenario sends each model-text
    literal's words. It does not show that the fingerprint depends on them: a literal can appear
    in a request by coincidence while the text that really reaches the model comes from elsewhere
    (the sweep found a one-page header, a partly readable header, the amateur-built label and
    others). This sweep edits every string literal of the covered modules, one at a time, and
    recomputes the fingerprint. A literal whose edit leaves the fingerprint unchanged and that is
    not named in ``tests/fixtures/rendered/not_model_text.toml`` (not model text, or model text no
    scenario can reach, each with a reason) is a gap: it prints and the exit status is 1. An edit
    that stops the package importing counts as moving the fingerprint (the literal is load-bearing
    for the program, if not for the model) and is only counted.

    A list entry names a value, so it also covers an equal value elsewhere in the module. One whose
    edit moves the fingerprint is counted as a warning (it may be a key the code branches on, or
    equal to a real text at another site, or carry a wrong reason); ``--verbose`` lists them. A
    warning does not change the exit status. The
    list has a third table, ``[selects]``: paths and patterns that choose what the model reads. No
    request holds the literal, so the reach test cannot find it, and the sweep must show that its
    edit moves the fingerprint; one that does not is ``MISFILED`` and fails the sweep.

Usage
    make s33-mutation-sweep
    uv run --locked python -m scripts.s33_mutation_sweep [--workers N]
"""

import argparse
import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from collections import Counter
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import ntsb_probable_cause
from ntsb_probable_cause.agent import texts

PACKAGE_ROOT: Final = Path(ntsb_probable_cause.__file__).resolve().parent
SRC_ROOT: Final = PACKAGE_ROOT.parent
NOT_MODEL_TEXT: Final = (
    Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "rendered" / "not_model_text.toml"
)
# Modules outside ``texts.TEXT_SOURCES`` whose literals may still reach a request: the evidence
# field labels and their paths, a document's header and its redaction labels, the page marker and
# the listing's lines.
EXTRA_MODULES: Final = (
    "agent/documents.py",
    "fields.py",
    "docket/attach.py",
    "docket/extract.py",
    "docket/listing.py",
)
MIN_PART: Final = 6  # an f-string's or a template's literal part counts from this many characters
MARK: Final = "·".encode()
_PRINT: Final = (
    "from ntsb_probable_cause.agent.rendered import rendered_sha256; print(rendered_sha256())"
)
_TIMEOUT_SECONDS: Final = 180


def covered() -> list[tuple[str, Path, str | None]]:
    """(module, file, only-class) of every module whose literals may be model text."""
    entries: list[tuple[str, Path, str | None]] = []
    for package, name in texts.TEXT_SOURCES:
        relative = "/".join([*package.split(".")[1:], name])
        entries.append((relative, PACKAGE_ROOT / relative, None))
    for relative in EXTRA_MODULES:
        entries.append((relative, PACKAGE_ROOT / relative, None))
    # The request-building ``Payload`` class holds the evidence payload's own wording.
    entries.append(("model/client.py", PACKAGE_ROOT / "model" / "client.py", "Payload"))
    return entries


def tables() -> dict[str, dict[str, str]]:
    """The list's four tables by name.

    ``plain`` (the top level) and ``unreachable`` hold literals no request holds, which the
    reach test checks stay absent; ``coincident`` holds literals whose words also occur in
    requests by chance; ``selects`` holds paths and patterns that choose what the model reads.
    """
    data = tomllib.loads(NOT_MODEL_TEXT.read_text(encoding="utf-8"))
    found = {name: data.pop(name) for name in ("unreachable", "coincident", "selects")}
    return {"plain": data, **found}


def listed() -> dict[str, str]:
    """Every listed literal with its reason, from all four tables."""
    return {key: reason for table in tables().values() for key, reason in table.items()}


def selecting() -> dict[str, str]:
    """The ``[selects]`` table: literals no request holds, whose edit the sweep must show moves it.

    A path or a pattern that picks what the model reads (a record field, a name to redact) is not
    text the reach test can find in a request, yet editing it changes the request. The sweep, not
    the reach test, proves it.
    """
    return tables()["selects"]


def _docstring_nodes(tree: ast.AST) -> set[int]:
    found: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Module | ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
            body = node.body
            if (
                body
                and isinstance(body[0], ast.Expr)
                and isinstance(body[0].value, ast.Constant)
                and isinstance(body[0].value.value, str)
            ):
                found.add(id(body[0].value))
    return found


def parts(value: str) -> Iterator[str]:
    """A literal's checkable parts: itself, or its text between ``{...}`` fields."""
    if re.search(r"\{[^{}]*\}", value):
        for part in re.split(r"\{[^{}]*\}", value):
            if len(part) >= MIN_PART:
                yield part
    else:
        yield value


def literals(path: Path, only_class: str | None = None) -> list[str]:
    """Every string literal of a module that is not a docstring (an f-string's: by part)."""
    tree: ast.AST = ast.parse(path.read_text(encoding="utf-8"))
    if only_class is not None:
        tree = next(
            n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == only_class
        )
    docstrings = _docstring_nodes(tree)
    in_fstring = {id(c) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for c in n.values}
    found: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings:
            continue
        if id(node) in in_fstring:
            if len(node.value) >= MIN_PART:
                found.append(node.value)
        else:
            found.extend(parts(node.value))
    return found


@dataclass(frozen=True)
class Site:
    """One string literal in a covered module: where its closing quote is, and its value."""

    module: str
    line: int
    value: str
    position: int  # byte offset in the file at which the mark is inserted


def _closing_quote(segment: bytes) -> int | None:
    for quote in (b'"""', b"'''", b'"', b"'"):
        if segment.endswith(quote):
            return len(quote)
    return None


def sites(module: str, path: Path, only_class: str | None) -> list[Site]:
    """Every literal of ``module`` that is not a docstring, with the offset to edit it at."""
    data = path.read_bytes()
    tree: ast.AST = ast.parse(data)
    if only_class is not None:
        tree = next(
            n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == only_class
        )
    docstrings = _docstring_nodes(tree)
    starts = [0]
    for line in data.split(b"\n"):
        starts.append(starts[-1] + len(line) + 1)
    in_fstring = {id(c) for n in ast.walk(tree) if isinstance(n, ast.JoinedStr) for c in n.values}
    found: list[Site] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        if id(node) in docstrings or node.end_lineno is None or node.end_col_offset is None:
            continue
        start = starts[node.lineno - 1] + node.col_offset
        end = starts[node.end_lineno - 1] + node.end_col_offset
        if id(node) in in_fstring:
            position = end
        else:
            quote = _closing_quote(data[start:end])
            if quote is None:
                continue
            position = end - quote
        found.append(Site(module, node.lineno, node.value, position))
    return sorted(found, key=lambda s: (s.module, s.line, s.position))


def present_keys() -> set[str]:
    """Every ``module:literal`` key a list entry may name: the reach test's and the sweep's."""
    keys: set[str] = set()
    for module, path, only_class in covered():
        keys.update(f"{module}:{literal}" for literal in literals(path, only_class))
        keys.update(f"{module}:{site.value}" for site in sites(module, path, only_class))
    return keys


def is_listed(site: Site, names: dict[str, str]) -> bool:
    """Whether the literal, or any of its checkable parts, is on the list."""
    if f"{site.module}:{site.value}" in names:
        return True
    return any(f"{site.module}:{part}" in names for part in parts(site.value))


def _hash_in(source: Path) -> str:
    """The fingerprint (or an ``ERROR:`` line) a fresh interpreter computes over ``source``."""
    result = subprocess.run(  # noqa: S603 -- our own interpreter and a fixed program
        [sys.executable, "-c", _PRINT],
        env={"PYTHONPATH": str(source), "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
        capture_output=True,
        text=True,
        check=False,
        timeout=_TIMEOUT_SECONDS,
    )
    if result.returncode == 0:
        return result.stdout.strip()
    tail = result.stderr.strip().splitlines() or ["?"]
    return "ERROR:" + tail[-1][:200]


def _copy_src(destination: Path) -> None:
    shutil.copytree(SRC_ROOT, destination, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


def _mutate(worker: Path, site: Site) -> str:
    """The fingerprint with ``site`` edited in the worker's copy; the copy is restored after."""
    target = worker / "ntsb_probable_cause" / site.module
    original = (PACKAGE_ROOT / site.module).read_bytes()
    target.write_bytes(original[: site.position] + MARK + original[site.position :])
    try:
        return _hash_in(worker)
    finally:
        target.write_bytes(original)


def sweep(all_sites: Sequence[Site], workers: int) -> tuple[str, list[tuple[Site, str]]]:
    """The baseline fingerprint and every site's result (a hash or an ``ERROR:`` line)."""
    baseline = _hash_in(SRC_ROOT)
    if baseline.startswith("ERROR:"):
        raise RuntimeError(f"the baseline fingerprint did not compute: {baseline}")
    with tempfile.TemporaryDirectory(prefix="s33sweep-") as scratch:
        folders = [Path(scratch) / f"w{n}" for n in range(workers)]
        for folder in folders:
            _copy_src(folder)

        def work(index: int) -> list[tuple[Site, str]]:
            return [(site, _mutate(folders[index], site)) for site in all_sites[index::workers]]

        with ThreadPoolExecutor(workers) as pool:
            results = [pair for chunk in pool.map(work, range(workers)) for pair in chunk]
    return baseline, sorted(results, key=lambda r: (r[0].module, r[0].line, r[0].position))


def report(baseline: str, results: Sequence[tuple[Site, str]], *, verbose: bool = False) -> int:
    """Print the sweep's findings; return the exit status (1 when a literal is a gap)."""
    names = listed()
    selects = selecting()
    counts: Counter[str] = Counter()
    gaps: list[Site] = []
    stale: list[Site] = []
    misfiled: list[Site] = []
    for site, result in results:
        if result.startswith("ERROR:"):
            counts["breaks the import"] += 1
        elif result != baseline:
            counts["moves the fingerprint"] += 1
            if is_listed(site, names) and not is_listed(site, selects):
                stale.append(site)
        else:
            counts["leaves it unchanged"] += 1
            if not is_listed(site, names):
                gaps.append(site)
            elif is_listed(site, selects):
                misfiled.append(site)
    sys.stdout.write(f"{len(results)} literals in {len({s.module for s, _ in results})} modules\n")
    for outcome in ("moves the fingerprint", "breaks the import", "leaves it unchanged"):
        sys.stdout.write(f"  {counts[outcome]:5d} {outcome}\n")
    sys.stdout.write(f"  {len(gaps):5d} unchanged and not on the list (gaps)\n")
    sys.stdout.write(f"  {len(misfiled):5d} on [selects] yet unchanged (misfiled)\n")
    sys.stdout.write(
        f"  {len(stale):5d} on the list, yet moving it moves the fingerprint (a key the code "
        "branches on, or the same value as a real text elsewhere in the module"
        + ("" if verbose else "; --verbose lists them")
        + ")\n"
    )
    for site in stale if verbose else ():
        sys.stdout.write(f"  moves: {site.module}:{site.line} {site.value!r}\n")
    for site in misfiled:
        sys.stdout.write(f"MISFILED {site.module}:{site.line} {site.value!r}\n")
    for site in gaps:
        sys.stdout.write(f"GAP {site.module}:{site.line} {site.value!r}\n")
    if gaps:
        sys.stdout.write(
            "Each gap is model text the fingerprint does not follow: extend "
            "agent/rendered.py so a scenario sends it, or list it in "
            "tests/fixtures/rendered/not_model_text.toml with its reason.\n"
        )
    return 1 if gaps or misfiled else 0


def main(argv: Sequence[str] | None = None) -> int:
    """Run the sweep over every covered module; return the exit status."""
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n", maxsplit=1)[0])
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 1))
    parser.add_argument("--verbose", action="store_true", help="list the warnings too")
    args = parser.parse_args(argv)
    all_sites = [s for module, path, only in covered() for s in sites(module, path, only)]
    baseline, results = sweep(all_sites, args.workers)
    return report(baseline, results, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
