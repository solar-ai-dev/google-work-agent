from __future__ import annotations

import json

import pytest
from evaluation.contracts.canonical_case import CanonicalCaseV7
from pydantic import ValidationError
from tests.support.evaluation_case import make_case


def test_canonical_case_round_trip_and_hash_are_stable() -> None:
    case = make_case()

    round_tripped = CanonicalCaseV7.model_validate_json(case.canonical_json(), strict=True)

    assert round_tripped == case
    assert round_tripped.stable_hash() == case.stable_hash()


def test_canonical_case_rejects_unknown_and_incompatible_version() -> None:
    payload = make_case().model_dump(mode="json")
    payload["unknown"] = True
    with pytest.raises(ValidationError):
        CanonicalCaseV7.model_validate(payload, strict=True)

    payload = make_case().model_dump(mode="json")
    payload["schema_version"] = 6
    with pytest.raises(ValidationError):
        CanonicalCaseV7.model_validate_json(json.dumps(payload), strict=True)


def test_canonical_case_rejects_required_hard_negative_overlap() -> None:
    payload = make_case().model_dump(mode="json")
    payload["hard_negative_resource_ids"] = ["mail-1"]

    with pytest.raises(ValidationError, match="overlap"):
        CanonicalCaseV7.model_validate(payload, strict=True)
