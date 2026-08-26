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
