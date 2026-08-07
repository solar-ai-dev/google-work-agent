"""Request body size helpers."""

from __future__ import annotations


def is_body_too_large(*, content_length: int | None, actual_length: int, limit_bytes: int) -> bool:
    if content_length is not None and content_length > limit_bytes:
        return True
    return actual_length > limit_bytes
