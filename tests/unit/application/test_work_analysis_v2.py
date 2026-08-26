from __future__ import annotations

from inspect import signature

import pytest

import google_work_agent.application.orchestration.assemble_work_analysis_output as work_analysis_v2
from google_work_agent.application.orchestration.assemble_work_analysis_output import (
    WORK_ANALYSIS_FACTS_OUTPUT_SCHEMA,
    WORK_ANALYSIS_GAPS_OUTPUT_SCHEMA,
    WORK_ANALYSIS_RELATIONS_OUTPUT_SCHEMA,
    WORK_ANALYSIS_V2_NODE_CHAIN,
    WorkAnalysisV2NodeChain,
    WorkAnalysisV2ValidationError,
    build_current_run_fact_identity_resolver,
    build_frozen_route_connector_resolver,
    materialize_complete_work_analysis_result_v2,
    project_work_analysis_confirmation_required_v1,
    project_work_analysis_retrieval_required_v1,
    validate_and_merge_work_analysis_risks,
    validate_work_analysis_local_aggregation,
)
from google_work_agent.ports.system.contracts.workflow_handoff import AgentNodeResumeTargetV2


def _local(*, relation_type: str = "DEPENDS_ON", right_ref: str = "fact-2"):
    return {
        "fact_candidates": [
            {
                "fact_id": "fact-1",
                "fact_type": "TASK",
                "value": "submit report",
                "evidence_refs": ["ev-1"],
            },
            {
                "fact_id": "fact-2",
                "fact_type": "TASK",
                "value": "submit report",
                "evidence_refs": ["ev-2"],
            },
        ],
        "relation_candidates": [
            {
                "relation_type": relation_type,
                "left_ref": "fact-1",
                "right_ref": right_ref,
                "evidence_refs": ["ev-1", "ev-2"],
            }
        ],
        "relation_validation_ambiguities": [],
        "ambiguity_candidates": [],
        "risk_candidates": [],
        "relation_validation_risks": [],
        "gap_decision": {"disposition": "COMPLETE"},
        "evidence_refs": ["ev-1", "ev-2"],
    }


def _meta():
    return {
        "artifact_id": "analysis-1",
        "revision": 1,
        "based_on": [{"artifact_id": "retrieval-1", "revision": 1}],
    }


def _request_intent():
    return {
        "schema_version": 2,
        "meta": {"artifact_id": "intent-1", "revision": 1, "based_on": []},
        "goal": "deduplicate the report task",
        "completion_conditions": ["identify duplicate"],
        "constraints": [],
        "requested_effect_hints": ["UPDATE"],
        "requested_resource_hints": ["TASK"],
        "analysis_requirement": "REQUIRED",
        "ambiguity": {
            "requires_confirmation": False,
            "reason_codes": [],
            "missing_fields": [],
        },
    }


def _retrieval_result():
    return {
        "schema_version": 1,
        "meta": {
            "artifact_id": "retrieval-1",
            "revision": 1,
            "based_on": [{"artifact_id": "intent-1", "revision": 1}],
        },
        "coverage": "SUFFICIENT",
        "context_bundle_ref": "context-1",
        "evidence_refs": ["ev-1", "ev-2"],
        "selected_segment_ids": ["seg-1", "seg-2"],
        "source_resource_refs": ["task:task-1", "task:task-2"],
        "source_statuses": [],
        "missing_information": [],
        "retrieval_rounds": 1,
    }


def _evidence():
    return [
        {
            "schema_version": 1,
            "evidence_id": "ev-1",
            "resource_handle": "task:task-1",
            "segment_id": "seg-1",
            "kind": "excerpt",
            "excerpt": "Submit report",
            "locator": None,
            "reason_codes": ["SUPPORTS"],
        },
        {
            "schema_version": 1,
            "evidence_id": "ev-2",
            "resource_handle": "task:task-2",
            "segment_id": "seg-2",
            "kind": "excerpt",
            "excerpt": "Submit report",
            "locator": None,
            "reason_codes": ["SUPPORTS"],
        },
    ]


def _tool_route_plan(*, connectors=("connector-tasks-a",)):
    return {
        "schema_version": 2,
        "input_plan": {
            "schema_version": 1,
            "meta": {
                "artifact_id": "input-plan-1",
                "revision": 1,
                "based_on": [{"artifact_id": "intent-1", "revision": 1}],
            },
            "input_routes": [
                {
                    "route_id": f"route-{index}",
                    "resource_type": "TASK",
                    "connector_id": connector_id,
                    "allowed_read_tool_ids": ["tasks.read"],
                    "required": True,
                    "reason_codes": ["REQUESTED_INPUT"],
                }
                for index, connector_id in enumerate(connectors, start=1)
            ],
        },
        "output_plan": {
            "schema_version": 1,
            "meta": {
                "artifact_id": "output-plan-1",
                "revision": 1,
                "based_on": [{"artifact_id": "intent-1", "revision": 1}],
            },
            "output_mode": "ANSWER",
        },
        "tool_registry_version": "registry-1",
    }


def _connector_resolver():
    return build_frozen_route_connector_resolver(_tool_route_plan())


def _identity_resolver(fact):
    return [
        (
            "connector-tasks-a",
            "task:task-1" if fact["fact_id"] == "fact-1" else "task:task-2",
        )
    ]


def _materialize(local, *, relation_validator=None, fact_identity_resolver=None):
    return materialize_complete_work_analysis_result_v2(
        local,
        meta=_meta(),
        allowed_evidence_refs={"ev-1", "ev-2"},
        policy_confirmation_receipt_refs=[],
        relation_validator=relation_validator,
        fact_identity_resolver=fact_identity_resolver,
    )


def test_node_chain_is_exact_approved_amendment_topology() -> None:
    assert WORK_ANALYSIS_V2_NODE_CHAIN == (
        "extract_work_facts",
        "resolve_relations",
        "validate_relations",
        "assess_analysis_gaps",
        "validate_risks",
        "assemble_analysis",
        "validate",
    )


def test_llm_candidate_schemas_do_not_expose_deterministic_authority_fields() -> None:
    assert not hasattr(work_analysis_v2, "WORK_ANALYSIS_CANDIDATE_OUTPUT_SCHEMA")
    assert not hasattr(work_analysis_v2, "WorkAnalysisCandidateV2")
    assert "validated_risks" not in signature(
        materialize_complete_work_analysis_result_v2
    ).parameters
    schema_text = repr(
        (
            WORK_ANALYSIS_FACTS_OUTPUT_SCHEMA.json_schema,
            WORK_ANALYSIS_RELATIONS_OUTPUT_SCHEMA.json_schema,
            WORK_ANALYSIS_GAPS_OUTPUT_SCHEMA.json_schema,
        )
    )
    for forbidden in (
        "validated_relations",
        "relation_validation_risks",
        "validated_risks",
        "action_necessity",
        "policy_confirmation_receipt_refs",
        "availability_results",
        "based_on",
        "interrupt_id",
        "resume_target",
    ):
        assert forbidden not in schema_text


def test_local_aggregation_rejects_caller_supplied_validated_risks() -> None:
    local = _local()
    local["validated_risks"] = []
    with pytest.raises(WorkAnalysisV2ValidationError, match="keys are invalid"):
        validate_work_analysis_local_aggregation(
            local,
            allowed_evidence_refs={"ev-1", "ev-2"},
        )


def test_gap_needs_more_data_projects_exact_retrieval_needs_without_synthesis() -> None:
    decision = {
        "disposition": "NEEDS_MORE_DATA",
        "needs": [
            {
                "required_information": "recipient email chosen by assess_analysis_gaps",
                "reason_codes": ["MISSING_RECIPIENT"],
            }
        ],
    }
    signal = project_work_analysis_retrieval_required_v1(decision)
    assert signal == {
        "kind": "RETRIEVAL_REQUIRED",
        "reason_codes": ["MISSING_RECIPIENT"],
        "needs": decision["needs"],
    }


def test_gap_confirmation_attaches_only_application_owned_resume_metadata() -> None:
    decision = {
        "disposition": "NEEDS_CONFIRMATION",
        "question": "Which task should be updated?",
        "options": ["Task A", "Task B"],
        "reason_codes": ["TARGET_AMBIGUOUS"],
    }
    signal = project_work_analysis_confirmation_required_v1(
        decision,
        interrupt_id="interrupt-1",
        resume_target=AgentNodeResumeTargetV2(
            kind="AGENT_NODE",
            semantic_owner_id="WORK_ANALYSIS",
            compiled_subgraph_id="SIX_WORK_ANALYSIS",
            node_id="analysis.finalize",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v1",
        ),
    )
    assert signal["question"] == decision["question"]
    assert signal["options"] == decision["options"]
    assert signal["interrupt_id"] == "interrupt-1"
    assert signal["semantic_owner_id"] == "WORK_ANALYSIS"
    assert "reason_codes" not in signal


def test_relation_operands_must_be_same_invocation_fact_ids() -> None:
    with pytest.raises(WorkAnalysisV2ValidationError, match="WorkFactV1.fact_id"):
        validate_work_analysis_local_aggregation(
            _local(right_ref="task:task-2"),
            allowed_evidence_refs={"ev-1", "ev-2"},
        )


def test_current_run_fact_identity_is_connector_scoped() -> None:
    resolver = build_current_run_fact_identity_resolver(
        _evidence(),
        connector_for_resource_handle=_connector_resolver(),
    )
    assert list(
        resolver(
            {
                "fact_id": "fact-1",
                "fact_type": "TASK",
                "value": "submit report",
                "evidence_refs": ["ev-1"],
            }
        )
    ) == [("connector-tasks-a", "task:task-1")]


def test_frozen_route_connector_resolution_fails_closed_when_connector_is_ambiguous() -> None:
    resolver = build_frozen_route_connector_resolver(
        _tool_route_plan(connectors=("connector-tasks-a", "connector-tasks-b"))
    )
    assert resolver("task:task-1") is None


def test_guarded_relation_does_not_promote_when_operand_identity_is_not_exactly_one() -> None:
    local = validate_work_analysis_local_aggregation(
        _local(relation_type="DUPLICATES"),
        allowed_evidence_refs={"ev-1", "ev-2"},
    )
    validator_called = False

    def validator(_input):
        nonlocal validator_called
        validator_called = True
        return {"accepted": True, "validator_codes": ["EXACT"]}

    result = _materialize(
        local,
        relation_validator=validator,
        fact_identity_resolver=lambda fact: (
            [] if fact["fact_id"] == "fact-2" else _identity_resolver(fact)
        ),
    )
    assert validator_called is False
    assert result["relations"] == []
    assert result["ambiguities"][0]["code"] == "RELATION_OPERAND_IDENTITY_UNRESOLVED"


def test_guarded_relation_validator_receives_connector_and_resource_handle() -> None:
    local = validate_work_analysis_local_aggregation(
        _local(relation_type="DUPLICATES"),
        allowed_evidence_refs={"ev-1", "ev-2"},
    )

    def validator(input_value):
        assert input_value["left_connector_id"] == "connector-tasks-a"
        assert input_value["right_connector_id"] == "connector-tasks-a"
        assert input_value["left_resource_handle"] == "task:task-1"
        assert input_value["right_resource_handle"] == "task:task-2"
        assert "left_identity" not in input_value
        assert "right_identity" not in input_value
        return {
            "accepted": True,
            "validator_codes": ["TASK_EXACT_DUPLICATE_VALIDATED"],
            "action_necessity": "NOT_REQUIRED",
        }

    result = _materialize(
        local,
        relation_validator=validator,
        fact_identity_resolver=_identity_resolver,
    )
    assert result["relations"][0]["relation_type"] == "DUPLICATES"
    assert result["action_necessity"] == "NOT_REQUIRED"


def test_risk_duplicate_identity_uses_full_normalized_payload() -> None:
    exact = {
        "code": "SCHEDULE_RISK",
        "severity": "WARNING",
        "description": "same evidence-backed risk",
        "evidence_refs": ["ev-1", "ev-1"],
    }
    same_normalized = {
        "code": "SCHEDULE_RISK",
        "severity": "WARNING",
        "description": "same evidence-backed risk",
        "evidence_refs": ["ev-1"],
    }
    same_code_different_payload = {
        "code": "SCHEDULE_RISK",
        "severity": "INFO",
        "description": "different valid risk",
        "evidence_refs": ["ev-2"],
    }
    result = validate_and_merge_work_analysis_risks(
        risk_candidates=[exact],
        relation_validation_risks=[same_normalized, same_code_different_payload],
        allowed_evidence_refs={"ev-1", "ev-2"},
    )
    assert result == [
        {
            "code": "SCHEDULE_RISK",
            "severity": "WARNING",
            "description": "same evidence-backed risk",
            "evidence_refs": ["ev-1"],
        },
        same_code_different_payload,
    ]


def test_blocking_risk_cannot_materialize_complete_artifact() -> None:
    local = _local()
    local["risk_candidates"] = [
        {
            "code": "UNRESOLVED_BLOCKER",
            "severity": "BLOCKING",
            "description": "must be blocked before Domain",
            "evidence_refs": ["ev-1"],
        }
    ]
    with pytest.raises(WorkAnalysisV2ValidationError, match="BLOCKED workflow signal"):
        _materialize(local)


class _Provider:
    def __init__(self, *, gap_decision=None, risks=None, relation_type="DUPLICATES"):
        self.calls = []
        self.gap_decision = gap_decision or {"disposition": "COMPLETE"}
        self.risks = risks or []
        self.relation_type = relation_type

    def extract_work_facts(self, *, semantic_input):
        self.calls.append("extract_work_facts")
        assert set(semantic_input) == {"user_request", "request_intent", "evidence"}
        return {"fact_candidates": _local()["fact_candidates"]}

    def resolve_relations(self, *, semantic_input, work_facts):
        self.calls.append("resolve_relations")
        assert len(work_facts) == 2
        return {
            "relation_candidates": _local(
                relation_type=self.relation_type
            )["relation_candidates"]
        }

    def assess_analysis_gaps(
        self,
        *,
        semantic_input,
        work_facts,
        validated_relations,
        relation_validation_ambiguities,
    ):
        self.calls.append("assess_analysis_gaps")
        assert len(work_facts) == 2
        return {
            "gap_decision": self.gap_decision,
            "ambiguity_candidates": [],
            "risk_candidates": self.risks,
            "evidence_refs": ["ev-1", "ev-2"],
        }


def _node_chain(provider, *, satisfier=None):
    def validator(input_value):
        assert input_value["left_connector_id"] == "connector-tasks-a"
        assert input_value["right_connector_id"] == "connector-tasks-a"
        assert input_value["left_resource_handle"] == "task:task-1"
        assert input_value["right_resource_handle"] == "task:task-2"
        return {
            "accepted": True,
            "validator_codes": ["CURRENT_RUN_IDENTITY_VALIDATED"],
        }

    return WorkAnalysisV2NodeChain(
        candidate_provider=provider,
        connector_for_resource_handle=_connector_resolver(),
        relation_validator=validator,
        retrieval_need_satisfier=satisfier,
    )


def _run_chain(chain, *, receipts=None, interrupt_id=None, resume_target=None):
    return chain.run(
        user_request="Deduplicate my report task",
        request_intent=_request_intent(),
        retrieval_result=_retrieval_result(),
        evidence_drafts=_evidence(),
        meta=_meta(),
        policy_confirmation_receipt_refs=receipts or [],
        interrupt_id=interrupt_id,
        resume_target=resume_target,
    )


def test_node_chain_produces_v2_artifact_without_exposing_receipts_to_semantic_provider() -> None:
    provider = _Provider()
    result = _run_chain(
        _node_chain(provider),
        receipts=[{"artifact_id": "receipt-1", "revision": 2}],
    )
    assert provider.calls == [
        "extract_work_facts",
        "resolve_relations",
        "assess_analysis_gaps",
    ]
    assert result["schema_version"] == 2
    assert result["policy_confirmation_receipt_refs"] == [
        {"artifact_id": "receipt-1", "revision": 2}
    ]


def test_node_chain_blocking_risk_returns_signal_and_no_partial_artifact() -> None:
    provider = _Provider(
        risks=[
            {
                "code": "UNRESOLVED_BLOCKER",
                "severity": "BLOCKING",
                "description": "cannot safely complete analysis",
                "evidence_refs": ["ev-1"],
            }
        ]
    )
    outcome = _run_chain(_node_chain(provider))
    assert outcome == {"kind": "BLOCKED", "reason_codes": ["UNRESOLVED_BLOCKER"]}
    assert "schema_version" not in outcome


def test_node_chain_needs_more_data_uses_semantic_need_or_route_reconsideration() -> None:
    decision = {
        "disposition": "NEEDS_MORE_DATA",
        "needs": [
            {
                "required_information": "current task owner",
                "reason_codes": ["TASK_OWNER_REQUIRED"],
            }
        ],
    }
    provider = _Provider(gap_decision=decision, relation_type="DEPENDS_ON")
    retrieval_signal = _run_chain(_node_chain(provider, satisfier=lambda _needs: True))
    assert retrieval_signal == {
        "kind": "RETRIEVAL_REQUIRED",
        "reason_codes": ["TASK_OWNER_REQUIRED"],
        "needs": decision["needs"],
    }

    provider = _Provider(gap_decision=decision, relation_type="DEPENDS_ON")
    route_signal = _run_chain(_node_chain(provider, satisfier=lambda _needs: False))
    assert route_signal == {
        "kind": "ROUTE_RECONSIDERATION_REQUIRED",
        "reason_codes": ["TASK_OWNER_REQUIRED"],
    }
    assert "schema_version" not in route_signal


def test_override_without_receipt_stays_confirmation_and_application_owns_resume_metadata() -> None:
    provider = _Provider(
        gap_decision={
            "disposition": "NEEDS_CONFIRMATION",
            "question": "Allow this duplicate override?",
            "options": ["Allow", "Cancel"],
            "reason_codes": ["DUPLICATE_OVERRIDE"],
        },
        risks=[
            {
                "code": "DUPLICATE_OVERRIDE",
                "severity": "WARNING",
                "description": "duplicate override requires confirmed authority",
                "evidence_refs": ["ev-1"],
            }
        ],
    )
    outcome = _run_chain(
        _node_chain(provider),
        interrupt_id="interrupt-override-1",
        resume_target=AgentNodeResumeTargetV2(
            kind="AGENT_NODE",
            semantic_owner_id="WORK_ANALYSIS",
            compiled_subgraph_id="SIX_WORK_ANALYSIS",
            node_id="analysis.assess_information_gaps",
            graph_profile="SIX_ROLE_BASELINE",
            graph_version="v2",
        ),
    )
    assert outcome["kind"] == "CONFIRMATION_REQUIRED"
    assert outcome["semantic_owner_id"] == "WORK_ANALYSIS"
    assert outcome["question"] == "Allow this duplicate override?"
    assert "schema_version" not in outcome


def test_override_complete_without_receipt_fails_closed_instead_of_creating_artifact() -> None:
    provider = _Provider(
        risks=[
            {
                "code": "CONFLICT_OVERRIDE",
                "severity": "WARNING",
                "description": "conflict override requires confirmed authority",
                "evidence_refs": ["ev-1"],
            }
        ]
    )
    with pytest.raises(WorkAnalysisV2ValidationError, match="must remain NEEDS_CONFIRMATION"):
        _run_chain(_node_chain(provider))
