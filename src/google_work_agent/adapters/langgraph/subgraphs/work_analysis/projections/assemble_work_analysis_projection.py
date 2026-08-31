from __future__ import annotations

from collections.abc import Mapping
from typing import TypedDict, cast

from google_work_agent.application.agents.work_analysis.assemble_work_analysis import (
    ActionNecessityV1,
)
from google_work_agent.application.agents.work_analysis.contracts.work_analysis_result import (
    StateArtifactRefV1,
    WorkAmbiguityV1,
    WorkFactV1,
    WorkRelationV1,
    WorkRiskV1,
)
from google_work_agent.application.use_cases.run.policy_confirmation_receipt import (
    PolicyConfirmationReceiptV1,
)


class AssembleWorkAnalysisInput(TypedDict):
    based_on: list[StateArtifactRefV1]
    work_facts: list[WorkFactV1]
    validated_relations: list[WorkRelationV1]
    ambiguities: list[WorkAmbiguityV1]
    risks: list[WorkRiskV1]
    evidence_refs: list[str]
    action_necessity_candidate: ActionNecessityV1
    action_necessity_reason: str | None
    policy_confirmation_receipts: list[PolicyConfirmationReceiptV1]


def project_assemble_work_analysis_input(
    state: Mapping[str, object],
) -> AssembleWorkAnalysisInput:
    required = (
        "request_intent",
        "fact_candidates",
        "validated_relations",
        "ambiguity_candidates",
        "operational_risk_candidates",
        "evidence_refs",
        "__analysis_operational_risk_assessment__",
    )
    if any(key not in state for key in required):
        raise ValueError("missing typed input projection for analysis.finalize")
    assessment = cast(Mapping[str, object], state["__analysis_operational_risk_assessment__"])
    based_on: list[StateArtifactRefV1] = []
    for key in ("request_intent", "tool_route_plan", "retrieval_result"):
        artifact = state.get(key)
        if not isinstance(artifact, Mapping):
            continue
        meta = artifact.get("meta")
        if not isinstance(meta, Mapping):
            continue
        artifact_id, revision = meta.get("artifact_id"), meta.get("revision")
        if isinstance(artifact_id, str) and isinstance(revision, int):
            based_on.append({"artifact_id": artifact_id, "revision": revision})
    return {
        "based_on": based_on,
        "work_facts": cast(list[WorkFactV1], state["fact_candidates"]),
        "validated_relations": cast(list[WorkRelationV1], state["validated_relations"]),
        "ambiguities": cast(list[WorkAmbiguityV1], state["ambiguity_candidates"]),
        "risks": cast(list[WorkRiskV1], state["operational_risk_candidates"]),
        "evidence_refs": list(cast(list[str], state["evidence_refs"])),
        "action_necessity_candidate": cast(
            ActionNecessityV1, assessment["action_necessity_candidate"]
        ),
        "action_necessity_reason": cast(str | None, assessment["action_necessity_reason"]),
        "policy_confirmation_receipts": cast(
            list[PolicyConfirmationReceiptV1], state.get("policy_confirmation_receipts", [])
        ),
    }


__all__ = ["AssembleWorkAnalysisInput", "project_assemble_work_analysis_input"]
