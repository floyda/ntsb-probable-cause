# The recorder's container image (S2.5 Task 12, spec §9.2). Runs `ntsb-record run` on AWS
# Fargate every night (Task 13's EventBridge schedule); the recorder's own NTSB API key never
# appears here -- it is injected at container start, from Parameter Store on Fargate.
#
# Pinned by digest, not just the tag (fix round 1, Minor 7): the tag's manifest can move; the
# digest cannot. Confirmed live before use, and again independently at fix round 1 (Task 12
# report): an anonymous ghcr.io pull token, then a manifest HEAD/GET against
# `ghcr.io/v2/astral-sh/uv/manifests/python3.14-bookworm-slim`, returning this exact
# `docker-content-digest`. `.github/dependabot.yml`'s new `docker` entry keeps it current --
# `astral-sh/uv`'s own published image, Python 3.14 on Debian bookworm-slim, so `uv` is
# already on PATH and no separate Python install step is needed.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim@sha256:7cf77f594be8042dab6daa9fe326f90962252268b4f120a7f5dccce4d947e6c1

WORKDIR /app

# Compile to bytecode at build time (fix round 1, Minor 1), not on every container start --
# this is the recorder's *hot* path: it runs once a night from a fresh container, so a
# start-time compile is pure repeated cost with no cache to amortize it against.
ENV UV_COMPILE_BYTECODE=1

# Dependencies first, in their own layer, so an app-code-only change does not re-resolve or
# re-download anything: `--no-install-project` installs everything `uv.lock` pins except this
# package itself, which has no source to install yet.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra aws --no-install-project

# `hatchling` (pyproject.toml's build backend) needs `README.md` present for its `readme`
# field; `LICENSE` is copied alongside it for completeness (an SPDX `license = "MIT"`, as this
# project uses, does not itself require the file on disk) -- a build that copies only `src`
# and `apps` fails on the missing `readme`.
COPY README.md LICENSE ./
COPY src ./src
COPY apps ./apps
RUN uv sync --locked --no-dev --extra aws

# `ARG COMMIT_SHA` has no default: with no `--build-arg`, it is an empty string, and the `ENV`
# below carries that empty string into `NTSB_COMMIT_SHA`. `Settings.commit_sha`
# (src/ntsb_probable_cause/settings.py) treats an empty `NTSB_COMMIT_SHA` as unset, so an image
# built without the build arg never pretends to have a commit -- `ntsb-record run` refuses to
# guess one (controller note 2). CI (`.github/workflows/ci.yml`, job `image-push`) always passes the
# short 7-character SHA of `GITHUB_SHA`, matching the short SHA `gitinfo.commit_state()` records
# for every other entrypoint.
ARG COMMIT_SHA
ENV NTSB_COMMIT_SHA=${COMMIT_SHA}
ENV NTSB_DATA_DIR=/tmp/ntsb

# Non-root: Fargate does not require root, and there is no reason for this process to have it.
# Only `NTSB_DATA_DIR` (where the docket cache and any local store file are written at
# runtime) is `chown`ed to that user -- NOT `/app` (fix round 1, Minor 1): a recursive chown of
# `/app` duplicates the whole venv (hundreds of MB) into a new image layer on every build, and
# it would make this process's own installed code writable by the user running it, which it
# has no reason to be. `/app` stays owned by root and world-readable, which `uv sync`'s default
# permissions already leave it.
RUN useradd --create-home --shell /usr/sbin/nologin recorder \
    && mkdir -p /tmp/ntsb \
    && chown recorder:recorder /tmp/ntsb
USER recorder

# The venv's own `ntsb-record` script on `PATH`, not `uv run` (fix round 1, Minor 2): `uv run`
# would re-resolve the project against `pyproject.toml`/`uv.lock` on every container start (or
# require `--no-sync`, which still needs `uv`'s own cache and a writable `HOME` to check
# against), for no benefit once the image already has the exact environment `uv sync` built
# baked into `/app/.venv`. This also means the running process depends on nothing but that venv
# -- no `uv` binary, no `uv` cache, no `HOME` -- at runtime.
ENV PATH=/app/.venv/bin:$PATH
ENTRYPOINT ["ntsb-record"]
CMD ["run"]
