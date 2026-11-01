import { describe, expect, it } from "vitest";
import type { Counts } from "./board-index-types";
import { closureNights, openLines } from "./open";

const counts = (over: Partial<Counts>): Counts => ({
    awaiting_ntsb: 0,
    closures_per_night: {},
    coded: 0,
    not_coded: {},
    open_watched: 923,
    open_with_docket: 2,
    ...over,
});

describe("the Open cases page's lines (S5 step 6c, Task 1)", () => {
    it("counts the open cases watched and those with a docket", () => {
        const lines = openLines(counts({}));
        expect(lines[0]).toBe("923 open cases are being watched.");
        expect(lines[1]).toBe("2 of them have a docket so far.");
    });
    it("says one case and one docket in the singular", () => {
        const lines = openLines(counts({ open_watched: 1, open_with_docket: 1 }));
        expect(lines[0]).toBe("1 open case is being watched.");
        expect(lines[1]).toBe("1 of them has a docket so far.");
    });
    it("says most open cases have no docket only while fewer than half have one", () => {
        const most = "Most open cases have no docket to read until then.";
        expect(openLines(counts({})).join(" ")).toContain(most);
        expect(openLines(counts({ open_watched: 4, open_with_docket: 2 })).join(" ")).not.toContain(
            most,
        );
        expect(openLines(counts({ open_watched: 0, open_with_docket: 0 })).join(" ")).not.toContain(
            most,
        );
    });
    it("always says when Ellery codes a case", () => {
        expect(openLines(counts({}))).toContain(
            "Ellery codes each case once, when the NTSB closes it.",
        );
    });
});

describe("the closures each night (S5 step 6c, Task 1)", () => {
    it("lists every night, newest first, with its date written out", () => {
        const rows = closureNights(
            counts({ closures_per_night: { "2026-09-23": 7, "2026-10-17": 12, "2026-10-01": 13 } }),
        );
        expect(rows).toEqual([
            { night: "2026-10-17", label: "17 Oct 2026", count: 12 },
            { night: "2026-10-01", label: "1 Oct 2026", count: 13 },
            { night: "2026-09-23", label: "23 Sep 2026", count: 7 },
        ]);
    });
    it("is empty before the first closure", () => {
        expect(closureNights(counts({}))).toEqual([]);
    });
});
