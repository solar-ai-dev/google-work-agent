from __future__ import annotations

from collections.abc import Mapping
from typing import Literal, cast

from google_work_agent.application.agents.request_understanding.contracts.request_intent import (
    AmbiguityV1, ConstraintKindValue, ConstraintV1, RequestIntentCandidateV1, RequestIntentV2,
)

class RequestUnderstandingValidationError(ValueError):
    """Raised when a Request Understanding artifact violates its owner contract."""

_CONSTRAINT_KINDS = {"PERSON", "EMAIL", "DATE", "TIME", "RESOURCE", "SCOPE", "USER_REQUIREMENT"}
_EFFECTS = {"READ", "CREATE", "UPDATE", "SEND", "DELETE"}

def validate_intent(value: object, *, require_meta: bool = False) -> RequestIntentCandidateV1 | RequestIntentV2:
    root = _mapping(value, "$")
    expected = {"schema_version", "goal", "completion_conditions", "constraints", "requested_effect_hints", "requested_resource_hints", "analysis_requirement", "ambiguity"}
    if require_meta:
        expected.add("meta")
    if set(root) != expected:
        raise RequestUnderstandingValidationError("RequestIntentV2 fields are invalid")
    if root.get("schema_version") != 2:
        raise RequestUnderstandingValidationError("$.schema_version must be 2")
    goal = _string(root, "goal", "$")
    completion_conditions = _string_list(root.get("completion_conditions"), "$.completion_conditions")
    constraints = [_constraint(item, f"$.constraints[{index}]") for index, item in enumerate(_list(root.get("constraints"), "$.constraints"))]
    effects = _string_list(root.get("requested_effect_hints"), "$.requested_effect_hints")
    if any(effect not in _EFFECTS for effect in effects):
        raise RequestUnderstandingValidationError("$.requested_effect_hints contains an invalid effect")
    resource_hints = _string_list(root.get("requested_resource_hints"), "$.requested_resource_hints")
    analysis_requirement = root.get("analysis_requirement")
    if analysis_requirement not in {"NONE", "REQUIRED"}:
        raise RequestUnderstandingValidationError("$.analysis_requirement is invalid")
    ambiguity = _ambiguity(root.get("ambiguity"))
    candidate: RequestIntentCandidateV1 = {"schema_version": 2, "goal": goal, "completion_conditions": completion_conditions, "constraints": constraints, "requested_effect_hints": cast(list[Literal["READ", "CREATE", "UPDATE", "SEND", "DELETE"]], effects), "requested_resource_hints": resource_hints, "analysis_requirement": cast(Literal["NONE", "REQUIRED"], analysis_requirement), "ambiguity": ambiguity}
    if not require_meta:
        return candidate
    meta = _mapping(root.get("meta"), "$.meta")
    if set(meta) != {"artifact_id", "revision", "based_on"}:
        raise RequestUnderstandingValidationError("$.meta fields are invalid")
    artifact_id = _string(meta, "artifact_id", "$.meta")
    revision = meta.get("revision")
    based_on = meta.get("based_on")
    if not isinstance(revision, int) or revision < 1 or not isinstance(based_on, list):
        raise RequestUnderstandingValidationError("$.meta is invalid")
    return cast(RequestIntentV2, {**candidate, "meta": {"artifact_id": artifact_id, "revision": revision, "based_on": list(based_on)}})

def _ambiguity(value: object) -> AmbiguityV1:
    root = _mapping(value, "$.ambiguity")
    if set(root) != {"requires_confirmation", "reason_codes", "missing_fields"}:
        raise RequestUnderstandingValidationError("$.ambiguity fields are invalid")
    requires_confirmation = root.get("requires_confirmation")
    if not isinstance(requires_confirmation, bool):
        raise RequestUnderstandingValidationError("$.ambiguity.requires_confirmation must be boolean")
    return {"requires_confirmation": requires_confirmation, "reason_codes": _string_list(root.get("reason_codes"), "$.ambiguity.reason_codes"), "missing_fields": _string_list(root.get("missing_fields"), "$.ambiguity.missing_fields")}

def _constraint(value: object, path: str) -> ConstraintV1:
    root = _mapping(value, path)
    if set(root) != {"kind", "field", "value"}:
        raise RequestUnderstandingValidationError(f"{path} fields are invalid")
    kind = root.get("kind")
    if kind not in _CONSTRAINT_KINDS:
        raise RequestUnderstandingValidationError(f"{path}.kind is invalid")
    field = _string(root, "field", path)
    raw_value = root.get("value")
    normalized_value: str | list[str] = raw_value if isinstance(raw_value, str) else _string_list(raw_value, f"{path}.value")
    return {"kind": cast(ConstraintKindValue, kind), "field": field, "value": normalized_value}

def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise RequestUnderstandingValidationError(f"{path} must be an object")
    return cast(Mapping[str, object], value)

def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise RequestUnderstandingValidationError(f"{path} must be a list")
    return value

def _string(root: Mapping[str, object], key: str, path: str) -> str:
    value = root.get(key)
    if not isinstance(value, str):
        raise RequestUnderstandingValidationError(f"{path}.{key} must be a string")
    return value

def _string_list(value: object, path: str) -> list[str]:
    items = _list(value, path)
    if any(not isinstance(item, str) for item in items):
        raise RequestUnderstandingValidationError(f"{path} must contain strings")
    return cast(list[str], items)
