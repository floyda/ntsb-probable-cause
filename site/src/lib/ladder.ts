// The ladder (S5 spec §7.1): four ways of coding an accident, each with more machinery than the
// one before, drawn as horizontal bars from zero with a whisker for each 95% interval. Laid out
// here, at build time, as pure geometry; Ladder.astro only draws it. Labels sit above and below
// each bar, never beside it, so a phone needs no rotated or clipped text.
import { entry, usd, withInterval } from "./numbers";

export interface LadderStep {
    key: string;
    label: string;
    plain: string;
    rate: string;
    cost: string | null;
    billed: string | null;
}

/** The four steps, in order of machinery (spec §7.1; Andy, 2026-10-05). */
export const LADDER: readonly LadderStep[] = [
    {
        key: "baseline",
        label: "1. No model",
        plain: "always guess the commonest code",
        rate: "ladder.baseline.top1",
        cost: null,
        billed: null,
    },
    {
        key: "no_docket",
        label: "2. The case record only",
        plain: "the agent with the recorded facts, no documents",
        rate: "ladder.no_docket.top1",
        cost: "ladder.no_docket.cost",
        billed: null,
    },
    {
        key: "fixed",
        label: "3. Every document, fixed order",
        plain: "the fixed pipeline",
        rate: "ladder.fixed.top1",
        cost: "ladder.fixed.cost",
        billed: "ladder.fixed.billed",
    },
    {
        key: "loop",
        label: "4. Choosing what to read",
        plain: "the loop, version 1",
        rate: "ladder.loop.top1",
        cost: "ladder.loop.cost",
        billed: "ladder.loop.billed",
    },
];

export interface Box {
    x0: number;
    x1: number;
    top: number;
    bottom: number;
}

export type LabelRole = "title" | "plain" | "value" | "cost" | "tick" | "guess";

export interface Label {
    text: string;
    role: LabelRole;
    /** The text's anchor point and baseline, as SVG draws it. */
    x: number;
    y: number;
    anchor: "start" | "middle" | "end";
    size: number;
    bold: boolean;
    /** The space the text is estimated to take, for the overlap and width checks. */
    box: Box;
}

export interface Bar {
    key: string;
    x: number;
    y: number;
    width: number;
    height: number;
    /** The interval's two ends, in plot x. */
    whisker: [number, number];
}

export interface LadderGeometry {
    width: number;
    height: number;
    plotWidth: number;
    scaleMax: number;
    baselineX: number;
    bars: Bar[];
    /** Where the always-guessing mark crosses each bar: [top, bottom]. */
    marks: [number, number][];
    /** The axis line's y and its ticks' x. */
    axisY: number;
    ticks: number[];
    labels: Label[];
}

const TITLE = 15;
const SMALL = 13;
const TICK = 12;
const LEADING = 1.4;
const BAR = 16;
const GAP = 6;
const STEP_GAP = 20;
const MARK_REACH = 4;
// An over-estimate of Atkinson Hyperlegible Next's mean advance, so a label measured here as
// fitting fits on the page (checked at phone width by the a11y suite's rendered boxes).
const ADVANCE = 0.6;
const ADVANCE_BOLD = 0.64;
// Room at the right for the last whisker's cap and the last tick's label.
const RIGHT = 4;

const estimate = (text: string, size: number, bold: boolean): number =>
    text.length * size * (bold ? ADVANCE_BOLD : ADVANCE);

function wrap(text: string, size: number, bold: boolean, width: number): string[] {
    const lines: string[] = [];
    let line = "";
    for (const word of text.split(" ")) {
        const next = line === "" ? word : `${line} ${word}`;
        if (line !== "" && estimate(next, size, bold) > width) {
            lines.push(line);
            line = word;
        } else line = next;
    }
    if (line !== "") lines.push(line);
    return lines;
}

function costText(step: LadderStep): string {
    if (step.cost === null) return "no model cost";
    const list = `list ${usd(step.cost)}`;
    return step.billed === null ? list : `${list} · billed ${usd(step.billed)}`;
}

/** The ladder's geometry at one drawing width. */
export function ladderLayout(steps: readonly LadderStep[], width: number): LadderGeometry {
    const plotWidth = width - RIGHT;
    const highs = steps.map((s) => entry(s.rate).high ?? entry(s.rate).value);
    const scaleMax = Math.ceil(Math.max(...highs) / 10) * 10;
    const x = (percent: number): number => (percent / scaleMax) * plotWidth;
    const labels: Label[] = [];
    const bars: Bar[] = [];
    let y = 0;

    const line = (text: string, role: LabelRole, size: number, bold = false): void => {
        const w = estimate(text, size, bold);
        const baseline = y + size;
        labels.push({
            text,
            role,
            x: 0,
            y: baseline,
            anchor: "start",
            size,
            bold,
            box: { x0: 0, x1: w, top: y, bottom: y + size * LEADING },
        });
        y += size * LEADING;
    };
    const block = (text: string, role: LabelRole, size: number, bold = false): void => {
        for (const part of wrap(text, size, bold, plotWidth)) line(part, role, size, bold);
    };

    for (const [i, step] of steps.entries()) {
        if (i > 0) y += STEP_GAP;
        block(step.label, "title", TITLE, true);
        block(step.plain, "plain", SMALL);
        y += GAP;
        const e = entry(step.rate);
        bars.push({
            key: step.key,
            x: 0,
            y,
            width: x(e.value),
            height: BAR,
            whisker: [x(e.low ?? e.value), x(e.high ?? e.value)],
        });
        y += BAR + GAP;
        block(withInterval(step.rate), "value", SMALL);
        block(costText(step), "cost", SMALL);
    }

    // The axis: a line and a tick every 10%, under the last step.
    y += STEP_GAP / 2;
    const axisY = y;
    const ticks: number[] = [];
    for (let t = 0; t <= scaleMax; t += 10) ticks.push(x(t));
    y += 4;
    for (const [i, tx] of ticks.entries()) {
        const text = `${String(i * 10)}%`;
        const w = estimate(text, TICK, false);
        const anchor = i === 0 ? "start" : i === ticks.length - 1 ? "end" : "middle";
        const x0 = anchor === "start" ? tx : anchor === "end" ? tx - w : tx - w / 2;
        labels.push({
            text,
            role: "tick",
            x: tx,
            y: y + TICK,
            anchor,
            size: TICK,
            bold: false,
            box: { x0, x1: x0 + w, top: y, bottom: y + TICK * LEADING },
        });
    }
    y += TICK * LEADING + GAP;

    // The always-guessing mark's own label, in a row of its own beneath the ticks.
    const baselineX = x(entry("ladder.baseline.top1").value);
    const guess = "dashed mark: always guessing";
    const gw = estimate(guess, SMALL, false);
    const gx0 = Math.min(Math.max(baselineX - gw / 2, 0), width - gw);
    labels.push({
        text: guess,
        role: "guess",
        x: gx0,
        y: y + SMALL,
        anchor: "start",
        size: SMALL,
        bold: false,
        box: { x0: gx0, x1: gx0 + gw, top: y, bottom: y + SMALL * LEADING },
    });
    y += SMALL * LEADING;

    const marks = bars.map((b): [number, number] => [
        b.y - MARK_REACH,
        b.y + b.height + MARK_REACH,
    ]);
    return {
        width,
        height: Math.ceil(y),
        plotWidth,
        scaleMax,
        baselineX,
        bars,
        marks,
        axisY,
        ticks,
        labels,
    };
}
