"""Architecture guards for Wave-B API runtime/control ownership."""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "src" / "google_work_agent" / "api" / "routes"
USE_CASES = ROOT / "src" / "google_work_agent" / "application" / "use_cases"


def test_runtime_and_identity_routes_use_application_handlers() -> None:
    runtime = (ROUTES / "runtime.py").read_text(encoding="utf-8")
    identity = (ROUTES / "identity.py").read_text(encoding="utf-8")
    assert ".query_service().get_runtime_summary()" not in runtime
    assert ".query_service().get_current_google_account()" not in identity
    assert "GetRuntimeSummaryHandler" in runtime
    assert "GetGoogleAccountHandler" in identity


def test_runtime_control_routes_do_not_import_provider_sdks() -> None:
    prohibited = ("googleapiclient", "google.oauth2", "requests", "httpx")
    for route_name in ("runtime.py", "identity.py", "llm.py", "settings.py", "health.py"):
        source = (ROUTES / route_name).read_text(encoding="utf-8")
        for dependency in prohibited:
            assert dependency not in source


def test_application_use_cases_do_not_depend_on_api_schemas() -> None:
    for owner in ("runtime", "identity", "llm", "settings", "backup", "health"):
        for path in (USE_CASES / owner).glob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert "google_work_agent.api.schemas" not in source


def test_target_routes_do_not_bypass_locked_dependency_boundary() -> None:
    prohibited = ("google_work_agent.api.container", "google_work_agent.api.route_dependencies")
    for route_name in ("runtime.py", "identity.py", "llm.py", "settings.py", "session.py", "health.py"):
        source = (ROUTES / route_name).read_text(encoding="utf-8")
        for dependency in prohibited:
            assert dependency not in source


def test_session_bootstrap_stays_transport_security_owned() -> None:
    source = (ROUTES / "session.py").read_text(encoding="utf-8")
    assert "bootstrap_grant_store" in source
    assert "local_session_manager" in source
    assert "httponly=True" in source
    assert 'samesite="strict"' in source
