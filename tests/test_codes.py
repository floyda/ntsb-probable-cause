import pytest

from ntsb_probable_cause.errors import SchemaError
from ntsb_probable_cause.scoring import codes
from ntsb_probable_cause.scoring.codes import load_tables


def test_tables_have_the_measured_sizes() -> None:
    t = load_tables()
    assert len(t.phases) >= 43
    assert len(t.events) == 97
    assert len(t.categories) == 130
    assert len(t.items) == 1019
    assert len(t.modifiers) == 73


def test_the_supplement_adds_codes_the_dictionary_lacks_decision_0105() -> None:
    t = load_tables()
    assert t.phases["553"] == "Landing-aborted after touchdown"
    assert t.phases["601"] == "Autorotation"
    assert t.events["850"] == "Medical event"
    assert t.compose_occurrence("553", "470") == "553470"
    assert t.compose_occurrence("601", "092") == "601092"
    assert {"281", "282", "284"} <= set(t.events)


def test_the_supplement_never_replaces_a_dictionary_label() -> None:
    assert not _supplement_overlaps()


def test_a_supplement_row_for_another_table_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        codes, "_rows", lambda _resource: [{"table": "items", "code": "01011100", "label": "x"}]
    )
    with pytest.raises(SchemaError, match="unsupported table 'items'"):
        codes.read_supplement()


def _supplement_overlaps() -> list[str]:
    return [
        f"{table} {code}"
        for table, rows in codes.read_supplement().items()
        for code in rows
        if code in codes.read_dictionary_table(table)
    ]


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
