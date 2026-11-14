// The Open cases page's words (spec §8; S5 step 6c): counts only, from the export's `counts`.
// An open case enters the site only as a number (decision 0024), so nothing here takes a row.
import type { Counts } from "./board-index-types";
import { closedLong } from "./words";

/** The page's counted lines. "Most have no docket" is said only while the counts bear it out. */
export function openLines(c: Counts): string[] {
    const watched =
        c.open_watched === 1
            ? "1 open case is being watched."
            : `${String(c.open_watched)} open cases are being watched.`;
    const docket = `${String(c.open_with_docket)} of them ${c.open_with_docket === 1 ? "has" : "have"} a docket so far.`;
    const lines = [watched, docket, "Ellery runs once on each case, when the NTSB closes it."];
    if (c.open_watched > 0 && c.open_with_docket * 2 < c.open_watched) {
        lines.push("Most open cases have no docket to read until then.");
    }
    return lines;
}

export interface NightRow {
    night: string;
    label: string;
    count: number;
}

/**
 * Stops the build on counts that cannot be true: an export written without the recorder's store
 * has zero counts (S4's `board.py`), which the page would state as fact (review, 2026-11-01).
 */
export function checkCounts(c: Counts, rows: number): void {
    if (rows > 0 && c.open_watched === 0) {
        throw new Error("open cases: the export has closed cases but watches no open case");
    }
    if (c.open_with_docket > c.open_watched) {
        throw new Error("open cases: more open cases with a docket than open cases watched");
    }
}

/** The closures on each night, newest first. */
export function closureNights(c: Counts): NightRow[] {
    return Object.entries(c.closures_per_night)
        .flatMap(([night, count]) =>
            count === undefined ? [] : [{ night, label: closedLong(night), count }],
        )
        .sort((a, b) => b.night.localeCompare(a.night));
}
