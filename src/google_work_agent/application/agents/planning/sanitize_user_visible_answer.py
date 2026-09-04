"""Remove internal workflow identifiers from user-visible answer prose."""

from __future__ import annotations

import re
from collections.abc import Iterable

_INTERNAL_REFERENCE_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:evidence|fact|artifact|segment)[-_:][A-Za-z0-9_.:-]+"
    r"(?![A-Za-z0-9_.:-])",
    re.IGNORECASE,
)
_REASON_CODE = re.compile(r"(?<![A-Z0-9_])(?:[A-Z][A-Z0-9]*_){1,}[A-Z0-9]+(?![A-Z0-9_])")
_INTERNAL_FIELD_LABELS = re.compile(
    r"`?(?:work_facts|evidence_refs|reason_codes|risks|thought_process)`?",
    re.IGNORECASE,
)
_FOREIGN_SCRIPT_FRAGMENT = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\u0400-\u04ff]+")


def sanitize_user_visible_answer(
    answer: str,
    *,
    internal_refs: Iterable[str],
    user_request: str,
    source_texts: Iterable[str] = (),
) -> str:
    """Replace diagnostic-only refs and codes while retaining natural prose."""

    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    reference_label = "확인한 자료" if korean else "the reviewed material"
    state_label = "내부 상태" if korean else "an internal status"
    result = answer
    for ref in sorted(set(internal_refs), key=len, reverse=True):
        if ref:
            result = result.replace(ref, reference_label)
    result = _INTERNAL_REFERENCE_TOKEN.sub(reference_label, result)
    result = _INTERNAL_FIELD_LABELS.sub(reference_label, result)
    result = _REASON_CODE.sub(state_label, result)
    if korean:
        source_text = "\n".join(source_texts)
        result = _FOREIGN_SCRIPT_FRAGMENT.sub(
            lambda match: match.group(0) if match.group(0) in source_text else "",
            result,
        )
        result = re.sub(r"[ \t]{2,}", " ", result)
    return result.strip()


__all__ = ["sanitize_user_visible_answer"]
