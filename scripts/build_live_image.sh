#!/usr/bin/env bash
# Build the live image from a clean commit, push it as `live-<sha>`, and print its digest.
#
# Status
#     Live tool (S4 Task 12, decision 0171). Andy runs it before `cdk deploy`; the printed digest
#     is the CDK context `live_image_digest`. It refuses a tree with uncommitted changes, builds
#     for linux/amd64 with COMMIT_SHA baked in, never tags `latest`, and prints no key. It needs
#     the `ntsb` AWS profile and a docker login to ECR (see docs/runbooks/live-cloud-nights.md).
set -euo pipefail
set +x
if [[ -n "$(git status --porcelain)" ]]; then
  echo "build_live_image: the tree has uncommitted changes; commit them first." >&2
  exit 1
fi
sha="$(git rev-parse --short HEAD)"
repo="$(aws cloudformation describe-stacks --profile "${AWS_PROFILE:-ntsb}" --region eu-west-2 \
  --stack-name NtsbLiveStack \
  --query "Stacks[0].Outputs[?OutputKey=='RepositoryUri'].OutputValue" --output text)"
if [[ -z "$repo" || "$repo" == "None" ]]; then
  echo "build_live_image: could not read RepositoryUri from NtsbLiveStack." >&2
  exit 1
fi
meta="$(mktemp)"
trap 'rm -f "$meta"' EXIT
docker buildx build --platform linux/amd64 --build-arg COMMIT_SHA="$sha" \
  -t "$repo:live-$sha" --metadata-file "$meta" --push . >&2
sed -n 's/.*"containerimage.digest": *"\(sha256:[0-9a-f]*\)".*/\1/p' "$meta" | head -n 1
