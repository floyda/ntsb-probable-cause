#!/usr/bin/env bash
# Print the shell settings an `ntsb-live` command needs, for `eval "$(scripts/live_env.sh)"`.
#
# Status
#     Live tool (S3.3, decision 0158; S4 Task 14, decision 0171). The `s4-*` and `s33-report`
#     recipes call it. It reads two bucket names from AWS (read-only CloudFormation calls) and
#     spends nothing. It prints no key.
#
# What it prints: `export AWS_PROFILE=...` (default `ntsb`, an explicit value wins);
# `export NTSB_STORE=...` (an explicit value wins; otherwise `s3://<BucketName>/recorder.sqlite`
# from the `NtsbRecorderStack` output); and, when the stack exists, `export NTSB_LIVE_BUCKET=...`
# (an explicit value wins; otherwise `LiveBucketName` from the `NtsbLiveStack` output). A missing
# live stack prints no live line and is not an error. If the recorder lookup fails or is empty
# (most likely `pass` is locked or the profile is missing) it prints a plain message and then
# aws's own error on stderr, exits 1, and prints no export at all (decision 0166).
set -euo pipefail
set +x
profile="${AWS_PROFILE:-ntsb}"
store_line=""
live_line=""
err_file="$(mktemp)"
trap 'rm -f "$err_file"' EXIT
if [[ -z "${NTSB_STORE:-}" ]]; then
  bucket="$(aws cloudformation describe-stacks --profile "$profile" --region eu-west-2 \
    --stack-name NtsbRecorderStack \
    --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text 2>"$err_file")" || bucket=""
  if [[ -z "$bucket" || "$bucket" == "None" ]]; then
    echo "live_env: the $profile profile could not read the stack that holds the recorder bucket name. Check that your AWS login is current (aws login) and that the profile exists (see docs/runbooks/live-cloud-nights.md). Or set NTSB_STORE yourself." >&2
    echo "live_env: aws said:" >&2
    cat "$err_file" >&2  # aws's own error carries no secret; it tells a login problem from another
    exit 1
  fi
  store_line="$(printf 'export NTSB_STORE=%q\n' "s3://$bucket/recorder.sqlite")"
fi
if [[ -z "${NTSB_LIVE_BUCKET:-}" ]]; then
  # Optional: before the first deploy the stack does not exist, and that is fine.
  live="$(aws cloudformation describe-stacks --profile "$profile" --region eu-west-2 \
    --stack-name NtsbLiveStack \
    --query "Stacks[0].Outputs[?OutputKey=='LiveBucketName'].OutputValue" --output text 2>/dev/null)" || live=""
  if [[ -n "$live" && "$live" != "None" ]]; then
    live_line="$(printf 'export NTSB_LIVE_BUCKET=%q\n' "$live")"
  fi
fi
# Every line only after the lookups, quoted for `eval` whatever the names hold.
printf 'export AWS_PROFILE=%q\n' "$profile"
[[ -z "$store_line" ]] || printf '%s\n' "$store_line"
[[ -z "$live_line" ]] || printf '%s\n' "$live_line"
