import { describe, expect, it } from "vitest";
import { exportDir, loadExport } from "./export";
import { ROUTE_QUESTIONS, routeCase, stripItems } from "./route";

const { index, cases } = loadExport(exportDir());
const get = (n: string) => {
    const k = cases.get(n);
    if (k === undefined) throw new Error(n);
    return k;
};

describe("the first page's case (S5 step 6b)", () => {
    it("is the newest closed case that has a trail", () => {
        expect(routeCase(index, cases)?.case_number).toBe(index.rows[0]?.case_number);
        const noTrail = index.rows.filter((r) => cases.get(r.case_number)?.trail === null);
        expect(noTrail.length).toBeGreaterThan(0);
        const rows = [...noTrail, ...index.rows.filter((r) => !noTrail.includes(r))];
        const first = rows.find((r) => cases.get(r.case_number)?.trail !== null);
        expect(routeCase({ ...index, rows }, cases)?.case_number).toBe(first?.case_number);
    });
    it("is none when no case has a trail", () => {
        const rows = index.rows.filter((r) => cases.get(r.case_number)?.trail === null);
        expect(routeCase({ ...index, rows }, cases)).toBeUndefined();
    });
});

describe("the trail strip", () => {
    it("shows each belief the trail holds, with what happened between them", () => {
        expect(stripItems(get("XXX26XX001"))).toEqual([
            {
                kind: "belief",
                name: "Before reading",
                event: expect.any(String),
                matched: expect.any(Boolean),
            },
            { kind: "step", text: "read 2 of 4 documents offered" },
            {
                kind: "belief",
                name: "After reading",
                event: expect.any(String),
                matched: expect.any(Boolean),
            },
            { kind: "step", text: "read 1 of 2 documents offered" },
            {
                kind: "belief",
                name: "After reading again",
                event: expect.any(String),
                matched: expect.any(Boolean),
            },
            { kind: "step", text: "4 coding look-ups" },
            {
                kind: "belief",
                name: "The answer",
                event: expect.any(String),
                matched: expect.any(Boolean),
            },
        ]);
    });
    it("marks a belief that put the NTSB's first code first", () => {
        const k = get("XXX26XX001");
        const answer = stripItems(k).at(-1);
        const ntsb = k.verdict?.occurrence[0]?.code;
        const agent = k.trail?.beliefs.find((b) => b.kind === "answer")?.first.code;
        expect(answer).toMatchObject({ matched: ntsb === agent });
    });
    it("cannot mark a belief when the NTSB has not published its codes", () => {
        const items = stripItems(get("XXX26XX006"));
        for (const item of items) if (item.kind === "belief") expect(item.matched).toBeNull();
    });
    it("says one look-up, and a read choice with nothing on offer", () => {
        expect(stripItems(get("XXX26XX002"))).toContainEqual({
            kind: "step",
            text: "1 coding look-up",
        });
        expect(stripItems(get("XXX26XX004"))).toContainEqual({
            kind: "step",
            text: "nothing on offer to read",
        });
    });
    it("is empty for a case with no trail", () => {
        expect(stripItems(get("XXX26XX005"))).toEqual([]);
    });
});

describe("the eight questions' one-line answers (Andy, 2026-10-21)", () => {
    it("has the eight questions, in order, each linking to its Path stop", () => {
        expect(ROUTE_QUESTIONS.map((q) => q.anchor)).toEqual([
            "answer-key",
            "case-record",
            "docket",
            "scanned-pages",
            "coding",
            "consistency",
            "choosing",
            "newly-closed",
        ]);
    });
    it("words question 6 from the measured rate", () => {
        expect(ROUTE_QUESTIONS[5]?.answer).toBe(
            "Not fully: cases with the same cause sentence share a first code in about one case in three.",
        );
    });
});
