from google_work_agent.application.agents.planning.assemble_plan import assemble_plan


def test_assembly_consumes_previously_derived_dependencies() -> None:
    seeds = [
        {
            "action_id": "a1",
            "route_id": "r1",
            "tool_id": "tasks_update_task",
            "effect": "UPDATE",
            "arguments": {},
            "evidence_refs": ["e1"],
        },
        {
            "action_id": "a2",
            "route_id": "r2",
            "tool_id": "tasks_update_task",
            "effect": "UPDATE",
            "arguments": {},
            "evidence_refs": ["e1"],
        },
    ]
    plan = assemble_plan(
        artifact_id="p1",
        revision=1,
        based_on=[],
        action_seeds=seeds,  # type: ignore[arg-type]
        dependency_candidates=[
            {"action_id": "a2", "depends_on_action_id": "a1", "reason": "SAME_RESOURCE_ORDER"}
        ],  # type: ignore[list-item]
    )
    assert plan["actions"][1]["depends_on_action_ids"] == ["a1"]
