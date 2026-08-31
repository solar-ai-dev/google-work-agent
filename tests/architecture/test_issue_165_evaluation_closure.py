from __future__ import annotations

import ast
import re
import subprocess
from pathlib import Path

from evaluation.reporting.write_results import RESULT_FILENAMES

ROOT = Path(__file__).parents[2]
EVALUATION_ROOT = ROOT / "evaluation"
PRODUCTION_ROOT = ROOT / "src" / "google_work_agent"

EXPECTED_CURRENT_FILES = {
    "evaluation/contracts/canonical_case.py",
    "evaluation/contracts/e2e_projection.py",
    "evaluation/contracts/product_episode_projection.py",
    "evaluation/contracts/routing_trajectory_projection.py",
    "evaluation/contracts/context_ready_snapshot.py",
    "evaluation/contracts/current_fixture_snapshot.py",
    "evaluation/contracts/experiment_config.py",
    "evaluation/contracts/node_evaluation_item.py",
    "evaluation/datasets/load_canonical_cases.py",
    "evaluation/datasets/canonical_cases_v7.jsonl",
    "evaluation/datasets/load_node_evaluation_items.py",
    "evaluation/datasets/node_evaluation_items_v1.jsonl",
    "evaluation/fixtures/load_current_fixture.py",
    "evaluation/fixtures/fixture_environment.py",
    "evaluation/fixtures/product_resource_projection.py",
    "evaluation/configs/load_experiment_config.py",
    "evaluation/projections/build_current_projections.py",
    "evaluation/projections/data/e2e_projection_v5.jsonl",
    "evaluation/projections/data/product_episode_e2e_projection_v1.jsonl",
    "evaluation/runner/run_experiment.py",
    "evaluation/graders/grade_item.py",
    "evaluation/graders/scoring-contract-v1.1.json",
    "evaluation/reporting/write_results.py",
    "evaluation/targets/target_registry.py",
    "evaluation/targets/node_product_target.py",
    "evaluation/targets/subgraph_product_target.py",
    "evaluation/targets/main_profile_product_target.py",
}
EXPECTED_MICRO_FILES = {
    "fault_profiles.jsonl",
    "injection_variants.jsonl",
    "paraphrase_robustness.jsonl",
    "resource_selected_variants.jsonl",
    "review_challenges.jsonl",
    "structured_output_repair.jsonl",
}


def test_formal_evaluation_paths_and_ledger_rows_are_exact() -> None:
    assert all((ROOT / path).is_file() for path in EXPECTED_CURRENT_FILES)
    assert {
        path.name for path in (EVALUATION_ROOT / "datasets" / "micro").glob("*.jsonl")
    } == EXPECTED_MICRO_FILES
    ledger = (ROOT / "implementation-inventory" / "ledger.md").read_text(encoding="utf-8")
    expected_rows = {
        "STR-010",
        *(f"STR-{number}" for number in range(315, 325)),
        *(f"STR-{number}" for number in range(519, 528)),
        *(f"NPA-{number:03d}" for number in range(32, 45)),
        "NPA-055",
        *(f"NPA-{number:03d}" for number in range(78, 89)),
    }
    for row_id in expected_rows:
        assert len(re.findall(rf"^\| {re.escape(row_id)} \|", ledger, flags=re.MULTILINE)) == 1


def test_required_current_repository_artifacts_are_actually_git_tracked() -> None:
    required = sorted(
        path for path in EXPECTED_CURRENT_FILES if path.endswith((".json", ".jsonl"))
    ) + sorted(f"evaluation/datasets/micro/{name}" for name in EXPECTED_MICRO_FILES)
    tracked = set(
        subprocess.run(
            ["git", "ls-files"], cwd=ROOT, check=True, capture_output=True, text=True
        ).stdout.splitlines()
    )
    assert set(required) <= tracked


def test_top_level_experiments_and_old_product_evaluation_authorities_are_absent() -> None:
    assert not (ROOT / "experiments").exists()
    assert not (ROOT / "scripts" / "experiments").exists()
    assert not (
        PRODUCTION_ROOT / "application" / "orchestration" / "controlled_post_retrieval.py"
    ).exists()
    assert not (
        PRODUCTION_ROOT / "application" / "orchestration" / "controlled_post_retrieval_profile.py"
    ).exists()
    assert (EVALUATION_ROOT / "compat" / "controlled_post_retrieval.py").is_file()
    assert (EVALUATION_ROOT / "compat" / "experiments").is_dir()


def test_product_runtime_has_zero_evaluation_or_experiments_imports() -> None:
    violations: list[str] = []
    for path in PRODUCTION_ROOT.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            if any(
                module == "evaluation" or module.startswith("evaluation.") for module in modules
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
            if any(
                module == "experiments" or module.startswith("experiments.") for module in modules
            ):
                violations.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_current_evaluation_has_no_product_mutation_or_compat_dependency() -> None:
    violations: list[str] = []
    for path in EVALUATION_ROOT.rglob("*.py"):
        if "compat" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text, filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom):
                modules = [node.module or ""]
            else:
                continue
            if any(module.startswith("evaluation.compat") for module in modules):
                violations.append(f"compat:{path.relative_to(ROOT)}:{node.lineno}")
            if any(
                module.startswith(
                    (
                        "google_work_agent.adapters.persistence",
                        "google_work_agent.domain",
                        "google_work_agent.application.prompt_runtime",
                    )
                )
                for module in modules
            ):
                violations.append(f"product-mutation:{path.relative_to(ROOT)}:{node.lineno}")
    assert violations == []


def test_runner_has_no_implicit_credentials_or_direct_provider_boundary() -> None:
    runner = (EVALUATION_ROOT / "runner" / "run_experiment.py").read_text(encoding="utf-8")
    assert "os.environ" not in runner
    assert "os.getenv" not in runner
    tree = ast.parse(runner)
    imported_modules = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {node.module or "" for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert not any(
        module.startswith(("google.auth", "googleapiclient", "httpx", "requests"))
        for module in imported_modules
    )


def test_product_python_has_no_gold_grader_or_scoring_authority() -> None:
    forbidden = re.compile(
        r"CanonicalCaseV7|EndStateGoldV1|grader_gold_ref|decision_script|"
        r"scoring-contract-v1\.1|def\s+grade_item\b|def\s+write_results\b"
    )
    violations = [
        str(path.relative_to(ROOT))
        for path in PRODUCTION_ROOT.rglob("*.py")
        if forbidden.search(path.read_text(encoding="utf-8"))
    ]
    assert violations == []


def test_scoring_and_result_writer_have_one_current_authority_and_exact_artifacts() -> None:
    current_sources = [path for path in EVALUATION_ROOT.rglob("*.py") if "compat" not in path.parts]
    grade_owners = []
    result_owners = []
    for path in current_sources:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = {
            node.name
            for node in tree.body
            if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef)
        }
        if "grade_item" in names:
            grade_owners.append(path.relative_to(ROOT).as_posix())
        if "write_results" in names:
            result_owners.append(path.relative_to(ROOT).as_posix())
    assert grade_owners == ["evaluation/graders/grade_item.py"]
    assert result_owners == ["evaluation/reporting/write_results.py"]
    assert RESULT_FILENAMES == (
        "experiment_manifest.json",
        "candidate_config.json",
        "config_diff.json",
        "evaluation_items.jsonl",
        "node_results.jsonl",
        "trajectory_results.jsonl",
        "grader_results.jsonl",
        "case_failures.jsonl",
        "summary_metrics.json",
        "budget_report.json",
        "human_review.md",
        "product_decision_record.md",
    )


def test_every_formal_evaluation_symbol_has_one_current_authority() -> None:
    expected = {
        "CanonicalCaseV7": "evaluation/contracts/canonical_case.py",
        "EndStateGoldV1": "evaluation/contracts/canonical_case.py",
        "E2EProjectionV5": "evaluation/contracts/e2e_projection.py",
        "ProductEpisodeE2EProjectionV1": ("evaluation/contracts/product_episode_projection.py"),
        "RoutingTrajectoryProjectionV2": ("evaluation/contracts/routing_trajectory_projection.py"),
        "ContextReadySnapshotV1": "evaluation/contracts/context_ready_snapshot.py",
        "EvaluationPolicyProjectionV1": "evaluation/contracts/context_ready_snapshot.py",
        "CurrentFixtureSnapshotV1": "evaluation/contracts/current_fixture_snapshot.py",
        "ExperimentConfigV1": "evaluation/contracts/experiment_config.py",
        "ExperimentTargetV1": "evaluation/contracts/experiment_config.py",
        "NodeEvaluationItemV1": "evaluation/contracts/node_evaluation_item.py",
        "load_canonical_cases": "evaluation/datasets/load_canonical_cases.py",
        "load_node_evaluation_items": "evaluation/datasets/load_node_evaluation_items.py",
        "load_current_fixture": "evaluation/fixtures/load_current_fixture.py",
        "project_product_resources": "evaluation/fixtures/product_resource_projection.py",
        "load_experiment_config": "evaluation/configs/load_experiment_config.py",
        "build_current_projections": "evaluation/projections/build_current_projections.py",
        "resolve_target": "evaluation/targets/target_registry.py",
        "execute_node_product_target": "evaluation/targets/node_product_target.py",
        "execute_subgraph_product_target": "evaluation/targets/subgraph_product_target.py",
        "execute_main_profile_product_target": "evaluation/targets/main_profile_product_target.py",
        "run_experiment": "evaluation/runner/run_experiment.py",
        "grade_item": "evaluation/graders/grade_item.py",
        "write_results": "evaluation/reporting/write_results.py",
    }
    owners: dict[str, list[str]] = {symbol: [] for symbol in expected}
    for root in (EVALUATION_ROOT, PRODUCTION_ROOT):
        for path in root.rglob("*.py"):
            if "compat" in path.parts:
                continue
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in tree.body:
                if (
                    isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
                    and node.name in owners
                ):
                    owners[node.name].append(path.relative_to(ROOT).as_posix())
    assert owners == {symbol: [path] for symbol, path in expected.items()}

    scoring_contracts = [
        path.relative_to(ROOT).as_posix()
        for path in EVALUATION_ROOT.rglob("scoring-contract-*.json")
        if "compat" not in path.parts
    ]
    assert scoring_contracts == ["evaluation/graders/scoring-contract-v1.1.json"]
