import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { AWAY, cardFor, cardVersion, cardWords, CARD_DIR } from "./cards";
import { ROUTE_QUESTIONS } from "./route";
import { SITE_LINE, SITE_QUESTION } from "./site";

const DIR = join(__dirname, "../../public", CARD_DIR);

/** A PNG's width and height, from its header: no image library needed. */
function pngSize(path: string): { width: number; height: number } {
    const bytes = readFileSync(path);
    expect(bytes.subarray(1, 4).toString("latin1")).toBe("PNG");
    return { width: bytes.readUInt32BE(16), height: bytes.readUInt32BE(20) };
}

describe("the cards' words (S5 step 6c, Task 2)", () => {
    it("has the site card first, then one card per Path question in order", () => {
        expect(cardWords().map((c) => c.name)).toEqual([
            "site",
            ...ROUTE_QUESTIONS.map((q) => `q-${q.anchor}`),
        ]);
    });
    it("puts the site's question and line on the site card", () => {
        expect(cardFor()).toMatchObject({ question: SITE_QUESTION, line: SITE_LINE });
    });
    it("puts each question's own answer on its card, except where it points up the page", () => {
        for (const q of ROUTE_QUESTIONS) {
            const c = cardFor(`q-${q.anchor}`);
            expect(c.question).toBe(q.question);
            if (q.anchor === "newly-closed") {
                expect(c.line).toBe("The live board answers this in public.");
            } else expect(c.line).toBe(q.answer);
            expect(c.line).not.toMatch(/\babove\b|\bbelow\b/);
        }
    });
    it("gives each card a text alternative holding every word drawn", () => {
        for (const c of cardWords()) {
            expect(c.alt).toContain("Ellery");
            expect(c.alt).toContain(c.question);
            expect(c.alt).toContain(c.line);
        }
    });
    it("stops when an answer a card rewords has changed", () => {
        const away = AWAY["newly-closed"];
        expect(away?.from).toBe(ROUTE_QUESTIONS.find((q) => q.anchor === "newly-closed")?.answer);
        if (away === undefined) return;
        const was = away.from;
        away.from = "Something else.";
        try {
            expect(() => cardWords()).toThrow(/answer changed/);
        } finally {
            away.from = was;
        }
    });
    it("marks each card's words with a version that changes with them", () => {
        const c = cardFor();
        expect(cardVersion(c)).toMatch(/^[0-9a-f]{8}$/);
        expect(cardVersion({ ...c, line: `${c.line}!` })).not.toBe(cardVersion(c));
        expect(new Set(cardWords().map(cardVersion)).size).toBe(cardWords().length);
    });
    it("refuses a card that does not exist", () => {
        expect(() => cardFor("q-nowhere")).toThrow(/no card named/);
    });
});

describe("the committed cards (S5 step 6c, Task 2; plan Review Focus 2)", () => {
    it("were drawn with today's words: re-run `pnpm cards` when this fails", () => {
        const drawn: unknown = JSON.parse(readFileSync(join(DIR, "cards.json"), "utf8"));
        expect(drawn).toEqual(cardWords());
    });
    it.each(cardWords().map((c) => c.name))("%s is a 1200 by 630 PNG", (name) => {
        const path = join(DIR, `${name}.png`);
        expect(existsSync(path)).toBe(true);
        expect(pngSize(path)).toEqual({ width: 1200, height: 630 });
    });
});
