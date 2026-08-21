from __future__ import annotations

from typing import cast

from google_work_agent.application.workflows.post_retrieval_runtime_v2 import (
    PostRetrievalRuntimeV2Boundary,
)
from google_work_agent.application.workflows.domain_validation_v2 import (
    RunScopedResourceIdentityReader,
)


class _UnusedPlanning:
    def run(self, **_kwargs):
        raise AssertionError("not used")


class _UnusedReview:
    def run(self, **_kwargs):
        raise AssertionError("not used")


class _DomainValidation:
    def __init__(self) -> None:
        self.kwargs = None

    def __call__(self, **kwargs):
        self.kwargs = kwargs
        return {
            "schema_version": 1,
            "result": "REQUIRE_APPROVAL",
            "reason_codes": ["WRITE_EFFECT_PRESENT"],
            "blocked_action_ids": [],
        }


def test_boundary_calls_canonical_domain_validation_with_v2_artifacts() -> None:
    domain = _DomainValidation()
    boundary = PostRetrievalRuntimeV2Boundary(
        planning=cast(object, _UnusedPlanning()),
        review=cast(object, _UnusedReview()),
        domain_validation=cast(object, domain),
    )
    plan = {
        "schema_version": 2,
        "meta": {"artifact_id": "plan-1", "revision": 2, "based_on": []},
        "actions": [],
    }
    review = {
        "schema_version": 2,
        "meta": {
            "artifact_id": "review-1",
            "revision": 1,
            "based_on": [{"artifact_id": "plan-1", "revision": 2}],
        },
        "status": "PASS",
        "summary": "safe",
    }
    analysis = {
        "schema_version": 2,
        "meta": {"artifact_id": "analysis-1", "revision": 1, "based_on": []},
        "work_facts": [],
        "relations": [],
        "ambiguities": [],
        "risks": [],
        "evidence_refs": [],
        "policy_confirmation_receipt_refs": [],
        "action_necessity": "REQUIRED",
    }
    reader = cast(RunScopedResourceIdentityReader, object())
    result = boundary.domain_validate(
        run_id="run-1",
        planning_result=plan,
        plan_review=review,
        work_analysis_result=analysis,
        evidence_drafts=[],
        policy_confirmation_receipts=[],
        resource_identity_reader=reader,
    )
    assert result["result"] == "REQUIRE_APPROVAL"
    assert domain.kwargs is not None
    assert domain.kwargs["planning_result"] is plan
    assert domain.kwargs["plan_review"] is review
    assert domain.kwargs["work_analysis_result"] is analysis
    assert domain.kwargs["resource_identity_reader"] is reader
