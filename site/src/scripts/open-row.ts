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
            adopted.tabIndex = -1;
            adopted.focus();
            history.pushState({ case: link.dataset["case"] }, "", link.href);
            shownPath = window.location.pathname;
        })
        .catch(() => {
            window.location.href = link.href;
        });
}

document.addEventListener("click", (event) => {
    const target = event.target;
    if (!(target instanceof Element)) return;
    const link = target.closest<HTMLAnchorElement>("a[data-case]");
    if (link === null) return;
    if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault();
    openCase(link);
});

// The path of the case on show. A change of anchor also fires popstate, so reload only when the
// path itself changes (review, 2026-10-13: the rail of step 6 links to anchors).
let shownPath = window.location.pathname;

window.addEventListener("popstate", () => {
    if (window.location.pathname !== shownPath) window.location.reload();
});
