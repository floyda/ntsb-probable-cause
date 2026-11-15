// The dark mode button (decision 0222), as on floyda.dev. Dark is the default, whatever the
// system's setting; a reader who chooses light keeps it. Loaded in the page's head, before the
// page is drawn, so that reader never sees dark first. The choice is kept in this browser only,
// under the key "theme"; nothing is sent anywhere. Without this script the site is dark and the
// button is not shown (SiteHeader.astro).
(function () {
    var KEY = "theme";
    var root = document.documentElement;
    root.setAttribute("data-js", "");
    var saved;
    try {
        saved = window.localStorage.getItem(KEY);
    } catch {
        saved = null;
    }
    root.setAttribute("data-theme", saved === "light" ? "light" : "dark");
    function isDark() {
        return root.getAttribute("data-theme") !== "light";
    }
    function mark() {
        var buttons = document.querySelectorAll("[data-theme-toggle]");
        for (var i = 0; i < buttons.length; i++) {
            buttons[i].setAttribute("aria-pressed", isDark() ? "true" : "false");
        }
    }
    document.addEventListener("DOMContentLoaded", mark);
    document.addEventListener("click", function (event) {
        var target = event.target;
        var button = target && target.closest ? target.closest("[data-theme-toggle]") : null;
        if (!button) return;
        var next = isDark() ? "light" : "dark";
        root.setAttribute("data-theme", next);
        mark();
        try {
            window.localStorage.setItem(KEY, next);
        } catch {
            /* Storage blocked: the choice lasts for this page only. */
        }
    });
})();
