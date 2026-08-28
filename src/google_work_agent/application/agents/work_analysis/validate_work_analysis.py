"""Validate the official Work Analysis artifact."""

from __future__ import annotations

from collections.abc import Mapping
from typing import cast

from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    WorkAnalysisResultV2,
)

_GUARDED = frozenset({"DUPLICATES", "CONFLICTS_WITH"})
_RISK_SEVERITIES = frozenset({"INFO", "WARNING", "BLOCKING"})


def validate_work_analysis(value: object) -> WorkAnalysisResultV2:
    if not isinstance(value, Mapping):
        raise ValueError("WorkAnalysisResultV2 must be an object")
    root = dict(value)
    expected = {
        "schema_version",
        "meta",
        "work_facts",
        "relations",
        "ambiguities",
        "risks",
        "evidence_refs",
        "policy_confirmation_receipt_refs",
        "action_necessity",
    }
    if set(root) != expected:
        raise ValueError("WorkAnalysisResultV2 keys do not match the contract")
    if root["schema_version"] != 2:
        raise ValueError("WorkAnalysisResultV2.schema_version must be 2")
    facts = _object_list(root["work_facts"], "work_facts")
    fact_ids = [_text(item.get("fact_id"), "fact_id") for item in facts]
    if len(fact_ids) != len(set(fact_ids)):
        raise ValueError("duplicate work fact id")
    fact_id_set = set(fact_ids)
    for relation in _object_list(root["relations"], "relations"):
        relation_type = _text(relation.get("relation_type"), "relation_type")
        if _text(relation.get("left_ref"), "left_ref") not in fact_id_set:
            raise ValueError("relation left_ref is unknown")
        if _text(relation.get("right_ref"), "right_ref") not in fact_id_set:
            raise ValueError("relation right_ref is unknown")
        codes = _strings(relation.get("validator_codes"), "validator_codes")
        if relation_type in _GUARDED and not codes:
            raise ValueError("guarded relation lacks deterministic validation")
    for risk in _object_list(root["risks"], "risks"):
        if risk.get("severity") not in _RISK_SEVERITIES:
            raise ValueError("invalid work risk severity")
    _strings(root["evidence_refs"], "evidence_refs")
    if root["action_necessity"] not in {"REQUIRED", "NOT_REQUIRED"}:
        raise ValueError("invalid action_necessity")
    return cast(WorkAnalysisResultV2, root)


def _object_list(value: object, field: str) -> list[dict[str, object]]:
    if not isinstance(value, list) or not all(isinstance(item, Mapping) for item in value):
        raise ValueError(f"{field} must be a list of objects")
    return [dict(item) for item in value]


def _text(value: object, field: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _strings(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) and item for item in value):
        raise ValueError(f"{field} must be a list of non-empty strings")
    if len(value) != len(set(value)):
        raise ValueError(f"{field} contains duplicates")
    return list(value)
