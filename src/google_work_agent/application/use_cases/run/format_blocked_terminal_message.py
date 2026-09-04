"""Format user-facing blocked results from bounded terminal reason facts."""

from collections.abc import Sequence


def format_blocked_terminal_message(
    *,
    korean: bool,
    source_kind: str,
    reason_codes: Sequence[str],
) -> str:
    """Explain the blocked outcome without exposing internal reason codes."""

    reasons = frozenset(reason_codes)
    if "CONTEXT_BLOCKED" in reasons:
        if korean:
            return (
                "요청과 일치하는 Google 자료를 찾지 못해 답변을 완성하지 못했습니다. "
                "Google 변경은 실행하지 않았습니다. 검색 조건을 바꾸거나 확인할 자료를 "
                "지정해 다시 요청해 주세요."
            )
        return (
            "I could not complete the answer because no matching Google source was found. "
            "No Google change was executed. Try different search terms or select the source "
            "you want me to check."
        )
    if source_kind == "INVALID_REQUEST":
        return (
            "요청을 처리하는 데 필요한 조건을 확인하지 못해 안전하게 중단했습니다. "
            "요청 대상을 더 구체적으로 알려주세요."
            if korean
            else (
                "I could not determine the information needed to handle the request safely. "
                "Please specify the target more precisely."
            )
        )
    return (
        "안전 정책 또는 필수 조건 때문에 요청하신 작업을 실행하지 않았습니다. "
        "Google 변경은 실행하지 않았습니다."
        if korean
        else (
            "I did not execute the request because a safety policy or required condition "
            "blocked it. No Google change was executed."
        )
    )


__all__ = ["format_blocked_terminal_message"]
