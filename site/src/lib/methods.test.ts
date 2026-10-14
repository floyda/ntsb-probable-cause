import { describe, expect, it } from "vitest";
import { anchorFor, entryLink, groupOf, GROUPS, keysOf, methodsLink, shown } from "./methods";
import { numbers } from "./numbers";

describe("the Methods page's groups (S5 step 5, Task 2)", () => {
    const keys = Object.keys(numbers().entries);
    it("puts every entry in exactly one group", () => {
        for (const key of keys) {
            const holding = GROUPS.filter((g) => g.prefixes.some((p) => key.startsWith(p)));
            expect(
                holding.map((g) => g.id),
                key,
            ).toHaveLength(1);
        }
    });
    it("leaves no group empty", () => {
        for (const g of GROUPS)
            expect(
                keys.some((k) => groupOf(k).id === g.id),
                g.id,
            ).toBe(true);
    });
    it("names each question's group by its Path anchor", () => {
        expect(groupOf("q7.loop_vs_fixed").id).toBe("choosing");
        expect(groupOf("ladder.no_docket.top1").id).toBe("ladder");
        expect(methodsLink("choosing")).toBe("/methods/#choosing");
    });
    it("orders a group's rows as its figure reads", () => {
        expect(keysOf("ladder")).toEqual([
            "ladder.baseline.top1",
            "ladder.no_docket.top1",
            "ladder.fixed.billed",
            "ladder.fixed.top1",
            "ladder.loop.billed",
            "ladder.loop.top1",
        ]);
        expect(keysOf("choosing")[0]).toBe("q7.loop_vs_fixed");
        expect(keysOf("choosing").at(-1)).toBe("q7.path.answer");
    });
    it("refuses a key no group holds, so a new entry cannot go unlisted", () => {
        expect(() => groupOf("q9.anything")).toThrow(/q9\.anything/);
    });
    it("refuses a link to a group that does not exist", () => {
        expect(() => methodsLink("nowhere")).toThrow(/nowhere/);
    });
    it("links a page section and one entry's row", () => {
        expect(methodsLink("withheld")).toBe("/methods/#withheld");
        expect(entryLink("ladder.loop.top1")).toBe("/methods/#n-ladder-loop-top1");
        expect(() => entryLink("ladder.loop.top2")).toThrow();
    });
});

describe("an entry's anchor and its shown value", () => {
    it("makes an anchor from the key", () => {
        expect(anchorFor("ladder.loop.top1")).toBe("n-ladder-loop-top1");
        expect(anchorFor("q7.path.reading.stayed_right")).toBe("n-q7-path-reading-stayed_right");
    });
    it("shows each entry as the other pages do, by its unit", () => {
        expect(shown("ladder.loop.top1")).toBe("23.5% [19.2%, 27.5%], 400 cases");
        expect(shown("q7.loop_vs_fixed")).toBe("−9.5 points [−14.0, −5.2] on 400 cases");
        expect(shown("ladder.loop.billed")).toBe("$2.06");
        expect(shown("q5.first_right")).toBe("88 of 399");
        expect(shown("q4.pages.total")).toBe("16,790");
    });
});
