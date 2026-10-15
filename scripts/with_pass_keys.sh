#!/usr/bin/env bash
# Run one command with the coding memory's two keys from `pass`, printing neither (0202, 0207).
# Usage: scripts/with_pass_keys.sh <command> [args...]
set -euo pipefail
OPENROUTER_API_KEY="$(pass show "${NTSB_PASS_OPENROUTER:-api/openrouter}" | sed -n 1p)"
ANTHROPIC_API_KEY="$(pass show "${NTSB_PASS_ANTHROPIC:-api/anthropic}" | sed -n 1p)"
export OPENROUTER_API_KEY ANTHROPIC_API_KEY
exec "$@"
