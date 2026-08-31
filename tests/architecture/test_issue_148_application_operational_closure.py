"""#148 operational Application ownership and negative-proof gate."""

from pathlib import Path

ROOT = Path(__file__).parents[2]
SRC = ROOT / "src" / "google_work_agent"
OWNERS = (
    "runtime_status",
    "runtime_mode",
    "connection",
    "llm_credential",
    "setting",
    "backup",
    "diagnostic_bundle",
    "shutdown",
    "attachment",
    "resource",
    "sse_event",
    "trace_event",
)
MUTABLE_OPERATIONS = {
    "runtime_mode/update_runtime_mode.py": "reconcile_update",
    "connection/start_authorization.py": "reconcile_authorization_start",
    "connection/revoke_connection.py": "reconcile_revoke_connection",
    "llm_credential/store_llm_credential.py": "reconcile_credential",
    "llm_credential/delete_llm_credential.py": "reconcile_credential",
    "setting/update_settings.py": "reconcile_settings",
    "backup/create_backup.py": "reconcile_backup",
    "backup/restore_backup.py": "reconcile_restore",
    "diagnostic_bundle/create_diagnostic_bundle.py": "reconcile_bundle",
    "shutdown/request_shutdown.py": "reconcile_shutdown",
    "attachment/create_staged_attachment.py": "reconcile_stage",
}


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_all_mutable_operational_handlers_use_one_replay_adjudicator() -> None:
    for relative, reconcile_name in MUTABLE_OPERATIONS.items():
        source = _read(SRC / "application" / "use_cases" / relative)
        replay_import = (
            "application.use_cases.operational_replay import execute_operational_command"
        )
        assert replay_import in source
        assert "execute_operational_command(" in source
        assert reconcile_name in source
        assert "command_receipt" not in source.casefold()

    replay_implementations = list(
        (SRC / "adapters" / "system").glob("*operational_command_replay*.py")
    )
    assert [path.name for path in replay_implementations] == [
        "filesystem_operational_command_replay.py"
    ]


def test_issue_owned_application_scope_has_no_raw_infrastructure_import() -> None:
    forbidden = (
        "from pathlib import",
        "import os",
        "import shutil",
        "import sqlite3",
        "import subprocess",
        "import tempfile",
        "import keyring",
    )
    for owner in OWNERS:
        for path in (SRC / "application" / "use_cases" / owner).glob("*.py"):
            source = _read(path)
            assert not any(token in source for token in forbidden), path
            assert ".adapters." not in source, path


def test_resource_routes_use_injected_exact_handlers_only() -> None:
    route = _read(SRC / "api" / "routes" / "resources.py")
    dependencies = _read(SRC / "api" / "dependencies" / "resources.py")
    container = _read(SRC / "api" / "container.py")
    composition = _read(SRC / "api" / "composition.py")
    production = route + dependencies + container + composition

    assert "resource_query_service" not in production
    assert "ListResourcesHandler(" not in route
    assert "GetResourceCountHandler(" not in route
    assert "GetResourceDetailHandler(" not in route
    assert '@router.get("/gmail/count"' in route
    assert '@router.get("/{source}/count"' not in route
    for field in (
        "list_resources_handler",
        "get_resource_count_handler",
        "get_resource_detail_handler",
    ):
        assert field in dependencies
        assert field in container
        assert field in composition


def test_resource_support_has_no_legacy_query_facade() -> None:
    access = _read(SRC / "application" / "use_cases" / "resource" / "connector_resource_access.py")
    opaque = _read(SRC / "application" / "use_cases" / "resource" / "opaque_continuation_access.py")
    for method in (
        "def get_gmail_thread_detail(",
        "def list_gmail_threads(",
        "def list_tasks(",
        "def list_calendar_resources(",
        "def count_gmail_threads(",
        "def count_tasks(",
        "def count_calendar_resources(",
    ):
        assert method not in access
        assert method not in opaque


def test_trace_handler_is_the_only_application_trace_append_authority() -> None:
    trace_dir = SRC / "application" / "use_cases" / "trace_event"
    assert not (trace_dir / "observability.py").exists()
    emit_source = _read(trace_dir / "emit_trace_event.py")
    assert "unit_of_work.traces.append(" in emit_source
    assert "from pathlib import" not in emit_source
    assert (SRC / "adapters" / "system" / "sanitized_jsonl_log.py").is_file()


def test_runtime_mode_guard_precedes_replay_reservation() -> None:
    source = _read(SRC / "application" / "use_cases" / "runtime_mode" / "update_runtime_mode.py")
    guard = source.index("if self._has_active_run()")
    replay = source.index("execute_operational_command(", guard)
    assert guard < replay


def test_no_issue_owned_compatibility_alias_survives() -> None:
    for owner in OWNERS:
        for path in (SRC / "application" / "use_cases" / owner).glob("*.py"):
            source = _read(path)
            assert "handle = __call__" not in source, path
