#!/usr/bin/env bash
# Print the shell settings an `ntsb-live` command needs, for `eval "$(scripts/live_env.sh)"`.
#
# Status
#     Live tool (S3.3, decision 0158). The `s33-dry-run` and `s33-morning` recipes call it. It
#     reads the recorder stack's bucket name from AWS (one read-only CloudFormation call) and
#     spends nothing. It prints no key.
#
# What it prints: `export AWS_PROFILE=...` (default `ntsb`, an explicit value wins) and
# `export NTSB_STORE=...` (an explicit value wins; otherwise `s3://<BucketName>/recorder.sqlite`
# from the `NtsbRecorderStack` output). If the lookup fails or is empty (most likely the AWS login
# has expired) it prints a plain message on stderr and exits 1, and prints no export.
set -euo pipefail
set +x
profile="${AWS_PROFILE:-ntsb}"
echo "export AWS_PROFILE='$profile'"
if [[ -n "${NTSB_STORE:-}" ]]; then
  exit 0
fi
bucket="$(aws cloudformation describe-stacks --profile "$profile" --region eu-west-2 \
  --stack-name NtsbRecorderStack \
  --query "Stacks[0].Outputs[?OutputKey=='BucketName'].OutputValue" --output text 2>/dev/null)" || bucket=""
if [[ -z "$bucket" || "$bucket" == "None" ]]; then
  echo "live_env: could not read the recorder bucket name from AWS. The login has probably expired: run 'aws login --profile $profile' and try again. Or set NTSB_STORE yourself." >&2
  exit 1
fi
echo "export NTSB_STORE='s3://$bucket/recorder.sqlite'"
