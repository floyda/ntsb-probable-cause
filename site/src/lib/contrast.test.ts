import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

// The Quiet look's colour pairs (S5 step 6a, Task 1), checked by number in both themes. axe checks
// the built pages too; this catches a token change before any page is built.
const css = readFileSync(join(__dirname, "..", "styles", "tokens.css"), "utf8");

function block(source: string): Record<string, string> {
    const pairs: [string, string][] = [
        ...source.matchAll(/(--[\w-]+):\s*(#[0-9a-fA-F]{6})\s*;/g),
    ].map((m) => [m[1] ?? "", m[2] ?? ""]);
    return Object.fromEntries(pairs);
}

const light = block(/:root\s*{([\s\S]*?)}/.exec(css)?.[1] ?? "");
const dark = {
    ...light,
    ...block(/prefers-color-scheme:\s*dark\)\s*{\s*:root\s*{([\s\S]*?)}/.exec(css)?.[1] ?? ""),
};

/** WCAG 2.2's contrast ratio between two #rrggbb colours. */
function ratio(a: string, b: string): number {
    const lum = (hex: string): number => {
        const [r, g, bl] = [1, 3, 5].map((i) => {
            const c = parseInt(hex.slice(i, i + 2), 16) / 255;
            return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
        });
        return 0.2126 * (r ?? 0) + 0.7152 * (g ?? 0) + 0.0722 * (bl ?? 0);
    };
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
    return ((hi ?? 0) + 0.05) / ((lo ?? 0) + 0.05);
}

// Text on a surface: each needs 4.5:1 (WCAG 1.4.3).
const TEXT_PAIRS: [string, string][] = [
    ["--ink", "--ground"],
    ["--ink", "--paper"],
    ["--ink-muted", "--ground"],
    ["--ink-muted", "--paper"],
    ["--sign-ink", "--sign"],
    ["--board-ink", "--board-ground"],
    ["--board-dim", "--board-ground"],
];

describe("the Quiet look's colours (S5 step 6a)", () => {
    it("reads the colour tokens in both themes", () => {
        expect(Object.keys(light).length).toBeGreaterThan(10);
        expect(dark["--ground"]).not.toBe(light["--ground"]);
    });
    for (const [theme, tokens] of [
        ["light", light],
        ["dark", dark],
    ] as const) {
        it.each(TEXT_PAIRS)(`${theme}: %s on %s is at least 4.5:1`, (fg, bg) => {
            const a = tokens[fg];
            const b = tokens[bg];
            expect(a, fg).toBeDefined();
            expect(b, bg).toBeDefined();
            expect(ratio(a ?? "", b ?? "")).toBeGreaterThanOrEqual(4.5);
        });
    }
    it("computes a known ratio", () => {
        expect(ratio("#000000", "#ffffff")).toBeCloseTo(21, 5);
    });
});
