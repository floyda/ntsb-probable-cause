#!/usr/bin/env bash
# Run one paid make target from a separate, clean checkout reset to the branch tip.
#
# Status
#     Live tool (S3.2, spec §14), used by S3.2's held-out runs and S3.3's live mornings. Andy
#     runs it in his own terminal, once per paid target. It spends money only through the make
#     target it is given; it spends nothing itself.
#
# Usage: NTSB_PAID_BRANCH=<branch> scripts/paid_run.sh <make-target> [VAR=value ...]
# The branch is required, with no default: a default outlives the stage it was written for, and
# the wrong branch's tip would run the wrong code and take the ledger row. Never main.
# Keys are read from `pass` here and never printed. A held-out target's ledger row is
# committed and pushed before the script ends, so the next held-out target can start.
set -euo pipefail
set +x
branch="${NTSB_PAID_BRANCH:?set NTSB_PAID_BRANCH to the branch whose tip runs (never main)}"
if [[ "$branch" == "main" ]]; then
  echo "refusing: NTSB_PAID_BRANCH is main; a paid run commits and pushes its ledger row to its branch, never to main." >&2
  exit 1
fi
checkout="${NTSB_PAID_CHECKOUT:-$HOME/Workspace/ntsb-demo-agent/ntsb-paid-runs}"
data_dir="${NTSB_DATA_DIR:-$HOME/Workspace/ntsb-demo-agent/ntsb-probable-cause/data}"
pass_entry="${NTSB_PASS_OPENROUTER:-api/openrouter}"
target="${1:?usage: scripts/paid_run.sh <make-target> [VAR=value ...]}"; shift
if [[ ! -d "$checkout/.git" ]]; then
  git clone --quiet git@github.com:floyda/ntsb-probable-cause.git "$checkout"
fi
cd "$checkout"
git fetch --quiet --prune origin
if git rev-parse --verify --quiet "refs/heads/$branch" >/dev/null; then
  unpushed="$(git rev-list --count "origin/$branch..$branch")"
  if [[ "$unpushed" != "0" ]]; then
    echo "refusing: local $branch holds $unpushed commit(s) not on origin/$branch (a ledger row committed but not pushed?). Push them from $checkout before the next run: the reset below would discard them." >&2
    exit 1
  fi
fi
if [[ -n "$(git status --porcelain)" ]]; then
  echo "refusing: $checkout has uncommitted changes (a ledger row not committed?). Commit (never discard) a ledger row, and push it, before the next run." >&2
  exit 1
fi
git checkout --quiet -B "$branch" "origin/$branch"
echo "checkout $checkout at $(git rev-parse --short HEAD) ($branch)"
uv sync --quiet --locked
export NTSB_DATA_DIR="$data_dir"
OPENROUTER_API_KEY="$(pass show "$pass_entry" | sed -n 1p)"
export OPENROUTER_API_KEY
# --locked refuses a lockfile that would change; UV_LOCKED=1 makes every nested uv run refuse
# the same way (decision 161).
export UV_LOCKED=1
make "$target" "$@"
if ! git diff --quiet -- docs/results/heldout-ledger.md; then
  git add docs/results/heldout-ledger.md
  git commit --quiet -m "Held-out ledger: $target"
  if ! git push --quiet origin "HEAD:$branch"; then
    echo "LEDGER ROW COMMITTED LOCALLY BUT NOT PUSHED: run 'git -C $checkout push origin HEAD:$branch' before the next run. The next run refuses until it is pushed." >&2
    exit 1
  fi
  echo "ledger row committed and pushed: $(git rev-parse --short HEAD)"
fi
