// Checks over the built pages (S5 step 2): run after `pnpm run build`.
import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import { describe, expect, it } from "vitest";
import { exampleCase } from "../src/lib/example-case";
import { exportDir, loadExport, onSample } from "../src/lib/export";
import { findingParts, findingRows } from "../src/lib/findings";
import { LADDER } from "../src/lib/ladder";
import { anchorFor, shown } from "../src/lib/methods";
import { cardFor, cardVersion } from "../src/lib/cards";
import { closureNights, openLines } from "../src/lib/open";
import { ROUTE_QUESTIONS } from "../src/lib/route";
import { AUTHOR_URL, PAGES } from "../src/lib/site";
import { count, countOf, numbers, pointsOn, usd, withInterval } from "../src/lib/numbers";
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

// These name cases of the sample, so a real export skips them (the morning build, publish mode).
const onSampleOnly = describe.skipIf(!built || !onSample());

onSampleOnly("the opened case says only what is known (review, 2026-10-13)", () => {
    const { cases } = loadExport(exportDir());
    const page = (n: string): string =>
        visibleText(readFileSync(join(DIST, "case", n, "index.html"), "utf8"));
    const get = (n: string) => {
        const k = cases.get(n);
        if (k === undefined) throw new Error(`sample lacks ${n}`);
        return k;
    };

    it("an awaiting case still lists the agent's findings", () => {
        // Shown as its item and detail, with its area apart (step 6a).
        const parts = findingParts(get("XXX26XX006").answer?.findings[0]?.label ?? "missing");
        // Item and detail in the same finding line, not anywhere on the page (review).
        const html = readFileSync(join(DIST, "case", "XXX26XX006", "index.html"), "utf8");
        const lines = html.split('<span class="line"').slice(1).map(visibleText);
        expect(
            lines.some((l) => l.includes(parts.item) && l.includes(parts.detail ?? "missing")),
        ).toBe(true);
    });

    it("a not-coded case still lists the NTSB's findings", () => {
        // Shown as its item and detail, with its area apart (step 6a).
        const parts = findingParts(get("XXX26XX005").verdict?.findings[0]?.label ?? "missing");
        // Item and detail in the same finding line, not anywhere on the page (review).
        const html = readFileSync(join(DIST, "case", "XXX26XX005", "index.html"), "utf8");
        const lines = html.split('<span class="line"').slice(1).map(visibleText);
        expect(
            lines.some((l) => l.includes(parts.item) && l.includes(parts.detail ?? "missing")),
        ).toBe(true);
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
        "%s shows no account of the evidence (Andy, 2026-10-14: not until a names check)",
        (n) => {
            const kase = cases.get(n);
            if (kase?.trail == null) throw new Error(`no trail for ${n}`);
            const text = trailText(n);
            for (const belief of kase.trail.beliefs) expect(text).not.toContain(belief.account);
        },
    );

    it.each(withTrail.map((k) => k.case_number))(
        "%s never calls the agent's notes predictions (spec §6)",
        (n) => {
            expect(trailText(n).toLowerCase()).not.toContain("predict");
        },
    );
});

describe.skipIf(!built)("scrolling frames (review, 2026-10-14)", () => {
    it.each(
        htmlFiles()
            .map((p) => relative(DIST, p).split(sep).join("/"))
            .filter((p) => readFileSync(join(DIST, p), "utf8").includes('class="frame'))
            .concat(["index.html"]),
    )("%s: every sideways-scrolling frame is a labelled, focusable region (WCAG 2.1.1)", (page) => {
        const html = readFileSync(join(DIST, page), "utf8");
        const frames = [...html.matchAll(/<div[^>]*class="(?:board-frame|frame)[^"]*"[^>]*>/g)].map(
            (m) => m[0],
        );
        expect(frames.length).toBeGreaterThan(0);
        for (const frame of frames) {
            expect(frame).toMatch(/tabindex="0"/);
            expect(frame).toMatch(/role="region"/);
            expect(frame).toMatch(/aria-label(?:ledby)?="[^"]+"/);
        }
    });
});

describe.skipIf(!built)("the Path page (S5 step 4, Task 5)", () => {
    const html = (): string => readFileSync(join(DIST, "path", "index.html"), "utf8");
    const REPO_ROOT = join(process.cwd(), "..");

    it.each([
        "answer-key",
        "case-record",
        "docket",
        "scanned-pages",
        "coding",
        "consistency",
        "choosing",
        "newly-closed",
    ])("holds the question anchor #%s", (id) => {
        expect(html()).toContain(`id="${id}"`);
    });

    // Every entry in the numbers file is on the page, formatted as numbers.ts formats it, so a
    // figure cannot be dropped or retyped without this failing (spec §17.3). The history and
    // limits entries are the Methods page's alone (spec §9 items 6 and 7; S5 step 5).
    const { entries } = numbers();
    const onPath = Object.keys(entries).filter((k) => !/^(history|limits)\./.test(k));
    it.each(onPath)("shows %s as the numbers file has it", (key) => {
        const e = entries[key];
        if (e === undefined) throw new Error(key);
        const shown =
            e.unit === "percent"
                ? withInterval(key)
                : e.unit === "points"
                  ? pointsOn(key) // a paired figure always with its cases (§12 item 9)
                  : e.unit === "usd"
                    ? usd(key)
                    : e.n === null
                      ? count(key)
                      : countOf(key);
        expect(visibleText(html())).toContain(shown);
    });

    it("links only to repository paths that exist", () => {
        const links = [
            ...html().matchAll(
                /href="https:\/\/github\.com\/floyda\/ntsb-probable-cause\/(blob|tree)\/main\/([^"#]+)"/g,
            ),
        ];
        expect(links.length).toBeGreaterThan(10);
        for (const [, kind, path] of links) {
            const target = join(REPO_ROOT, path ?? "");
            expect(existsSync(target), path).toBe(true);
            expect(statSync(target).isDirectory(), path).toBe(kind === "tree");
        }
    });

    it("shows question 1's case word for word, and no other case number but the strip's", () => {
        const example = exampleCase();
        const text = visibleText(html());
        expect(text).toContain(example.cause ?? "missing");
        for (const code of example.occurrence) expect(text).toContain(code.label);
        for (const f of example.findings) expect(text).toContain(f.label);
        // Case numbers on the page: question 1's, and the board's own closed cases in the strip.
        const { index } = loadExport(exportDir());
        const allowed = new Set([example.case_number, ...index.rows.map((r) => r.case_number)]);
        const found = text.match(/\b[A-Z]{3}\d{2}[A-Z]{2}\d{3}[A-Z]?\b/g) ?? [];
        expect(found).toContain(example.case_number);
        for (const n of found) expect(allowed.has(n), n).toBe(true);
    });

    it("labels question 7's counts where they are drawn, so a swapped count fails", () => {
        // Review, 2026-10-14: a bare small count can appear anywhere on the page, so each of the
        // figure's counts is checked inside its own labelled phrase.
        const text = visibleText(html());
        const c = (key: string): string => count(`q7.path.${key}`);
        const cases = c("cases");
        for (const [name, key] of [
            ["Before reading", "before"],
            ["After reading", "after"],
            ["The answer", "answer"],
        ] as const) {
            expect(text).toContain(`${name}: ${c(key)} of ${cases} the same`);
        }
        expect(text).toContain(
            `Reading the documents it chose: ${c("reading.fixed")} became the same, ${c("reading.broken")} became different`,
        );
        expect(text).toContain(
            `The coding step: ${c("coding.fixed")} became the same, ${c("coding.broken")} became different`,
        );
        for (const move of ["reading", "coding"]) {
            const row = ["stayed_right", "fixed", "broken", "stayed_wrong"]
                .map((k) => c(`${move}.${k}`))
                .join(" ");
            expect(text).toContain(row);
        }
        expect(text).toContain(
            `${count("q6.one.distinct")} different first codes across its ${count("q6.one.cases")} cases`,
        );
    });

    it("shows question 6's sentence and every first code it received", () => {
        const text = visibleText(html());
        expect(text).toContain(numbers().texts["q6.one.sentence"] ?? "missing");
        for (const row of numbers().lists["q6.one.codes"] ?? []) {
            expect(text).toContain(String(row["label"]));
        }
        expect(text).toContain("the most different first codes");
    });

    it("gives the ladder's data table all four steps", () => {
        const tables = [
            ...html().matchAll(/<caption[^>]*>The ladder's figures<\/caption>([\s\S]*?)<\/table>/g),
        ];
        expect(tables.length).toBeGreaterThan(0);
        for (const [, body] of tables) {
            const text = visibleText(body ?? "");
            for (const step of LADDER) expect(text).toContain(`${step.label}: ${step.plain}`);
        }
    });
});

describe.skipIf(!built)("the Methods page (S5 step 5, Task 5)", () => {
    const methods = (): string => readFileSync(join(DIST, "methods", "index.html"), "utf8");
    const REPO_ROOT = join(process.cwd(), "..");
    const { entries, lists, texts } = numbers();
    const ids = (html: string): Set<string> =>
        new Set([...html.matchAll(/\sid="([^"]+)"/g)].map((m) => m[1] ?? ""));

    // Every entry has exactly one row, and the row shows its value as the other pages do.
    it.each(Object.keys(entries))("gives %s one row with its value", (key) => {
        const anchor = anchorFor(key);
        // One id on the whole page, then the row it opens (review, 2026-10-14).
        expect([...methods().matchAll(new RegExp(`\\sid="${anchor}"`, "g"))]).toHaveLength(1);
        const rows = [
            ...methods().matchAll(
                new RegExp(`<li[^>]*\\sid="${anchor}"[^>]*>([\\s\\S]*?)</li>`, "g"),
            ),
        ];
        expect(rows).toHaveLength(1);
        const row = visibleText(rows[0]?.[1] ?? "");
        const e = entries[key];
        expect(row).toContain(shown(key));
        for (const field of [e?.sample, e?.script, e?.results_file.split("/").at(-1)]) {
            expect(row).toContain(field ?? "missing");
        }
        expect(row).toContain(
            e?.model === "none" ? "none: no model call" : (e?.model ?? "missing"),
        );
        if (e?.run != null) expect(row).toContain(e.run);
    });

    it("resolves every link into Methods, from every page", () => {
        const targets = ids(methods());
        const broken: string[] = [];
        for (const page of htmlFiles()) {
            const html = readFileSync(page, "utf8");
            const own = page === join(DIST, "methods", "index.html");
            for (const m of html.matchAll(/href="(\/methods\/)?#([^"]+)"/g)) {
                if (m[1] === undefined && !own) continue; // another page's own anchor
                if (!targets.has(m[2] ?? ""))
                    broken.push(`${relative(DIST, page)} -> #${m[2] ?? ""}`);
            }
        }
        expect(broken).toEqual([]);
    });

    it("links every Path question to Methods", () => {
        const path = readFileSync(join(DIST, "path", "index.html"), "utf8");
        expect([...path.matchAll(/>How this was measured</g)]).toHaveLength(8);
    });

    it("links only to files and commits that exist", () => {
        const html = methods();
        const known = new Set(
            Object.values(entries).flatMap((e) => [e.recorded_in, e.run_commit ?? ""]),
        );
        known.add(texts["s32.registered_in"] ?? "");
        const files = [
            ...html.matchAll(
                /href="https:\/\/github\.com\/floyda\/ntsb-probable-cause\/(blob|tree)\/([0-9a-f]{40}|main)\/([^"#]+)"/g,
            ),
        ];
        expect(files.length).toBeGreaterThan(Object.keys(entries).length);
        for (const [, kind, ref, path] of files) {
            const target = join(REPO_ROOT, path ?? "");
            expect(existsSync(target), path).toBe(true);
            expect(statSync(target).isDirectory(), path).toBe(kind === "tree");
            if (ref === "main") continue;
            expect(known.has(ref ?? ""), ref).toBe(true);
            // The file as it was at that commit, not only as it is now (review, 2026-10-14).
            const type = execFileSync("git", ["cat-file", "-t", `${ref ?? ""}:${path ?? ""}`], {
                cwd: REPO_ROOT,
                encoding: "utf8",
            }).trim();
            expect(type, `${ref ?? ""}:${path ?? ""}`).toBe(kind === "tree" ? "tree" : "blob");
        }
        const commits = [
            ...html.matchAll(
                /href="https:\/\/github\.com\/floyda\/ntsb-probable-cause\/commit\/([^"]+)"/g,
            ),
        ];
        expect(commits.length).toBeGreaterThan(Object.keys(entries).length);
        for (const [, sha] of commits) expect(known.has(sha ?? ""), sha).toBe(true);
    });

    it("prints each prediction in the registration's words, with its outcome", () => {
        const text = visibleText(methods());
        // Read from the registration itself, not from the numbers file, so a parse that changed
        // a word or a colon is caught (review, 2026-10-14).
        const plain = (md: string): string => md.replace(/[*`]/g, "").replace(/\s+/g, " ").trim();
        const lines = readFileSync(join(REPO_ROOT, "docs/rounds/s3-registration.md"), "utf8").split(
            "\n",
        );
        const items: string[] = [];
        for (const line of lines.slice(lines.indexOf("## The predictions") + 1)) {
            if (line.startsWith("## ")) break;
            if (/^\d+\. /.test(line)) items.push(line.replace(/^\d+\. /, ""));
            else if (line.startsWith("   ") && items.length > 0)
                items.push(`${items.pop() ?? ""} ${line}`);
            else if (line.startsWith("Not predicted")) expect(text).toContain(plain(line));
        }
        expect(items).toHaveLength(9);
        for (const item of items) expect(text).toContain(plain(item));
        for (const p of lists["s32.predictions"] ?? []) {
            expect(text).toContain(
                `${p["outcome"] === "met" ? "Met." : "Not met."} ${String(p["result"])}`,
            );
        }
    });

    it("keeps evaluation numbers out of the board's section", () => {
        const board = /<section[^>]*id="board"[^>]*>([\s\S]*?)<\/section>/.exec(methods());
        expect(board).not.toBeNull();
        expect(board?.[1]).not.toMatch(/\sid="n-/);
    });
});

describe.skipIf(!built)("the top bar and the footer (S5 step 6a, Task 2)", () => {
    const all = htmlFiles()
        .filter((p) => !p.endsWith("404.html"))
        .map((p) => relative(DIST, p).split(sep).join("/"));
    const CURRENT: Record<string, string> = {
        "index.html": "/",
        "path/index.html": "/path/",
        "methods/index.html": "/methods/",
        "open/index.html": "/open/",
    };
    const read = (page: string): string => readFileSync(join(DIST, page), "utf8");

    it.each(all)("%s opens with a skip link to its content", (page) => {
        const html = read(page);
        const first = /<body[^>]*>[\s\S]*?<a\s[^>]*href="([^"]+)"[^>]*>([^<]*)</.exec(html);
        expect(first?.[1]).toBe("#content");
        expect(first?.[2]).toBe("Skip to content");
        expect(html).toMatch(/<main[^>]*\sid="content"/);
    });

    it.each(all)("%s has the top bar, in order, marking the right page", (page) => {
        const html = read(page);
        const head = /<header[^>]*class="site-head[\s\S]*?<\/header>/.exec(html)?.[0] ?? "";
        const hrefs = [...head.matchAll(/<a[^>]*href="([^"]+)"/g)].map((m) => m[1]);
        expect(hrefs).toEqual(["/", ...PAGES.map((p) => p.href)]);
        const marked = [...head.matchAll(/<a[^>]*href="([^"]+)"[^>]*aria-current="page"/g)].map(
            (m) => m[1],
        );
        const current = CURRENT[page];
        expect(marked).toEqual(current === undefined ? [] : [current]);
    });

    it.each(all)("%s ends with the footer", (page) => {
        const foot = /<footer[^>]*class="site-foot[\s\S]*?<\/footer>/.exec(read(page))?.[0] ?? "";
        expect(foot).toContain(`href="${AUTHOR_URL}"`);
        expect(visibleText(foot)).toContain("Built by Andy Floyd");
        expect(foot).toContain('href="https://github.com/floyda/ntsb-probable-cause"');
        expect(foot).toContain('href="/methods/"');
        expect(foot).toContain('href="/open/"');
    });
});

describe.skipIf(!built)("the Open cases page (S5 step 6c, Task 1)", () => {
    const { index, cases } = loadExport(exportDir());
    const html = built ? readFileSync(join(DIST, "open", "index.html"), "utf8") : "";
    const text = visibleText(html);

    it("states the open cases watched and those with a docket", () => {
        for (const line of openLines(index.counts)) expect(text).toContain(line);
    });

    it("gives each night's closures a row, newest first", () => {
        const table = /<table[\s\S]*?<\/table>/.exec(html)?.[0] ?? "";
        const rows = /<tbody[\s\S]*?<\/tbody>/.exec(table)?.[0] ?? "";
        const cells = [...rows.matchAll(/<tr[\s\S]*?<\/tr>/g)].map((m) => visibleText(m[0]).trim());
        expect(cells).toEqual(
            closureNights(index.counts).map((n) => `${n.label} ${String(n.count)}`),
        );
    });

    it("names no case and links to no case page (decision 0024)", () => {
        expect(html).not.toContain('href="/case/');
        for (const n of [...cases.keys(), ...index.rows.map((r) => r.case_number)]) {
            expect(html, n).not.toContain(n);
        }
    });
});

describe.skipIf(!built)("the rail of places (S5 step 6a, Task 3)", () => {
    const RAILS: Record<string, number> = {
        "index.html": 6,
        "path/index.html": 10,
        "methods/index.html": 9,
    };
    it.each(Object.entries(RAILS))("%s has a rail of %i places, each on the page", (page, n) => {
        const html = readFileSync(join(DIST, page), "utf8");
        const rail = /<nav[^>]*class="rail[\s\S]*?<\/nav>/.exec(html)?.[0] ?? "";
        const ids = [...rail.matchAll(/href="#([^"]+)"/g)].map((m) => m[1] ?? "");
        expect(ids).toHaveLength(n);
        const positions = ids.map((id) => html.search(new RegExp(`\\sid="${id}"`)));
        for (const [i, at] of positions.entries()) expect(at, ids[i]).toBeGreaterThan(-1);
        expect(positions).toEqual([...positions].sort((a, b) => a - b));
    });
    it("draws no rail on a case or trail page", () => {
        for (const page of htmlFiles().filter((p) => p.includes(`${sep}case${sep}`))) {
            expect(readFileSync(page, "utf8"), page).not.toMatch(/<nav[^>]*class="rail/);
        }
    });
});

describe.skipIf(!built)("the way back (S5 step 6a, Task 4)", () => {
    const { cases } = loadExport(exportDir());
    const back = (html: string): string[] => {
        const nav = /<nav[^>]*aria-label="Back"[\s\S]*?<\/nav>/.exec(html)?.[0] ?? "";
        return [...nav.matchAll(/<a[^>]*href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g)].map(
            (m) => `${m[1] ?? ""} ${visibleText(m[2] ?? "").trim()}`,
        );
    };
    const mainOpens = (html: string): boolean =>
        /<main[^>]*>\s*<nav[^>]*aria-label="Back"/.test(html);

    it.each([...cases.keys()])("case %s opens with a way back to the board", (n) => {
        const html = readFileSync(join(DIST, "case", n, "index.html"), "utf8");
        expect(mainOpens(html)).toBe(true);
        expect(back(html)).toEqual(["/#board ← All closed cases"]);
    });

    it.each([...cases.keys()].filter((n) => existsSync(join(DIST, "case", n, "trail"))))(
        "the trail of %s leads back to the board and to its case",
        (n) => {
            const html = readFileSync(join(DIST, "case", n, "trail", "index.html"), "utf8");
            expect(mainOpens(html)).toBe(true);
            expect(back(html)).toEqual(["/#board ← All closed cases", `/case/${n}/ ← This case`]);
        },
    );
});

describe.skipIf(!built)("the Quiet look's signs (S5 step 6a, Task 5)", () => {
    const SIGN = /<span[^>]*class="sign[" ]/g;
    it.each(["index.html", "path/index.html", "methods/index.html"])(
        "%s labels every place in its rail with a sign before its heading",
        (page) => {
            const html = readFileSync(join(DIST, page), "utf8");
            const rail = /<nav[^>]*class="rail[\s\S]*?<\/nav>/.exec(html)?.[0] ?? "";
            const ids = [...rail.matchAll(/href="#([^"]+)"/g)].map((m) => m[1] ?? "");
            expect(ids.length).toBeGreaterThan(0);
            for (const id of ids) {
                const at = html.search(new RegExp(`\\sid="${id}"`));
                const start = html.lastIndexOf("<section", at);
                const heading = html.indexOf("<h2", start);
                expect(start, id).toBeGreaterThan(-1);
                expect(html.slice(start, heading), id).toMatch(SIGN);
            }
            // No sign stands alone: there are as many signs as places.
            expect([...html.matchAll(SIGN)]).toHaveLength(ids.length);
        },
    );
});

describe.skipIf(!built)("why it happened (S5 step 6a, Andy, 2026-10-19)", () => {
    const { cases } = loadExport(exportDir());
    const graded = [...cases.values()].filter(
        (k) => k.comparison !== null && k.grade !== "abstained",
    );
    it("has graded sample cases to check", () => {
        expect(graded.length).toBeGreaterThan(0);
    });
    it.each(graded.map((k) => k.case_number))(
        "%s shows each finding once, under its tag or in a close pair",
        (n) => {
            const k = cases.get(n);
            const c = k?.comparison;
            if (c === undefined || c === null) throw new Error(n);
            const html = readFileSync(join(DIST, "case", n, "index.html"), "utf8");
            const text = visibleText(html);
            // Counted from the case file, not from the code under test (review, 2026-10-19):
            // every finding carries exactly one tag, of its own kind.
            const count = (who: string): number =>
                [...html.matchAll(new RegExp(`class="tag ${who}[" ]`, "g"))].length;
            expect(count("both")).toBe(c.findings_both.length);
            expect(count("ntsb")).toBe(c.findings_ntsb_only.length);
            expect(count("agent")).toBe(c.findings_agent_only.length);
            const all = [...c.findings_both, ...c.findings_ntsb_only, ...c.findings_agent_only];
            for (const f of all) {
                const parts = findingParts(f.label);
                expect(text).toContain(parts.item);
                expect(text).toContain(parts.detail ?? "missing");
            }
            const rows = findingRows(c.findings_both, c.findings_ntsb_only, c.findings_agent_only);
            if (rows.some((r) => r.kind === "close")) expect(text).toMatch(/Close: the same/);
            // The area's levels are read as separate words (review, 2026-10-19).
            expect(text).not.toMatch(/Personnel issuesTask/);
        },
    );
});

describe.skipIf(!built)("the first page as a route (S5 step 6b)", () => {
    const home = (): string => readFileSync(join(DIST, "index.html"), "utf8");
    it("ends with the path taken: eight questions, each with its answer and its Path stop", () => {
        const html = home();
        const stop = /<section[^>]*id="path"[\s\S]*?<\/section>/.exec(html)?.[0] ?? "";
        const text = visibleText(stop);
        for (const q of ROUTE_QUESTIONS) {
            expect(stop).toContain(`href="/path/#${q.anchor}"`);
            expect(text).toContain(q.question);
            expect(text).toContain(q.answer);
        }
    });
    it("asks whether a loop was needed, with the ladder and its sentence", () => {
        const stop = /<section[^>]*id="loop"[\s\S]*?<\/section>/.exec(home())?.[0] ?? "";
        expect(stop).toMatch(/<figure[^>]*class="ladder/);
        expect(visibleText(stop)).toContain("A step up in machinery is not a step up in result");
    });
    it("shows the trail of the case it opens, with a link to the full trail", () => {
        const html = home();
        const opened = /<article[^>]*data-case="([^"]+)"/.exec(html)?.[1];
        expect(opened).toBeDefined();
        const strip = /<div[^>]*id="route-strip"[\s\S]*?<\/div>/.exec(html)?.[0] ?? "";
        expect(strip).toContain(`href="/case/${opened ?? ""}/trail/"`);
        expect(visibleText(strip)).toContain("Before reading");
    });
});

describe.skipIf(!built)("the link-preview tags (S5 step 6c, Task 3; plan Review Focus 1)", () => {
    const SITE = "https://ellery.demo.floyda.dev";
    const all = htmlFiles()
        .filter((p) => !p.endsWith("404.html"))
        .map((p) => relative(DIST, p).split(sep).join("/"));
    const forwards = ROUTE_QUESTIONS.map((q) => `path/${q.anchor}/index.html`);
    const meta = (html: string, key: string): string[] =>
        [...html.matchAll(new RegExp(`<meta[^>]*(?:property|name)="${key}"[^>]*>`, "g"))].map(
            (m) => /content="([^"]*)"/.exec(m[0])?.[1] ?? "",
        );
    const read = (page: string): string => readFileSync(join(DIST, page), "utf8");
    const decode = (s: string): string =>
        s
            .replace(/&#39;|&#x27;/g, "'")
            .replace(/&quot;/g, '"')
            .replace(/&amp;/g, "&");

    it.each(all)("%s has each preview tag once, its image built", (page) => {
        const html = read(page);
        for (const key of [
            "og:title",
            "og:description",
            "og:url",
            "og:image",
            "og:image:alt",
            "og:type",
            "twitter:card",
        ]) {
            expect(meta(html, key), key).toHaveLength(1);
        }
        expect(meta(html, "twitter:card")).toEqual(["summary_large_image"]);
        const image = meta(html, "og:image")[0] ?? "";
        expect(image).toMatch(new RegExp(`^${SITE}/cards/[a-z-]+\\.png\\?v=[0-9a-f]{8}$`));
        expect(existsSync(join(DIST, image.slice(SITE.length).split("?")[0] ?? ""))).toBe(true);
        expect(meta(html, "og:url")[0]).toBe(`${SITE}/${page.replace(/index\.html$/, "")}`);
    });

    it("gives the 404 page every tag but an address, which it does not have", () => {
        const html = read("404.html");
        expect(meta(html, "og:url")).toEqual([]);
        expect(meta(html, "og:image")).toHaveLength(1);
    });

    // og:url is the shared address itself, already posted by whoever shares it; every other tag
    // is what the preview adds, and none names the case.
    it("keeps every case's number out of what a shared link shows (spec §11)", () => {
        const { cases } = loadExport(exportDir());
        const casePages = all.filter((p) => p.startsWith("case/"));
        expect(casePages.length).toBeGreaterThan(0);
        for (const page of casePages) {
            const head = /<head>[\s\S]*?<\/head>/.exec(read(page))?.[0] ?? "";
            const shared = [...head.matchAll(/<meta[^>]*(?:property="og:|name="twitter:)[^>]*>/g)]
                .map((m) => m[0])
                .filter((tag) => !tag.includes('property="og:url"'))
                .join(" ");
            for (const n of cases.keys()) expect(shared, page).not.toContain(n);
        }
    });

    it.each(all.filter((p) => !forwards.includes(p)))("%s uses the site card", (page) => {
        const html = read(page);
        expect(meta(html, "og:image")).toEqual([
            `${SITE}/cards/site.png?v=${cardVersion(cardFor())}`,
        ]);
        expect(decode(meta(html, "og:image:alt")[0] ?? "")).toBe(cardFor().alt);
    });

    it.each(ROUTE_QUESTIONS.map((q) => q.anchor))(
        "/path/%s/ carries its question's card and forwards to its stop",
        (anchor) => {
            const html = read(`path/${anchor}/index.html`);
            const card = cardFor(`q-${anchor}`);
            expect(meta(html, "og:image")).toEqual([
                `${SITE}/cards/q-${anchor}.png?v=${cardVersion(card)}`,
            ]);
            expect(decode(meta(html, "og:image:alt")[0] ?? "")).toBe(card.alt);
            expect(decode(meta(html, "og:title")[0] ?? "")).toBe(card.question);
            expect(decode(meta(html, "og:description")[0] ?? "")).toBe(card.line);
            expect(html).toMatch(
                new RegExp(
                    `<meta[^>]*http-equiv="refresh"[^>]*content="0;\\s*url=/path/#${anchor}"`,
                ),
            );
            expect(html).toContain(`<link rel="canonical" href="${SITE}/path/">`);
            expect(html).toMatch(
                new RegExp(`<main[\\s\\S]*href="/path/#${anchor}"[\\s\\S]*</main>`),
            );
        },
    );

    it("links each Path question to its forwarding page", () => {
        const html = read("path/index.html");
        for (const q of ROUTE_QUESTIONS) {
            const stop = new RegExp(
                `<section[^>]*id="${q.anchor}"[\\s\\S]*?href="/path/${q.anchor}/"[^>]*>Link to this question<`,
            );
            expect(html, q.anchor).toMatch(stop);
        }
    });

    it("refreshes no page but the forwarding pages", () => {
        for (const page of all.filter((p) => !forwards.includes(p))) {
            expect(read(page), page).not.toContain('http-equiv="refresh"');
        }
    });
});
