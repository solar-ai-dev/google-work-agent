from google_work_agent.application.use_cases.connection.revoke_connection import (
    RevokeConnectionHandler,
)


def test_revoke_connection__has_exact__application_owner() -> None:
    assert (
        RevokeConnectionHandler.__module__
        == "google_work_agent.application.use_cases.connection.revoke_connection"
    )
    assert RevokeConnectionHandler.__name__ == "RevokeConnectionHandler"
