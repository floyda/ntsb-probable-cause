import { defineConfig } from "@playwright/test";

// Draws the preview cards (S5 step 6c, Task 2): `pnpm cards`, run by hand when a card's words
// change, never by the build. Playwright's runner loads the site's TypeScript as it is, so the
// cards take their words from src/lib/cards.ts with no copy.
export default defineConfig({
    testDir: "scripts",
    testMatch: "make-cards.spec.ts",
    reporter: [["list"]],
    use: { viewport: { width: 1200, height: 630 }, colorScheme: "dark" },
});
