import { defineConfig } from "@playwright/test";

// The accessibility check (S5 spec §12 item 8, §19.2) runs over the built files, served as
// plain files the way S3 serves them.
const LIGHT = {
    cookies: [],
    origins: [
        { origin: "http://127.0.0.1:4321", localStorage: [{ name: "theme", value: "light" }] },
    ],
};

export default defineConfig({
    testDir: "tests",
    // Playwright runs the *.spec.ts files; Vitest runs the *.test.ts files.
    testMatch: "**/*.spec.ts",
    fullyParallel: true,
    forbidOnly: true,
    reporter: [["list"]],
    use: { baseURL: "http://127.0.0.1:4321" },
    webServer: {
        command: "node tests/serve.mjs",
        url: "http://127.0.0.1:4321/",
        reuseExistingServer: false,
    },
    // Dark is the site's default (decision 0222), so the light and phone checks start as a
    // reader who chose light: the choice public/theme.js keeps in the browser.
    projects: [
        { name: "light", use: { storageState: LIGHT, viewport: { width: 1280, height: 800 } } },
        { name: "dark", use: { viewport: { width: 1280, height: 800 } } },
        { name: "phone", use: { storageState: LIGHT, viewport: { width: 390, height: 844 } } },
    ],
});
