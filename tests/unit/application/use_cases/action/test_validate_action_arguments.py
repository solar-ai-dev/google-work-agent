from google_work_agent.application.use_cases.action.validate_action_arguments import (
    ValidateActionArgumentsHandler,
)


def test_validate_action_arguments__has_exact__application_owner() -> None:
    assert (
        ValidateActionArgumentsHandler.__module__
        == "google_work_agent.application.use_cases.action.validate_action_arguments"
    )
    assert ValidateActionArgumentsHandler.__name__ == "ValidateActionArgumentsHandler"
