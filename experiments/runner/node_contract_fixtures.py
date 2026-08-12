"""Deterministic synthetic Contract Fixtures for the 8 LLM Nodes.

These exist for exactly one purpose: confirm that a Node, given a VALID
input, returns output that satisfies its own Typed Output Contract (shape +
enum + required + semantic cross-references). They are NOT a Gold dataset --
no expected_status/expected_answer/grader is attached to any fixture, and
none is used by node_contract_stability_runner.py to judge whether the
model's business decision was "correct".

Not built from experiments/datasets/google_workspace/node_capability_dev:
that dataset's input.json shape predates the current R8.4 prompt_input
contracts (e.g. request_understanding.classify's real prompt_input is
{request_text, entry_mode, selected_resource_ids} -- the dataset's
input.json instead has {user_request, entry_context, conversation_context,
current_time, timezone, allowed_sources}, none of which match). Reusing it
as-is would silently send today's prompts an input shape they were never
authored against. See the Node Contract Audit report for the full
comparison; this is a new, intentionally small, hand-built fixture set
kept in sync with the real invoke_*_llm call sites instead.

No live Google API, no real Gmail body text -- every resource/segment/
evidence value below is invented. FIXTURE_SET_VERSION is bumped whenever a
fixture's shape changes, so a stability run's ledger can record exactly
which fixture generation produced it.
"""

from __future__ import annotations

import uuid

from google_work_agent.application.workflows.api_acquisition import AcquisitionResultV1
from google_work_agent.application.workflows.context_retrieval import (
    ContextBundleV1,
    ContextRetrievalAgent,
    ContextRetrievalResultV1,
    EvidenceDraftV1,
)
from google_work_agent.application.workflows.request_understanding import RequestIntentV1
from google_work_agent.application.workflows.solution_planning import (
    ActionDraftV1,
    ActionPlanDraftV1,
    AnswerDraftV1,
)
from google_work_agent.application.workflows.work_analysis import (
    AnalysisFindingV1,
    WorkAnalysisResultV1,
)
from google_work_agent.ports import WorkflowCorrelationContext, WorkflowStartRequest

FIXTURE_SET_VERSION = "node-contract-fixtures-v1"

RESOURCE_HANDLE = "gmail_thread:thread-kim"
SEGMENT_ID = "seg-1"
EVIDENCE_ID = "evidence-1"
ACTION_ID = "action-1"


def new_request(request_text: str) -> WorkflowStartRequest:
    run_id = str(uuid.uuid4())
    return WorkflowStartRequest(
        run_id=run_id,
        conversation_id=str(uuid.uuid4()),
        workflow_key=f"workflow-{run_id}",
        entry_mode="AGENT_SEARCH",
        requested_mode="AUTO",
        request_text=request_text,
        selected_resource_ids=(),
        correlation=WorkflowCorrelationContext(
            request_id=str(uuid.uuid4()),
            command_id=str(uuid.uuid4()),
            api_contract_version="1",
        ),
    )


def request_intent() -> RequestIntentV1:
    return {
        "schema_version": 2,
        "goal": {
            "summary": "김대리 메일에서 이번 주 후속 작업 정리",
            "user_visible_objective": "김대리 메일 기준으로 이번 주 해야 할 일을 정리",
        },
        "completion_criteria": ["Evidence-backed follow-up summary is available."],
        "semantic_constraints": {
            "topics": [{"text": "후속 작업", "source_text": "후속 작업"}],
            "people": [{"mention": "김대리", "role_hint": None, "source_text": "김대리"}],
            "time": [],
            "sources": [{"source": "GMAIL", "mention": "메일", "confidence": "HIGH"}],
            "status_or_state": [],
            "negative_constraints": [],
            "policy_or_safety_constraints": [],
        },
        "ambiguity": {"is_ambiguous": False, "items": []},
        "unsupported_scope": {"is_unsupported": False, "reason_code": None, "explanation": None},
    }


def acquisition_result() -> AcquisitionResultV1:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "resource_handles": [RESOURCE_HANDLE],
        "source_summaries": [
            {
                "source": "GMAIL",
                "status": "COMPLETE",
                "resources": [
                    {
                        "resource_handle": RESOURCE_HANDLE,
                        "resource_type": "gmail_thread",
                        "resource_id": "thread-kim",
                        "parent_id": None,
                        "version": "1",
                        "payload": {
                            "subject": "Atlas 런칭 준비",
                            "snippet": "김대리: 이번 주 금요일까지 QR 코드 인쇄를 확인해 주세요.",
                            "body": (
                                "안녕하세요, 김대리입니다. 이번 주 금요일까지 "
                                "Atlas 런칭용 QR 코드 인쇄 상태를 확인해 주시고, "
                                "완료되면 회신 부탁드립니다."
                            ),
                        },
                    }
                ],
            }
        ],
        "missing_slots": [],
        "remaining_budget": {"sources": 2, "pages": 2, "candidates": 19, "details": 9},
    }


def context_bundle() -> ContextBundleV1:
    return {
        "schema_version": 1,
        "resource_refs": [
            {
                "resource_handle": RESOURCE_HANDLE,
                "source": "GMAIL",
                "resource_type": "gmail_thread",
                "resource_id": "thread-kim",
                "parent_id": None,
                "version": "1",
            }
        ],
        "segment_refs": [
            {
                "segment_id": SEGMENT_ID,
                "resource_handle": RESOURCE_HANDLE,
                "source": "GMAIL",
                "locator": {"kind": "resource_payload", "position": 0},
            }
        ],
        "evidence_refs": [EVIDENCE_ID],
        "normalized_context": [
            {
                "evidence_id": EVIDENCE_ID,
                "resource_handle": RESOURCE_HANDLE,
                "segment_id": SEGMENT_ID,
                "kind": "excerpt",
                "excerpt": "김대리: 이번 주 금요일까지 QR 코드 인쇄를 확인해 주세요.",
            }
        ],
        "missing_information": [],
        "ambiguity": None,
    }


def evidence_drafts() -> list[EvidenceDraftV1]:
    return [
        {
            "schema_version": 1,
            "evidence_id": EVIDENCE_ID,
            "resource_handle": RESOURCE_HANDLE,
            "segment_id": SEGMENT_ID,
            "kind": "excerpt",
            "excerpt": "김대리: 이번 주 금요일까지 QR 코드 인쇄를 확인해 주세요.",
            "locator": {"kind": "resource_payload", "position": 0},
            "reason_codes": ["GOAL_RELEVANT"],
        }
    ]


def context_result() -> ContextRetrievalResultV1:
    return {
        "schema_version": 1,
        "status": "SUFFICIENT",
        "context_bundle": context_bundle(),
        "evidence_drafts": evidence_drafts(),
        "selected_segment_ids": [SEGMENT_ID],
        "excluded_resource_handles": [],
        "missing_slots": [],
        "additional_acquisition_request": None,
        "sufficiency": {
            "schema_version": 1,
            "reason_codes": ["CONTEXT_READY"],
            "summary": "Context is ready for analysis.",
        },
        "llm_provider_result": {"provider": "fixture"},
    }


def analysis_finding() -> AnalysisFindingV1:
    return {
        "schema_version": 1,
        "finding_id": "finding-1",
        "kind": "FACT",
        "statement": "김대리가 QR 코드 인쇄 확인을 요청했다.",
        "evidence_refs": [EVIDENCE_ID],
        "resource_refs": [RESOURCE_HANDLE],
        "segment_refs": [SEGMENT_ID],
        "related_resource_handles": [RESOURCE_HANDLE],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
    }


def analysis_result() -> WorkAnalysisResultV1:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "summary": "김대리가 QR 코드 인쇄 확인을 요청했다.",
        "findings": [analysis_finding()],
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": [EVIDENCE_ID],
        "resource_refs": context_bundle()["resource_refs"],
        "segment_refs": context_bundle()["segment_refs"],
        "additional_acquisition_request": None,
        "llm_provider_result": {"provider": "fixture"},
    }


def answer_draft() -> AnswerDraftV1:
    return {
        "schema_version": 1,
        "status": "ANSWER_ONLY",
        "answer": "김대리가 이번 주 금요일까지 QR 코드 인쇄 확인을 요청했습니다.",
        "evidence_refs": [EVIDENCE_ID],
        "resource_refs": context_bundle()["resource_refs"],
        "reason_codes": ["EVIDENCE_SUPPORTED"],
        "confirmation": None,
        "blockers": [],
        "llm_provider_result": {"provider": "fixture"},
    }


def action_draft() -> ActionDraftV1:
    return {
        "schema_version": 2,
        "action_id": ACTION_ID,
        "position": 1,
        "effect": "CREATE",
        "tool_name": "tasks_create_task",
        "arguments": {"tasklist_id": "@default", "title": "QR 코드 인쇄 확인"},
        "expected": {"status": "needsAction"},
        "evidence_refs": [EVIDENCE_ID],
        "resource_refs": [RESOURCE_HANDLE],
        "target_resource_ref_id": None,
        "depends_on_action_ids": [],
        "user_visible_reason": "김대리 요청에 따라 QR 코드 인쇄 확인 작업을 생성합니다.",
    }


def plan_draft() -> ActionPlanDraftV1:
    return {
        "schema_version": 2,
        "status": "PLAN_READY",
        "plan_id": "plan-1",
        "summary": "QR 코드 인쇄 확인 작업 생성",
        "objective": "김대리 요청 처리",
        "actions": [action_draft()],
        "evidence_refs": [EVIDENCE_ID],
        "resource_refs": context_bundle()["resource_refs"],
        "confirmation": None,
        "llm_provider_result": {"provider": "fixture"},
    }


def build_segments(agent: ContextRetrievalAgent) -> list[object]:
    """Segments built the same way select_evidence() builds them in
    production -- from acquisition_result(), via the agent's own public
    method, never hand-rolled to avoid drifting from the real _SourceSegment
    shape (a module-private dataclass in context_retrieval.py)."""
    return agent.build_segments_from_acquisition(acquisition_result())


def acquisition_agent_kwargs() -> dict[str, object]:
    return {
        "request_intent": request_intent(),
        "request": new_request("김대리 메일 확인해서 이번 주 할 일 정리해줘."),
    }


def context_select_evidence_kwargs(agent: ContextRetrievalAgent) -> dict[str, object]:
    return {
        "request_intent": request_intent(),
        "acquisition_result": acquisition_result(),
        "request": new_request("김대리 메일 확인해서 이번 주 할 일 정리해줘."),
        "segments": build_segments(agent),
    }


def context_assess_sufficiency_kwargs() -> dict[str, object]:
    return {
        "request_intent": request_intent(),
        "acquisition_result": acquisition_result(),
        "request": new_request("김대리 메일 확인해서 이번 주 할 일 정리해줘."),
        "context_bundle": context_bundle(),
        "evidence_drafts": evidence_drafts(),
    }


def analysis_analyze_kwargs() -> dict[str, object]:
    return {
        "request_intent": request_intent(),
        "context_result": context_result(),
        "request": new_request("김대리 메일 확인해서 이번 주 할 일 정리해줘."),
    }


def planning_answer_only_kwargs() -> dict[str, object]:
    return {
        "request_intent": request_intent(),
        "context_result": context_result(),
        "analysis_result": analysis_result(),
        "request": new_request("김대리가 뭐 해달라고 했는지 알려줘."),
    }


def planning_draft_plan_kwargs() -> dict[str, object]:
    return {
        "request_intent": request_intent(),
        "context_result": context_result(),
        "analysis_result": analysis_result(),
        "request": new_request("김대리가 요청한 QR 코드 확인 작업을 태스크로 만들어줘."),
    }


def review_inspect_kwargs() -> dict[str, object]:
    # policy_review_context is intentionally omitted (defaults to None) so
    # PlanReviewAgent.invoke_inspect_llm builds its own shortlisted
    # tool_policies -- passing the full ~19-tool build_policy_review_context_v1()
    # here would bypass that shortlisting and reproduce the exact
    # Native-Tool-Calling reliability failure it exists to fix.
    return {
        "request_intent": request_intent(),
        "context_result": context_result(),
        "analysis_result": analysis_result(),
        "answer_draft": None,
        "plan_draft": plan_draft(),
        "request": new_request("김대리가 요청한 QR 코드 확인 작업을 태스크로 만들어줘."),
    }


__all__ = [
    "FIXTURE_SET_VERSION",
    "acquisition_agent_kwargs",
    "acquisition_result",
    "analysis_analyze_kwargs",
    "analysis_result",
    "answer_draft",
    "context_assess_sufficiency_kwargs",
    "context_result",
    "context_select_evidence_kwargs",
    "new_request",
    "plan_draft",
    "planning_answer_only_kwargs",
    "planning_draft_plan_kwargs",
    "request_intent",
    "review_inspect_kwargs",
]
