import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import type { CaseFile } from "./board-case-types";
import type { BoardIndex } from "./board-index-types";
import {
    aircraftLabel,
    caseReportUrl,
    closedLabel,
    differenceSentence,
    docketUrl,
    eventOf,
    factsLine,
    stampLine,
    tookLabel,
    totalsLine,
    withheldLine,
} from "./words";

const SAMPLE = join(__dirname, "../../../tests/fixtures/board");
const index = JSON.parse(readFileSync(join(SAMPLE, "index.json"), "utf8")) as BoardIndex;
const kase = (n: number): CaseFile =>
    JSON.parse(readFileSync(join(SAMPLE, `cases/XXX26XX00${String(n)}.json`), "utf8")) as CaseFile;

describe("small labels", () => {
    it("takes the event from a phase / event label", () => {
        expect(eventOf("Maneuvering-Low-alt flying / Aerodynamic stall/spin")).toBe(
            "Aerodynamic stall/spin",
        );
        expect(eventOf("Takeoff")).toBe("Takeoff");
    });
    it("writes dates and durations", () => {
        expect(closedLabel("2026-10-09")).toBe("9 Oct");
        expect(tookLabel(47)).toBe("47 days");
        expect(tookLabel(61)).toBe("2 mo");
        expect(tookLabel(427)).toBe("14 mo");
    });
    it("writes the aircraft as category and engines", () => {
        expect(
            aircraftLabel({ category: "Airplane", engines: 1, engine_type: "Reciprocating" }),
        ).toBe("Aeroplane, 1 piston");
        expect(
            aircraftLabel({ category: "Helicopter", engines: 1, engine_type: "Turbo shaft" }),
        ).toBe("Helicopter, 1 turboshaft");
        expect(aircraftLabel({ category: "Airplane", engines: 1, engine_type: null })).toBe(
            "Aeroplane, 1 engine",
        );
        expect(aircraftLabel({ category: null, engines: null, engine_type: null })).toBe(
            "Not recorded",
        );
    });
});

describe("board lines", () => {
    it("states the export's own build time and the last closures", () => {
        expect(stampLine(index)).toBe("Updated 06:00 UTC, 10 Oct · last closures 9 Oct");
    });
    it("counts each grade, leaving out zeros", () => {
        expect(totalsLine(index.rows)).toBe(
            "Since launch: 1 same first code, 1 same codes in another order, 1 different, 1 agent abstained, 2 not coded, 1 awaiting the NTSB's codes.",
        );
    });
});

describe("the difference sentence (spec §5 part 2; code writes it, never a model)", () => {
    it("same first code", () => {
        expect(differenceSentence(kase(1))).toBe(
            "Both put “Aerodynamic stall/spin” first, and their sequences match.",
        );
    });
    it("same codes, other order", () => {
        expect(differenceSentence(kase(2))).toBe(
            "Both name “Hard landing”. The NTSB put it first; the agent put “Loss of control on ground” first.",
        );
    });
    it("different", () => {
        expect(differenceSentence(kase(3))).toBe(
            "The NTSB put “Fuel exhaustion” first. The agent put “Landing area undershoot” first and did not name the NTSB's first code.",
        );
    });
    it("abstained", () => {
        expect(differenceSentence(kase(4))).toBe(
            "The agent abstained: it judged the evidence too thin to code. The NTSB put “Loss of engine power (total)” first.",
        );
    });
    it("not coded uses S4's fixed sentence", () => {
        expect(differenceSentence(kase(5))).toBe(
            "A document in the docket held the NTSB's probable cause, so the case could not be shown to the agent.",
        );
    });
    it("awaiting the NTSB's codes", () => {
        expect(differenceSentence(kase(6))).toBe(
            "The NTSB has not published its codes yet. The agent put “Loss of engine power (partial)” first.",
        );
    });
});

describe("the opened case's lines", () => {
    it("lists the facts, documents read as 'N of M'", () => {
        expect(factsLine(kase(1))).toEqual([
            "XXX26XX001",
            "closed 9 Oct 2026",
            "took 47 days",
            "Aeroplane, 1 piston",
            "TX",
            "Personal",
            "Fatal",
            "3 of 5 documents read",
        ]);
    });
    it("says when the case was coded and that the verdict was withheld", () => {
        expect(withheldLine(kase(1))).toBe(
            "Coded 9 Oct 2026, 03:14 UTC, from the docket as published at closure. The NTSB's cause and codes were withheld from the agent. Code version a1b2c3d.",
        );
        expect(withheldLine(kase(5))).toBeNull();
    });
    it("builds the docket address from the NTSB's case key, or none", () => {
        expect(docketUrl(900101)).toBe("https://data.ntsb.gov/Docket?ProjectID=900101");
        expect(docketUrl(null)).toBeNull();
    });
    it("builds the NTSB's final report address from the case key, or none", () => {
        // Checked 2026-10-13 against a 2009 development case: a PDF final report naming the case.
        expect(caseReportUrl(73354)).toBe(
            "https://data.ntsb.gov/carol-repgen/api/Aviation/ReportMain/GenerateNewestReport/73354/pdf",
        );
        expect(caseReportUrl(null)).toBeNull();
    });
    it("never writes undefined or an empty item for any sample case", () => {
        for (const n of [1, 2, 3, 4, 5, 6, 7]) {
            const c = kase(n);
            for (const text of [differenceSentence(c), ...factsLine(c)]) {
                expect(text).not.toMatch(/undefined|null|NaN/);
                expect(text.trim()).not.toBe("");
            }
        }
    });
});
