// Every word the board and the opened case write, from the export alone (S5 spec §4, §5). Pure
// functions: no model call and no I/O. The difference sentence is written here from the two
// code lists (spec §5 part 2; decision 0173 item 5 on S4's branch leaves its wording to S5).
import type { Aircraft, CaseFile, Code } from "./board-case-types";
import type { BoardIndex, BoardRow } from "./board-index-types";

export type Grade = BoardRow["grade"];
export type MarkShape = "filled" | "half" | "open" | "dashed" | "square" | "diamond";

/** Each grade's word and mark (spec §4). Shape carries the meaning, never colour (§11). */
export const GRADES: Record<Grade, { word: string; mark: MarkShape }> = {
    same_first: { word: "same first code", mark: "filled" },
    same_codes_other_order: { word: "same codes in another order", mark: "half" },
    different: { word: "different", mark: "open" },
    abstained: { word: "agent abstained", mark: "dashed" },
    not_coded: { word: "not coded", mark: "square" },
    awaiting_ntsb: { word: "awaiting the NTSB's codes", mark: "diamond" },
};

const GRADE_ORDER: readonly Grade[] = [
    "same_first",
    "same_codes_other_order",
    "different",
    "abstained",
    "not_coded",
    "awaiting_ntsb",
];

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** The event part of an NTSB "phase / event" label. */
export function eventOf(label: string): string {
    const cut = label.lastIndexOf(" / ");
    return cut === -1 ? label : label.slice(cut + 3);
}

function dateParts(iso: string): { year: number; month: number; day: number } {
    // A calendar date, read by its parts so no time zone can move it.
    const [year, month, day] = iso.slice(0, 10).split("-").map(Number);
    return { year: year ?? 0, month: month ?? 1, day: day ?? 1 };
}

/** "9 Oct". */
export function closedLabel(iso: string): string {
    const { month, day } = dateParts(iso);
    return `${String(day)} ${MONTHS[month - 1] ?? ""}`;
}

/** "9 Oct 2026". */
export function closedLong(iso: string): string {
    const { year } = dateParts(iso);
    return `${closedLabel(iso)} ${String(year)}`;
}

/** How long the investigation ran: days under two months, else whole months. */
export function tookLabel(days: number): string {
    if (days < 60) return days === 1 ? "1 day" : `${String(days)} days`;
    return `${String(Math.floor(days / 30.44))} mo`;
}

const CATEGORIES: Record<string, string> = { Airplane: "Aeroplane" };
const ENGINE_TYPES: Record<string, string> = {
    Reciprocating: "piston",
    "Turbo prop": "turboprop",
    "Turbo shaft": "turboshaft",
    "Turbo fan": "turbofan",
    "Turbo jet": "turbojet",
    Electric: "electric",
};

/** "Aeroplane, 1 piston": category and engines, never make or model (spec §4). */
export function aircraftLabel(aircraft: Aircraft): string {
    const { category, engines, engine_type: engineType } = aircraft;
    const kind =
        engineType === null ? null : (ENGINE_TYPES[engineType] ?? engineType.toLowerCase());
    let power: string | null = null;
    if (engines !== null && kind !== null) power = `${String(engines)} ${kind}`;
    else if (engines !== null) power = engines === 1 ? "1 engine" : `${String(engines)} engines`;
    else if (kind !== null) power = kind;
    const parts = [category === null ? null : (CATEGORIES[category] ?? category), power].filter(
        (p): p is string => p !== null,
    );
    return parts.length === 0 ? "Not recorded" : parts.join(", ");
}

function timeOf(isoDateTime: string): string {
    return isoDateTime.slice(11, 16);
}

/** "Updated 06:00 UTC, 10 Oct · last closures 9 Oct": the export's own time, never the site's. */
export function stampLine(index: BoardIndex): string {
    const built = index.stamp.built_at;
    const updated = `Updated ${timeOf(built)} UTC, ${closedLabel(built)}`;
    const latest = index.rows
        .map((r) => r.closed_on)
        .sort()
        .at(-1);
    return latest === undefined
        ? `${updated} · no closures yet`
        : `${updated} · last closures ${closedLabel(latest)}`;
}

/** The grades present, in the board's order, each with its count. */
export function gradeCounts(rows: readonly BoardRow[]): { grade: Grade; count: number }[] {
    const counts = new Map<Grade, number>();
    for (const row of rows) counts.set(row.grade, (counts.get(row.grade) ?? 0) + 1);
    return GRADE_ORDER.filter((g) => (counts.get(g) ?? 0) > 0).map((g) => ({
        grade: g,
        count: counts.get(g) ?? 0,
    }));
}

/** Counts since launch for each grade, abstains and failures included; no percentage (§12 item 10). */
export function totalsLine(rows: readonly BoardRow[]): string {
    const parts = gradeCounts(rows).map(
        ({ grade, count }) => `${String(count)} ${GRADES[grade].word}`,
    );
    return parts.length === 0
        ? "Since launch: no cases yet."
        : `Since launch: ${parts.join(", ")}.`;
}

/**
 * How to name two first codes side by side: by their event, unless the two codes differ but
 * share an event, when only the phase tells them apart and both are named in full (review,
 * 2026-10-13: S2.7 put 15 of 40 misses down to the wrong phase).
 */
export function firstNames(
    agent: Code | null,
    ntsb: Code | null,
): { agent: string | null; ntsb: string | null } {
    const full =
        agent !== null &&
        ntsb !== null &&
        agent.code !== ntsb.code &&
        eventOf(agent.label) === eventOf(ntsb.label);
    const name = (c: Code | null): string | null =>
        c === null ? null : full ? c.label : eventOf(c.label);
    return { agent: name(agent), ntsb: name(ntsb) };
}

/** What to say where the NTSB's part is missing: unpublished only when that is known. */
export function ntsbMissing(grade: Grade): string {
    return grade === "awaiting_ntsb" ? "Not yet published." : "Not available.";
}

/** The commit that coded the case, in the public repository (spec §5). */
const REPO_URL = "https://github.com/floyda/ntsb-probable-cause";

export function commitUrl(commit: string): string {
    return `${REPO_URL}/commit/${commit}`;
}

/** A repository path on GitHub's main branch: a file as a blob, a folder (ending "/") as a tree. */
export function repoUrl(path: string): string {
    return path.endsWith("/")
        ? `${REPO_URL}/tree/main/${path.replace(/\/$/, "")}`
        : `${REPO_URL}/blob/main/${path}`;
}

/** One sentence on where the two codings differ, written from the codes alone (spec §5). */
export function differenceSentence(c: CaseFile): string {
    if (c.grade === "not_coded") {
        return c.not_coded?.sentence ?? "The case was not coded.";
    }
    const agent = c.answer?.occurrence ?? [];
    const ntsb = c.verdict?.occurrence ?? [];
    const agentFirst = agent[0];
    const ntsbFirst = ntsb[0];
    const names = firstNames(agentFirst ?? null, ntsbFirst ?? null);
    const q = (name: string | null): string => `“${name ?? ""}”`;
    const ntsbClause =
        ntsbFirst === undefined
            ? "The NTSB has not published its codes yet."
            : `The NTSB put ${q(names.ntsb)} first.`;

    if (c.grade === "abstained") {
        return `The agent abstained: it judged the evidence too thin to code. ${ntsbClause}`;
    }
    if (c.grade === "awaiting_ntsb" || ntsbFirst === undefined) {
        const agentClause =
            agentFirst === undefined ? "" : ` The agent put ${q(names.agent)} first.`;
        return `The NTSB has not published its codes yet.${agentClause}`;
    }
    if (agentFirst === undefined) return ntsbClause;
    if (c.grade === "same_first") {
        const allSame = [
            ...(c.comparison?.agent_occurrence ?? []),
            ...(c.comparison?.ntsb_occurrence ?? []),
        ].every((m) => m.mark === "same_place");
        const tail = allSame ? "and their sequences match" : "and their later codes differ";
        return `Both put ${q(names.ntsb)} first, ${tail}.`;
    }
    if (c.grade === "same_codes_other_order") {
        return `Both name ${q(names.ntsb)}. The NTSB put it first; the agent put ${q(names.agent)} first.`;
    }
    const at = agent.findIndex((code) => code.code === ntsbFirst.code);
    const named =
        at === -1
            ? "did not name the NTSB's first code"
            : "named the NTSB's first code, but not in its first three";
    return `${ntsbClause} The agent put ${q(names.agent)} first and ${named}.`;
}

/** The opened case's line of facts, as separate items (spec §5 part 1). */
export function factsLine(c: CaseFile): string[] {
    const items = [
        c.case_number,
        `closed ${closedLong(c.closed_on)}`,
        `took ${tookLabel(c.took_days)}`,
        aircraftLabel(c.aircraft),
    ];
    const f = c.facts;
    if (f !== null) {
        for (const value of [f.state, f.kind_of_flight, f.injury_level]) {
            if (value !== null && value.trim() !== "") items.push(value);
        }
        items.push(`${String(f.documents_read)} of ${String(f.documents_listed)} documents read`);
    }
    return items;
}

/** When the case was coded, with the verdict withheld (spec §5); null when not coded. */
export function withheldLine(c: CaseFile): string | null {
    const w = c.withheld;
    if (w === null || w.coded_at === null) return null;
    return (
        `Coded ${closedLong(w.coded_at)}, ${timeOf(w.coded_at)} UTC, from the docket as published` +
        " at closure. The NTSB's cause and codes were withheld from the agent."
    );
}

/** The case's public docket (spike session 5: data.ntsb.gov/Docket?ProjectID={mKey}). */
export function docketUrl(mkey: number | null): string | null {
    return mkey === null ? null : `https://data.ntsb.gov/Docket?ProjectID=${String(mkey)}`;
}

/**
 * The NTSB's final report for the case, a PDF. The address was checked on 2026-10-13 against a
 * 2009 development-split case: it returned that case's "Aviation Investigation Final Report".
 */
export function caseReportUrl(mkey: number | null): string | null {
    return mkey === null
        ? null
        : `https://data.ntsb.gov/carol-repgen/api/Aviation/ReportMain/GenerateNewestReport/${String(mkey)}/pdf`;
}
