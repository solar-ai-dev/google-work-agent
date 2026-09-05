"""User-facing wording for the existing Tool Routing confirmation boundary."""

from collections.abc import Sequence


def format_route_confirmation(*, goal: str) -> str:
    return (
        f"요청하신 목표는 ‘{goal}’입니다. 어떤 자료에 어떤 작업을 적용할지 "
        "확정하지 못했습니다. 메일·태스크·일정 중 대상과 원하는 작업을 알려주세요. "
        "아직 생성하거나 변경한 내용은 없습니다."
    )


def format_scope_confirmation(resource_types: Sequence[str]) -> str:
    labels = dict.fromkeys(
        "메일" if resource.startswith("GMAIL") else
        "태스크" if resource.startswith("TASK") else
        "캘린더" if resource.startswith("CALENDAR") else "추가 업무 자료"
        for resource in resource_types
    )
    return (
        f"요청을 안전하게 처리하려면 {', '.join(labels)} 자료를 추가로 읽어야 합니다. "
        "중복이나 일정 충돌을 확인하기 위한 조회 범위를 넓혀도 될까요? "
        "조회 허용은 실제 생성·변경 승인이 아니며, 실행 전에 별도로 확인합니다."
    )
