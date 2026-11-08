// The Path page's worded claims (spec §7.2), each tied to the figures it rests on. A page that
// says "no better than guessing" or "about the same bill" must stop building when a re-run
// makes that untrue, rather than print it (plan Review Focus 5; review, 2026-10-14).
import { entry, list, NumbersError, type Entry } from "./numbers";

/** How far two bills may differ and still be "about the same": S3.2's registered band (0145). */
export const SAME_BILL_BAND = 0.1;

export interface Claim {
    id: string;
    says: string;
    holds: boolean;
}

function within(e: Entry, x: number): boolean {
    return e.low !== null && e.high !== null && e.low <= x && x <= e.high;
}

function below(e: Entry, x: number): boolean {
    return e.high !== null && e.high < x;
}

/** Every claim, judged on the entries `get` returns (the numbers file, unless a test passes one). */
export function pathClaims(get: (key: string) => Entry = entry): Claim[] {
    const loopBill = get("ladder.loop.billed").value;
    const fixedBill = get("ladder.fixed.billed").value;
    const vsFixed = get("q7.loop_vs_fixed").value;
    const vsAnswer = get("q7.loop_vs_answer").value;
    const n = (key: string): number => get(`q7.path.${key}`).value;
    // Each move must carry its checkpoint's count to the next, over every case counted.
    const carries = (move: string, from: string, to: string): boolean =>
        n(`${move}.stayed_right`) + n(`${move}.broken`) === n(from) &&
        n(`${move}.stayed_right`) + n(`${move}.fixed`) === n(to) &&
        n(`${move}.stayed_right`) +
            n(`${move}.fixed`) +
            n(`${move}.broken`) +
            n(`${move}.stayed_wrong`) ===
            n("cases");
    return [
        {
            // The first page's answer to question 3 (S5 step 6b): reading the docket is the
            // largest rise between neighbouring steps of the ladder.
            id: "q3.largest_gain",
            says: "reading the docket is the largest gain on the ladder",
            holds: ((): boolean => {
                const v = (k: string): number => get(`ladder.${k}.top1`).value;
                const gain = v("fixed") - v("no_docket");
                return gain > v("no_docket") - v("baseline") && gain > v("loop") - v("fixed");
            })(),
        },
        {
            id: "q2.no_better_than_guessing",
            says: "the case record alone did no better than guessing",
            holds: within(get("ladder.no_docket.top1"), get("ladder.baseline.top1").value),
        },
        {
            id: "q4.not_shown_to_help",
            says: "transcription's interval includes zero",
            holds: within(get("q4.v2_gain"), 0),
        },
        {
            id: "q7.loop_worse",
            says: "the loop was worse than the fixed pipeline on the first code",
            holds: below(get("q7.loop_vs_fixed"), 0),
        },
        {
            id: "q7.docket_mattered",
            says: "without the docket the loop did worse",
            holds: below(get("q7.no_docket_loss"), 0),
        },
        {
            id: "q7.same_bill",
            says: "the loop's bill was about the same as the pipeline's",
            holds: Math.abs(loopBill / fixedBill - 1) <= SAME_BILL_BAND,
        },
        {
            id: "q7.path_adds_up",
            says: "question 7's figure: each checkpoint's count carries to the next",
            holds: carries("reading", "before", "after") && carries("coding", "after", "answer"),
        },
        {
            id: "q7.path_improves",
            says: "question 7's figure: the loop improves from each point to the next",
            holds: n("before") < n("after") && n("after") < n("answer"),
        },
        {
            id: "q7.lead_from_tools",
            says: "most of the pipeline's lead came after its first answer",
            holds: vsFixed < 0 && Math.abs(vsAnswer) < Math.abs(vsFixed) / 2,
        },
    ];
}

/** Throws, naming every claim that no longer holds. */
export function assertPathClaims(get: (key: string) => Entry = entry): void {
    const broken = pathClaims(get).filter((c) => !c.holds);
    if (broken.length > 0) {
        throw new NumbersError(
            `the Path page's wording no longer fits its figures: ${broken.map((c) => `${c.id} (${c.says})`).join("; ")}`,
        );
    }
}

/** Whether one claim holds, for a component whose wording depends on it. */
export function claimHolds(id: string, get: (key: string) => Entry = entry): boolean {
    const claim = pathClaims(get).find((c) => c.id === id);
    if (claim === undefined) throw new NumbersError(`no claim ${id}`);
    return claim.holds;
}

/**
 * The predictions the Methods page was read against (S5 step 5, Task 3): those S3.2's claims
 * file scores met. The page prints every outcome from the numbers file; this stops the build when
 * a changed file would change which were met, until the page is read again.
 */
export const PREDICTIONS_MET: readonly number[] = [3, 7, 8, 9];

/** Throws unless the predictions met are exactly `PREDICTIONS_MET`. */
export function assertPredictionsAsRead(
    items: readonly Record<string, string | number>[] = list("s32.predictions"),
): void {
    const met = items.filter((p) => p["outcome"] === "met").map((p) => p["number"]);
    if (items.length !== 9 || met.join(",") !== PREDICTIONS_MET.join(",")) {
        throw new NumbersError(
            `S3.2's predictions met are now ${met.join(", ")}, not ${PREDICTIONS_MET.join(", ")}: read the Methods page again`,
        );
    }
}
