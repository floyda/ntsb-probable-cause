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
# Styles, scripts and images first, so no page is ever served before the files it names.
aws s3 sync "$out" "$target" --exclude "*.html"
# Then the pages.
aws s3 sync "$out" "$target" --exclude "*" --include "*.html"
# Then remove what is no longer used.
aws s3 sync "$out" "$target" --delete
# Then clear CloudFront's copies: one path, "/*", counts as one invalidation.
aws cloudfront create-invalidation --distribution-id "$DISTRIBUTION_ID" --paths "/*"
