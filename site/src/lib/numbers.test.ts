import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import {
    containsValue,
    count,
    countOf,
    entry,
    NumbersError,
    oneIn,
    oneInWords,
    parseNumbers,
    pct,
    points,
    usd,
    withInterval,
} from "./numbers";

describe("formatting by key, on the committed numbers file", () => {
    it("prints a rate, and a rate with its interval and count", () => {
        expect(pct("ladder.loop.top1")).toBe("23.5%");
        expect(withInterval("ladder.loop.top1")).toBe("23.5% [19.2%, 27.5%], 400 cases");
        expect(withInterval("ladder.baseline.top1")).toBe("17.7% [16.6%, 18.9%], 4,241 cases");
    });
    it("prints a difference in points with true minus signs, and a plus for a gain", () => {
        expect(points("q7.loop_vs_fixed")).toBe("−9.5 points [−14.0, −5.2]");
        expect(points("q3.docket_gain")).toBe("+14.3 points [+9.2, +19.3]");
        expect(points("q7.loop_vs_answer")).toBe("−4.2 points [−8.5, +0.0]");
    });
    it("prints dollars to the cent", () => {
        expect(usd("ladder.loop.billed")).toBe("$2.06");
        expect(usd("ladder.fixed.cost")).toBe("$2.34");
    });
    it("prints counts, alone and out of their total", () => {
        expect(count("q4.pages.total")).toBe("16,790");
        expect(countOf("q5.first_right")).toBe("88 of 399");
    });
    it("refuses an unknown key, so a typo fails the build", () => {
        expect(() => entry("ladder.loop.top2")).toThrow(NumbersError);
    });
    it("refuses a formatter that does not fit the entry's unit", () => {
        expect(() => pct("ladder.loop.billed")).toThrow(/usd/);
        expect(() => points("ladder.loop.top1")).toThrow(/percent/);
    });
});

describe("the first page's caveat (plan Review Focus 3)", () => {
    it("says about one case in four for the loop and one in three for the fixed method", () => {
        expect(oneIn("ladder.loop.top1")).toBe("one case in four");
        expect(oneIn("ladder.fixed.top1")).toBe("one case in three");
    });
    it("fails when no 'one in N' is near the rate, rather than saying something untrue", () => {
        // 41% sits between one in two (50%) and one in three (33.3%), near neither.
        expect(() => oneInWords(41)).toThrow(NumbersError);
        expect(oneInWords(20)).toBe("one case in five");
    });
});

describe("question 2's claim, no better than guessing (plan Review Focus 5)", () => {
    it("holds because the no-docket interval contains the baseline's rate", () => {
        expect(containsValue("ladder.no_docket.top1", "ladder.baseline.top1")).toBe(true);
        expect(containsValue("ladder.loop.top1", "ladder.fixed.top1")).toBe(false);
    });
});

describe("the file's shape", () => {
    it("refuses another format or a malformed entry", () => {
        expect(() => parseNumbers({ format: "site-numbers/2", entries: {}, lists: {} })).toThrow(
            NumbersError,
        );
        expect(() =>
            parseNumbers({
                format: "site-numbers/1",
                entries: { a: { value: "1" } },
                lists: {},
            }),
        ).toThrow(/a/);
    });
});

describe("no number is typed into a page (spec §17.3)", () => {
    const roots = ["pages", "components", "layouts"].map((d) => join(__dirname, "..", d));
    const files = roots.flatMap((root) =>
        readdirSync(root, { recursive: true, encoding: "utf8" })
            .filter((f) => f.endsWith(".astro"))
            .map((f) => join(root, f)),
    );
    it("finds the page sources", () => {
        expect(files.length).toBeGreaterThan(3);
    });
    it.each(files)("%s holds no percentage or dollar literal outside its styles", (file) => {
        const text = readFileSync(file, "utf8").replaceAll(/<style[\s\S]*?<\/style>/g, "");
        expect(text).not.toMatch(/\d%|\$\d/);
    });
});
