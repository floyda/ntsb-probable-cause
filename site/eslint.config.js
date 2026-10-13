// @ts-check
import js from "@eslint/js";
import astro from "eslint-plugin-astro";
import { defineConfig } from "eslint/config";
import globals from "globals";
import tseslint from "typescript-eslint";

// Accessibility is checked on the built pages by axe (tests/a11y.spec.ts), not by lint rules:
// eslint-plugin-jsx-a11y does not support ESLint 10 (plan Task 1, 2026-10-12).
export default defineConfig(
    {
        // The two generated type files are checked by `types:check` and the compiler instead.
        ignores: [
            "dist/",
            ".astro/",
            "test-results/",
            "playwright-report/",
            "src/lib/board-index-types.ts",
            "src/lib/board-case-types.ts",
        ],
    },
    js.configs.recommended,
    tseslint.configs.strictTypeChecked,
    astro.configs.recommended,
    { languageOptions: { globals: { ...globals.browser, ...globals.node } } },
    {
        files: ["**/*.ts", "**/*.mts"],
        languageOptions: {
            parserOptions: { projectService: true, tsconfigRootDir: import.meta.dirname },
        },
    },
    {
        // astro-eslint-parser takes `project`, not `projectService`.
        files: ["**/*.astro"],
        languageOptions: {
            parserOptions: {
                project: true,
                tsconfigRootDir: import.meta.dirname,
                extraFileExtensions: [".astro"],
            },
        },
    },
    { files: ["**/*.js", "**/*.mjs"], extends: [tseslint.configs.disableTypeChecked] },
    {
        // Tests edit raw export JSON on purpose to build broken exports.
        files: ["**/*.test.ts"],
        rules: {
            "@typescript-eslint/no-unsafe-assignment": "off",
            "@typescript-eslint/no-unsafe-member-access": "off",
        },
    },
);
