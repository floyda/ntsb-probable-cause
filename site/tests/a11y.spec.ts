import { existsSync, readdirSync, statSync } from "node:fs";
import { join, relative, sep } from "node:path";
import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

// Every built page, by its address: dist/methods/index.html -> /methods/.
function pages(root: string, prefix: string): string[] {
    if (!existsSync(root)) return [];
    const found: string[] = [];
    const walk = (dir: string): void => {
        for (const name of readdirSync(dir)) {
            const path = join(dir, name);
            if (statSync(path).isDirectory()) walk(path);
            else if (name.endsWith(".html")) {
                const rel = relative(root, path).split(sep).join("/");
                found.push(prefix + rel.replace(/(^|\/)index\.html$/, "$1"));
            }
        }
    };
    walk(root);
    return found.sort();
}

const addresses = [...pages("dist", "/"), ...pages("holding", "/_holding/")];

test("there is at least one page to check", () => {
    expect(addresses.length).toBeGreaterThan(0);
});

for (const address of addresses) {
    test(`WCAG 2.2 AA: ${address}`, async ({ page }, info) => {
        await page.goto(address);
        const results = await new AxeBuilder({ page })
            .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa", "wcag22aa"])
            .analyze();
        expect(results.violations, JSON.stringify(results.violations, null, 2)).toEqual([]);
        if (info.project.name === "phone") {
            const name = address.replace(/[^a-z0-9]+/gi, "-").replace(/^-|-$/g, "") || "home";
            await page.screenshot({ path: `test-results/phone/${name}.png`, fullPage: true });
        }
    });
}
