from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]

ALLOWED_TOP_LEVEL_DIRECTORIES = {
    ".claude",
    ".vscode",
    "config",
    "docs",
    "evaluation",
    "frontend",
    "installer",
    "launcher",
    "release",
    "scripts",
    "src",
    "tests",
}
FORBIDDEN_TRACKED_ROOTS = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "build",
    "dist",
    "node_modules",
    "runtime",
}
RETIRED_PATH_REFERENCES = {
    ".docsync",
    ".github/workflows/doc-sync-once.yml",
    "config/COLAB-EXPERIMENT-GUIDE.md",
    "config/requirements-colab.txt",
    "docs/design/",
    "prompts/agent/",
}


def test_tracked_repository__has_only_owned_roots__and_no_generated_artifacts() -> None:
    tracked = _tracked_files()
    directories = {path.split("/", 1)[0] for path in tracked if "/" in path}

    assert directories <= ALLOWED_TOP_LEVEL_DIRECTORIES
    assert not any(path.split("/", 1)[0] in FORBIDDEN_TRACKED_ROOTS for path in tracked)
    assert not any("__pycache__" in path.split("/") for path in tracked)
    assert not any(path.endswith((".pyc", ".pyo")) for path in tracked)


def test_retired_one_time_and_parallel_authority_paths__are_absent__without_stale_refs() -> None:
    tracked = _tracked_files()

    assert not any(path.startswith((".docsync/", "prompts/")) for path in tracked)
    for path in _text_files(tracked):
        content = path.read_text(encoding="utf-8")
        for retired in RETIRED_PATH_REFERENCES:
            assert retired not in content, f"{path.relative_to(ROOT)} still references {retired}"


def test_product_closure__contains_exactly__three_artifacts() -> None:
    tracked = _tracked_files()
    closure = sorted(path for path in tracked if path.startswith("docs/artifacts/product-closure/"))

    assert closure == [
        "docs/artifacts/product-closure/01-canonical-implementation-traceability.csv",
        "docs/artifacts/product-closure/02-cross-layer-runtime-traceability.csv",
        "docs/artifacts/product-closure/03-product-closure-report.md",
    ]


def test_top_level_config__is_retained_by__current_install_consumers() -> None:
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    cpu_requirements = ROOT / "config/requirements-cpu.txt"
    gpu_requirements = ROOT / "config/requirements-gpu.txt"

    assert "config\\requirements-cpu.txt" in readme
    assert "config\\requirements-gpu.txt" in readme
    assert cpu_requirements.is_file()
    assert gpu_requirements.is_file()
    assert "-r requirements-cpu.txt" in gpu_requirements.read_text(encoding="utf-8")


def test_production_packages__are_nonempty_and_have__no_alias_only_modules() -> None:
    tracked = _tracked_files()
    production_python = {
        path
        for path in tracked
        if path.startswith("src/google_work_agent/") and path.endswith(".py")
    }
    empty_packages: list[str] = []
    alias_only_modules: list[str] = []

    for init_path in sorted(path for path in production_python if path.endswith("/__init__.py")):
        prefix = init_path.rsplit("/", 1)[0] + "/"
        if not any(path != init_path and path.startswith(prefix) for path in tracked):
            empty_packages.append(prefix.rstrip("/"))

    for relative in sorted(production_python):
        path = ROOT / relative
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        body = [
            node
            for node in tree.body
            if not (
                isinstance(node, ast.Expr)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)
            )
        ]
        if body and all(_is_alias_statement(node) for node in body):
            alias_only_modules.append(relative)

    assert empty_packages == []
    assert alias_only_modules == []
    assert not any(
        token in Path(path).stem.lower()
        for path in production_python
        for token in ("compat", "legacy", "deprecated")
    )


def _is_alias_statement(node: ast.stmt) -> bool:
    if isinstance(node, (ast.Import, ast.ImportFrom)):
        return True
    if isinstance(node, ast.Assign):
        return all(
            isinstance(target, ast.Name) and target.id == "__all__" for target in node.targets
        )
    return (
        isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "__all__"
    )


def _tracked_files() -> set[str]:
    return set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.splitlines()
    )


def _text_files(tracked: set[str]) -> list[Path]:
    suffixes = {".json", ".jsonl", ".md", ".py", ".toml", ".txt", ".yaml", ".yml"}
    return [
        ROOT / path
        for path in sorted(tracked)
        if Path(path).suffix.lower() in suffixes and ROOT / path != Path(__file__).resolve()
    ]
