"""Remove personal data from records before they are saved as fixtures (decision 0015)."""

import copy
from collections.abc import Mapping

# Under aircrafts[].ownerOperators[]. In general aviation the owner or operator is often the pilot.
REDACTED_FIELDS = frozenset(
    {
        "registeredOwner",
        "ownerIndividual",
        "ownerAddress",
        "ownerZip",
        "operatorName",
        "operatorIndividual",
        "operatorDoingBusinessAs",
        "operatorAddress",
        "operatorZip",
        "operatorCertificateNumber",
    }
)


def redact_record(record: Mapping[str, object]) -> dict[str, object]:
    """Return a copy of ``record`` with every redacted owner/operator field removed."""
    result: dict[str, object] = copy.deepcopy(dict(record))
    aircrafts = result.get("aircrafts")
    for aircraft in aircrafts if isinstance(aircrafts, list) else []:
        operators = aircraft.get("ownerOperators") if isinstance(aircraft, dict) else None
        for operator in operators if isinstance(operators, list) else []:
            if isinstance(operator, dict):
                for field in REDACTED_FIELDS:
                    operator.pop(field, None)
    return result


def find_redacted_fields(value: object, path: str = "") -> list[str]:
    """Return the dotted path of every redacted field name found anywhere in ``value``."""
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            child_path = f"{path}.{key}" if path else str(key)
            if key in REDACTED_FIELDS:
                found.append(child_path)
            found.extend(find_redacted_fields(child, child_path))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(find_redacted_fields(child, f"{path}[{index}]"))
    return found
