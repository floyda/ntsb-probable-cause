#!/usr/bin/env bash
# Print the shell settings an `ntsb-live` command needs, for `eval "$(scripts/live_env.sh)"`.
#
# Status
#     Live tool (S3.3, decision 0158). The `s33-dry-run` and `s33-morning` recipes call it. It
#     reads the recorder stack's bucket name from AWS (one read-only CloudFormation call) and
#     spends nothing. It prints no key.
#
# What it prints: `export AWS_PROFILE=...` (default `ntsb-live`, an explicit value wins) and
# `export NTSB_STORE=...` (an explicit value wins; otherwise `s3://<BucketName>/recorder.sqlite`
# from the `NtsbRecorderStack` output). If the lookup fails or is empty (most likely `pass` is locked or
# the profile is missing) it prints a plain message and then aws's own error on stderr, exits 1, and prints
# no export.
set -euo pipefail
set +x
profile="${AWS_PROFILE:-ntsb-live}"
echo "export AWS_PROFILE='$profile'"
if [[ -n "${NTSB_STORE:-}" ]]; then
  exit 0
fi
err_file="$(mktemp)"
trap 'rm -f "$err_file"' EXIT
bucket="$(aws cloudformation describe-stacks --profile "$profile" --region eu-west-2 \
  --stack-name NtsbRecorderStack \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text 2>"$err_file")" || bucket=""
if [[ -z "$bucket" || "$bucket" == "None" ]]; then
  echo "live_env: the $profile profile could not read the stack that holds the recorder bucket name. Check that pass is unlocked and that the profile exists (see docs/runbooks/live-shadow-mornings.md, 'The live shadow's AWS key'). Or set NTSB_STORE yourself." >&2
  echo "live_env: aws said:" >&2
  cat "$err_file" >&2  # aws's own error carries no secret; it tells a login problem from another
  exit 1
fi
echo "export NTSB_STORE='s3://$bucket/recorder.sqlite'"
