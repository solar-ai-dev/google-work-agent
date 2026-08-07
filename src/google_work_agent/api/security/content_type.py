"""Content-Type validation helpers."""

from __future__ import annotations


def is_allowed_json_content_type(content_type: str | None) -> bool:
    if content_type is None:
        return False
    media_type, *_params = (part.strip().lower() for part in content_type.split(";"))
    if media_type != "application/json":
        return False
    for parameter in content_type.split(";")[1:]:
        normalized = parameter.strip().lower()
        if not normalized:
            continue
        if normalized != "charset=utf-8":
            return False
    return True
