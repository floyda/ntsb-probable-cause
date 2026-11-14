import { describe, expect, it } from "vitest";
import { halfShown } from "./first-codes";
import { list } from "./numbers";

const rows = (counts: number[]) => counts.map((count) => ({ count }));

describe("question 6's commonest codes, to half the cases", () => {
    it("shows the committed sentence's first five codes, 17 of 33 cases", () => {
        const all = list("q6.one.codes").map((r) => ({ count: Number(r["count"]) }));
        const { shown, rest, restCases } = halfShown(all);
        expect(shown.map((r) => r.count)).toEqual([4, 4, 3, 3, 3]);
        expect(rest).toHaveLength(13);
        expect(restCases).toBe(16);
    });
    it("stops as soon as half is covered", () => {
        expect(halfShown(rows([5, 3, 1, 1])).shown).toHaveLength(1); // 5 of 10
        expect(halfShown(rows([4, 3, 2, 1])).shown).toHaveLength(2); // 7 of 10
    });
    it("keeps a code tied with the last one shown", () => {
        expect(halfShown(rows([4, 2, 2, 2])).shown).toHaveLength(4); // 6 of 10, then the tie
    });
    it("shows everything when nothing is left", () => {
        expect(halfShown(rows([1, 1])).rest).toEqual([]);
        expect(halfShown([]).shown).toEqual([]);
    });
});
