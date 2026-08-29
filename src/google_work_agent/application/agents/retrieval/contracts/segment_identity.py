"""Stable Retrieval segment identity contract."""

from typing import Literal, Required, TypedDict


class SourceSegmentIdentityV1(TypedDict):
    schema_version: Required[Literal[1]]
    connector_id: Required[str]
    source_kind: Required[Literal["gmail", "tasks", "calendar"]]
    resource_type: Required[str]
    resource_id: Required[str]
    source_version_ref: Required[str | None]
    chunk_schema_version: Required[int]
    chunk_ordinal: Required[int]
    normalized_content_sha256: Required[str]


__all__ = ["SourceSegmentIdentityV1"]
