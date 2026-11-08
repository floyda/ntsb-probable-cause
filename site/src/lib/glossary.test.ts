import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { GLOSSARY } from "./glossary";

// Every fixed small-type term in the page sources (spec §12 item 4). A term built from data, such
// as a code's own label, is a code's name, not a term, and is skipped.
function smallTypeTerms(): string[] {
    const roots = ["pages", "components"].map((d) => join(__dirname, "..", d));
    const found = new Set<string>();
    for (const root of roots) {
        for (const f of readdirSync(root, { recursive: true, encoding: "utf8" })) {
            if (!f.endsWith(".astro")) continue;
            const source = readFileSync(join(root, f), "utf8");
            for (const m of source.matchAll(/<span class="term">([^<{]*)<\/span>/g)) {
                found.add((m[1] ?? "").replace(/^\s*·\s*/, "").trim());
            }
        }
    }
    return [...found].sort();
}

describe("the glossary (S5 step 5, Task 4)", () => {
    it("finds the small-type terms", () => {
        expect(smallTypeTerms()).toContain("NTSB findings");
    });
    it.each(smallTypeTerms())("defines %s", (shown) => {
        const known = GLOSSARY.flatMap((t) => [t.term, ...(t.seenAs ?? [])]);
        expect(known).toContain(shown);
    });
    it("is in alphabetical order, numbers last", () => {
        const words = GLOSSARY.map((t) => t.term);
        const lettered = words.filter((w) => /^[a-z]/i.test(w));
        expect(lettered).toEqual(
            [...lettered].sort((a, b) =>
                a.replace(/^The /, "").localeCompare(b.replace(/^The /, "")),
            ),
        );
    });
});
