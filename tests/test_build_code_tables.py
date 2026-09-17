from scripts.build_code_tables import coverage_check

from ntsb_probable_cause.scoring.codes import CodeTables

_TABLES = CodeTables(
    phases={"552": "Landing"},
    events={"230": "Loss of control on ground"},
    categories={},
    items={"02063040": "Powerplant"},
    modifiers={"44": "Fatigue/wear"},
)


def _record(*, occurrence: str | None, findings: list[tuple[str, bool]]) -> dict[str, object]:
    """A minimal raw record: one defining event and a list of (findingCode, inProbableCause)."""
    events = [{"isDefiningEvent": True, "eventCode": occurrence}] if occurrence else []
    findings_field = [
        {"findingNumber": i, "findingCode": code, "inProbableCause": in_cause}
        for i, (code, in_cause) in enumerate(findings)
    ]
    return {"aircrafts": [{"events": events, "findings": findings_field}]}


def test_all_composable_case_counts_but_flags_nothing() -> None:
    raw = _record(occurrence="552230", findings=[("0206304044", True)])
    result = coverage_check([("dev", raw)], _TABLES)
    assert result.by_split["dev"].cases == 1
    assert result.by_split["dev"].primary_not_composable == 0
    assert result.by_split["dev"].finding_not_composable == 0
    assert result.by_split["heldout"].cases == 0
    assert result.missing_occurrence_parts == []
    assert result.missing_finding_parts == []


def test_unknown_phase_and_event_are_flagged_and_ranked_by_case() -> None:
    raw = _record(occurrence="553060", findings=[])
    result = coverage_check([("dev", raw)], _TABLES)
    assert result.by_split["dev"].primary_not_composable == 1
    assert result.by_split["dev"].primary_not_composable_pct == 100.0
    assert dict(result.missing_occurrence_parts) == {"phase 553": 1, "event 060": 1}
    assert result.missing_finding_parts == []


def test_unflagged_finding_with_unknown_modifier_does_not_count() -> None:
    raw = _record(occurrence="552230", findings=[("0206304027", False)])
    result = coverage_check([("heldout", raw)], _TABLES)
    assert result.by_split["heldout"].finding_not_composable == 0
    assert result.missing_finding_parts == []


def test_two_flagged_findings_needing_the_same_modifier_rank_it_by_finding_not_case() -> None:
    raw = _record(
        occurrence="552230",
        findings=[("0206304027", True), ("0206304027", True)],
    )
    result = coverage_check([("heldout", raw)], _TABLES)
    assert result.by_split["heldout"].cases == 1
    assert result.by_split["heldout"].finding_not_composable == 1
    assert dict(result.missing_finding_parts) == {"modifier 27": 2}


def test_open_split_is_excluded() -> None:
    raw = _record(occurrence="553060", findings=[])
    result = coverage_check([("open", raw)], _TABLES)
    assert result.by_split["dev"].cases == 0
    assert result.by_split["heldout"].cases == 0
    assert result.missing_occurrence_parts == []


def test_missing_case_with_no_occurrence_events_is_not_flagged() -> None:
    raw = _record(occurrence=None, findings=[])
    result = coverage_check([("dev", raw)], _TABLES)
    assert result.by_split["dev"].cases == 1
    assert result.by_split["dev"].primary_not_composable == 0
