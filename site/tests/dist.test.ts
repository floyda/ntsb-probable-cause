// Checks over the built pages (S5 step 2): run after `pnpm run build`.
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";
import { exportDir, loadExport } from "../src/lib/export";
import { costLabel } from "../src/lib/trail";
import { differenceSentence } from "../src/lib/words";

const DIST = join(process.cwd(), "dist");
const built = existsSync(join(DIST, "index.html"));

/** The text a reader sees: tags and the contents of script and style removed. */
function visibleText(html: string): string {
    return html
        .replace(/<(script|style)[\s\S]*?<\/\1>/g, " ")
        .replace(/<[^>]+>/g, " ")
        .replace(/&#x27;|&#39;/g, "'")
        .replace(/&quot;/g, '"')
        .replace(/&amp;/g, "&")
        .replace(/\s+/g, " ");
}

describe.skipIf(!built)("the built case pages (needs `pnpm run build` first)", () => {
    const { cases } = loadExport(exportDir());

    it.each([...cases.keys()])("%s has its own page with its difference sentence", (n) => {
        const kase = cases.get(n);
        expect(kase).toBeDefined();
        if (kase === undefined) return;
        const html = readFileSync(join(DIST, "case", n, "index.html"), "utf8");
        const text = visibleText(html);
        expect(text).toContain(differenceSentence(kase));
        expect(text).not.toMatch(/\b(undefined|null|NaN)\b/);
    });
});

/** Every built HTML file, by its path under dist/. */
function htmlFiles(dir: string = DIST): string[] {
    const found: string[] = [];
    for (const name of readdirSync(dir)) {
        const path = join(dir, name);
        if (statSync(path).isDirectory()) found.push(...htmlFiles(path));
        else if (name.endsWith(".html")) found.push(path);
    }
    return found;
}

function builtFileFor(href: string): string {
    const path = href.split(/[?#]/)[0] ?? "/";
    if (path.endsWith("/")) return join(DIST, path, "index.html");
    const last = path.split("/").pop() ?? "";
    return last.includes(".") ? join(DIST, path) : join(DIST, path, "index.html");
}

describe.skipIf(!built)("the opened case says only what is known (review, 2026-10-13)", () => {
    const { cases } = loadExport(exportDir());
    const page = (n: string): string =>
        visibleText(readFileSync(join(DIST, "case", n, "index.html"), "utf8"));
    const get = (n: string) => {
        const k = cases.get(n);
        if (k === undefined) throw new Error(`sample lacks ${n}`);
        return k;
    };

    it("an awaiting case still lists the agent's findings", () => {
        const label = get("XXX26XX006").answer?.findings[0]?.label ?? "missing";
        expect(page("XXX26XX006")).toContain(label);
    });

    it("a not-coded case still lists the NTSB's findings", () => {
        const label = get("XXX26XX005").verdict?.findings[0]?.label ?? "missing";
        expect(page("XXX26XX005")).toContain(label);
    });

    it("an abstained case shows no graded agent codes", () => {
        const leaning = get("XXX26XX004").answer?.occurrence[0]?.label ?? "missing";
        expect(page("XXX26XX004")).not.toContain(leaning);
    });

    it("an unreadable case never claims the NTSB has not published", () => {
        expect(page("XXX26XX007")).not.toContain("Not yet published");
    });

    it("the code version links to its commit", () => {
        const html = readFileSync(join(DIST, "case", "XXX26XX001", "index.html"), "utf8");
        expect(html).toContain(
            'href="https://github.com/floyda/ntsb-probable-cause/commit/a1b2c3d"',
        );
    });
});

describe.skipIf(!built)("checks over every built page (needs `pnpm run build` first)", () => {
    const pages = built ? htmlFiles() : [];

    it("gives a page only to the cases on the board (S4 may leave dropped files behind)", () => {
        const { index } = loadExport(exportDir());
        const listed = new Set(index.rows.map((r) => r.case_number));
        const caseDir = join(DIST, "case");
        const built = existsSync(caseDir) ? readdirSync(caseDir) : [];
        expect(built.filter((n) => !listed.has(n))).toEqual([]);
        expect([...listed].filter((n) => !built.includes(n))).toEqual([]);
    });

    it.each(pages.map((p) => relative(DIST, p).split(sep).join("/")))(
        "%s has no inline script or style (the Content-Security-Policy is 'self')",
        (page) => {
            const html = readFileSync(join(DIST, page), "utf8");
            expect(html).not.toMatch(/<script(?![^>]*\ssrc=)[^>]*>/);
            expect(html).not.toMatch(/<style[\s>]/);
        },
    );

    it.each(pages.map((p) => relative(DIST, p).split(sep).join("/")))(
        "%s links only to pages and files that exist",
        (page) => {
            const html = readFileSync(join(DIST, page), "utf8");
            const hrefs = [...html.matchAll(/\s(?:href|src)="(\/[^"]*)"/g)].map((m) => m[1] ?? "/");
            const missing = hrefs.filter((href) => !existsSync(builtFileFor(href)));
            expect(missing).toEqual([]);
        },
    );

    it.each(pages.map((p) => relative(DIST, p).split(sep).join("/")))(
        "%s shows no aircraft registration",
        (page) => {
            const text = visibleText(readFileSync(join(DIST, page), "utf8"));
            const found = [...text.matchAll(/\bN[1-9][0-9A-HJ-NP-Z]{2,5}\b/g)]
                .map((m) => m[0])
                .filter((m) => (m.match(/[0-9]/g) ?? []).length >= 2);
            expect(found).toEqual([]);
        },
    );
});

describe.skipIf(!built)("the trail pages (needs `pnpm run build` first)", () => {
    const { cases } = loadExport(exportDir());
    const withTrail = [...cases.values()].filter((k) => k.trail !== null);
    const trailText = (n: string): string =>
        visibleText(readFileSync(join(DIST, "case", n, "trail", "index.html"), "utf8"));

    it("exist exactly for the cases that have a trail", () => {
        const expected = withTrail.map((k) => k.case_number).sort();
        const found = [...cases.keys()]
            .filter((n) => existsSync(join(DIST, "case", n, "trail", "index.html")))
            .sort();
        expect(found).toEqual(expected);
        const caseDir = join(DIST, "case");
        const stray = readdirSync(caseDir).filter(
            (n) => existsSync(join(caseDir, n, "trail")) && !expected.includes(n),
        );
        expect(stray).toEqual([]);
    });

    it.each(withTrail.map((k) => k.case_number))(
        "%s shows every belief's cause and the total cost",
        (n) => {
            const kase = cases.get(n);
            if (kase?.trail == null) throw new Error(`no trail for ${n}`);
            const text = trailText(n);
            for (const belief of kase.trail.beliefs) expect(text).toContain(belief.cause);
            expect(text).toContain(costLabel(kase.trail.total_usd));
        },
    );

    it.each(withTrail.map((k) => k.case_number))(
        "%s never calls the agent's notes predictions (spec §6)",
        (n) => {
            expect(trailText(n).toLowerCase()).not.toContain("predict");
        },
    );
});
