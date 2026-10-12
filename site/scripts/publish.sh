#!/usr/bin/env bash
# Publishes the site to its bucket and clears CloudFront's copies (S5 spec §18.1, §19.1).
# Run by CodeBuild from the repository root. Step 1 has one mode, `holding`, which publishes
# site/holding/ only: launch is Andy's decision (spec §20), and a later plan adds the site
# mode behind a switch only his deploy can turn.
set -euo pipefail

: "${SITE_BUCKET:?SITE_BUCKET is not set}"
: "${DISTRIBUTION_ID:?DISTRIBUTION_ID is not set}"

case "${SITE_MODE:-}" in
  holding) out="site/holding" ;;
  *)
    echo "publish.sh: mode '${SITE_MODE:-}' is not allowed in step 1; only 'holding'" >&2
    exit 2
    ;;
esac

target="s3://${SITE_BUCKET}"
# 1. Hashed assets first. Their names change with their content, so a year's caching is safe.
aws s3 sync "$out" "$target" --exclude "*" --include "_astro/*" \
  --cache-control "public, max-age=31536000, immutable"
# 2. Other files, cached briefly.
aws s3 sync "$out" "$target" --exclude "_astro/*" --exclude "*.html" \
  --cache-control "public, max-age=300"
# 3. Then the pages, which a browser must check again each time, so a new board shows at once.
aws s3 sync "$out" "$target" --exclude "*" --include "*.html" --cache-control "no-cache"
# 4. Clear CloudFront's copies ("/*" counts as one path) and wait until every edge has.
invalidation=$(aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" \
  --paths "/*" --query Invalidation.Id --output text)
aws cloudfront wait invalidation-completed --distribution-id "$DISTRIBUTION_ID" --id "$invalidation"
# 5. Only then remove files no longer used, and never the hashed assets: an old page still held
#    by a browser may name them (review, 2026-10-12).
aws s3 sync "$out" "$target" --delete --exclude "_astro/*"
