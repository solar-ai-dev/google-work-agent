"""Canonical get-run-snapshot wire response."""

from google_work_agent.api.schemas.model import ApiModel


class RunSnapshotResponseV1(ApiModel):
    snapshot: dict[str, object]
    api_contract_version: str


__all__ = ["RunSnapshotResponseV1"]
