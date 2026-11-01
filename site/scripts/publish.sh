#!/usr/bin/env bash
# Publishes the site to its bucket and clears CloudFront's copies (S5 spec §18.1, §19.1).
# Run by CodeBuild from the repository root. The mode is the build's SITE_MODE, which only a
# `cdk deploy` sets (`site_mode` in infra/app.py), because launch is Andy's decision (spec §20):
# - `holding` publishes site/holding/, the holding line;
# - `site` copies S4's export, checks it is whole, builds the site from it, checks the built
#   pages, and publishes site/dist/.
# Any failure stops the script before the first upload, so yesterday's site stays.
set -euo pipefail

: "${SITE_BUCKET:?SITE_BUCKET is not set}"
: "${DISTRIBUTION_ID:?DISTRIBUTION_ID is not set}"

case "${SITE_MODE:-}" in
  holding) out="site/holding" ;;
  site)
    : "${LIVE_BUCKET:?LIVE_BUCKET is not set}"
    export_dir="$(mktemp -d)/board-1"
    # The night's export, into a fresh folder (spec §22). Case files S4 could not delete come
    # too; the build reads only those index.json lists.
    aws s3 sync "s3://${LIVE_BUCKET}/export/board-1/" "$export_dir" --only-show-errors
    (
      cd site
      # Whole only when the finished mark's built_at equals index.json's (spec §22). The line it
      # prints is required, so a script that loads but checks nothing cannot pass (review,
      # 2026-11-01).
      node scripts/check-finished.ts "$export_dir" | grep -qx "check-finished: the export is whole"
      # From the lockfile, under the supply-chain settings in pnpm-workspace.yaml (spec §17.2).
      pnpm install --frozen-lockfile
      rm -rf dist
      # The build checks the export against board/1, the counts and the claims, and stops on
      # any fault; the page checks then cover respect (§11), links and the preview tags. The
      # browser checks run on every pull request, not here (plan 2026-11-01, choice 1).
      BOARD_EXPORT_DIR="$export_dir" pnpm run build
      # The page checks skip when nothing was built, so the build's first page must exist.
      test -f dist/index.html
      BOARD_EXPORT_DIR="$export_dir" pnpm exec vitest run tests/dist.test.ts
    )
    # A newer night may have landed while this build ran, and its own build publishes it. Two
    # builds can overlap, so an older one must never publish last over a newer one; nor one
    # whose copy caught S4 mid-upload, when the mark changes too (review, 2026-11-01).
    aws s3 cp "s3://${LIVE_BUCKET}/export/board-1/_finished.json" "${export_dir}.mark-now" \
      --only-show-errors
    if ! cmp -s "${export_dir}/_finished.json" "${export_dir}.mark-now"; then
      echo "publish.sh: a newer export arrived during this build; its own build publishes it"
      exit 0
    fi
    out="site/dist"
    ;;
  *)
    echo "publish.sh: mode '${SITE_MODE:-}' is not allowed; only 'holding' or 'site'" >&2
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
