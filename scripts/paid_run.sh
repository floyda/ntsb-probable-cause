#!/usr/bin/env bash
# Run one paid make target from a separate, clean checkout reset to the branch tip.
#
# Status
#     Live tool (S3.2, spec §14). The S3.2 paid-run wrapper: Andy runs it in his own terminal,
#     once per paid s32 target. It spends money only through the make
#     target it is given; it spends nothing itself.
#
# Usage: scripts/paid_run.sh <make-target> [VAR=value ...]
# Keys are read from `pass` here and never printed. A held-out target's ledger row is
# committed and pushed before the script ends, so the next held-out target can start.
set -euo pipefail
set +x
branch="${NTSB_PAID_BRANCH:-s3-2-claims}"
checkout="${NTSB_PAID_CHECKOUT:-$HOME/Workspace/ntsb-demo-agent/ntsb-paid-runs}"
data_dir="${NTSB_DATA_DIR:-$HOME/Workspace/ntsb-demo-agent/ntsb-probable-cause/data}"
pass_entry="${NTSB_PASS_OPENROUTER:-api/openrouter}"
target="${1:?usage: scripts/paid_run.sh <make-target> [VAR=value ...]}"; shift
if [[ ! -d "$checkout/.git" ]]; then
  git clone --quiet git@github.com:floyda/ntsb-probable-cause.git "$checkout"
fi
cd "$checkout"
git fetch --quiet origin
if [[ -n "$(git status --porcelain)" ]]; then
  echo "refusing: $checkout has uncommitted changes (a ledger row not pushed?). Commit or discard them first." >&2
  exit 1
fi
git checkout --quiet -B "$branch" "origin/$branch"
echo "checkout $checkout at $(git rev-parse --short HEAD) ($branch)"
uv sync --quiet --frozen
export NTSB_DATA_DIR="$data_dir"
OPENROUTER_API_KEY="$(pass show "$pass_entry" | head -n 1)"
export OPENROUTER_API_KEY
make "$target" "$@"
if ! git diff --quiet -- docs/results/heldout-ledger.md; then
  git add docs/results/heldout-ledger.md
  git commit --quiet -m "Held-out ledger: $target"
  git push --quiet origin "HEAD:$branch"
  echo "ledger row committed and pushed: $(git rev-parse --short HEAD)"
fi
