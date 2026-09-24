"""A private, offline marking page: cards, choices, text fields, and a CSV of the marks.

Status
    Live helper (S2.6). Every S2.6 hand-check renders through this: the analysis sentences
    (Task 2), the 60 inventory labels (Task 12), the handwriting answer key and the
    invented-words review (Task 13). The pages hold private material and are written under
    ``data/`` only, never committed.

Andy marks by clicking, never in a spreadsheet (reported unworkable twice in S2; see
``scripts/handcheck_page.py``). The page is one self-contained file opened with
``file://``: no server, no network. Marks are kept in the browser as they are made, so a
reload loses nothing; the CSV is built from the page itself when Andy downloads it, so a
prefilled text field he never touched still exports its prefilled value.

The caller escapes every piece of text it puts into ``body_html``; this module escapes the
values it places itself (choices, prefilled text).
"""

import csv
import html
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from string import Template


@dataclass(frozen=True)
class Choice:
    """One question answered by picking one option (radio buttons).

    A card counts as marked when every ``required`` choice is answered; an optional one
    (for example "the right label, if the shown one is wrong") may stay empty.
    """

    name: str
    options: tuple[str, ...]
    required: bool = True


@dataclass(frozen=True)
class Card:
    """One item to mark: its body, its choices and its text fields ``(name, prefilled)``."""

    row: int
    body_html: str
    choices: tuple[Choice, ...] = ()
    text_fields: tuple[tuple[str, str], ...] = ()


_PAGE = Template(
    """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><title>$title</title>
<style>
body{font-family:system-ui,sans-serif;max-width:72rem;margin:2rem auto;padding:0 1rem;
line-height:1.5}
.card{border:1px solid #bbb;border-radius:6px;padding:1rem;margin:1rem 0}
mark{background:#fde68a}.meta{color:#555;font-size:.9rem}
img{max-width:100%;border:1px solid #ddd}
textarea{width:100%;min-height:3rem;font-family:ui-monospace,monospace}
pre{white-space:pre-wrap;background:#f6f6f6;padding:.5rem}
</style></head><body>
<h1>$title</h1>
$intro
<p id="progress"></p>
$cards
<button type="button" id="download">Download marks as CSV</button>
<script>
var KEY = $key;
var FIELDS = $fields;
var CSV_NAME = $csv;
$script
</script>
</body></html>
"""
)

_SCRIPT = """
function load() {
  try { return JSON.parse(localStorage.getItem(KEY) || "{}"); } catch (e) { return {}; }
}
function save(m) { try { localStorage.setItem(KEY, JSON.stringify(m)); } catch (e) {} }
var marks = load();
var cards = document.querySelectorAll(".card");
function set(row, name, value) {
  marks[row] = marks[row] || {}; marks[row][name] = value; save(marks); progress();
}
function done(card) {
  var names = JSON.parse(card.dataset.required);
  return names.every(function (n) {
    return card.querySelector('input[data-field="' + n + '"]:checked') !== null;
  });
}
function progress() {
  var n = 0;
  cards.forEach(function (c) { if (done(c)) { n++; } });
  document.getElementById("progress").textContent = n + " of " + cards.length + " marked";
}
cards.forEach(function (card) {
  var row = card.dataset.row;
  card.querySelectorAll("[data-field]").forEach(function (el) {
    var name = el.dataset.field;
    var saved = (marks[row] || {})[name];
    if (el.type === "radio") {
      if (saved === el.value) { el.checked = true; }
      el.addEventListener("change", function () { set(row, name, el.value); });
    } else {
      if (saved !== undefined) { el.value = saved; }
      el.addEventListener("input", function () { set(row, name, el.value); });
    }
  });
});
progress();
function quote(s) { return '"' + String(s || "").replace(/"/g, '""') + '"'; }
function value(card, name) {
  var checked = card.querySelector('input[data-field="' + name + '"]:checked');
  if (checked) { return checked.value; }
  var text = card.querySelector('textarea[data-field="' + name + '"]');
  return text ? text.value : "";
}
document.getElementById("download").addEventListener("click", function () {
  var lines = [["row"].concat(FIELDS).join(",")];
  cards.forEach(function (c) {
    var cells = [c.dataset.row].concat(FIELDS.map(function (f) { return quote(value(c, f)); }));
    lines.push(cells.join(","));
  });
  var blob = new Blob([lines.join("\\n") + "\\n"], { type: "text/csv" });
  var a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = CSV_NAME;
  a.click();
});
"""


def _card(card: Card) -> str:
    esc = html.escape
    fieldsets = "".join(
        f"<fieldset><legend>{esc(choice.name)}</legend>"
        + " ".join(
            f'<label><input type="radio" name="r{card.row}-{esc(choice.name)}" '
            f'data-field="{esc(choice.name)}" value="{esc(option)}"> {esc(option)}</label>'
            for option in choice.options
        )
        + "</fieldset>"
        for choice in card.choices
    )
    areas = "".join(
        f'<label>{esc(name)}<textarea data-field="{esc(name)}">{esc(value)}</textarea></label>'
        for name, value in card.text_fields
    )
    required = esc(json.dumps([choice.name for choice in card.choices if choice.required]))
    return (
        f'<div class="card" data-row="{card.row}" data-required="{required}">'
        f"{card.body_html}{fieldsets}{areas}</div>"
    )


def render(
    *, title: str, intro_html: str, cards: Sequence[Card], storage_key: str, csv_name: str
) -> str:
    """The self-contained page. Field names become CSV columns in first-seen order."""
    names: list[str] = []
    for card in cards:
        for name in [c.name for c in card.choices] + [n for n, _ in card.text_fields]:
            if name not in names:
                names.append(name)
    return _PAGE.substitute(
        title=html.escape(title),
        intro=intro_html,
        cards="\n".join(_card(card) for card in cards),
        key=json.dumps(storage_key),
        fields=json.dumps(names),
        csv=json.dumps(csv_name),
        script=_SCRIPT,
    )


def read_marks(path: Path) -> dict[int, dict[str, str]]:
    """A downloaded CSV, by row number: every field's value, empty where unmarked."""
    with path.open(newline="") as handle:
        return {
            int(row["row"]): {k: v for k, v in row.items() if k != "row"}
            for row in csv.DictReader(handle)
        }
