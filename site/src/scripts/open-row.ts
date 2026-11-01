// A chosen board row opens its case beneath the board (spec §4, §5). Without this script each
// row is a plain link to the case's own page, which shows the same article.
function openCase(link: HTMLAnchorElement): void {
    const current = document.getElementById("opened");
    if (current === null) return;
    void fetch(link.href)
        .then((response) => {
            if (!response.ok) throw new Error(String(response.status));
            return response.text();
        })
        .then((html) => {
            const page = new DOMParser().parseFromString(html, "text/html");
            const next = page.getElementById("opened");
            if (next === null) throw new Error("no case on the page");
            const adopted = document.importNode(next, true);
            current.replaceWith(adopted);
            // Stop 4's strip follows the chosen case (S5 step 6b); a case with no trail says so.
            const strip = document.getElementById("route-strip");
            if (strip !== null) {
                const nextStrip = page.getElementById("route-strip");
                if (nextStrip !== null) strip.replaceWith(document.importNode(nextStrip, true));
                else {
                    const none = document.createElement("p");
                    none.id = "route-strip";
                    none.textContent = "This case has no trail to show.";
                    strip.replaceWith(none);
                }
            }
            // The stop's sign stays in view above the case (review, 2026-10-21): scroll to the
            // stop, then move focus without scrolling again.
            adopted.tabIndex = -1;
            const stop = document.getElementById("case") ?? adopted;
            // A jump, not a glide: a smooth scroll is skipped by some embedded browsers.
            stop.scrollIntoView({ block: "start" });
            adopted.focus({ preventScroll: true });
            // The address follows the case so it can be shared. A frame that forbids it (a
            // sandboxed preview) still shows the case; only a failed fetch opens the case's page.
            try {
                history.pushState({ case: link.dataset["case"] }, "", link.href);
            } catch {
                // The case is shown; the address stays as it was.
            }
            shownPath = window.location.pathname;
        })
        .catch(() => {
            window.location.href = link.href;
        });
}

// A tap anywhere on a row opens its case, not only on its date (review, 2026-10-21); the date
// stays the row's link for the keyboard and with scripts off.
function rowLink(target: Element): HTMLAnchorElement | null {
    const link = target.closest<HTMLAnchorElement>("a[data-case]");
    if (link !== null) return link;
    if (target.closest("a, button") !== null) return null;
    const row = target.closest(".board tbody tr");
    return row?.querySelector<HTMLAnchorElement>("a[data-case]") ?? null;
}

// The board first shows its newest rows (5 on a phone, 20 in the wider window); the button shows
// the rest and moves focus to the first row it showed (Andy, 2026-10-22). The older rows are
// taken out of the table, not hidden by a style: Safari kept the space of hidden rows, so the
// phone's board scrolled over empty space (Andy, 2026-10-22).
const PHONE = window.matchMedia("(max-width: 640px)");
const shownFirst = (): number => (PHONE.matches ? 5 : 20);

for (const board of document.querySelectorAll<HTMLElement>(".board")) {
    board.dataset["rowsOpen"] = "";
    const more = board.querySelector<HTMLButtonElement>(".board-more");
    const body = board.querySelector("tbody");
    if (more === null || body === null) continue;
    const rows = [...body.rows];
    // The newest rows stay; the rest wait outside the table, in order, so the rows on show are
    // always the first ones. Once every row is on show there is nothing for the button to do.
    const show = (n: number): void => {
        for (const row of rows.slice(0, n)) if (!row.isConnected) body.append(row);
        if (body.rows.length === rows.length) {
            delete board.dataset["capped"];
            PHONE.removeEventListener("change", widen);
        }
    };
    // A change of width only ever adds rows: narrowing after load (a turned tablet, a zoom to
    // 200%) would otherwise take away the rows being read, and the focus with them (review,
    // 2026-10-30).
    const widen = (): void => {
        show(shownFirst());
    };
    for (const row of rows.slice(shownFirst())) row.remove();
    board.dataset["capped"] = "";
    PHONE.addEventListener("change", widen);
    show(shownFirst());
    more.addEventListener("click", () => {
        const first = body.rows.length;
        show(rows.length);
        rows[first]?.querySelector<HTMLAnchorElement>("a[data-case]")?.focus();
    });
}

document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const link = rowLink(target);
    if (link === null) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    // Selecting a row's text is not a choice of the row.
    if (link !== target.closest("a") && (window.getSelection()?.toString() ?? "") !== "") return;
    event.preventDefault();
    openCase(link);
});

// The path of the case on show. A change of anchor also fires popstate, so reload only when the
// path itself changes (review, 2026-10-13: the rail of step 6 links to anchors).
let shownPath = window.location.pathname;

window.addEventListener("popstate", () => {
    if (window.location.pathname !== shownPath) window.location.reload();
});
