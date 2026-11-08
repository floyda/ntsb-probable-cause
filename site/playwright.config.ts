import { defineConfig } from "@playwright/test";

// The accessibility check (S5 spec §12 item 8, §19.2) runs over the built files, served as
// plain files the way S3 serves them.
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
    projects: [
        { name: "light", use: { colorScheme: "light", viewport: { width: 1280, height: 800 } } },
        { name: "dark", use: { colorScheme: "dark", viewport: { width: 1280, height: 800 } } },
        { name: "phone", use: { colorScheme: "light", viewport: { width: 390, height: 844 } } },
    ],
});
