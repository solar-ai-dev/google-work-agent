from google_work_agent.application.workflows import (
    DomainValidationResult,
    DomainValidationService,
    build_domain_validation_output_v1,
)


def test_domain_validation_allows_read_only_plan() -> None:
    output = build_domain_validation_output_v1(
        plan_draft=_plan_draft(
            actions=[
                _action(
                    action_id="action-read",
                    position=1,
                    effect="READ",
                    tool_name="gmail_get_thread",
                )
            ]
        ),
        analysis_result=_analysis_result(),
    )

    assert output["result"] == DomainValidationResult.ALLOW_READ.value
    assert output["reason_codes"] == ["READ_ONLY_PLAN"]


def test_domain_validation_requires_approval_for_write_plan() -> None:
    service = DomainValidationService()
    output = service(
        plan_draft=_plan_draft(
            actions=[
                _action(
                    action_id="action-send",
                    position=1,
                    effect="SEND",
                    tool_name="gmail_send",
                )
            ]
        ),
        analysis_result=_analysis_result(),
    )

    assert output["result"] == DomainValidationResult.REQUIRE_APPROVAL.value
    assert output["reason_codes"] == ["WRITE_EFFECT_PRESENT"]


def test_domain_validation_blocks_invalid_plan_draft() -> None:
    output = build_domain_validation_output_v1(
        plan_draft=_plan_draft(
            actions=[
                _action(
                    action_id="action-invalid",
                    position=1,
                    effect="READ",
                    tool_name="gmail_delete_message",
                )
            ]
        ),
        analysis_result=_analysis_result(),
    )

    assert output["result"] == DomainValidationResult.BLOCK.value
    assert output["reason_codes"] == ["PLAN_DRAFT_INVALID"]


def _analysis_result() -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "COMPLETE",
        "summary": "Enough context to validate the plan.",
        "findings": [],
        "missing_information": [],
        "confirmation": None,
        "blockers": [],
        "evidence_refs": ["evidence-1"],
        "resource_refs": [
            {
                "resource_handle": "gmail_thread:thread-kim",
                "source": "GMAIL",
                "resource_type": "gmail_thread",
                "resource_id": "thread-kim",
                "parent_id": None,
                "version": "1",
            }
        ],
        "segment_refs": [],
        "additional_acquisition_request": None,
        "llm_provider_result": {"provider": "fake"},
    }


def _plan_draft(*, actions: list[dict[str, object]]) -> dict[str, object]:
    return {
        "schema_version": 1,
        "status": "PLAN_READY",
        "plan_id": "plan-1",
        "summary": "Draft plan for validation.",
        "objective": "Validate deterministic domain policy.",
        "actions": actions,
        "evidence_refs": ["evidence-1"],
        "resource_refs": _analysis_result()["resource_refs"],
        "confirmation": None,
    }


def _action(
    *,
    action_id: str,
    position: int,
    effect: str,
    tool_name: str,
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "action_id": action_id,
        "position": position,
        "effect": effect,
        "tool_name": tool_name,
        "arguments": {"payload": {"title": "Follow up"}},
        "expected": {"result": "ok"},
        "evidence_refs": ["evidence-1"],
        "resource_refs": ["gmail_thread:thread-kim"],
        "target_resource_ref_id": None,
        "depends_on_action_ids": [],
        "user_visible_reason": "Support the follow-up request.",
    }
