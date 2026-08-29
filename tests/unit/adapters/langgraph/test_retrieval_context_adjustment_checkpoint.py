from google_work_agent.adapters.langgraph.checkpoint_control import _control_writes
from google_work_agent.ports.system.contracts.workflow_handoff import (
    ContextAdjustmentControlV1,
)


def test_exclusion_obligation_is_checkpointed_before_retrieval_entry() -> None:
    writes = dict(
        _control_writes(
            ContextAdjustmentControlV1(
                kind="CONTEXT_ADJUSTMENT",
                adjustment={"kind": "EXCLUDE_EVIDENCE", "segment_ids": ["segment-1"]},
            ),
            goto_node="retrieval.plan_query",
        )
    )
    assert writes["exclusion_obligation_segment_ids"] == ["segment-1"]


def test_pending_user_need_is_checkpointed_before_retrieval_entry() -> None:
    writes = dict(
        _control_writes(
            ContextAdjustmentControlV1(
                kind="CONTEXT_ADJUSTMENT",
                adjustment={
                    "kind": "RETRIEVE_MORE",
                    "requested_information": "Need the invoice total.",
                },
            ),
            goto_node="retrieval.plan_query",
        )
    )
    assert writes["pending_user_retrieval_need"] == {
        "schema_version": 1,
        "required_information": "Need the invoice total.",
        "reason_codes": ["USER_CONTEXT_ADJUSTMENT"],
    }
