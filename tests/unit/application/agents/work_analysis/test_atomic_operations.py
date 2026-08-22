from google_work_agent.application.agents.work_analysis.detect_duplicate_conflict_candidates import detect_duplicate_conflict_candidates
from google_work_agent.application.agents.work_analysis.extract_work_facts import extract_work_facts
from google_work_agent.application.agents.work_analysis.resolve_temporal_dependencies import resolve_temporal_dependencies


def _semantic_input():
    return {"user_request": "x", "request_intent": {}, "evidence": []}


def test_extract_work_facts_rejects_evidence_outside_current_result():
    def produce(_input):
        return {"fact_candidates": [{"fact_id": "f1", "fact_type": "TASK", "value": "x", "evidence_refs": ["stale"]}]}
    try:
        extract_work_facts(semantic_input=_semantic_input(), produce=produce, allowed_evidence_refs={"e1"})
    except ValueError as exc:
        assert "outside" in str(exc)
    else:
        raise AssertionError("cross-run/stale evidence must fail closed")


def test_guarded_relation_remains_candidate_until_validation():
    facts = [{"fact_id": "f1", "fact_type": "TASK", "value": "a", "evidence_refs": ["e1"]}, {"fact_id": "f2", "fact_type": "TASK", "value": "b", "evidence_refs": ["e1"]}]
    def produce(_input, _facts):
        return {"relation_candidates": [{"relation_type": "DUPLICATES", "left_ref": "f1", "right_ref": "f2", "evidence_refs": ["e1"]}]}
    result = detect_duplicate_conflict_candidates(semantic_input=_semantic_input(), work_facts=facts, produce=produce, allowed_evidence_refs={"e1"})
    assert result == [{"relation_type": "DUPLICATES", "left_ref": "f1", "right_ref": "f2", "evidence_refs": ["e1"]}]
    assert "validator_codes" not in result[0]


def test_temporal_operation_does_not_absorb_duplicate_semantics():
    facts = [{"fact_id": "f1", "fact_type": "DATE", "value": "a", "evidence_refs": ["e1"]}, {"fact_id": "f2", "fact_type": "DATE", "value": "b", "evidence_refs": ["e1"]}]
    def produce(_input, _facts):
        return {"relation_candidates": [{"relation_type": "DUPLICATES", "left_ref": "f1", "right_ref": "f2", "evidence_refs": ["e1"]}]}
    assert resolve_temporal_dependencies(semantic_input=_semantic_input(), work_facts=facts, produce=produce, allowed_evidence_refs={"e1"}) == []
