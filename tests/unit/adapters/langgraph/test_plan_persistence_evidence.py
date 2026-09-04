from typing import Any, cast

from google_work_agent.adapters.langgraph.main.plan_persistence import PlanPersistenceMixin
from google_work_agent.domain.evidence.model import EvidenceOriginType


def test_freebusy_evidence__materializes_without__durable_resource_ref() -> None:
    runtime = object.__new__(PlanPersistenceMixin)
    state = {
        "run_id": "run-1",
        "tool_route_plan": {
            "input_plan": {
                "input_routes": [
                    {
                        "resource_type": "CALENDAR_FREEBUSY",
                        "connector_id": "google_workspace",
                    }
                ]
            }
        },
    }
    acquisition_result = {
        "source_summaries": [
            {
                "source": "CALENDAR",
                "resources": [
                    {
                        "resource_handle": "calendar_freebusy:primary:query-hash",
                        "resource_type": "calendar_freebusy",
                        "resource_id": "primary",
                        "payload": {"calendars": []},
                    }
                ],
            }
        ]
    }
    retrieval_result = {
        "meta": {"artifact_id": "retrieval-1"},
    }
    evidence = {
        "segment_id": "segment-1",
        "kind": "AVAILABILITY",
        "excerpt": "The requested interval is available.",
        "resource_handle": "calendar_freebusy:primary:query-hash",
        "reason_codes": ["CONTEXT"],
        "locator": {"calendar_id": "primary"},
    }

    result = runtime._materialize_write_evidence(
        state=cast(Any, state),
        retrieval_result=cast(Any, retrieval_result),
        acquisition_result=cast(Any, acquisition_result),
        logical_evidence_id="evidence-1",
        persisted_evidence_id="persisted-evidence-1",
        draft=evidence,
    )

    assert result.origin_type is EvidenceOriginType.DERIVED
    assert result.resource_ref_id is None
    assert result.locator_json is not None
