import pytest

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring.codes import load_tables


def test_tables_have_the_measured_sizes() -> None:
    t = load_tables()
    assert len(t.phases) >= 43
    assert len(t.events) == 93
    assert len(t.categories) == 130
    assert len(t.items) == 1019
    assert len(t.modifiers) == 73


def test_compose_and_validate() -> None:
    t = load_tables()
    assert t.compose_occurrence("552", "230") == "552230"
    assert t.compose_finding("02063040", "44") == "0206304044"
    with pytest.raises(SchemaError):
        t.compose_occurrence("999", "230")
    with pytest.raises(SchemaError):
        t.compose_finding("02063040", "ZZ")


def test_items_under_a_category_are_its_children_only() -> None:
    t = load_tables()
    children = t.items_under("020630")
    assert children
    assert all(k.startswith("020630") for k in children)


def test_render_lists_code_then_label() -> None:
    line = load_tables().render("modifiers").splitlines()[0]
    code, label = line.split("  ", 1)
    assert len(code) == 2
    assert label
