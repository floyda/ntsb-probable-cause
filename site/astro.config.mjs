// @ts-check
import { defineConfig } from "astro/config";

// The site is built ahead of time as plain files (decision 0003; S5 spec §17).
export default defineConfig({
    site: "https://ellery.demo.floyda.dev",
    output: "static",
    trailingSlash: "ignore",
    build: {
        // Every page is a folder with index.html, so /methods/ and /methods both work behind
        // CloudFront's URL rewrite (infra/site_url_rewrite.js).
        format: "directory",
        // Styles as files, never inline, so the Content-Security-Policy can stay 'self'.
        inlineStylesheets: "never",
    },
    // No telemetry, no third-party requests at build or read time.
    devToolbar: { enabled: false },
});
