"""Pure segmentation and chunking for context retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import partial
from math import ceil

import google_work_agent.application.workflows._schema_support as _schema
from google_work_agent.application.workflows.handoff_contracts import AcquisitionResultV1


@dataclass(frozen=True, slots=True)
class ContextBudget:
    max_segments: int = 24
    # Safety ceiling applied per-segment after chunking. Kept comfortably above
    # chunk_max_tokens' char-equivalent (~900 tokens * 4 chars/token) so a
    # legitimate max-size chunk never gets clipped by this outer cap.
    max_segment_chars: int = 4000
    max_evidence: int = 12
    max_excerpt_chars: int = 1200
    max_normalized_context_items: int = 12
    # docs/05-context-retrieval.md section 10: Gmail chunk target/max/overlap,
    # expressed in tokens per the canonical contract. Token counts here are a
    # deterministic approximation (see _estimate_tokens), not a real
    # tokenizer -- the project has none, and docs/00-CODE-AGENT-START-HERE.md
    # says not to add a new tokenizer dependency for this.
    chunk_target_tokens: int = 600
    chunk_max_tokens: int = 900
    chunk_overlap_tokens: int = 80


DEFAULT_CONTEXT_BUDGET = ContextBudget()


@dataclass(frozen=True, slots=True)
class _SourceSegment:
    segment_id: str
    resource_handle: str
    source: str
    resource_type: str
    resource_id: str
    parent_id: str | None
    version: str | None
    locator: dict[str, object]
    text: str


_TEXT_KEYS = (
    "title",
    "subject",
    "summary",
    "snippet",
    "body",
    "text",
    "description",
    "notes",
)


class ContextRetrievalValidationError(ValueError):
    """Raised when context retrieval structured output is invalid."""


_GMAIL_RESOURCE_TYPES = {"gmail_thread", "gmail_message"}


def _segments_from_acquisition(
    acquisition_result: AcquisitionResultV1,
    context_budget: ContextBudget,
) -> list[_SourceSegment]:
    """Build ordered, bounded Segments from Stage 5 acquisition resources.

    Each resource's normalized text is chunked per docs/05 section 10 (Gmail
    chunk target/max/overlap) rather than truncated to a single Segment, so a
    long Gmail message becomes multiple ordered, overlapping Segments instead
    of losing everything past the first max_segment_chars characters.
    """

    segments: list[_SourceSegment] = []
    seen: set[tuple[str, str]] = set()
    for source_summary in acquisition_result["source_summaries"]:
        source = str(source_summary.get("source", "UNKNOWN"))
        resources = source_summary.get("resources", [])
        if not isinstance(resources, list):
            continue
        for resource in resources:
            resource_map = _require_mapping(resource, "$.source_summaries[].resources[]")
            resource_handle = _require_string(resource_map, "resource_handle", "$.resource")
            resource_type = str(resource_map.get("resource_type", ""))
            text = _resource_text(resource_map, resource_type=resource_type)
            if not text.strip():
                continue
            dedupe_key = (resource_handle, text)
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            chunks = _chunk_text(text, context_budget)
            for chunk_index, chunk_text in enumerate(chunks):
                segment_id = f"seg-{len(segments) + 1}"
                segments.append(
                    _SourceSegment(
                        segment_id=segment_id,
                        resource_handle=resource_handle,
                        source=source,
                        resource_type=resource_type,
                        resource_id=str(resource_map.get("resource_id", "")),
                        parent_id=_optional_string(resource_map.get("parent_id")),
                        version=_optional_string(resource_map.get("version")),
                        locator={
                            "kind": "resource_payload",
                            "position": len(segments),
                            "chunk_index": chunk_index,
                            "chunk_count": len(chunks),
                        },
                        text=_truncate(chunk_text, context_budget.max_segment_chars),
                    )
                )
                if len(segments) >= context_budget.max_segments:
                    return segments
    return segments


def _resource_text(resource: dict[str, object], *, resource_type: str = "") -> str:
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
        for key, value in payload.items():
            if isinstance(value, str) and value.strip():
                parts.append(f"{key}: {value.strip()}")
    return "\n".join(parts)


_QUOTE_HEADER_PATTERN = re.compile(
    r"^(>|On .+ wrote:$|-{5,}\s*Original Message\s*-{5,}$|_{10,}$"
    r"|보낸사람\s*:|원본 메일|-{2,}\s*원본 메일\s*-{2,})",
    re.IGNORECASE,
)


_SIGNATURE_DELIMITER_PATTERN = re.compile(r"^--\s?$")


def _strip_email_quote_and_signature(text: str) -> str:
    kept_lines: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if _QUOTE_HEADER_PATTERN.match(stripped) or _SIGNATURE_DELIMITER_PATTERN.match(stripped):
            break
        kept_lines.append(line)
    return "\n".join(kept_lines).strip()


_BYTES_PER_ESTIMATED_TOKEN = 1


def _estimate_tokens(text: str) -> int:
    stripped = text.strip()
    if not stripped:
        return 0
    byte_length = len(stripped.encode("utf-8"))
    return max(1, ceil(byte_length / _BYTES_PER_ESTIMATED_TOKEN))


def _chunk_text(text: str, context_budget: ContextBudget) -> list[str]:
    """Split text into ordered, bounded, overlapping chunks.

    Short text (<= chunk_max_tokens) is returned as a single chunk unchanged.
    Longer text is split on whitespace word boundaries, accumulating words
    per chunk up to chunk_target_tokens (never exceeding chunk_max_tokens),
    then carrying roughly chunk_overlap_tokens worth of trailing words into
    the next chunk's start so nearby chunks share context at the boundary.
    """

    words = text.split()
    if not words:
        return []
    if _estimate_tokens(text) <= context_budget.chunk_max_tokens:
        return [text]

    chunks: list[str] = []
    start = 0
    total = len(words)
    while start < total:
        token_count = 0
        end = start
        while end < total:
            # +1 accounts for the joining space _estimate_tokens will count
            # once these words are actually " ".join()-ed -- with an exact
            # byte-count estimator (no rounding slack per word), omitting
            # this would let the real joined-chunk estimate creep past
            # chunk_max_tokens by one byte per word.
            separator_tokens = 1 if end > start else 0
            word_tokens = _estimate_tokens(words[end]) + separator_tokens
            if token_count + word_tokens > context_budget.chunk_max_tokens and end > start:
                break
            token_count += word_tokens
            end += 1
            if token_count >= context_budget.chunk_target_tokens:
                break
        chunks.append(" ".join(words[start:end]))
        if end >= total:
            break
        overlap_start = end
        overlap_tokens = 0
        while overlap_start > start and overlap_tokens < context_budget.chunk_overlap_tokens:
            overlap_start -= 1
            overlap_tokens += _estimate_tokens(words[overlap_start])
        start = max(overlap_start, start + 1)
    return chunks


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _truncate(value: str, max_chars: int) -> str:
    if len(value) <= max_chars:
        return value
    return value[:max_chars]
_require_mapping = partial(_schema.require_mapping, error_cls=ContextRetrievalValidationError)
_require_string = partial(_schema.require_string, error_cls=ContextRetrievalValidationError)

