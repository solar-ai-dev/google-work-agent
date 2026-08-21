from google_work_agent.application.agents.tool_routing.select_tool_if_needed import select_tool_if_needed
def test_select_tool_if_needed__single_registry_candidate__does_not_require_llm()->None:
    selected,budget=select_tool_if_needed(llm_runtime=None,route_id="route-1",connector_id="google_workspace",resource_type="TASK",effect="CREATE",eligible_tool_ids=("tasks_create_task",),request=None,retry_budget={})  # type: ignore[arg-type]
    assert selected=="tasks_create_task";assert budget=={}
