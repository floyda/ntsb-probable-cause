import { describe, expect, it } from "vitest";
import { LADDER, ladderLayout, type Box, type LadderGeometry } from "./ladder";
import { entry } from "./numbers";

const WIDTHS = [340, 640];
const overlaps = (a: Box, b: Box): boolean =>
    a.x0 < b.x1 && b.x0 < a.x1 && a.top < b.bottom && b.top < a.bottom;

describe.each(WIDTHS)("the ladder at a width of %i", (width) => {
    const g: LadderGeometry = ladderLayout(LADDER, width);

    it("has the four steps in order", () => {
        expect(g.bars.map((b) => b.key)).toEqual(["baseline", "no_docket", "fixed", "loop"]);
    });

    it("starts every bar at x = 0 of the plot", () => {
        for (const bar of g.bars) expect(bar.x).toBe(0);
    });

    it("draws every bar on one scale, from 0 to the largest whisker rounded up to 10%", () => {
        expect(g.scaleMax).toBe(40); // the fixed pipeline's high end, 37.5%
        for (const bar of g.bars) {
            const value = entry(LADDER.find((s) => s.key === bar.key)?.rate ?? "").value;
            expect(bar.width).toBeCloseTo((value / g.scaleMax) * g.plotWidth, 6);
        }
    });

    it("keeps every whisker inside the plot", () => {
        for (const bar of g.bars) {
            expect(bar.whisker[0]).toBeGreaterThanOrEqual(0);
            expect(bar.whisker[1]).toBeLessThanOrEqual(g.plotWidth);
            expect(bar.whisker[0]).toBeLessThan(bar.whisker[1]);
        }
    });

    it("puts the always-guessing mark at the baseline's value", () => {
        const baseline = entry("ladder.baseline.top1").value;
        expect(g.baselineX).toBeCloseTo((baseline / g.scaleMax) * g.plotWidth, 6);
    });

    it("draws the loop's bar shorter than the fixed pipeline's (spec §7.1)", () => {
        const [, , fixed, loop] = g.bars;
        expect(loop?.width ?? 0).toBeLessThan(fixed?.width ?? 0);
    });

    it("keeps every label inside the width, and no two labels overlapping", () => {
        for (const label of g.labels) {
            expect(label.box.x0, label.text).toBeGreaterThanOrEqual(0);
            expect(label.box.x1, label.text).toBeLessThanOrEqual(width);
        }
        for (const [i, a] of g.labels.entries()) {
            for (const b of g.labels.slice(i + 1)) {
                expect(overlaps(a.box, b.box), `${a.text} | ${b.text}`).toBe(false);
            }
        }
    });

    it("keeps every bar clear of every label", () => {
        for (const bar of g.bars) {
            const box = { x0: 0, x1: g.plotWidth, top: bar.y, bottom: bar.y + bar.height };
            for (const label of g.labels) expect(overlaps(box, label.box), label.text).toBe(false);
        }
    });

    it("prints each step's rate with its interval and count, and its cost", () => {
        const text = g.labels.map((l) => l.text).join("\n");
        expect(text).toContain("23.5% [19.2%, 27.5%], 400 cases");
        expect(text).toContain("list $2.34 · billed $2.13");
        expect(text).toContain("list $3.93 · billed $2.06");
        expect(text).toContain("no model cost");
        expect(text).toContain("always guessing");
    });
});

describe("wrapping", () => {
    it("wraps a step's plain words at phone width rather than letting them run off", () => {
        const narrow = ladderLayout(LADDER, 340);
        const wide = ladderLayout(LADDER, 640);
        expect(narrow.labels.length).toBeGreaterThan(wide.labels.length);
        expect(narrow.height).toBeGreaterThan(wide.height);
    });
});
