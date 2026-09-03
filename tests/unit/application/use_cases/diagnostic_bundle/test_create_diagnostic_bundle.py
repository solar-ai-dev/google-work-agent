from google_work_agent.application.use_cases.diagnostic_bundle.create_diagnostic_bundle import (
    CreateDiagnosticBundleHandler,
)


def test_create_diagnostic_bundle__has_exact__application_owner() -> None:
    assert (
        CreateDiagnosticBundleHandler.__module__
        == "google_work_agent.application.use_cases.diagnostic_bundle.create_diagnostic_bundle"
    )
    assert CreateDiagnosticBundleHandler.__name__ == "CreateDiagnosticBundleHandler"
