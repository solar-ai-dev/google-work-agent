"""Canonical Retrieval deterministic operation: normalize_segments."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from math import ceil
from typing import Literal, cast

from google_work_agent.application.agents.retrieval.contracts.retrieval_result import (
    AcquisitionResultV1,
)
from google_work_agent.application.agents.retrieval.contracts.segment_identity import (
    SourceSegmentIdentityV1,
)


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_segments: int = 24
    max_segment_chars: int = 4000
    max_evidence: int = 12
    max_excerpt_chars: int = 1200
    max_normalized_context_items: int = 12
    chunk_target_tokens: int = 600
    chunk_max_tokens: int = 900
    chunk_overlap_tokens: int = 80


DEFAULT_CONTEXT_BUDGET = ContextBudget()
CHUNK_SCHEMA_VERSION = 1


@dataclass(frozen=True, slots=True)
class SourceSegment:
    segment_id: str
    resource_handle: str
    source: str
    resource_type: str
    resource_id: str
    parent_id: str | None
    version: str | None
    locator: dict[str, object]
    text: str


_TEXT_KEYS = ("title", "subject", "summary", "snippet", "body", "text", "description", "notes")
_GMAIL_RESOURCE_TYPES = {"gmail_thread", "gmail_message"}
_QUOTE_HEADER_PATTERN = re.compile(
    r"^(>|On .+ wrote:$|-{5,}\s*Original Message\s*-{5,}$|_{10,}$"
    r"|보낸사람\s*:|원본 메일|-{2,}\s*원본 메일\s*-{2,})",
    re.IGNORECASE,
)
_SIGNATURE_DELIMITER_PATTERN = re.compile(r"^--\s?$")


def normalize_segments(
    acquisition_result: AcquisitionResultV1,
    *,
    context_budget: ContextBudget = DEFAULT_CONTEXT_BUDGET,
) -> list[SourceSegment]:
    """Normalize, deduplicate, sanitize, chunk, and bound acquired resources."""
    segments: list[SourceSegment] = []
    seen: set[tuple[str, str]] = set()
    for summary in acquisition_result["source_summaries"]:
        source = str(summary.get("source", "UNKNOWN"))
        resources = summary.get("resources", [])
        if not isinstance(resources, list):
            continue
        for raw in resources:
            if not isinstance(raw, dict):
                raise ValueError("$.source_summaries[].resources[] must be object")
            handle = raw.get("resource_handle")
            if not isinstance(handle, str) or not handle:
                raise ValueError("resource_handle must be non-empty string")
            resource_type = str(raw.get("resource_type", ""))
            text = _resource_text(raw, resource_type=resource_type)
            if not text.strip() or (handle, text) in seen:
                continue
            seen.add((handle, text))
            chunks = _chunk_text(text, context_budget)
            for index, chunk in enumerate(chunks):
                normalized_chunk = _truncate(chunk, context_budget.max_segment_chars)
                identity: SourceSegmentIdentityV1 = {
                    "schema_version": 1,
                    "connector_id": _connector_id(raw, summary),
                    "source_kind": _source_kind(source),
                    "resource_type": resource_type,
                    "resource_id": str(raw.get("resource_id", "")),
                    "source_version_ref": _optional_string(raw.get("version")),
                    "chunk_schema_version": CHUNK_SCHEMA_VERSION,
                    "chunk_ordinal": index,
                    "normalized_content_sha256": hashlib.sha256(
                        normalized_chunk.encode("utf-8")
                    ).hexdigest(),
                }
                segments.append(
                    SourceSegment(
                        segment_id=_segment_id(identity),
                        resource_handle=handle,
                        source=source,
                        resource_type=resource_type,
                        resource_id=str(raw.get("resource_id", "")),
                        parent_id=_optional_string(raw.get("parent_id")),
                        version=_optional_string(raw.get("version")),
                        locator={
                            "kind": "resource_payload",
                            "position": len(segments),
                            "chunk_index": index,
                            "chunk_count": len(chunks),
                        },
                        text=normalized_chunk,
                    )
                )
                if len(segments) >= context_budget.max_segments:
                    return segments
    return segments


def _resource_text(resource: dict[str, object], *, resource_type: str) -> str:
    payload = resource.get("payload")
    if not isinstance(payload, dict):
        return ""
    parts: list[str] = []
    for key in _TEXT_KEYS:
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            normalized = value.strip()
            if key == "body" and resource_type in _GMAIL_RESOURCE_TYPES:
                normalized = _strip_email_quote_and_signature(normalized)
            if normalized:
                parts.append(normalized)
    if not parts:
        parts.extend(
            f"{key}: {value.strip()}"
            for key, value in payload.items()
            if isinstance(value, str) and value.strip()
        )
    return "\n".join(parts)


def _strip_email_quote_and_signature(text: str) -> str:
    kept: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if _QUOTE_HEADER_PATTERN.match(stripped) or _SIGNATURE_DELIMITER_PATTERN.match(stripped):
            break
        kept.append(line)
    return "\n".join(kept).strip()


def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    return 0 if not stripped else max(1, ceil(len(stripped.encode("utf-8"))))


def _chunk_text(text: str, context_budget: ContextBudget) -> list[str]:
    words = text.split()
    if not words:
        return []
    if _estimate_tokens(text) <= context_budget.chunk_max_tokens:
        return [text]
    chunks: list[str] = []
    start = 0
    while start < len(words):
        count = 0
        end = start
        while end < len(words):
            word_tokens = _estimate_tokens(words[end]) + (1 if end > start else 0)
            if count + word_tokens > context_budget.chunk_max_tokens and end > start:
                break
            count += word_tokens
            end += 1
            if count >= context_budget.chunk_target_tokens:
                break
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        overlap_start = end
        overlap = 0
        while overlap_start > start and overlap < context_budget.chunk_overlap_tokens:
            overlap_start -= 1
            overlap += _estimate_tokens(words[overlap_start])
        start = max(overlap_start, start + 1)
    return chunks


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)


def _truncate(value: str, max_chars: int) -> str:
    return value if len(value) <= max_chars else value[:max_chars]


def _connector_id(resource: dict[str, object], summary: dict[str, object]) -> str:
    value = resource.get("connector_id", summary.get("connector_id", "google_workspace"))
    if not isinstance(value, str) or not value.strip():
        raise ValueError("connector_id must be a non-empty string")
    return value


def _source_kind(source: str) -> LiteralSourceKind:
    try:
        return cast(
            LiteralSourceKind,
            {"GMAIL": "gmail", "TASKS": "tasks", "CALENDAR": "calendar"}[source.upper()],
        )
    except KeyError as error:
        raise ValueError(f"unsupported retrieval source kind: {source}") from error


def _segment_id(identity: SourceSegmentIdentityV1) -> str:
    canonical = json.dumps(identity, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return "seg_" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


LiteralSourceKind = Literal["gmail", "tasks", "calendar"]


class RetrievalValidationError(ValueError):
    """Raised when a Retrieval semantic result violates its current contract."""


__all__ = [
    "ContextBudget",
    "DEFAULT_CONTEXT_BUDGET",
    "RetrievalValidationError",
    "SourceSegment",
    "_chunk_text",
    "_estimate_tokens",
    "_resource_text",
    "_strip_email_quote_and_signature",
    "_truncate",
]
