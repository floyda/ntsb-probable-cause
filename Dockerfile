# The recorder's container image (S2.5 Task 12, spec §9.2). Runs `ntsb-record run` on AWS
# Fargate every night (Task 13's EventBridge schedule); the recorder's own NTSB API key never
# appears here -- it is injected at container start, from Parameter Store on Fargate.
#
# Base image confirmed to exist by a manifest HEAD against ghcr.io before this was written
# (Task 12 report): `astral-sh/uv`'s own published image, Python 3.14 on Debian bookworm-slim,
# so `uv` is already on PATH and no separate Python install step is needed.
FROM ghcr.io/astral-sh/uv:python3.14-bookworm-slim

WORKDIR /app

# Dependencies first, in their own layer, so an app-code-only change does not re-resolve or
# re-download anything: `--no-install-project` installs everything `uv.lock` pins except this
# package itself, which has no source to install yet.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --extra aws --no-install-project

# `hatchling` (pyproject.toml's build backend) needs `README.md` (its `readme` field) and
# `LICENSE` (its `license` field) present to build the project's own wheel in the next
# `uv sync`; a build that copies only `src` and `apps` fails on a missing `readme`.
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
# `NTSB_DATA_DIR` is created and handed to that user before the switch, so the docket cache and
# any local store file it writes at runtime land somewhere it can write.
RUN useradd --create-home --shell /usr/sbin/nologin recorder \
    && mkdir -p /tmp/ntsb \
    && chown -R recorder:recorder /app /tmp/ntsb
USER recorder

ENTRYPOINT ["uv", "run", "--no-sync", "ntsb-record"]
CMD ["run"]
