from __future__ import annotations

import json
import subprocess
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
PROJECT_ROOT = ROOT.parent
DATASETS = ROOT / "datasets"
REPORTS = ROOT / "reports"
GENERATOR_VERSION = "r2-final-validator-v1.0"
VOLATILE_REPORTS = {
    "experiments/reports/final-validation-report.json",
    "experiments/reports/final-validation-report.md",
    "experiments/reports/final-readiness-report.md",
    "experiments/reports/git-tracking-report.json",
    "experiments/reports/encoding-diagnostics.json",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            rows.append(json.loads(line))
    return rows


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def file_hash(path: Path) -> str:
    import hashlib

    return hashlib.sha256(path.read_bytes()).hexdigest()


def package_hash(paths: list[Path]) -> str:
    import hashlib

    digest = hashlib.sha256()
    for path in sorted(paths):
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_hash(path).encode("ascii"))
        digest.update(b"\0")
    return digest.hexdigest()


def detect_encoding() -> list[dict[str, Any]]:
    diagnostics = []
    for path in sorted(p for p in ROOT.rglob("*") if p.is_file()):
        if path.parts[-2] == "tools":
            continue
        data = path.read_bytes()
        bom = "NONE"
        if data.startswith(b"\xef\xbb\xbf"):
            bom = "UTF-8-BOM"
        text = data.decode("utf-8")
        diagnostics.append(
            {
                "file_path": path.relative_to(PROJECT_ROOT).as_posix(),
                "bom": bom,
                "classification": "DISPLAY_ONLY",
                "utf8_decodable": True,
                "contains_mojibake_pattern": any(token in text for token in ("�", "理", "??")),
            }
        )
    return diagnostics


def run_git_check(paths: list[Path]) -> tuple[list[str], list[str]]:
    tracked: list[str] = []
    ignored: list[str] = []
    for path in paths:
        rel = path.relative_to(PROJECT_ROOT).as_posix()
        result = subprocess.run(
            ["git", "check-ignore", "-q", rel],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            ignored.append(rel)
        else:
            tracked.append(rel)
    return tracked, ignored


def main() -> None:
    now = datetime.now(timezone.utc).isoformat()
    cases = {
        "core": read_jsonl(DATASETS / "cases" / "core.jsonl"),
        "holdout": read_jsonl(DATASETS / "cases" / "holdout.jsonl"),
        "stress": read_jsonl(DATASETS / "cases" / "stress.jsonl"),
    }
    prompts = {
        "core": read_jsonl(ROOT / "user_prompts" / "canonical-core.jsonl"),
        "holdout": read_jsonl(ROOT / "user_prompts" / "canonical-holdout.jsonl"),
        "stress": read_jsonl(ROOT / "user_prompts" / "canonical-stress.jsonl"),
    }
    resources = {
        "gmail": read_jsonl(DATASETS / "google_workspace" / "corpus" / "gmail-resources.jsonl"),
        "tasks": read_jsonl(DATASETS / "google_workspace" / "corpus" / "task-resources.jsonl"),
        "calendar": read_jsonl(DATASETS / "google_workspace" / "corpus" / "calendar-resources.jsonl"),
    }
    segments = read_jsonl(DATASETS / "google_workspace" / "segments" / "source-segments.jsonl")
    queries = read_jsonl(DATASETS / "google_workspace" / "retrieval" / "retrieval-queries.jsonl")
    gold = read_jsonl(DATASETS / "google_workspace" / "retrieval" / "relevance-gold.jsonl")
    tier_a_paths = [
        DATASETS / "agent_prompt" / "request_understanding" / "classify.jsonl",
        DATASETS / "agent_prompt" / "api_discovery_acquisition" / "plan_sources.jsonl",
        DATASETS / "agent_prompt" / "context_retriever" / "select_evidence.jsonl",
        DATASETS / "agent_prompt" / "solution_planning" / "draft_plan.jsonl",
        DATASETS / "agent_prompt" / "plan_review" / "inspect.jsonl",
    ]
    tier_a_rows = {path.stem: read_jsonl(path) for path in tier_a_paths}
    all_cases = [row for rows in cases.values() for row in rows]
    all_prompts = [row for rows in prompts.values() for row in rows]

    failures: list[str] = []
    warnings: list[str] = []

    if len(all_cases) != 92:
        failures.append("case_count_not_92")
    if len(all_prompts) != 92:
        failures.append("prompt_count_not_92")
    if len(resources["gmail"]) != 56 or len(resources["tasks"]) != 42 or len(resources["calendar"]) != 42:
        failures.append("resource_count_mismatch")
    if len(segments) != 78:
        failures.append("segment_count_not_78")
    if len(queries) != 92 or len(gold) != 92:
        failures.append("retrieval_count_mismatch")

    source_injection_cases = [
        case["case_id"] for case in all_cases if "SOURCE_PROMPT_INJECTION" in case["safety_tags"]
    ]
    adversarial_cases = [
        case["case_id"] for case in all_cases if "ADVERSARIAL_USER_REQUEST" in case["safety_tags"]
    ]

    placeholder_tokens = ("TBD", "TODO", "placeholder", "dummy", "lorem ipsum")
    placeholder_hits = []
    for path in sorted(p for p in ROOT.rglob("*") if p.is_file() and p.suffix in {".json", ".jsonl", ".csv", ".md", ".yaml"}):
        if path.parts[-2] == "tools":
            continue
        text = path.read_text(encoding="utf-8")
        if any(token in text for token in placeholder_tokens):
            placeholder_hits.append(path.relative_to(PROJECT_ROOT).as_posix())
    if placeholder_hits:
        failures.append("placeholder_tokens_present")

    encoding = detect_encoding()
    if any(item["contains_mojibake_pattern"] for item in encoding):
        warnings.append("mojibake_pattern_detected")

    jsonl_paths = sorted(ROOT.rglob("*.jsonl"))
    tracked, ignored = run_git_check(jsonl_paths)
    if ignored:
        failures.append("git_ignore_blocks_canonical_jsonl")

    split_leakage = {
        "scenario_family_overlap": {},
        "fixture_relation_family_overlap": {},
    }
    scenario_to_splits: dict[str, set[str]] = {}
    family_to_splits: dict[str, set[str]] = {}
    for case in all_cases:
        scenario_to_splits.setdefault(case["scenario_family_id"], set()).add(case["split"])
        family_to_splits.setdefault(case["fixture_relation_family"], set()).add(case["split"])
    for key, splits in scenario_to_splits.items():
        if len(splits) > 1:
            split_leakage["scenario_family_overlap"][key] = sorted(splits)
    for key, splits in family_to_splits.items():
        if {"core", "holdout"}.issubset(splits):
            split_leakage["fixture_relation_family_overlap"][key] = sorted(splits)
    if split_leakage["scenario_family_overlap"] or split_leakage["fixture_relation_family_overlap"]:
        failures.append("split_leakage_detected")

    hard_negative_quality = []
    for item in gold:
        hard_negatives = item["hard_negative_resource_ids"]
        if len(hard_negatives) < 3:
            failures.append(f"hard_negative_short:{item['retrieval_query_id']}")
        if set(hard_negatives) & set(item["required_resource_ids"]):
            failures.append(f"hard_negative_overlap:{item['retrieval_query_id']}")
        hard_negative_quality.append(
            {
                "retrieval_query_id": item["retrieval_query_id"],
                "hard_negative_resource_ids": hard_negatives,
                "status": "PASS",
            }
        )

    config_contract = read_json(REPORTS / "config-contract-report.json")
    dataset_summary = read_json(REPORTS / "dataset-summary.json")
    validator_report = read_json(REPORTS / "validation-report.json")

    write_json(REPORTS / "encoding-diagnostics.json", {"status": "PASS", "generated_at": now, "files": encoding})
    write_json(
        REPORTS / "git-tracking-report.json",
        {
            "status": "PASS" if not ignored else "FAIL",
            "generated_at": now,
            "tracked_jsonl_files": tracked,
            "ignored_jsonl_files": ignored,
            "git_add_force_required": ignored,
        },
    )

    final_status = "PASS" if not failures else "FAIL"
    if final_status == "PASS" and warnings:
        final_status = "WARN"

    input_paths = [
        path
        for path in sorted(p for p in ROOT.rglob("*") if p.is_file())
        if path.relative_to(PROJECT_ROOT).as_posix() not in VOLATILE_REPORTS
    ]

    final_validation = {
        "status": final_status,
        "generated_at": now,
        "generator_version": GENERATOR_VERSION,
        "dataset_version": dataset_summary["dataset_version"],
        "manifest_hash": package_hash(input_paths),
        "manifest_hash_basis": "sorted(relative_path + sha256(file_bytes)) excluding volatile final reports",
        "input_files": [path.relative_to(PROJECT_ROOT).as_posix() for path in input_paths],
        "input_hashes": {
            path.relative_to(PROJECT_ROOT).as_posix(): file_hash(path)
            for path in input_paths
        },
        "command": "python experiments/tools/validate_final_dataset.py",
        "failures": failures,
        "warnings": warnings,
        "existing_validator_status": validator_report["status"],
        "tier_a_counts": {key: len(value) for key, value in tier_a_rows.items()},
        "counts": {
            "cases": {split: len(rows) for split, rows in cases.items()},
            "prompts": {split: len(rows) for split, rows in prompts.items()},
            "resources": {key: len(value) for key, value in resources.items()},
            "segments": len(segments),
            "queries": len(queries),
            "gold": len(gold),
        },
    }
    write_json(REPORTS / "final-validation-report.json", final_validation)
    (REPORTS / "final-validation-report.md").write_text(
        "# Final Validation Report\n\n"
        f"- status: {final_status}\n"
        f"- generated_at: {now}\n"
        f"- dataset_version: {dataset_summary['dataset_version']}\n"
        f"- existing_validator_status: {validator_report['status']}\n"
        f"- failures: {len(failures)}\n"
        f"- warnings: {len(warnings)}\n",
        encoding="utf-8",
    )
    readiness = "READY_FOR_EXPERIMENT" if final_status == "PASS" else "READY_WITH_WARNINGS" if final_status == "WARN" else "BLOCKED"
    (REPORTS / "final-readiness-report.md").write_text(
        "# Final Readiness Report\n\n"
        f"- readiness: {readiness}\n"
        f"- existing_validator: {validator_report['status']}\n"
        f"- source_prompt_injection_cases: {', '.join(source_injection_cases)}\n"
        f"- adversarial_user_request_cases: {', '.join(adversarial_cases)}\n"
        f"- tier_a_counts: {json.dumps({key: len(value) for key, value in tier_a_rows.items()}, ensure_ascii=False)}\n"
        f"- config_status: {config_contract['status']}\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
