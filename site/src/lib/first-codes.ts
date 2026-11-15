// Question 6's figure shows the commonest first codes until they cover at least half the
// sentence's cases, and gathers the rest under one line (Andy, 2026-10-14). A code tied with the
// last one shown is shown too, so the file's order never decides which.

export interface Shown<T> {
    shown: T[];
    rest: T[];
    restCases: number;
}

/** Split rows (most common first) at the point they first cover half the cases. */
export function halfShown<T extends { count: number }>(rows: readonly T[]): Shown<T> {
    const total = rows.reduce((sum, r) => sum + r.count, 0);
    let covered = 0;
    let cut = 0;
    while (cut < rows.length && covered * 2 < total) {
        covered += rows[cut]?.count ?? 0;
        cut++;
    }
    const last = rows[cut - 1]?.count;
    while (cut < rows.length && rows[cut]?.count === last) cut++;
    const rest = rows.slice(cut);
    return {
        shown: rows.slice(0, cut),
        rest,
        restCases: rest.reduce((sum, r) => sum + r.count, 0),
    };
}
