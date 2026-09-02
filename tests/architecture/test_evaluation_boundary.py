from __future__ import annotations

import ast
import subprocess
from pathlib import Path

ROOT = Path(__file__).parents[2]
EVALUATION = ROOT / "evaluation"
PRODUCT_ROOTS = (ROOT / "src" / "google_work_agent", ROOT / "launcher")

EXPECTED_EVALUATION_CODE = {
    "evaluation/__init__.py",
    "evaluation/client/__init__.py",
    "evaluation/client/http.py",
    "evaluation/dataset.py",
    "evaluation/grader.py",
    "evaluation/runner.py",
}


def test_single_evaluation_owner__has_no_legacy__framework_or_parallel_root() -> None:
    assert not (ROOT / "experiments").exists()
    assert not (EVALUATION / "compat").exists()
    assert not any(
        (EVALUATION / name).exists()
        for name in (
            "contracts",
            "domain",
            "application",
            "infrastructure",
            "orchestration",
            "targets",
            "fixtures",
            "projections",
            "reporting",
        )
    )
    tracked = _tracked_files()
    assert {
        path for path in tracked if path.startswith("evaluation/") and path.endswith(".py")
    } == (EXPECTED_EVALUATION_CODE)


def test_product_and__evaluation_import_graph__is_bidirectionally_closed() -> None:
    product_violations: list[str] = []
    for root in PRODUCT_ROOTS:
        for path in root.rglob("*.py"):
            for module, line in _imports(path):
                if module == "evaluation" or module.startswith("evaluation."):
                    product_violations.append(f"{path.relative_to(ROOT)}:{line}:{module}")
    assert product_violations == []

    evaluation_violations: list[str] = []
    for path in EVALUATION.rglob("*.py"):
        for module, line in _imports(path):
            if module == "google_work_agent" or module.startswith("google_work_agent."):
                evaluation_violations.append(f"{path.relative_to(ROOT)}:{line}:{module}")
            if module == "importlib" or module.startswith("importlib."):
                evaluation_violations.append(f"dynamic:{path.relative_to(ROOT)}:{line}:{module}")
    assert evaluation_violations == []


def test_evaluation_assets_are__repository_only_and_results__are_local_by_default() -> None:
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'include = ["google_work_agent*"]' in pyproject
    assert "evaluation*" not in pyproject
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "/evaluation/results/" in gitignore
    tracked = _tracked_files()
    assert not any(path.startswith("evaluation/results/") for path in tracked)
    required = {
        "evaluation/README.md",
        "evaluation/datasets/e2e/canonical_cases_v7.jsonl",
        "evaluation/datasets/e2e/product_episodes_v1.jsonl",
        "evaluation/datasets/agent/node_evaluation_items_v1.jsonl",
        "evaluation/scoring-contract-v1.1.json",
    }
    assert required <= tracked


def test_evaluation_assets__do_not_reference__retired_experiments_tree() -> None:
    checked_suffixes = {".json", ".jsonl", ".md"}
    for owner in (EVALUATION / "configs", EVALUATION / "datasets"):
        for path in owner.rglob("*"):
            if path.is_file() and path.suffix in checked_suffixes:
                assert "experiments/" not in path.read_text(encoding="utf-8"), path


def _tracked_files() -> set[str]:
    return set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.splitlines()
    )


def _imports(path: Path) -> list[tuple[str, int]]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    result: list[tuple[str, int]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            result.extend((alias.name, node.lineno) for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            result.append((node.module or "", node.lineno))
    return result
