from collections.abc import Mapping


def route_after_extract_work_facts(state: object) -> str:
    """Do not spend three Provider calls on relations with no possible operands."""

    if isinstance(state, Mapping) and state.get("fact_candidates") == []:
        return "validate_relations"
    return "resolve_entity_relations"
