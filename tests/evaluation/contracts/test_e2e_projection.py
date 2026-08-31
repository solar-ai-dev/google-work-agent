from __future__ import annotations

import pytest
from evaluation.projections.build_current_projections import _project_case
from pydantic import ValidationError
from tests.evaluation.conftest import make_case


def test_e2e_projection_is_closed_self_contained_and_gold_free_at_product_boundary() -> None:
    projection = _project_case(make_case())

    assert projection.schema_version == 5
    assert projection.end_state_gold.schema_version == 1
    assert isinstance(projection.product_input, dict)
    assert "gold" not in projection.product_input
    assert "end_state_gold" not in projection.product_input


def test_e2e_projection_rejects_unknown_field() -> None:
    projection = _project_case(make_case())
    payload = projection.model_dump(mode="json")
    payload["extra"] = "not-allowed"

    with pytest.raises(ValidationError):
        type(projection).model_validate(payload, strict=True)
