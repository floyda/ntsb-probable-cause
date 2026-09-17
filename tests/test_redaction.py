from pathlib import Path
from typing import Any, cast

from scripts.check_fixtures_redacted import main, withheld_columns_in

from ntsb_probable_cause.data.redaction import REDACTED_FIELDS, find_redacted_fields, redact_record

RECORD: dict[str, object] = {
    "ntsbNumber": "ERA09CA119",
    "aircrafts": [
        {
            "aircraftMake": "CESSNA",
            "ownerOperators": [
                {
                    "regulationFlightConductedUnder": "091",
                    "registeredOwner": "x",
                    "ownerIndividual": "x",
                    "ownerAddress": "x",
                    "ownerZip": "x",
                    "operatorName": "x",
                    "operatorIndividual": "x",
                    "operatorDoingBusinessAs": "x",
                    "operatorAddress": "x",
                    "operatorZip": "x",
                    "operatorCertificateNumber": "x",
                    "ownerCity": "kept",
                }
            ],
        }
    ],
}


def test_redacted_field_list_matches_the_spec() -> None:
    assert len(REDACTED_FIELDS) == 10


def test_redact_removes_every_listed_field_and_keeps_the_rest() -> None:
    redacted = redact_record(RECORD)
    assert find_redacted_fields(redacted) == []
    aircraft = cast("list[dict[str, Any]]", redacted["aircrafts"])[0]
    assert aircraft["ownerOperators"][0] == {
        "regulationFlightConductedUnder": "091",
        "ownerCity": "kept",
    }
    assert aircraft["aircraftMake"] == "CESSNA"


def test_redact_does_not_modify_its_input() -> None:
    redact_record(RECORD)
    assert len(find_redacted_fields(RECORD)) == 10


def test_find_reports_paths_anywhere_in_the_document() -> None:
    assert find_redacted_fields({"record": {"list": [{"ownerZip": "1"}]}}) == [
        "record.list[0].ownerZip"
    ]


def test_withheld_columns_are_found_however_the_header_is_spelled(tmp_path: Path) -> None:
    """Verdict and synthesis columns trip the check whatever their casing or separator.

    The two sheets this guards against were spelled `ntsb_probable_cause` and
    `factual_account`; a re-export could as easily write `NTSB Probable Cause`.
    """
    path = tmp_path / "sheet.csv"
    path.write_text("case_id,NTSB Probable Cause,Factual-Account,notes\nX,a,b,c\n")
    assert withheld_columns_in(path) == ["Factual-Account", "NTSB Probable Cause"]


def test_a_case_id_and_event_date_sheet_passes(tmp_path: Path) -> None:
    path = tmp_path / "ids.csv"
    path.write_text("case_id,event_date\nX,2021-01-01\n")
    assert withheld_columns_in(path) == []
    assert main([str(path)]) == 0


def test_the_check_fails_on_a_sheet_carrying_a_withheld_column(tmp_path: Path) -> None:
    """The regression this exists for: 70 held-out cases' cause and narrative text in git.

    Both sheets sat under `tests/fixtures/eval/` guarded only by a README sentence saying
    they never enter a payload. Decision 0016 requires the guard be code, not convention.
    """
    path = tmp_path / "decidability_full.csv"
    path.write_text("case_id,ntsb_probable_cause\nX,the pilot's failure to maintain airspeed\n")
    assert main([str(path)]) == 1


def test_the_committed_fixtures_are_clean() -> None:
    assert main([]) == 0
