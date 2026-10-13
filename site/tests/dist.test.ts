// Checks over the built pages (S5 step 2): run after `pnpm run build`.
import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { exportDir, loadExport } from "../src/lib/export";
import { differenceSentence } from "../src/lib/words";

const DIST = join(process.cwd(), "dist");
const built = existsSync(join(DIST, "index.html"));

/** The text a reader sees: tags and the contents of script and style removed. */
function visibleText(html: string): string {
    return html
        .replace(/<(script|style)[\s\S]*?<\/\1>/g, " ")
        .replace(/<[^>]+>/g, " ")
        .replace(/&#x27;|&#39;/g, "'")
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, "&")
        .replace(/\s+/g, " ");
}

describe.skipIf(!built)("the built case pages (needs `pnpm run build` first)", () => {
    const { cases } = loadExport(exportDir());

    it.each([...cases.keys()])("%s has its own page with its difference sentence", (n) => {
        const kase = cases.get(n);
        expect(kase).toBeDefined();
        if (kase === undefined) return;
        const html = readFileSync(join(DIST, "case", n, "index.html"), "utf8");
        const text = visibleText(html);
        expect(text).toContain(differenceSentence(kase));
        expect(text).not.toMatch(/\b(undefined|null|NaN)\b/);
    });
});
