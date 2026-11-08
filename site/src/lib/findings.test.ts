import { describe, expect, it } from "vitest";
import { findingParts, findingRows } from "./findings";

const code = (label: string, c = "0000000000") => ({ code: c, label });
const FUEL = code(
    "Personnel issues — Task performance — Planning/preparation — Fuel planning - Incorrect use/operation",
);
const WEATHER = code(
    "Personnel issues — Task performance — Planning/preparation — Weather planning - Incorrect use/operation",
);
const CONTROL_USE = code(
    "Personnel issues — Task performance — Use of equip/info — Aircraft control - Incorrect use/operation",
);
const CONTROL_KEPT = code(
    "Personnel issues — Task performance — Use of equip/info — Aircraft control - Not attained/maintained",
);
const FUEL_SYSTEM = code(
    "Aircraft — Aircraft systems — Fuel system — Fuel distribution - Malfunction",
);

describe("a finding's parts (S5 step 6a)", () => {
    it("splits the area, the item and the detail", () => {
        expect(findingParts(FUEL.label)).toEqual({
            area: ["Personnel issues", "Task performance", "Planning/preparation"],
            item: "Fuel planning",
            detail: "Incorrect use/operation",
        });
    });
    it("keeps a hyphen inside a word as part of the item", () => {
        expect(
            findingParts(
                "Environmental issues — Physical environment — Low-alt flying - Effect on equipment",
            ).item,
        ).toBe("Low-alt flying");
    });
    it("reads a label with no area or no detail as an item alone", () => {
        expect(findingParts("0206304011")).toEqual({ area: [], item: "0206304011", detail: null });
        expect(findingParts("Aircraft — Fuel distribution")).toEqual({
            area: ["Aircraft"],
            item: "Fuel distribution",
            detail: null,
        });
    });
});

describe("the rows of a compared case's findings", () => {
    it("puts findings both named first, then close pairs, then the rest", () => {
        const rows = findingRows([CONTROL_USE], [FUEL, FUEL_SYSTEM], [WEATHER]);
        expect(rows.map((r) => r.kind)).toEqual(["one", "close", "one"]);
        expect(rows[0]).toEqual({ kind: "one", who: "both", finding: CONTROL_USE });
        expect(rows[1]).toEqual({ kind: "close", how: "item", ntsb: FUEL, agent: WEATHER });
        expect(rows[2]).toEqual({ kind: "one", who: "ntsb", finding: FUEL_SYSTEM });
    });
    it("pairs the same item with a different detail before the same area", () => {
        const rows = findingRows([], [CONTROL_KEPT, FUEL], [WEATHER, CONTROL_USE]);
        expect(rows).toEqual([
            { kind: "close", how: "detail", ntsb: CONTROL_KEPT, agent: CONTROL_USE },
            { kind: "close", how: "item", ntsb: FUEL, agent: WEATHER },
        ]);
    });
    it("pairs each finding at most once", () => {
        const rows = findingRows([], [FUEL, FUEL], [WEATHER]);
        expect(rows.filter((r) => r.kind === "close")).toHaveLength(1);
        expect(rows.at(-1)).toEqual({ kind: "one", who: "ntsb", finding: FUEL });
    });
    it("never pairs findings from different areas", () => {
        const rows = findingRows([], [FUEL_SYSTEM], [WEATHER]);
        expect(rows).toEqual([
            { kind: "one", who: "ntsb", finding: FUEL_SYSTEM },
            { kind: "one", who: "agent", finding: WEATHER },
        ]);
    });
    it("never pairs labels it cannot split into an area", () => {
        const rows = findingRows([], [code("0206103011")], [code("0206102011")]);
        expect(rows.every((r) => r.kind === "one")).toBe(true);
    });
});
