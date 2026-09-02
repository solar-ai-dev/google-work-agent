# ruff: noqa: E501
from __future__ import annotations

import ast
import csv
import json
import re
from collections import Counter
from pathlib import Path
from typing import cast

ROOT = Path(__file__).resolve().parents[2]
ARTIFACT_ROOT = ROOT / "docs/artifacts/product-closure"
ARTIFACT_1 = ARTIFACT_ROOT / "01-canonical-implementation-traceability.csv"
ARTIFACT_2 = ARTIFACT_ROOT / "02-cross-layer-runtime-traceability.csv"
REPORT = ARTIFACT_ROOT / "03-product-closure-report.md"
CLOSURE_REVIEW_BEGIN = "<!-- BEGIN_CLOSURE_REVIEW_JSON -->"
CLOSURE_REVIEW_END = "<!-- END_CLOSURE_REVIEW_JSON -->"
CLOSURE_REVIEW_FIELDS = {
    "schema_version",
    "internal_reviewed_by",
    "internal_review_source_sha",
    "internal_review_reason",
    "reviewed_requirement_rows",
    "reviewed_lineage_rows",
    "maximum_proof_reuse_without_manual_review",
    "manually_reviewed_reused_proofs",
    "machine_enforced_runtime_proofs",
    "frontend_chain",
    "defect_proof_map",
    "independent_external_semantic_review_status",
    "review_scope",
}
NEGATIVE_ENFORCEMENT_STALE_REVIEW_TOKENS = (
    "04-runtime-authority-closure-" + "review.json",
    "REVIEW_" + "MANIFEST",
    "runtime-authority-closure-" + "review",
)
DELETED_EVALUATION_PATHS = {
    "evaluation/runner/run_experiment.py",
    "evaluation/runner/verify_product_identity.py",
    "tests/evaluation/runner/test_run_experiment.py",
}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _python_symbols(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    symbols = {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    for node in tree.body:
        targets: list[ast.expr] = []
        if isinstance(node, ast.Assign):
            targets = node.targets
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
        symbols.update(target.id for target in targets if isinstance(target, ast.Name))
    return symbols


def _typescript_symbols(path: Path) -> set[str]:
    source = path.read_text(encoding="utf-8")
    symbols = set(
        re.findall(
            r"(?m)^(?:export\s+)?(?:default\s+)?(?:async\s+)?"
            r"(?:function|class|interface|type|enum|const|let|var)\s+([A-Za-z_$][\w$]*)",
            source,
        )
    )
    for group in re.findall(r"(?m)^export\s+(?:type\s+)?\{([^}]+)\}", source):
        symbols.update(
            raw.strip().split(" as ")[-1].strip() for raw in group.split(",") if raw.strip()
        )
    return symbols


def _symbols(path: Path) -> set[str]:
    if path.suffix == ".py":
        return _python_symbols(path)
    if path.suffix in {".ts", ".tsx"}:
        return _typescript_symbols(path)
    return set()


def _assert_path_and_symbol(path_value: str, symbol_value: str, *, context: str) -> None:
    if path_value.startswith("N/A —"):
        assert symbol_value.startswith("N/A —"), f"{context}: unreasoned N/A symbol"
        return
    path = ROOT / path_value
    assert path.exists(), f"{context}: stale path {path_value}"
    if path.suffix in {".py", ".ts", ".tsx"}:
        assert symbol_value in _symbols(path), (
            f"{context}: stale symbol {path_value}::{symbol_value}"
        )
    else:
        assert symbol_value.startswith("N/A —"), (
            f"{context}: static artifact requires a reasoned N/A symbol"
        )


def _report_counter(name: str) -> int:
    match = re.search(
        rf"^{re.escape(name)} = (\d+)$", REPORT.read_text(encoding="utf-8"), re.MULTILINE
    )
    assert match is not None, f"missing report counter: {name}"
    return int(match.group(1))


def _closure_review_metadata() -> dict[str, object]:
    report = REPORT.read_text(encoding="utf-8")
    assert report.count(CLOSURE_REVIEW_BEGIN) == 1
    assert report.count(CLOSURE_REVIEW_END) == 1
    begin = report.index(CLOSURE_REVIEW_BEGIN) + len(CLOSURE_REVIEW_BEGIN)
    end = report.index(CLOSURE_REVIEW_END)
    assert begin < end
    decoded = json.loads(report[begin:end].strip())
    assert isinstance(decoded, dict)
    assert set(decoded) == CLOSURE_REVIEW_FIELDS
    assert decoded["schema_version"] == 1
    return cast(dict[str, object], decoded)


def _definition(path: Path, symbol: str) -> ast.AST:
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and (
            node.name == symbol
        ):
            return node
    raise AssertionError(f"missing definition: {path.relative_to(ROOT)}::{symbol}")


def _has_asserting_behavior(path: Path, symbol: str) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    definitions = {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }

    def visits_assertion(node: ast.AST, visited: set[str]) -> bool:
        for child in ast.walk(node):
            if isinstance(child, ast.Assert):
                return True
            if not isinstance(child, ast.Call):
                continue
            if isinstance(child.func, ast.Attribute) and child.func.attr in {"raises", "fail"}:
                return True
            if isinstance(child.func, ast.Name) and child.func.id in definitions:
                helper = child.func.id
                if helper not in visited and visits_assertion(
                    definitions[helper], visited | {helper}
                ):
                    return True
        return False

    return visits_assertion(_definition(path, symbol), {symbol})


def test_canonical_traceability_rows__against_current_tree__have_exact_unique_identity_and_locators() -> (
    None
):
    rows = _rows(ARTIFACT_1)
    ids = [row["requirement_id"] for row in rows]
    assert len(rows) == 1_011
    assert len(set(ids)) == 1_011
    for row in rows:
        source = ROOT / row["canonical_source"]
        assert source.is_file(), f"{row['requirement_id']}: stale canonical source"
        assert row["canonical_locator"].strip(), (
            f"{row['requirement_id']}: missing canonical locator"
        )
        assert row["canonical_requirement"].strip(), f"{row['requirement_id']}: missing requirement"


def test_canonical_traceability_owners__against_current_tree__resolve_exact_paths_symbols_and_callers() -> (
    None
):
    for row in _rows(ARTIFACT_1):
        requirement_id = row["requirement_id"]
        _assert_path_and_symbol(
            row["final_production_owner_path"],
            row["final_production_owner_symbol"],
            context=f"{requirement_id} owner",
        )
        _assert_path_and_symbol(
            row["final_actual_caller_path"],
            row["final_actual_caller_symbol"],
            context=f"{requirement_id} caller",
        )
        assert row["final_runtime_binding"].strip()
        assert row["final_persistence_or_effect"].strip()
        assert row["final_api_or_frontend_destination"].strip()
        for field in (
            "final_production_owner_path",
            "final_production_owner_symbol",
            "final_actual_caller_path",
            "final_actual_caller_symbol",
            "final_persistence_or_effect",
            "final_api_or_frontend_destination",
        ):
            if row[field].startswith("N/A"):
                assert row[field].startswith("N/A —"), (
                    f"{requirement_id}: unreasoned N/A in {field}"
                )


def test_canonical_traceability_tests__against_collected_sources__resolve_exact_asserting_targets() -> (
    None
):
    for row in _rows(ARTIFACT_1):
        path = ROOT / row["final_test_path"]
        assert path.is_file(), f"{row['requirement_id']}: stale test path"
        proof = row["final_test_target_or_assertion"]
        prefix, separator, detail = proof.partition(" [")
        assert separator and " — asserts `" in detail, (
            f"{row['requirement_id']}: weak proof description"
        )
        recorded_path, separator, target = prefix.partition("::")
        assert separator and recorded_path == row["final_test_path"]
        if target.startswith("test_title:"):
            title = json.loads(target.removeprefix("test_title:"))
            test_source = path.read_text(encoding="utf-8")
            assert title in test_source
            assert "expect(" in test_source, f"{row['requirement_id']}: non-asserting frontend proof"
        else:
            assert target in _python_symbols(path), (
                f"{row['requirement_id']}: stale exact test target"
            )
            assert _has_asserting_behavior(path, target), (
                f"{row['requirement_id']}: exact test target has no assertion"
            )


def test_closure_known_regressions__in_current_artifacts__use_corrected_semantic_owners_and_taxonomy() -> (
    None
):
    requirements = {row["requirement_id"]: row for row in _rows(ARTIFACT_1)}
    assert requirements["A-FUNC-001"]["final_production_owner_symbol"] == "StartupFlow"
    assert (
        requirements["A-FUNC-001"]["final_test_path"] == "frontend/tests/app/startup_flow.test.tsx"
    )
    assert (
        "ApproveActionHandler" not in requirements["B-DOM-REQ-036"]["final_production_owner_symbol"]
    )
    assert (
        requirements["B-DOM-REQ-036"]["final_production_owner_symbol"] == "transition_reject_action"
    )
    assert "routing/route_after_" in requirements["F-LG-REQ-012"]["final_production_owner_path"]
    for requirement_id in ("F-LG-REQ-012", "L-ARCH-006", "L-ARCH-071", "L-ARCH-072", "L-ARCH-076"):
        assert requirements[requirement_id]["final_disposition"] == "PASS"
        assert requirements[requirement_id]["non_blocking_debt"].startswith("N/A —")

    lineages = {row["lineage_id"]: row for row in _rows(ARTIFACT_2)}
    assert lineages["X1-PC-FINAL-001"]["consumer_symbol"] == "ScheduleRunExecutionHandler"
    assert "build_production_runtime" not in lineages["X1-PC-FINAL-001"]["consumer_symbol"]
    assert all(
        row["lineage_kind"] == "AUTHORITY"
        for lineage_id, row in lineages.items()
        if lineage_id.startswith("FINAL-AUTHORITY-")
    )


def test_cross_layer_traceability__against_current_tree__has_closed_taxonomy_contracts_and_proofs() -> (
    None
):
    rows = _rows(ARTIFACT_2)
    assert len(rows) == 88
    assert len({row["lineage_id"] for row in rows}) == 88
    assert Counter(row["lineage_kind"] for row in rows) == {
        "HANDOFF": 53,
        "AUTHORITY": 16,
        "SCENARIO": 19,
    }
    for row in rows:
        assert row["lineage_kind"] in {"HANDOFF", "AUTHORITY", "SCENARIO"}
        assert row["final_status"] == "PASS"
        assert row["semantic_authority_count"] == "1"
        assert row["competing_authority"] == "NO"
        _assert_path_and_symbol(
            row["producer_path"], row["producer_symbol"], context=f"{row['lineage_id']} producer"
        )
        _assert_path_and_symbol(
            row["consumer_path"], row["consumer_symbol"], context=f"{row['lineage_id']} consumer"
        )
        proof_path, separator, target_and_detail = row["test_or_runtime_proof"].partition("::")
        assert separator, f"{row['lineage_id']}: proof has no exact target"
        path = ROOT / proof_path
        assert path.is_file(), f"{row['lineage_id']}: stale proof path"
        target = target_and_detail.split(" [", 1)[0]
        if target.startswith("test_title:"):
            test_source = path.read_text(encoding="utf-8")
            assert json.loads(target.removeprefix("test_title:")) in test_source
            assert "expect(" in test_source, f"{row['lineage_id']}: non-asserting proof"
        else:
            assert target in _python_symbols(path), f"{row['lineage_id']}: stale proof target"
            assert _has_asserting_behavior(path, target), (
                f"{row['lineage_id']}: exact proof target has no assertion"
            )


def test_embedded_closure_review_metadata__binds_actual_callers__effects_and_asserting_tests() -> (
    None
):
    review = _closure_review_metadata()
    assert review["internal_reviewed_by"] == "Codex"
    product_source = re.search(
        r"^PRODUCT_SOURCE_SHA = ([0-9a-f]{40})$",
        REPORT.read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    assert product_source is not None
    assert review["internal_review_source_sha"] == product_source.group(1)
    assert review["reviewed_requirement_rows"] == len(_rows(ARTIFACT_1))
    assert review["reviewed_lineage_rows"] == len(_rows(ARTIFACT_2))
    assert isinstance(review["internal_review_reason"], str)
    assert review["internal_review_reason"].strip()
    assert review["independent_external_semantic_review_status"] == "PENDING"
    assert review["review_scope"] == "INTERNAL_WORKER_REVIEW_PLUS_MACHINE_CHECKS"

    proofs = cast(list[dict[str, str]], review["machine_enforced_runtime_proofs"])
    for proof in proofs:
        caller_path = ROOT / proof["caller_path"]
        effect_path = ROOT / proof["effect_path"]
        test_path = ROOT / proof["test_path"]
        _assert_path_and_symbol(
            proof["owner_path"], proof["owner_symbol"], context=proof["defect_id"]
        )
        _assert_path_and_symbol(
            proof["caller_path"], proof["caller_symbol"], context=proof["defect_id"]
        )
        _assert_path_and_symbol(
            proof["effect_path"], proof["effect_symbol"], context=proof["defect_id"]
        )
        caller_source = caller_path.read_text(encoding="utf-8")
        assert proof["owner_symbol"] in caller_source, (
            f"{proof['defect_id']}: caller neither imports nor injects owner"
        )
        composition_source = (ROOT / "src/google_work_agent/api/composition.py").read_text(
            encoding="utf-8"
        )
        assert proof["composition_symbol"] in (
            caller_source + composition_source
        ), f"{proof['defect_id']}: production composition binding is absent"
        effect_source = effect_path.read_text(encoding="utf-8")
        assert any(
            marker in effect_source
            for marker in ("invoke_structured(", "write_bytes(", "save(", "edge_map(")
        ), f"{proof['defect_id']}: effect locator has no effect operation"
        assert _has_asserting_behavior(test_path, proof["test_symbol"]), (
            f"{proof['defect_id']}: cited exact test is non-asserting"
        )

    frontend = cast(dict[str, str], review["frontend_chain"])
    api_source = (ROOT / frontend["api_path"]).read_text(encoding="utf-8")
    controller_source = (ROOT / frontend["controller_path"]).read_text(encoding="utf-8")
    component_source = (ROOT / frontend["component_path"]).read_text(encoding="utf-8")
    test_source = (ROOT / frontend["test_path"]).read_text(encoding="utf-8")
    assert f"function {frontend['api_symbol']}" in api_source
    assert frontend["api_symbol"] in controller_source
    assert frontend["controller_symbol"] in controller_source
    assert frontend["component_symbol"] in component_source
    assert "onCancel" in component_source and "expect(" in test_source


def test_traceability_proof_reuse__is_bounded_or__explicitly_manually_reviewed() -> None:
    review = _closure_review_metadata()
    threshold = review["maximum_proof_reuse_without_manual_review"]
    assert isinstance(threshold, int)
    proofs = Counter(
        row["final_test_target_or_assertion"].split(" [", 1)[0] for row in _rows(ARTIFACT_1)
    )
    excessive = {target: count for target, count in proofs.items() if count > threshold}
    assert excessive == review["manually_reviewed_reused_proofs"]


def test_product_closure_artifact_set__contains_exactly__three_current_files() -> None:
    expected = {
        "01-canonical-implementation-traceability.csv",
        "02-cross-layer-runtime-traceability.csv",
        "03-product-closure-report.md",
    }
    actual = {path.name for path in ARTIFACT_ROOT.iterdir() if path.is_file()}
    assert actual == expected


def test_retired_review_artifact__has_zero_live__current_repository_references() -> None:
    roots = (
        ROOT / "docs",
        ROOT / "src",
        ROOT / "tests",
        ROOT / "release",
        ROOT / "scripts",
        ROOT / "launcher",
        ROOT / "installer",
        ROOT / "frontend/src",
        ROOT / "frontend/tests",
    )
    searchable_suffixes = {".csv", ".json", ".md", ".py", ".ts", ".tsx"}
    for base in roots:
        for path in base.rglob("*"):
            if not path.is_file() or path.suffix not in searchable_suffixes:
                continue
            source = path.read_text(encoding="utf-8")
            for index, stale in enumerate(NEGATIVE_ENFORCEMENT_STALE_REVIEW_TOKENS):
                if index == 1:
                    live_reference = re.search(
                        rf"(?<![A-Za-z0-9_]){re.escape(stale)}(?![A-Za-z0-9_])",
                        source,
                    )
                    assert live_reference is None, f"stale review artifact reference: {path}"
                else:
                    assert stale not in source, f"stale review artifact reference: {path}"


def test_deleted_runtime_authorities__have_zero__closure_artifact_references() -> None:
    current_truth = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (ARTIFACT_1, ARTIFACT_2, REPORT)
    )
    for stale in (
        "a271de37e1888341021dab95ddf5ed3e136bc37b",
        "ports/system/contracts/application_settings.py",
        "frontend/src/app/App.test.tsx",
        "_load_installed_approved_models",
        "adapters/readiness/composite.py",
        "adapters/connectors/google/mcp",
    ):
        assert stale not in current_truth


def test_closure_report_counters__against_traceability_csvs__are_mechanically_equal() -> None:
    requirements = _rows(ARTIFACT_1)
    lineages = _rows(ARTIFACT_2)
    dispositions = Counter(row["final_disposition"] for row in requirements)
    kinds = Counter(row["lineage_kind"] for row in lineages)
    expected = {
        "CANONICAL_REQUIREMENTS_TOTAL": len(requirements),
        "UNIQUE_REQUIREMENT_IDS": len({row["requirement_id"] for row in requirements}),
        "PASS_REQUIREMENTS": dispositions["PASS"],
        "OPEN_REQUIREMENTS": dispositions["OPEN"],
        "NON_BLOCKING_DEBT_REQUIREMENTS": dispositions["NON_BLOCKING_DEBT"],
        "TOTAL_LINEAGE_ROWS": len(lineages),
        "HANDOFF_ROWS": kinds["HANDOFF"],
        "AUTHORITY_ROWS": kinds["AUTHORITY"],
        "SCENARIO_ROWS": kinds["SCENARIO"],
    }
    for name, value in expected.items():
        assert _report_counter(name) == value


def test_historical_findings__in_closure_artifacts__are_semantically_accounted() -> None:
    rows = [*_rows(ARTIFACT_1), *_rows(ARTIFACT_2)]
    finding_rows: dict[str, list[dict[str, str]]] = {}
    for row in rows:
        for finding_id in row.get("pre_remediation_finding_ids", "").split(";"):
            if finding_id and not finding_id.startswith("N/A"):
                finding_rows.setdefault(finding_id, []).append(row)
    assert len(finding_rows) == 189
    assert all(
        any(row.get("final_disposition", row.get("final_status")) == "PASS" for row in linked_rows)
        for linked_rows in finding_rows.values()
    )
    assert _report_counter("HISTORICAL_FINDING_IDS_UNIQUE") == len(finding_rows)
    assert _report_counter("ORPHAN_HISTORICAL_FINDINGS") == 0
    assert _report_counter("UNACCOUNTED_OLD_FINDINGS") == 0


def test_current_evaluation_and_generic_templates__in_closure_artifacts__contain_no_stale_or_repeated_misuse() -> (
    None
):
    text = ARTIFACT_1.read_text(encoding="utf-8") + ARTIFACT_2.read_text(encoding="utf-8")
    assert not DELETED_EVALUATION_PATHS.intersection(text.split())
    for deleted in DELETED_EVALUATION_PATHS:
        assert deleted not in text
    requirements = _rows(ARTIFACT_1)
    caller_counts = Counter(
        (row["final_actual_caller_path"], row["final_actual_caller_symbol"]) for row in requirements
    )
    assert (
        caller_counts[("src/google_work_agent/api/composition.py", "build_production_runtime")] <= 8
    )
    assert caller_counts[("frontend/src/app/main_shell.tsx", "MainShell")] <= 12
    assert all(
        "previous generic lineage template was not reused" in row["notes"]
        for row in _rows(ARTIFACT_2)
    )


def test_p0_negative_capabilities__across_current_product_tree__remain_absent() -> None:
    production = "\n".join(
        path.relative_to(ROOT).as_posix()
        for base in (ROOT / "src", ROOT / "frontend/src")
        for path in base.rglob("*")
        if path.is_file()
    )
    assert "rename_conversation" not in production
    assert "delete_conversation" not in production
    assert "evaluation/runner/run_experiment.py" not in production
    assert not (ROOT / "src/google_work_agent/ports/system/contracts/runtime.py").exists()


def test_forbidden_production_filename_exceptions__against_canonical_registry__have_no_code_only_entries() -> (
    None
):
    enforcement_path = ROOT / "tests/architecture/test_repository_architecture.py"
    enforcement = enforcement_path.read_text(encoding="utf-8")
    tree = ast.parse(enforcement)
    bad_name = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "bad_name"
    )
    source = ast.get_source_segment(enforcement, bad_name)
    assert source is not None
    assert "ROLE_FILES" in source
    assert "runtime.py" not in source
    assert "ports/system/contracts" not in source
    registry = (
        ROOT / "docs/canonical/16-repository-architecture/13-exception-registry.md"
    ).read_text(encoding="utf-8")
    for role_file in ("state.py", "graph.py", "model.py", "composition.py"):
        assert f"`{role_file}`" in registry
