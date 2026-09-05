from google_work_agent.application.agents.tool_routing.format_route_confirmation import (
    format_route_confirmation,
)


def test_route_confirmation__preserves_korean_goal_and__explains_unperformed_work() -> None:
    result = format_route_confirmation(user_request="일정을 정리해줘", goal="일정 정리")
    assert "일정 정리" in result
    assert "메일·태스크·일정" in result
    assert "아직 생성하거나 변경한 내용은 없습니다" in result
    assert "Please" not in result


def test_route_confirmation__preserves_english_goal_and__explains_unperformed_work() -> None:
    result = format_route_confirmation(user_request="Organize work", goal="Organize work")
    assert "Organize work" in result
    assert "Nothing has been created or changed" in result
