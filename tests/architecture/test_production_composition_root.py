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
