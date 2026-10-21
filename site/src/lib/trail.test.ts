import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { CaseFile } from "./board-case-types";
import {
    closestLine,
    confidenceLabel,
    costLabel,
    documentLine,
    lookupDetails,
    lookupName,
    titleShown,
    trailSteps,
    verdictView,
} from "./trail";

const SAMPLE = join(__dirname, "../../../tests/fixtures/board");
const kase = (n: number): CaseFile =>
    JSON.parse(readFileSync(join(SAMPLE, `cases/XXX26XX00${String(n)}.json`), "utf8")) as CaseFile;
const shape = (c: CaseFile): string[] =>
    trailSteps(c).map((s) =>
        s.kind === "belief" ? s.belief.kind : s.kind === "read" ? s.choice.step : "lookups",
    );

describe("the order of the steps", () => {
    it("interleaves beliefs and read choices (case 1: two reads, each followed by a belief)", () => {
        expect(shape(kase(1))).toEqual([
            "h0",
            "choice1",
            "h1",
            "choice2",
            "h2",
            "lookups",
            "answer",
        ]);
    });
    it("never invents a belief the export lacks (case 2: a read with no belief after it)", () => {
        expect(shape(kase(2))).toEqual(["h0", "choice1", "lookups", "answer"]);
    });
    it("has no steps for a case without a trail", () => {
        expect(trailSteps(kase(5))).toEqual([]);
    });
    it("marks change from the belief before, and nothing on the first", () => {
        const changes = trailSteps(kase(1)).flatMap((s) =>
            s.kind === "belief" ? [s.changed] : [],
        );
        expect(changes).toEqual([
            null,
            "first code changed",
            "first code unchanged",
            "first code unchanged",
        ]);
    });
    it("costs the lookups step from the export's own figures", () => {
        const step = trailSteps(kase(1)).find((s) => s.kind === "lookups");
        expect(step?.kind === "lookups" ? costLabel(step.cost_usd) : "").toBe("$0.0050");
    });
});

describe("the words", () => {
    it("prints confidence plainly, without float noise", () => {
        expect(confidenceLabel(0.45000000000000007)).toBe("confidence 0.45");
        expect(confidenceLabel(0.62)).toBe("confidence 0.62");
    });
    it("prints cost to four decimals", () => {
        expect(costLabel(0.0038)).toBe("$0.0038");
        expect(costLabel(0.0322)).toBe("$0.0322");
    });
    it("names each document's fate, with pages when known", () => {
        const base = { position: 1, title: "x", note: null };
        expect(
            documentLine({ ...base, decision: "read", pages: 12, not_offered_reason: null }),
        ).toEqual({ decision: "read", detail: "12 pages" });
        expect(
            documentLine({ ...base, decision: "scan_only", pages: 1, not_offered_reason: null }),
        ).toEqual({ decision: "scan only", detail: "no text to read · 1 page" });
        expect(
            documentLine({
                ...base,
                decision: "not_offered",
                pages: 9,
                not_offered_reason: "photo_only",
            }),
        ).toEqual({ decision: "not offered", detail: "photographs only · 9 pages" });
        expect(
            documentLine({
                ...base,
                decision: "not_offered",
                pages: 4,
                not_offered_reason: "already_read",
            }),
        ).toEqual({ decision: "already read", detail: "at the first read choice · 4 pages" });
        expect(
            documentLine({ ...base, decision: "skipped", pages: null, not_offered_reason: null }),
        ).toEqual({ decision: "skipped", detail: null });
    });
    it("names the tools in plain words", () => {
        expect(lookupName("occurrence_usage")).toBe("Looked up how often codes come first");
        expect(lookupName("new_tool")).toBe("new tool");
    });
});

describe("the closest belief", () => {
    it("names the first belief to match the NTSB's first code (case 1: after the first read)", () => {
        expect(closestLine(kase(1))).toBe(
            "Closest to the NTSB: after the first read choice, the first belief to put “Aerodynamic stall/spin” first.",
        );
    });
    it("says so when no belief matched (case 3)", () => {
        expect(closestLine(kase(3))).toBe(
            "No belief put the NTSB's first code, “Fuel exhaustion”, first.",
        );
    });
    it("is left out while the NTSB has not published (case 6)", () => {
        expect(closestLine(kase(6))).toBeNull();
    });
});

describe("review fixes (2026-10-14)", () => {
    it("names an abstained answer as such (case 4)", () => {
        const last = trailSteps(kase(4)).at(-1);
        expect(last?.kind === "belief" ? last.name : "").toBe("The answer: the agent abstained");
    });

    it("never credits an abstained answer as the closest belief", () => {
        const c = kase(4);
        const ntsb = c.verdict?.occurrence[0];
        const answer = c.trail?.beliefs.find((b) => b.kind === "answer");
        if (ntsb === undefined || answer === undefined) throw new Error("sample changed");
        answer.first = ntsb; // the abstained answer leaned to the NTSB's own first code
        expect(closestLine(c)).toBe(
            "No belief put the NTSB's first code, “Loss of engine power (total)”, first.",
        );
    });

    it("writes lookups in plain words, codes by their labels where the case has them", () => {
        const c = kase(1);
        const [describe, usage, findings, suggest] = c.trail?.lookups ?? [];
        if (!describe || !usage || !findings || !suggest) throw new Error("sample changed");
        expect(lookupDetails(describe, c).asked).toBe(
            "about the occurrence code Maneuvering-Low-alt flying / Aerodynamic stall/spin",
        );
        expect(lookupDetails(usage, c).asked).toBe(
            "about Maneuvering-Low-alt flying / Aerodynamic stall/spin; Maneuvering-Low-alt flying / Loss of control in flight",
        );
        expect(lookupDetails(findings, c).asked).toBe(
            "after Maneuvering-Low-alt flying / Aerodynamic stall/spin",
        );
        expect(lookupDetails(suggest, c).asked).toBe("for the phase Maneuvering");
        expect(lookupDetails(usage, c).why).toBe("See how often each code is coded first.");
        expect(lookupDetails(usage, c).note).toBe("Decides which code to put first.");
    });

    it("shows a verdict's cause even when it has no codes", () => {
        const c = kase(1);
        if (c.verdict === null) throw new Error("sample changed");
        c.verdict.occurrence = [];
        expect(verdictView(c)).toEqual({ first: null, cause: c.verdict.cause, closest: null });
        expect(verdictView(kase(6))).toBeNull();
    });

    it("falls back to the code number when the case holds no label for it", () => {
        const c = kase(1);
        const lookup = { tool: "occurrence_usage", cost_usd: 0, arguments: { codes: ["999999"] } };
        expect(lookupDetails(lookup, c).asked).toBe("about code 999999");
    });
});

describe("a document's title as shown (decision 0187)", () => {
    const LOST = "A��";
    it("shows the dash the NTSB lost as an en dash", () => {
        expect(titleShown(`MEMORANDUM FOR RECORD ${LOST} PILOT`)).toBe(
            "MEMORANDUM FOR RECORD – PILOT",
        );
        expect(titleShown(`A ${LOST} B ${LOST} C`)).toBe("A – B – C");
    });
    it("changes nothing else, a lone replacement mark included", () => {
        for (const title of ["PILOT'S STATEMENT", "A� B", "��", "MEMO - AIRPORT", "AA"]) {
            expect(titleShown(title)).toBe(title);
        }
    });
});
