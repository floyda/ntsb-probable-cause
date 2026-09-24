"""scripts/marking_page.py: an offline page, fields by name, a CSV Andy downloads."""

from pathlib import Path

from scripts import marking_page
from scripts.marking_page import Card, Choice


def test_the_page_carries_every_card_choice_and_prefilled_text() -> None:
    cards = [
        Card(row=1, body_html="<p>one</p>", choices=(Choice("mark", ("right", "wrong")),)),
        Card(row=2, body_html="<p>two</p>", text_fields=(("key", "line one\nline two"),)),
    ]
    page = marking_page.render(
        title="A check", intro_html="<p>intro</p>", cards=cards, storage_key="k1", csv_name="m.csv"
    )
    assert '<div class="card" data-row="1"' in page
    assert 'value="right"' in page
    assert 'value="wrong"' in page
    assert "line one\nline two</textarea>" in page
    assert '"k1"' in page
    assert '"m.csv"' in page
    assert '["mark", "key"]' in page


def test_an_optional_choice_does_not_hold_a_card_back() -> None:
    card = Card(
        row=1,
        body_html="",
        choices=(
            Choice("label", ("right", "wrong")),
            Choice("correct", ("a", "b"), required=False),
        ),
    )
    page = marking_page.render(
        title="t", intro_html="", cards=[card], storage_key="k", csv_name="c.csv"
    )
    assert 'data-required="[&quot;label&quot;]"' in page


def test_prefilled_text_is_escaped() -> None:
    card = Card(row=1, body_html="", text_fields=(("key", "</textarea><script>x</script>"),))
    page = marking_page.render(
        title="t", intro_html="", cards=[card], storage_key="k", csv_name="c.csv"
    )
    assert "<script>x</script>" not in page


def test_read_marks_by_row(tmp_path: Path) -> None:
    path = tmp_path / "marks.csv"
    path.write_text('row,mark,notes\n1,"right",""\n2,"","later"\n')
    assert marking_page.read_marks(path) == {
        1: {"mark": "right", "notes": ""},
        2: {"mark": "", "notes": "later"},
    }
