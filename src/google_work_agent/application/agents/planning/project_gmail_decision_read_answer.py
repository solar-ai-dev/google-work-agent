"""Project explicit Gmail decision statements without generative reinterpretation."""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import NamedTuple

from google_work_agent.application.agents.planning.contracts.planning_semantics import (
    AnswerDraftCandidateV2,
    AnswerOutlineV1,
)

_DECISION_REQUEST_MARKERS = ("결정", "확정", "decision", "decided", "confirmed")
_DECISION_CLAUSE = re.compile(
    r"(?P<clause>[^.!?]{0,180}?(?:결정|확정)(?:되었|됐)?(?:습니다|됨)?[.!?]?)"
)
_FINAL_CONFIGURATION = re.compile(
    r"(?P<clause>(?:→\s*)?최종\s+구성\s+확정\s+[^.!?]{1,180}?)(?=\s+프로필은|[-]{5,}|$)"
)
_CONTEXT_LABEL = re.compile(
    r"([0-9A-Za-z가-힣()/_-]+(?:\s+[0-9A-Za-z가-힣()/_-]+){0,4}\s+(?:여부|방식|구성))"
)
_LINK = re.compile(r"\[?https?://\S+\]?", re.IGNORECASE)
_DIVIDER = re.compile(r"-{5,}")


class GmailDecisionReadAnswerProjection(NamedTuple):
    outline: AnswerOutlineV1
    draft: AnswerDraftCandidateV2


def project_gmail_decision_read_answer(
    *,
    user_request: str,
    request_intent: Mapping[str, object],
    evidence: Sequence[Mapping[str, object]],
) -> GmailDecisionReadAnswerProjection | None:
    """Return explicit decision clauses when Gmail evidence labels them as decided."""

    if not _supports_request(user_request, request_intent):
        return None

    claims: list[str] = []
    refs: list[str] = []
    for item in evidence:
        excerpt = item.get("excerpt")
        evidence_ref = _evidence_ref(item)
        if not isinstance(excerpt, str) or evidence_ref is None:
            continue
        item_claims = _decision_claims(excerpt)
        if not item_claims:
            continue
        for claim in item_claims:
            _merge_claim(claims, claim)
        refs.append(evidence_ref)
    if not claims:
        return None

    korean = any("\uac00" <= character <= "\ud7a3" for character in user_request)
    if korean:
        lead = "관련 Gmail 자료에서 결정 또는 확정으로 명시된 내용은 다음과 같습니다."
        section = "Gmail 자료에 명시된 결정 사항"
    else:
        lead = "The related Gmail messages explicitly record these decisions:"
        section = "Decisions explicitly recorded in Gmail"
    answer = f"{lead}\n\n" + "\n".join(f"- {claim}" for claim in claims)
    unique_refs = list(dict.fromkeys(refs))
    return GmailDecisionReadAnswerProjection(
        outline={"sections": [section], "evidence_refs": unique_refs},
        draft={"schema_version": 2, "answer": answer, "evidence_refs": unique_refs},
    )


def _supports_request(user_request: str, request_intent: Mapping[str, object]) -> bool:
    resources = _strings(request_intent.get("requested_resource_hints"))
    combined = " ".join([user_request, *_requested_information(request_intent)]).casefold()
    return (
        bool(resources)
        and all(resource.startswith("GMAIL") for resource in resources)
        and set(_strings(request_intent.get("requested_effect_hints"))) == {"READ"}
        and any(marker in combined for marker in _DECISION_REQUEST_MARKERS)
    )


def _requested_information(request_intent: Mapping[str, object]) -> list[str]:
    constraints = request_intent.get("constraints")
    if not isinstance(constraints, list):
        return []
    values: list[str] = []
    for constraint in constraints:
        if not isinstance(constraint, Mapping) or constraint.get("field") != "required_information":
            continue
        values.extend(_strings(constraint.get("value")))
    return values


def _decision_claims(excerpt: str) -> list[str]:
    source = _DIVIDER.sub(" ", _LINK.sub(" ", excerpt))
    final_matches = list(_FINAL_CONFIGURATION.finditer(source))
    matches = [
        match
        for match in _DECISION_CLAUSE.finditer(source)
        if not (final_matches and "최종 구성 확정" in match.group("clause"))
    ]
    matches.extend(final_matches)
    claims: list[str] = []
    for match in matches:
        claim = _clean_claim(match.group("clause"))
        claim = _with_context_label(claim, source=source, start=match.start())
        if claim and claim not in claims:
            claims.append(claim)
    return claims


def _clean_claim(value: str) -> str:
    claim = " ".join(value.replace("*", " ").split()).strip(" -→")
    if "→" in claim:
        before, after = claim.rsplit("→", 1)
        context = " ".join(before.split())[-90:].strip(" -")
        claim = f"{context} → {after.strip()}" if context else after.strip()
    return claim


def _with_context_label(claim: str, *, source: str, start: int) -> str:
    if "→" not in claim:
        return claim
    labels = _CONTEXT_LABEL.findall(source[max(0, start - 240) : start])
    if not labels:
        return claim
    label = " ".join(labels[-1].split()).strip(" -():~")
    return claim if label in claim else f"{label}: {claim}"


def _merge_claim(claims: list[str], claim: str) -> None:
    for index, existing in enumerate(claims):
        if claim in existing:
            claims[index] = claim
            return
        if existing in claim:
            return
    claims.append(claim)


def _evidence_ref(item: Mapping[str, object]) -> str | None:
    value = item.get("evidence_ref") or item.get("evidence_id") or item.get("id")
    return value if isinstance(value, str) and value else None


def _strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    return [item for item in value if isinstance(item, str)] if isinstance(value, list) else []


__all__ = ["GmailDecisionReadAnswerProjection", "project_gmail_decision_read_answer"]
