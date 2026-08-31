import ast
from pathlib import Path

ROOT = Path("src/google_work_agent")


def test_background_executor_has_one_production_binding_in_composition_root() -> None:
    bindings: list[Path] = []
    for path in ROOT.rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "BackgroundRunExecutorAdapter(" in text and path.name != "background_run_executor.py":
            bindings.append(path)

    assert bindings == [ROOT / "api" / "composition.py"]


def test_production_composition_symbol_is_exact() -> None:
    source = (ROOT / "api" / "composition.py").read_text(encoding="utf-8")
    assert "def build_production_runtime(" in source
    assert "CheckpointEffectiveBindingResolver(" in source
    assert "checkpoint, resume_target_registry" in source


def test_full_delivery_container_has_one_production_construction_authority() -> None:
    owners: list[Path] = []
    for path in ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        if any(
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ApiContainer"
            for node in ast.walk(tree)
        ):
            owners.append(path)

    assert owners == [ROOT / "api" / "composition.py"]


def test_launcher_only_supplies_environment_values_to_composition() -> None:
    launcher = ROOT / "launcher" / "dev.py"
    tree = ast.parse(launcher.read_text(encoding="utf-8"))
    forbidden_constructors: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
            continue
        name = node.func.id
        if name.endswith(("Adapter", "Handler", "Registry", "Service")):
            forbidden_constructors.append(name)

    assert forbidden_constructors == []
    source = launcher.read_text(encoding="utf-8")
    assert "build_production_container(" in source
    assert "DeferredApiContainer(" in source


def test_legacy_launcher_composition_authority_is_absent() -> None:
    assert not (ROOT / "launcher" / "connector_composition.py").exists()
    offenders = [
        path
        for path in ROOT.rglob("*.py")
        if "launcher.connector_composition" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []


def test_fastapi_app_assembly_has_one_authority() -> None:
    owners = [
        path for path in ROOT.rglob("*.py") if "def create_app(" in path.read_text(encoding="utf-8")
    ]
    assert owners == [ROOT / "api" / "app.py"]


def test_deferred_startup_task_is_tracked_and_not_workflow_execution_authority() -> None:
    source = (ROOT / "api" / "composition.py").read_text(encoding="utf-8")
    create_task_sites = [
        path
        for path in ROOT.rglob("*.py")
        if "asyncio.create_task(" in path.read_text(encoding="utf-8")
    ]
    assert create_task_sites == [ROOT / "api" / "composition.py"]
    assert "worker = asyncio.create_task(\n            asyncio.to_thread(" in source
    assert "core = await asyncio.shield(worker)" in source


def test_startup_and_shutdown_callbacks_preserve_required_order() -> None:
    source = (ROOT / "api" / "composition.py").read_text(encoding="utf-8")
    startup = source.index("startup_callbacks=(")
    reconcile = source.index("_reconcile_inflight_executions,", startup)
    drain = source.index("_drain_workflow_handoffs,", startup)
    live_loop = source.index("_start_workflow_handoff_reconciliation_loop,", startup)
    assert startup < reconcile < drain < live_loop

    shutdown = source.index("shutdown_callbacks=(", startup)
    stop_runtime = source.index("_stop_workflow_handoff_runtime,", shutdown)
    close_graph = source.index("workflow_runtime.close,", shutdown)
    close_connectors = source.index("connector_registry.close_all,", shutdown)
    assert shutdown < stop_runtime < close_graph < close_connectors


def test_sqlite_checkpoint_adapter_is_the_only_production_sqlite_saver_owner() -> None:
    owners: list[Path] = []
    import_line = "from langgraph.checkpoint.sqlite import SqliteSaver"
    for path in ROOT.rglob("*.py"):
        if import_line in path.read_text(encoding="utf-8"):
            owners.append(path)

    assert owners == [ROOT / "adapters/system/sqlite_checkpoint.py"]


def test_typed_checkpoint_projection_is_joined_to_native_checkpoint_truth() -> None:
    source = (ROOT / "adapters/system/sqlite_checkpoint.py").read_text(encoding="utf-8")
    assert "REFERENCES checkpoints(" in source
    assert "JOIN checkpoints" in source
    assert "checkpoint_blob BLOB" not in source


def test_application_never_reads_or_patches_opaque_checkpoint_blob() -> None:
    offenders = [
        path
        for path in (ROOT / "application").rglob("*.py")
        if ".checkpoint_blob" in path.read_text(encoding="utf-8")
    ]
    assert offenders == []
