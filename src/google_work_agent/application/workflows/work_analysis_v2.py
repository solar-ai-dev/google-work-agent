"""Work Analysis V2 local contracts and official-artifact finalization.

Only ``WorkAnalysisResultV2`` is a Main-State artifact. Every contract in this
module other than the official artifact types is invocation-local and must not
be persisted in Parent/Main State or registered as a Product Prompt artifact.

Canonical authority (Workflow v7.21):
* ``assess_analysis_gaps`` solely owns semantic retrieval needs, confirmation
  text/options/reasons, and semantic risk candidates.
* WorkRelation operands are same-invocation ``WorkFactV1.fact_id`` values.
* guarded DUPLICATES/CONFLICTS_WITH relations require deterministic resolution
  through current-run Evidence to exactly one normalized resource identity per
  operand before the relation validator may promote the relation.
* only deterministic ``validated_risks`` enter ``WorkAnalysisResultV2.risks``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Literal, NotRequired, Protocol, TypedDict, cast

from google_work_agent.application.workflows.handoff_contracts import (
    BlockedSignalV1,
    ConfirmationRequiredV1,
    RegisteredResumeTargetRefV1,
    RetrievalNeedV1,
    RetrievalRequiredV1,
    RouteReconsiderationRequiredV1,
    StateArtifactMetaV1,
    StateArtifactRefV1,
)
from google_work_agent.application.workflows.state_artifacts_v2 import (
    WorkAmbiguityV1,
    WorkAnalysisResultV2,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)

ActionNecessityV1 = Literal["REQUIRED", "NOT_REQUIRED"]
_GUARDED_RELATION_TYPES = frozenset({"DUPLICATES", "CONFLICTS_WITH"})
_RISK_SEVERITIES = frozenset({"INFO", "WARNING", "BLOCKING"})


class WorkRelationLocalCandidate(TypedDict):
    relation_type: str
    left_ref: str
    right_ref: str
    evidence_refs: list[str]


class WorkAnalysisGapCompleteV1(TypedDict):
    disposition: Literal["COMPLETE"]


class WorkAnalysisGapNeedsMoreDataV1(TypedDict):
    disposition: Literal["NEEDS_MORE_DATA"]
    needs: list[RetrievalNeedV1]


class WorkAnalysisGapNeedsConfirmationV1(TypedDict):
    disposition: Literal["NEEDS_CONFIRMATION"]
    question: str
    options: list[str]
    reason_codes: list[str]


class WorkAnalysisGapRouteReconsiderationV1(TypedDict):
    disposition: Literal["ROUTE_RECONSIDERATION_REQUIRED"]
    reason_codes: list[str]


class WorkAnalysisGapBlockedV1(TypedDict):
    disposition: Literal["BLOCKED"]
    reason_codes: list[str]


WorkAnalysisGapDecisionV1 = (
    WorkAnalysisGapCompleteV1
    | WorkAnalysisGapNeedsMoreDataV1
    | WorkAnalysisGapNeedsConfirmationV1
    | WorkAnalysisGapRouteReconsiderationV1
    | WorkAnalysisGapBlockedV1
)


class WorkAnalysisLocalAggregation(TypedDict):
    """Pre-final invocation-local Work Analysis aggregation; never Parent State."""

    fact_candidates: list[dict[str, object]]
    relation_candidates: list[WorkRelationLocalCandidate]
    relation_validation_ambiguities: list[dict[str, object]]
    ambiguity_candidates: list[dict[str, object]]
    risk_candidates: list[dict[str, object]]
    relation_validation_risks: list[dict[str, object]]
    validated_risks: list[WorkRiskV1]
    gap_decision: WorkAnalysisGapDecisionV1
    evidence_refs: list[str]


class NormalizedCurrentResourceIdentityV1(TypedDict):
    """Read-only identity projected from current-run Evidence; never provider raw data."""

    resource_type: str
    resource_id: str
    parent_id: str | None


class FactIdentityResolver(Protocol):
    """Integration adapter over the final ephemeral current-run Retrieval boundary.

    Implementations must resolve only through the supplied WorkFact's
    ``evidence_refs`` and current-run Evidence. Cross-run lookup and raw provider
    payloads are forbidden. Returning zero or multiple identities is fail-closed.
    """

    def __call__(self, fact: WorkFactV1) -> Sequence[NormalizedCurrentResourceIdentityV1]: ...


class GuardedRelationValidationInputV1(TypedDict):
    relation: WorkRelationLocalCandidate
    left_fact: WorkFactV1
    right_fact: WorkFactV1
    left_identity: NormalizedCurrentResourceIdentityV1
    right_identity: NormalizedCurrentResourceIdentityV1


class RelationValidationOutcomeV1(TypedDict):
    accepted: bool
    validator_codes: list[str]
    ambiguity: NotRequired[WorkAmbiguityV1 | None]
    risk: NotRequired[WorkRiskV1 | None]
    action_necessity: NotRequired[ActionNecessityV1]


RelationValidator = Callable[[GuardedRelationValidationInputV1], RelationValidationOutcomeV1]


class WorkAnalysisV2ValidationError(ValueError):
    pass


def validate_work_analysis_gap_decision_v1(value: object) -> WorkAnalysisGapDecisionV1:
    root = _mapping(value, "$.gap_decision")
    disposition = _text(root.get("disposition"), "$.gap_decision.disposition")
    if disposition == "COMPLETE":
        _exact(root, {"disposition"}, "$.gap_decision")
        return cast(WorkAnalysisGapCompleteV1, dict(root))
    if disposition == "NEEDS_MORE_DATA":
        _exact(root, {"disposition", "needs"}, "$.gap_decision")
        raw_needs = _list(root["needs"], "$.gap_decision.needs")
        if not raw_needs:
            raise WorkAnalysisV2ValidationError("NEEDS_MORE_DATA requires at least one RetrievalNeedV1")
        needs = [_retrieval_need(v, f"$.gap_decision.needs[{i}]") for i, v in enumerate(raw_needs)]
        return {"disposition": "NEEDS_MORE_DATA", "needs": needs}
    if disposition == "NEEDS_CONFIRMATION":
        _exact(root, {"disposition", "question", "options", "reason_codes"}, "$.gap_decision")
        return {
            "disposition": "NEEDS_CONFIRMATION",
            "question": _text(root["question"], "$.gap_decision.question"),
            "options": _strings(root["options"], "$.gap_decision.options"),
            "reason_codes": _non_empty_strings(root["reason_codes"], "$.gap_decision.reason_codes"),
        }
    if disposition in {"ROUTE_RECONSIDERATION_REQUIRED", "BLOCKED"}:
        _exact(root, {"disposition", "reason_codes"}, "$.gap_decision")
        reason_codes = _non_empty_strings(root["reason_codes"], "$.gap_decision.reason_codes")
        if disposition == "ROUTE_RECONSIDERATION_REQUIRED":
            return {"disposition": "ROUTE_RECONSIDERATION_REQUIRED", "reason_codes": reason_codes}
        return {"disposition": "BLOCKED", "reason_codes": reason_codes}
    raise WorkAnalysisV2ValidationError("$.gap_decision.disposition is invalid")


def project_work_analysis_retrieval_required_v1(
    decision: WorkAnalysisGapDecisionV1,
) -> RetrievalRequiredV1:
    """Losslessly project assess_analysis_gaps needs; never synthesize information text."""

    decision = validate_work_analysis_gap_decision_v1(decision)
    if decision["disposition"] != "NEEDS_MORE_DATA":
        raise WorkAnalysisV2ValidationError("retrieval projection requires NEEDS_MORE_DATA")
    needs = [dict(need) for need in decision["needs"]]
    reason_codes = _ordered_unique(
        code for need in needs for code in cast(list[str], need["reason_codes"])
    )
    if not reason_codes:
        raise WorkAnalysisV2ValidationError("RetrievalRequiredV1 requires reason_codes")
    return {"kind": "RETRIEVAL_REQUIRED", "reason_codes": reason_codes, "needs": needs}


def project_work_analysis_confirmation_required_v1(
    decision: WorkAnalysisGapDecisionV1,
    *,
    interrupt_id: str,
    resume_target: RegisteredResumeTargetRefV1,
) -> ConfirmationRequiredV1:
    """Attach Application-owned resume metadata to local Work Analysis semantics."""

    decision = validate_work_analysis_gap_decision_v1(decision)
    if decision["disposition"] != "NEEDS_CONFIRMATION":
        raise WorkAnalysisV2ValidationError("confirmation projection requires NEEDS_CONFIRMATION")
    return {
        "kind": "CONFIRMATION_REQUIRED",
        "interrupt_id": _text(interrupt_id, "interrupt_id"),
        "owner_subgraph": "WORK_ANALYSIS",
        "resume_target": _resume_target(resume_target),
        "question": decision["question"],
        "options": list(decision["options"]),
    }


def project_work_analysis_noncomplete_signal_v1(
    decision: WorkAnalysisGapDecisionV1,
) -> RouteReconsiderationRequiredV1 | BlockedSignalV1:
    decision = validate_work_analysis_gap_decision_v1(decision)
    if decision["disposition"] == "ROUTE_RECONSIDERATION_REQUIRED":
        return {"kind": "ROUTE_RECONSIDERATION_REQUIRED", "reason_codes": list(decision["reason_codes"])}
    if decision["disposition"] == "BLOCKED":
        return {"kind": "BLOCKED", "reason_codes": list(decision["reason_codes"])}
    raise WorkAnalysisV2ValidationError("reason signal projection requires route reconsideration or block")


def validate_work_analysis_local_aggregation(
    value: object,
    *,
    allowed_evidence_refs: set[str],
) -> WorkAnalysisLocalAggregation:
    root = _mapping(value, "$")
    _exact(
        root,
        {
            "fact_candidates",
            "relation_candidates",
            "relation_validation_ambiguities",
            "ambiguity_candidates",
            "risk_candidates",
            "relation_validation_risks",
            "validated_risks",
            "gap_decision",
            "evidence_refs",
        },
        "$",
    )
    top = _evidence_refs(root["evidence_refs"], "$.evidence_refs", allowed_evidence_refs)
    top_set = set(top)

    facts: list[dict[str, object]] = []
    fact_ids: set[str] = set()
    for i, raw in enumerate(_list(root["fact_candidates"], "$.fact_candidates")):
        path = f"$.fact_candidates[{i}]"
        fact = _fact(_mapping(raw, path), path, allowed_evidence_refs)
        if fact["fact_id"] in fact_ids:
            raise WorkAnalysisV2ValidationError(f"duplicate WorkFactV1.fact_id: {fact['fact_id']}")
        fact_ids.add(fact["fact_id"])
        _nested(fact["evidence_refs"], top_set, f"{path}.evidence_refs")
        facts.append(cast(dict[str, object], fact))

    relations: list[WorkRelationLocalCandidate] = []
    for i, raw in enumerate(_list(root["relation_candidates"], "$.relation_candidates")):
        path = f"$.relation_candidates[{i}]"
        relation = _relation(raw, path, allowed_evidence_refs)
        _nested(relation["evidence_refs"], top_set, f"{path}.evidence_refs")
        if relation["left_ref"] not in fact_ids:
            raise WorkAnalysisV2ValidationError(
                f"{path}.left_ref must reference same-invocation WorkFactV1.fact_id"
            )
        if relation["right_ref"] not in fact_ids:
            raise WorkAnalysisV2ValidationError(
                f"{path}.right_ref must reference same-invocation WorkFactV1.fact_id"
            )
        relations.append(relation)

    risk_candidates = _risk_sequence(
        root["risk_candidates"], "$.risk_candidates", allowed_evidence_refs, top_set
    )
    relation_risks = _risk_sequence(
        root["relation_validation_risks"],
        "$.relation_validation_risks",
        allowed_evidence_refs,
        top_set,
    )
    validated_risks = _risk_sequence(
        root["validated_risks"], "$.validated_risks", allowed_evidence_refs, top_set
    )

    return {
        "fact_candidates": facts,
        "relation_candidates": relations,
        "relation_validation_ambiguities": _ambiguities(
            root["relation_validation_ambiguities"],
            "$.relation_validation_ambiguities",
            allowed_evidence_refs,
            top_set,
        ),
        "ambiguity_candidates": _ambiguities(
            root["ambiguity_candidates"],
            "$.ambiguity_candidates",
            allowed_evidence_refs,
            top_set,
        ),
        "risk_candidates": [cast(dict[str, object], v) for v in risk_candidates],
        "relation_validation_risks": [cast(dict[str, object], v) for v in relation_risks],
        "validated_risks": validated_risks,
        "gap_decision": validate_work_analysis_gap_decision_v1(root["gap_decision"]),
        "evidence_refs": top,
    }


def validate_and_merge_work_analysis_risks(
    *,
    risk_candidates: Sequence[Mapping[str, object]],
    relation_validation_risks: Sequence[Mapping[str, object]],
    allowed_evidence_refs: set[str],
) -> list[WorkRiskV1]:
    """Validate, de-duplicate and deterministically merge all local risk sources."""

    by_code: dict[str, WorkRiskV1] = {}
    ordered: list[WorkRiskV1] = []
    for index, raw in enumerate([*risk_candidates, *relation_validation_risks]):
        risk = _risk(raw, f"$.risk_merge[{index}]", allowed_evidence_refs)
        existing = by_code.get(risk["code"])
        if existing is not None:
            if existing != risk:
                raise WorkAnalysisV2ValidationError(
                    f"duplicate risk code has conflicting payload: {risk['code']}"
                )
            continue
        by_code[risk["code"]] = risk
        ordered.append(risk)
    return ordered


def materialize_complete_work_analysis_result_v2(
    local: WorkAnalysisLocalAggregation,
    *,
    meta: StateArtifactMetaV1,
    allowed_evidence_refs: set[str],
    policy_confirmation_receipt_refs: Sequence[StateArtifactRefV1],
    relation_validator: RelationValidator | None = None,
    fact_identity_resolver: FactIdentityResolver | None = None,
) -> WorkAnalysisResultV2:
    """Create the official COMPLETE artifact from deterministic local finalization."""

    local = validate_work_analysis_local_aggregation(local, allowed_evidence_refs=allowed_evidence_refs)
    if local["gap_decision"]["disposition"] != "COMPLETE":
        raise WorkAnalysisV2ValidationError("COMPLETE artifact requires gap_decision COMPLETE")

    facts = [
        _fact(v, f"$.fact_candidates[{i}]", allowed_evidence_refs)
        for i, v in enumerate(local["fact_candidates"])
    ]
    facts_by_id = {fact["fact_id"]: fact for fact in facts}
    ambiguities = [
        _ambiguity(v, f"$.relation_validation_ambiguities[{i}]", allowed_evidence_refs)
        for i, v in enumerate(local["relation_validation_ambiguities"])
    ]
    ambiguities += [
        _ambiguity(v, f"$.ambiguity_candidates[{i}]", allowed_evidence_refs)
        for i, v in enumerate(local["ambiguity_candidates"])
    ]

    relation_risks: list[Mapping[str, object]] = list(local["relation_validation_risks"])
    relations: list[WorkRelationV1] = []
    action_necessity: ActionNecessityV1 = "REQUIRED"
    for relation in local["relation_candidates"]:
        left_fact = facts_by_id[relation["left_ref"]]
        right_fact = facts_by_id[relation["right_ref"]]
        if relation["relation_type"] not in _GUARDED_RELATION_TYPES:
            relations.append({**relation, "validator_codes": []})
            continue
        if relation_validator is None or fact_identity_resolver is None:
            raise WorkAnalysisV2ValidationError(
                f"{relation['relation_type']} requires deterministic relation and fact-identity validation"
            )
        left_identities = list(fact_identity_resolver(left_fact))
        right_identities = list(fact_identity_resolver(right_fact))
        if len(left_identities) != 1 or len(right_identities) != 1:
            ambiguities.append(
                {
                    "code": "RELATION_OPERAND_IDENTITY_UNRESOLVED",
                    "description": "guarded relation operand did not resolve to exactly one current-run identity",
                    "evidence_refs": _ordered_unique(
                        [*left_fact["evidence_refs"], *right_fact["evidence_refs"], *relation["evidence_refs"]]
                    ),
                }
            )
            continue
        outcome = relation_validator(
            {
                "relation": relation,
                "left_fact": left_fact,
                "right_fact": right_fact,
                "left_identity": _identity(left_identities[0], "left_identity"),
                "right_identity": _identity(right_identities[0], "right_identity"),
            }
        )
        codes = _non_empty_strings(
            outcome.get("validator_codes"), "$.relation_validation.validator_codes"
        )
        if outcome.get("accepted") is True:
            relations.append({**relation, "validator_codes": codes})
        elif outcome.get("ambiguity") is not None:
            ambiguities.append(
                _ambiguity(
                    cast(Mapping[str, object], outcome["ambiguity"]),
                    "$.relation_validation.ambiguity",
                    allowed_evidence_refs,
                )
            )
        if outcome.get("risk") is not None:
            relation_risks.append(cast(Mapping[str, object], outcome["risk"]))
        necessity = outcome.get("action_necessity")
        if necessity not in {None, "REQUIRED", "NOT_REQUIRED"}:
            raise WorkAnalysisV2ValidationError("invalid action_necessity")
        if necessity == "NOT_REQUIRED":
            action_necessity = "NOT_REQUIRED"

    risks = validate_and_merge_work_analysis_risks(
        risk_candidates=cast(Sequence[Mapping[str, object]], local["risk_candidates"]),
        relation_validation_risks=relation_risks,
        allowed_evidence_refs=allowed_evidence_refs,
    )
    declared_validated = list(local["validated_risks"])
    if declared_validated and declared_validated != risks:
        raise WorkAnalysisV2ValidationError("validated_risks does not match deterministic risk finalization")
    if any(risk["severity"] == "BLOCKING" for risk in risks):
        raise WorkAnalysisV2ValidationError(
            "unresolved BLOCKING risk requires Work Analysis BLOCKED disposition and Application BlockRun"
        )

    return {
        "schema_version": 2,
        "meta": _meta(meta),
        "work_facts": facts,
        "relations": relations,
        "ambiguities": ambiguities,
        "risks": risks,
        "evidence_refs": _evidence_refs(local["evidence_refs"], "$.evidence_refs", allowed_evidence_refs),
        "policy_confirmation_receipt_refs": [
            _artifact_ref(v, f"$.policy_confirmation_receipt_refs[{i}]")
            for i, v in enumerate(policy_confirmation_receipt_refs)
        ],
        "action_necessity": action_necessity,
    }


def _fact(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkFactV1:
    _exact(value, {"fact_id", "fact_type", "value", "evidence_refs"}, path)
    raw = value["value"]
    fact_value: str | list[str] = (
        _text(raw, f"{path}.value") if isinstance(raw, str) else _strings(raw, f"{path}.value")
    )
    return {
        "fact_id": _text(value["fact_id"], f"{path}.fact_id"),
        "fact_type": _text(value["fact_type"], f"{path}.fact_type"),
        "value": fact_value,
        "evidence_refs": _evidence_refs(value["evidence_refs"], f"{path}.evidence_refs", allowed),
    }


def _relation(value: object, path: str, allowed: set[str]) -> WorkRelationLocalCandidate:
    item = _mapping(value, path)
    _exact(item, {"relation_type", "left_ref", "right_ref", "evidence_refs"}, path)
    refs = _evidence_refs(item["evidence_refs"], f"{path}.evidence_refs", allowed)
    if not refs:
        raise WorkAnalysisV2ValidationError(f"{path}.evidence_refs must not be empty")
    return {
        "relation_type": _text(item["relation_type"], f"{path}.relation_type"),
        "left_ref": _text(item["left_ref"], f"{path}.left_ref"),
        "right_ref": _text(item["right_ref"], f"{path}.right_ref"),
        "evidence_refs": refs,
    }


def _retrieval_need(value: object, path: str) -> RetrievalNeedV1:
    item = _mapping(value, path)
    _exact(item, {"required_information", "reason_codes"}, path)
    return {
        "required_information": _text(item["required_information"], f"{path}.required_information"),
        "reason_codes": _non_empty_strings(item["reason_codes"], f"{path}.reason_codes"),
    }


def _resume_target(value: object) -> RegisteredResumeTargetRefV1:
    item = _mapping(value, "resume_target")
    _exact(item, {"subgraph_id", "node_id", "graph_version"}, "resume_target")
    if item["subgraph_id"] != "WORK_ANALYSIS":
        raise WorkAnalysisV2ValidationError("Work Analysis confirmation must resume WORK_ANALYSIS")
    return cast(
        RegisteredResumeTargetRefV1,
        {
            "subgraph_id": "WORK_ANALYSIS",
            "node_id": _text(item["node_id"], "resume_target.node_id"),
            "graph_version": _text(item["graph_version"], "resume_target.graph_version"),
        },
    )


def _ambiguities(
    value: object, path: str, allowed: set[str], top: set[str]
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for i, raw in enumerate(_list(value, path)):
        item_path = f"{path}[{i}]"
        item = _ambiguity(_mapping(raw, item_path), item_path, allowed)
        _nested(item["evidence_refs"], top, f"{item_path}.evidence_refs")
        result.append(cast(dict[str, object], item))
    return result


def _ambiguity(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkAmbiguityV1:
    _exact(value, {"code", "description", "evidence_refs"}, path)
    return {
        "code": _text(value["code"], f"{path}.code"),
        "description": _text(value["description"], f"{path}.description"),
        "evidence_refs": _evidence_refs(value["evidence_refs"], f"{path}.evidence_refs", allowed),
    }


def _risk_sequence(
    value: object, path: str, allowed: set[str], top: set[str]
) -> list[WorkRiskV1]:
    result: list[WorkRiskV1] = []
    for i, raw in enumerate(_list(value, path)):
        item_path = f"{path}[{i}]"
        risk = _risk(_mapping(raw, item_path), item_path, allowed)
        _nested(risk["evidence_refs"], top, f"{item_path}.evidence_refs")
        result.append(risk)
    return result


def _risk(value: Mapping[str, object], path: str, allowed: set[str]) -> WorkRiskV1:
    _exact(value, {"code", "severity", "description", "evidence_refs"}, path)
    severity = _text(value["severity"], f"{path}.severity")
    if severity not in _RISK_SEVERITIES:
        raise WorkAnalysisV2ValidationError(f"{path}.severity is invalid")
    return {
        "code": _text(value["code"], f"{path}.code"),
        "severity": cast(Literal["INFO", "WARNING", "BLOCKING"], severity),
        "description": _text(value["description"], f"{path}.description"),
        "evidence_refs": _evidence_refs(value["evidence_refs"], f"{path}.evidence_refs", allowed),
    }


def _identity(value: object, path: str) -> NormalizedCurrentResourceIdentityV1:
    item = _mapping(value, path)
    _exact(item, {"resource_type", "resource_id", "parent_id"}, path)
    parent = item["parent_id"]
    if parent is not None and (not isinstance(parent, str) or not parent):
        raise WorkAnalysisV2ValidationError(f"{path}.parent_id must be non-empty or null")
    return {
        "resource_type": _text(item["resource_type"], f"{path}.resource_type"),
        "resource_id": _text(item["resource_id"], f"{path}.resource_id"),
        "parent_id": cast(str | None, parent),
    }


def _meta(value: object) -> StateArtifactMetaV1:
    item = _mapping(value, "$.meta")
    _exact(item, {"artifact_id", "revision", "based_on"}, "$.meta")
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkAnalysisV2ValidationError("$.meta.revision is invalid")
    return {
        "artifact_id": _text(item["artifact_id"], "$.meta.artifact_id"),
        "revision": revision,
        "based_on": [
            _artifact_ref(v, f"$.meta.based_on[{i}]")
            for i, v in enumerate(_list(item["based_on"], "$.meta.based_on"))
        ],
    }


def _artifact_ref(value: object, path: str) -> StateArtifactRefV1:
    item = _mapping(value, path)
    _exact(item, {"artifact_id", "revision"}, path)
    revision = item["revision"]
    if not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
        raise WorkAnalysisV2ValidationError(f"{path}.revision is invalid")
    return {"artifact_id": _text(item["artifact_id"], f"{path}.artifact_id"), "revision": revision}


def _evidence_refs(value: object, path: str, allowed: set[str]) -> list[str]:
    refs = _strings(value, path)
    if len(refs) != len(set(refs)):
        raise WorkAnalysisV2ValidationError(f"{path} contains duplicates")
    unknown = [ref for ref in refs if ref not in allowed]
    if unknown:
        raise WorkAnalysisV2ValidationError(f"{path} contains unknown/current-run-invalid evidence refs: {unknown}")
    return refs


def _nested(refs: Sequence[str], top: set[str], path: str) -> None:
    missing = [ref for ref in refs if ref not in top]
    if missing:
        raise WorkAnalysisV2ValidationError(f"{path} must also be listed in top-level evidence_refs: {missing}")


def _ordered_unique(values: object) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for raw in cast(object, values):  # type: ignore[union-attr]
        value = _text(raw, "ordered_unique")
        if value not in seen:
            seen.add(value)
            result.append(value)
    return result


def _mapping(value: object, path: str) -> dict[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(k, str) for k in value):
        raise WorkAnalysisV2ValidationError(f"{path} must be an object with string keys")
    return dict(value)


def _list(value: object, path: str) -> list[object]:
    if not isinstance(value, list):
        raise WorkAnalysisV2ValidationError(f"{path} must be an array")
    return list(value)


def _strings(value: object, path: str) -> list[str]:
    return [_text(v, f"{path}[{i}]") for i, v in enumerate(_list(value, path))]


def _non_empty_strings(value: object, path: str) -> list[str]:
    items = _strings(value, path)
    if not items:
        raise WorkAnalysisV2ValidationError(f"{path} must not be empty")
    return items


def _text(value: object, path: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise WorkAnalysisV2ValidationError(f"{path} must be a non-empty string")
    return value


def _exact(value: Mapping[str, object], expected: set[str], path: str) -> None:
    if set(value) != expected:
        raise WorkAnalysisV2ValidationError(f"{path} keys are invalid")


__all__ = [
    "ActionNecessityV1",
    "FactIdentityResolver",
    "GuardedRelationValidationInputV1",
    "NormalizedCurrentResourceIdentityV1",
    "RelationValidationOutcomeV1",
    "RelationValidator",
    "WorkAnalysisGapDecisionV1",
    "WorkAnalysisLocalAggregation",
    "WorkAnalysisV2ValidationError",
    "WorkRelationLocalCandidate",
    "materialize_complete_work_analysis_result_v2",
    "project_work_analysis_confirmation_required_v1",
    "project_work_analysis_noncomplete_signal_v1",
    "project_work_analysis_retrieval_required_v1",
    "validate_and_merge_work_analysis_risks",
    "validate_work_analysis_gap_decision_v1",
    "validate_work_analysis_local_aggregation",
]
