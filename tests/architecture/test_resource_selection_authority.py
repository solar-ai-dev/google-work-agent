from pathlib import Path

ROOT = Path("src/google_work_agent")


def test_selection_handle_authentication__is_owned_only__by_canonical_operations() -> None:
    offenders = []
    authorities = {
        ROOT / "application/use_cases/resource/issue_selection_handle.py",
        ROOT / "application/use_cases/resource/resolve_selection_handle.py",
    }
    for path in ROOT.rglob("*.py"):
        if path in authorities:
            continue
        if "hmac.new(" in path.read_text(encoding="utf-8") and "selection_handle" in path.name:
            offenders.append(path)
    assert offenders == []


def test_resource_ref_application__operations_do_not__import_concrete_adapters() -> None:
    paths = (
        ROOT / "application/use_cases/resource_ref/resolve_resource_ref.py",
        ROOT / "application/use_cases/resource_ref/persist_resource_ref.py",
    )
    assert all("adapters." not in path.read_text(encoding="utf-8") for path in paths)


def test_start_run__wire_accepts_only__opaque_selection_handles() -> None:
    schema = (ROOT / "api/schemas/runs/start_run.py").read_text(encoding="utf-8")
    route = (ROOT / "api/routes/runs.py").read_text(encoding="utf-8")

    assert "selected_resource_handles" in schema
    assert "selected_resource_ids" not in schema
    assert "SelectedResourceRefModel" not in schema
    assert "ResolveSelectionHandleQuery(" in route
    assert "SelectedResourceRef(**" not in route


def test_start_run_has__no_raw_resource__wire_compatibility_path() -> None:
    frontend_submit = Path("frontend/src/features/run/request_composer.tsx").read_text(
        encoding="utf-8"
    )

    assert "selected_resource_handles: selectionHandles" in frontend_submit
    assert "selected_resource_ids" not in frontend_submit
