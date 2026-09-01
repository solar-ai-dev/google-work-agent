from google_work_agent.adapters.langgraph.checkpoint_control import (
    _command_writes,
    native_resume_command,
)
from google_work_agent.adapters.langgraph.subgraphs.retrieval.graph import (
    _authorize_context_adjustment_budget,
)
from google_work_agent.application.use_cases.run.guard_run_budget import (
    build_default_run_budget,
)
from google_work_agent.ports.system.contracts.workflow_handoff import (
    ContextAdjustmentControlV1,
)


def test_exclusion_obligation_is_checkpointed_before_retrieval_entry() -> None:
    writes = dict(
        _command_writes(
            native_resume_command(
                ContextAdjustmentControlV1(
                    kind="CONTEXT_ADJUSTMENT",
                    adjustment={"kind": "EXCLUDE_EVIDENCE", "segment_ids": ["segment-1"]},
                ),
                goto_node="retrieval.plan_query",
            )
        )
    )
    assert writes["exclusion_obligation_segment_ids"] == ["segment-1"]


def test_pending_user_need_is_checkpointed_before_retrieval_entry() -> None:
    writes = dict(
        _command_writes(
            native_resume_command(
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
    )
    assert writes["pending_user_retrieval_need"] == {
        "schema_version": 1,
        "required_information": "Need the invoice total.",
        "reason_codes": ["USER_CONTEXT_ADJUSTMENT"],
    }
    assert writes["work_analysis_result"] is None
    assert writes["planning_result"] is None
    assert writes["plan_review"] is None
    assert writes["approved_plan_id"] is None
    assert writes["__modify_review_plan_id__"] is None


def test_context_adjustment_charges_revision_and_additional_retrieval_budget() -> None:
    budget = _authorize_context_adjustment_budget(
        {
            "retry_budget": build_default_run_budget(),
            "__workflow_control__": {"kind": "CONTEXT_ADJUSTMENT"},
        }
    )

    assert budget["planning_revisions_used"] == 1
    assert budget["additional_retrieval_rounds_used"] == 1
    assert budget["llm_call_limit"] == budget["absolute_llm_call_limit"] == 24
