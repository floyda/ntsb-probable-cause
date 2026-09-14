from typing import Any, cast

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
