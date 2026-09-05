"""User-facing wording for the existing Tool Routing confirmation boundary."""


def format_route_confirmation(*, user_request: str, goal: str) -> str:
    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    if korean:
        return (
            f"요청하신 목표는 ‘{goal}’입니다. 어떤 자료에 어떤 작업을 적용할지 "
            "확정하지 못했습니다. 메일·태스크·일정 중 대상과 원하는 작업을 알려주세요. "
            "아직 생성하거나 변경한 내용은 없습니다."
        )
    return (
        f"Your goal is “{goal}”. I could not determine which resource and action to use. "
        "Please specify whether you want to work with mail, tasks, or calendar events "
        "and what you want to do. Nothing has been created or changed."
    )
