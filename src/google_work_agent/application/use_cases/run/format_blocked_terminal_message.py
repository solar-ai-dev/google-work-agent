"""Format user-facing blocked results from bounded terminal reason facts."""

from collections.abc import Sequence


def format_blocked_terminal_message(
    *,
    source_kind: str,
    reason_codes: Sequence[str],
) -> str:
    """Explain the blocked outcome without exposing internal reason codes."""

    reasons = frozenset(reason_codes)
    if "CONTEXT_BLOCKED" in reasons:
        return (
            "요청을 뒷받침할 충분한 근거를 확보하지 못해 작업을 완료하지 못했습니다. "
            "Google 변경은 실행하지 않았습니다. 검색 조건을 바꾸거나 확인할 자료를 "
            "지정해 다시 요청해 주세요."
        )
    if source_kind == "INVALID_REQUEST":
        return (
            "요청을 처리하는 데 필요한 조건을 확인하지 못해 안전하게 중단했습니다. "
            "요청 대상을 더 구체적으로 알려주세요."
        )
    return (
        "안전 정책 또는 필수 조건 때문에 요청하신 작업을 실행하지 않았습니다. "
        "Google 변경은 실행하지 않았습니다."
    )


__all__ = ["format_blocked_terminal_message"]
