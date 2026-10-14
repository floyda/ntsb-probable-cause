import { describe, expect, it } from "vitest";
import { assertPathClaims, assertPredictionsAsRead, claimHolds, pathClaims } from "./claims";
import { entry, list, type Entry } from "./numbers";

// The numbers file with one entry's fields replaced, as a re-run might move them.
const moved =
    (key: string, change: Partial<Entry>) =>
    (k: string): Entry =>
        k === key ? { ...entry(k), ...change } : entry(k);

describe("the Path page's claims", () => {
    it("all hold on the committed numbers file", () => {
        expect(pathClaims().filter((c) => !c.holds)).toEqual([]);
        expect(() => {
            assertPathClaims();
        }).not.toThrow();
    });

    it.each([
        ["q2.no_better_than_guessing", moved("ladder.no_docket.top1", { low: 18.0, high: 22.0 })],
        ["q4.not_shown_to_help", moved("q4.v2_gain", { low: 0.4 })],
        ["q7.loop_worse", moved("q7.loop_vs_fixed", { high: 0.5 })],
        ["q7.docket_mattered", moved("q7.no_docket_loss", { high: 1.0 })],
        ["q7.same_bill", moved("ladder.loop.billed", { value: 2.5 })],
        ["q7.lead_from_tools", moved("q7.loop_vs_answer", { value: -6.0 })],
        ["q7.path_adds_up", moved("q7.path.after", { value: 83 })],
        ["q7.path_improves", moved("q7.path.before", { value: 90 })],
        ["q7.path_adds_up", moved("q7.path.coding.stayed_wrong", { value: 291 })],
    ])("%s fails when its figures move", (id, get) => {
        expect(claimHolds(id, get)).toBe(false);
        expect(() => {
            assertPathClaims(get);
        }).toThrow(id);
    });
});

describe("S3.2's predictions as the Methods page was read (S5 step 5, Task 3)", () => {
    it("hold on the committed numbers file", () => {
        expect(() => {
            assertPredictionsAsRead();
        }).not.toThrow();
    });
    it("stop the build when a prediction's outcome changes", () => {
        const flipped = list("s32.predictions").map((p) =>
            p["number"] === 1 ? { ...p, outcome: "met" } : p,
        );
        expect(() => {
            assertPredictionsAsRead(flipped);
        }).toThrow(/1, 3, 7, 8, 9/);
    });
    it("stop the build when a prediction goes missing", () => {
        expect(() => {
            assertPredictionsAsRead(list("s32.predictions").slice(0, 8));
        }).toThrow(/read the Methods page again/);
    });
});
