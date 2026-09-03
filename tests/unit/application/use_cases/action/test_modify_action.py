from google_work_agent.application.use_cases.action.modify_action import ModifyActionHandler


def test_modify_action__has_exact__application_owner() -> None:
    assert (
        ModifyActionHandler.__module__
        == "google_work_agent.application.use_cases.action.modify_action"
    )
    assert ModifyActionHandler.__name__ == "ModifyActionHandler"
