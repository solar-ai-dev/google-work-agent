"""Normalize schema-shaped answer strings into user-visible prose."""

from __future__ import annotations

import json
import re
from collections.abc import Mapping

_SECTION_PAIR = re.compile(
    r'"section_title"\s*:\s*"(?P<title>(?:\\.|[^"\\])*)"\s*,\s*'
    r'"content"\s*:\s*"(?P<content>.*?)"\s*(?=\r?\n\s*})',
    re.DOTALL,
)


def normalize_generated_answer_prose(answer: str) -> str:
    """Recover prose from a nested section object emitted inside the answer field."""

    stripped = answer.strip()
    if not stripped.startswith(("{", "[")):
        return stripped

    sections = _sections_from_json(stripped) or _sections_from_relaxed_text(stripped)
    if not sections:
        raise ValueError("compose_answer answer must be user-visible prose")
    return "\n\n".join(f"## {title}\n\n{content}" for title, content in sections)


def _sections_from_json(value: str) -> list[tuple[str, str]]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, Mapping):
        return []
    raw_sections = parsed.get("sections")
    if not isinstance(raw_sections, list):
        return []
    result: list[tuple[str, str]] = []
    for section in raw_sections:
        if not isinstance(section, Mapping):
            continue
        title, content = section.get("section_title"), section.get("content")
        if (
            isinstance(title, str)
            and title.strip()
            and isinstance(content, str)
            and content.strip()
        ):
            result.append((title.strip(), content.strip()))
    return result


def _sections_from_relaxed_text(value: str) -> list[tuple[str, str]]:
    return [
        (_decode_fragment(match.group("title")), _decode_fragment(match.group("content")))
        for match in _SECTION_PAIR.finditer(value)
        if match.group("title").strip() and match.group("content").strip()
    ]


def _decode_fragment(value: str) -> str:
    escaped = value.replace("\r", "\\r").replace("\n", "\\n")
    try:
        return str(json.loads(f'"{escaped}"')).strip()
    except json.JSONDecodeError:
        return value.strip()


__all__ = ["normalize_generated_answer_prose"]
