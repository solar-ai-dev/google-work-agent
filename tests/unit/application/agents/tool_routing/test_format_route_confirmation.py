from google_work_agent.application.agents.tool_routing.format_route_confirmation import (
    format_route_confirmation,
    format_scope_confirmation,
)


def test_route_confirmation__preserves_korean_goal_and__explains_unperformed_work() -> None:
    result = format_route_confirmation(goal="일정 정리")
    assert "일정 정리" in result
    assert "메일·태스크·일정" in result
    assert "아직 생성하거나 변경한 내용은 없습니다" in result
    assert "Please" not in result


def test_route_confirmation__preserves_english_goal_and__explains_unperformed_work() -> None:
    result = format_route_confirmation(goal="Organize work")
    assert "Organize work" in result
    assert "아직 생성하거나 변경한 내용은 없습니다" in result


def test_scope_confirmation__uses_resource_labels__without_granting_write_approval() -> None:
    result = format_scope_confirmation(["TASK", "TASK_LIST", "CALENDAR_FREEBUSY"])
    assert "태스크, 캘린더" in result
    assert "실제 생성·변경 승인이 아니며" in result
    assert "TASK_LIST" not in result and "FREEBUSY" not in result
