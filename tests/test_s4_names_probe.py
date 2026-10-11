"""scripts/s4_names_probe.py: names counted outside the rule (S4 Task 4), on invented cases."""

from pathlib import Path

import pytest
from scripts import s4_names_probe as probe
from scripts.s4_names_probe import Loaded, NameCase, count_names

KNOWN = frozenset({"statement", "the", "pilot", "saw", "approach", "loss", "control"})
INVENTED = ("Smithers", "Quimby", "Invented", "Aviation")


def _case(titles: tuple[str, ...] = (), owners: tuple[str, ...] = (), **texts: str) -> NameCase:
    return NameCase(titles, owners, {k: (v,) for k, v in texts.items()})


def test_title_word_counts_in_one_and_not_three() -> None:
    case = _case(("Statement of Smithers",), note="Smithers saw the approach")
    note = count_names([case], KNOWN).by_kind["note"]
    assert (note.in_titles, note.outside, note.outside_words) == (1, 0, 0)


def test_word_outside_titles_and_owners_counts_in_three() -> None:
    case = _case(("Statement of Smithers",), cause="Quimby lost control")
    cause = count_names([case], KNOWN).by_kind["cause"]
    assert (cause.in_titles, cause.outside, cause.outside_words) == (0, 1, 1)


def test_owner_string_counts_in_two_and_not_three() -> None:
    case = _case(owners=("Invented Aviation LLC",), account="The pilot of Invented Aviation LLC")
    account = count_names([case], KNOWN).by_kind["account"]
    assert (account.owner_operator, account.outside, account.outside_words) == (1, 0, 0)


def test_distinct_words_once_per_case_and_cases_counted() -> None:
    cases = [_case(reason="Quimby and Quimby and Smithers"), _case(reason="The pilot")]
    counts = count_names(cases, KNOWN)
    assert counts.cases == 2
    assert counts.by_kind["reason"].outside == 1
    assert counts.by_kind["reason"].outside_words == 2


def _loader(run_ids: object) -> Loaded:
    case = _case(("Statement of Smithers",), ("Invented Aviation LLC",), cause="Quimby")
    return Loaded([case], ("run-one", "run-two"), no_listing=3)


def test_main_writes_counts_and_no_invented_word(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "result.txt"
    assert probe.main(["--out", str(out)], _loader) == 0
    written = out.read_text()
    assert written.strip() == capsys.readouterr().out.strip()
    assert "cause: (1) 0; (2) 0; (3) 1; (4) 1" in written
    assert "without a cached docket listing: 3" in written
    assert "cannot conclude" in written
    for word in INVENTED:
        assert word not in written


def test_rule_stands_when_nothing_is_outside(tmp_path: Path) -> None:
    def loader(run_ids: object) -> Loaded:
        texts = dict.fromkeys(probe.KINDS, ("The pilot saw",))
        return Loaded([NameCase((), (), texts)], ("a", "b"))

    out = tmp_path / "result.txt"
    probe.main(["--out", str(out)], loader)
    assert "result: the rule stands" in out.read_text()


def test_lookup_kinds_are_counted() -> None:
    case = _case(lookup_reason="Quimby asked", lookup_effect="Smithers", lookup_arg="Zorbo")
    by_kind = count_names([case], KNOWN).by_kind
    assert [by_kind[k].outside for k in ("lookup_reason", "lookup_effect", "lookup_arg")] == [
        1,
        1,
        1,
    ]


def test_scan_sizes_are_reported() -> None:
    case = NameCase((), (), {"note": ("Quimby saw", "The pilot")})
    note = count_names([case], KNOWN).by_kind["note"]
    assert (note.with_text, note.texts, note.words_scanned) == (1, 2, 2)


def test_empty_kind_means_cannot_conclude(tmp_path: Path) -> None:
    def loader(run_ids: object) -> Loaded:
        return Loaded([_case(note="The pilot saw")], ("a", "b"))

    out = tmp_path / "result.txt"
    probe.main(["--out", str(out)], loader)
    written = out.read_text()
    assert "cannot conclude: kind cause" in written
    assert "result: the rule stands" not in written
    assert "same detector as the rule" in written
