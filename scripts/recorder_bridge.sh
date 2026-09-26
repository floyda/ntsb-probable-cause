#!/bin/bash
# Runs one nightly recorder pass on Andy's Mac -- the "bridge" (spec S2.5 §9.3) that stands in
# for the AWS stack until it is deployed. Invoked by launchd; see
# docs/runbooks/recorder-bridge.md for how it is installed, checked and eventually retired.
#
# Status
#     Live tool (S2.5, Task 10). Runs nightly at 03:00 local time via
#     ~/Library/LaunchAgents/dev.floyda.ntsb-record.plist. Produces nothing itself -- it wraps
#     `uv run ntsb-record run`, whose own output is data/recorder.sqlite and its `runs` row
#     (store/db.py). This script's only job is getting the API key and the data directory
#     right, and leaving a trace in the log whichever way the night ends.
#
#     Fix round 1, Important 1: an `if (subshell); then ...; fi` with no `else` taken always
#     returns exit status 0 for the *compound statement itself* when the condition is false --
#     that is standard POSIX shell behaviour, not a bug in bash, but it means a `status=$?`
#     placed AFTER such an `if` never sees the subshell's real exit code. The run itself is now
#     executed as its own statement, with `status=$?` captured on the very next line, before
#     anything else can overwrite `$?` -- see the `run start`/`status=$?` block below.
#
# Usage:
#     scripts/recorder_bridge.sh <code-dir> [extra ntsb-record run arguments]
#
# <code-dir> is the checkout to run the recorder's code FROM -- the s25-recorder worktree
# until this stage merges, then the main checkout (the runbook names the exact path each
# time). The STORE and the LOG always live in the MAIN checkout's data/ directory, never the
# worktree's: NTSB_DATA_DIR below is a fixed absolute path for that reason, regardless of
# <code-dir>. Extra arguments (e.g. --dry-run, --verbose) are forwarded to `ntsb-record run`,
# for testing this script by hand -- launchd itself passes none.
#
# Two environment variables exist ONLY so tests/test_recorder_bridge_script.py can exercise
# this script quickly and in an isolated directory, never against the real `pass` or the real
# data directory (fix round 1, Important 1's test requirement). Neither is set by launchd, and
# neither weakens the production default -- both fall back to the real value when unset:
#   NTSB_BRIDGE_DATA_DIR   overrides the main checkout's data/ directory (default: the fixed
#                          absolute path below).
#   NTSB_BRIDGE_KEY_TIMEOUT overrides the `pass show` alarm, in seconds (default: 60).
#   NTSB_BRIDGE_RUN_TIMEOUT overrides the overall run's wall-clock alarm, in seconds
#                          (default: 5400 -- 90 minutes, the same ceiling the AWS Fargate task
#                          is given, spec §9.2, so a hung night can never run into the next
#                          one; fix round 1, Minor 4).
set -uo pipefail

if [ "$#" -lt 1 ]; then
    echo "usage: scripts/recorder_bridge.sh <code-dir> [extra ntsb-record run arguments]" >&2
    exit 2
fi
CODE_DIR="$1"
shift

# Never the worktree, never relative to wherever this script happens to run from -- a relative
# NTSB_DATA_DIR once resolved inside a worktree during development and nearly discarded 19 GB
# of already-fetched docket documents when the worktree was later removed (settings.py carries
# the same lesson for NTSB_DOCKET_DIR).
MAIN_DATA_DIR="${NTSB_BRIDGE_DATA_DIR:-/Users/floyda/Workspace/ntsb-demo-agent/ntsb-probable-cause/data}"
KEY_TIMEOUT="${NTSB_BRIDGE_KEY_TIMEOUT:-60}"
RUN_TIMEOUT="${NTSB_BRIDGE_RUN_TIMEOUT:-5400}"
LOG="$MAIN_DATA_DIR/recorder.log"
mkdir -p "$MAIN_DATA_DIR"

log() {
    printf '%s %s\n' "$(date -u '+%Y-%m-%dT%H:%M:%SZ')" "$1" >>"$LOG"
}

# `pass show` decrypts with GPG, which can pop a pinentry dialog and wait forever if the
# passphrase is not already cached in the GPG agent (docs/runbooks/recorder-bridge.md explains
# the trade-off; it is Andy's choice, not fixed here). 60 seconds is generous for a cached
# passphrase and short enough that one stuck night never blocks the next one. macOS has no
# `timeout(1)`; `perl -e 'alarm shift; exec @ARGV' N cmd...` is the portable substitute.
raw_key="$(perl -e 'alarm shift; exec @ARGV' "$KEY_TIMEOUT" pass show api/ntsb 2>/dev/null)"
pass_status=$?
if [ "$pass_status" -ne 0 ] || [ -z "$raw_key" ]; then
    log "NTSB key unavailable"
    exit 1
fi
# `pass` entries may carry extra lines after the secret itself; only the first is the key, and
# it is never echoed or logged anywhere, by this script or by ntsb-record (settings.py).
NTSB_API_KEY="${raw_key%%$'\n'*}"
export NTSB_API_KEY
export NTSB_DATA_DIR="$MAIN_DATA_DIR"

log "run start"
# The run itself, as its OWN statement -- not the condition of an `if` -- so `status=$?` on the
# very next line reliably captures its real exit code (see the Important 1 note above). Wrapped
# in its own wall-clock alarm (fix round 1, Minor 4): a hung night is killed by SIGALRM (exit
# 142) rather than running past the next scheduled 03:00 and blocking it -- launchd will not
# start a second instance of this job while one is still running.
(cd "$CODE_DIR" && perl -e 'alarm shift; exec @ARGV' "$RUN_TIMEOUT" uv run ntsb-record run "$@" >>"$LOG" 2>&1)
status=$?
if [ "$status" -eq 0 ]; then
    log "run done"
    exit 0
fi
if [ "$status" -eq 142 ]; then
    log "run exceeded the ${RUN_TIMEOUT}s wall-clock limit and was stopped"
fi
log "run failed exit=$status"
exit "$status"
