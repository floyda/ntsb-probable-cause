# 0011 — Tooling: uv on hatchling, Python 3.14, strict static analysis from the first commit

## Context

S0 creates the repository's first code. The spike had no tests, no linter and no lockfile,
and installed with `pip install -e .` on setuptools. This repository makes a stronger claim:
the agent that is evaluated is the agent that is deployed, and a stranger can check its
numbers. Andy is familiar with hatchling. Detail:
`docs/specs/2026-09-13-s0-foundation-design.md` §4.

## Decision

- **hatchling** as the build backend; **uv** as the project manager, with `uv.lock` committed.
- **Python pinned to 3.14.**
- **The library package is `ntsb_probable_cause`**, matching the distribution name. 0002's
  `src/ntsb_pc/` is renamed; its structure is unchanged. "pc" reads as "personal computer" to
  a reader outside the project.
- **Static analysis:** ruff (lint and format, wide rule set), mypy `--strict` with the
  pydantic plugin, import-linter, deptry, pip-audit, vulture.
- **Pre-commit** runs the same checks locally, plus gitleaks, check-added-large-files,
  file hygiene hooks, no-commit-to-branch on `main`, typos, actionlint, zizmor,
  `uv lock --check`, and local hooks that reject `data/` paths and unredacted fixtures.
- **Tests:** pytest, pytest-cov (branch coverage, 90% on the library), hypothesis,
  pytest-socket, respx. HTTP goes through httpx.
- Continuous integration runs lint, test and audit on every push.

## Why

1. **A lockfile makes the evaluated and deployed environments identical.** The laptop,
   continuous integration and the container install the same versions. Without it, "same
   code" does not mean "same behaviour".
2. **Strictness is cheapest at the start.** Turning on `--strict` or a wide ruff rule set
   later means fixing the whole codebase at once, which in practice means it never happens.
3. **import-linter turns an architecture rule into a check.** The evidence / synthesis /
   verdict boundary (0013, 0016) and the library-with-thin-apps rule (0002) are enforced
   by continuous integration rather than by review.
4. **Hooks enforce project rules directly.** check-added-large-files and the `data/` hook
   enforce "raw data never in git"; gitleaks is there because the repository is public and
   two API keys live in the environment.

## What this rules out

- **Hatch as the project manager.** Familiar, and its environments live in
  `pyproject.toml`. It has no built-in committed lockfile that we know of, and it is slower
  in continuous integration. hatchling is kept either way.
- **pip, venv and setuptools, as in the spike.** Simplest and universal. Locking would need
  pip-tools or constraints files maintained by hand.
- **A second type checker (pyright).** It catches some things mypy does not. Two checkers
  that disagree cost more time than they save on a codebase this size. This is a judgement.
- **Adding tooling later, "when needed".** A check that is not enforced from the start is
  indistinguishable from no check (roadmap §9).

## Status

Accepted, 2026-09-13.
