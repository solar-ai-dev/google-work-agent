from __future__ import annotations

import json
import re
import sys
import hashlib
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments"
DATASETS = EXP / "datasets"

CASE_FIELDS = {
    "evaluation_item_id",
    "case_id",
    "scenario_family_id",
    "fixture_relation_family",
    "split",
    "dataset_version",
    "category",
    "language",
    "entry_mode",
    "user_prompt_id",
    "fixture_snapshot_id",
    "expected_goal",
    "expected_completion_criteria",
    "required_sources",
    "required_resource_ids",
    "optional_sources",
    "forbidden_sources",
    "required_evidence",
    "expected_route",
    "expected_answer_type",
    "allowed_actions",
    "forbidden_actions",
    "argument_constraints",
    "verification_expectation",
    "ambiguity_expectation",
    "safety_tags",
    "human_rubric",
}

PROMPT_FIELDS = {
    "user_prompt_id",
    "case_id",
    "scenario_family_id",
    "split",
    "language",
    "entry_mode",
    "text",
    "paraphrase_group_id",
    "ambiguity_tags",
    "expected_confirmation",
}

RESOURCE_FIELDS = {
    "resource_id",
    "fixture_snapshot_id",
    "source",
    "resource_type",
    "title_or_subject",
    "body_or_description",
    "participants",
    "time_fields",
    "status",
    "version_token",
    "metadata",
}

SEGMENT_FIELDS = {
    "segment_id",
    "resource_id",
    "fixture_snapshot_id",
    "source",
    "text",
    "metadata",
    "chunk_index",
    "token_estimate",
}

QUERY_FIELDS = {
    "retrieval_query_id",
    "evaluation_item_id",
    "case_id",
    "fixture_snapshot_id",
    "query",
    "required_sources",
    "optional_sources",
    "forbidden_sources",
    "candidate_snapshot_id",
}

GOLD_FIELDS = {
    "retrieval_query_id",
    "required_resource_ids",
    "optional_resource_ids",
    "forbidden_resource_ids",
    "required_segment_ids",
    "optional_segment_ids",
    "hard_negative_resource_ids",
    "required_evidence",
}

NODE_FIELDS = {
    "node_dataset_item_id",
    "evaluation_item_id",
    "case_id",
    "node_id",
    "agent_role",
    "purpose",
    "input_schema_version",
    "output_schema_version",
    "input",
    "gold",
    "allowed_variations",
    "forbidden_outputs",
    "rubric",
}

FORBIDDEN_TOOLS = {
    "gmail_send_message",
    "gmail_delete_thread",
    "gmail_delete_message",
    "tasks_delete_task",
    "tasks_complete_task",
    "calendar_delete_event",
    "calendar_add_external_attendee",
    "gmail_modify_label",
}

REAL_EMAIL_RE = re.compile(r"\b[A-Za-z0-9._%+-]+@(gmail|googlemail|naver|daum|kakao|outlook|hotmail|yahoo|icloud)\.[A-Za-z]{2,}\b", re.I)
TOKEN_RE = re.compile(r"\b(ya29\.|AIza[0-9A-Za-z_-]{20,}|sk-[0-9A-Za-z_-]{20,})")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def add_error(errors: list[dict], code: str, path: str, item_id: str | None, reason: str) -> None:
    errors.append({"code": code, "path": path, "item_id": item_id, "reason": reason})


def read_json(path: Path, errors: list[dict]) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        add_error(errors, "json_parse", path.as_posix(), None, str(exc))
        return None


def read_jsonl(path: Path, errors: list[dict]) -> list[dict]:
    rows: list[dict] = []
    try:
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
                if not isinstance(row, dict):
                    add_error(errors, "jsonl_parse", path.as_posix(), f"line:{line_no}", "line is not an object")
                else:
                    rows.append(row)
            except Exception as exc:
                add_error(errors, "jsonl_parse", path.as_posix(), f"line:{line_no}", str(exc))
    except FileNotFoundError:
        add_error(errors, "missing_file", path.as_posix(), None, "file not found")
    return rows


def read_yaml_as_json(path: Path, errors: list[dict]) -> Any:
    return read_json(path, errors)


def require_fields(rows: list[dict], fields: set[str], path: Path, errors: list[dict], id_field: str) -> None:
    for row in rows:
        missing = sorted(fields - row.keys())
        if missing:
            add_error(errors, "missing_required_field", path.as_posix(), str(row.get(id_field)), ",".join(missing))


def check_duplicates(rows: list[dict], id_field: str, path: Path, errors: list[dict]) -> None:
    seen: set[str] = set()
    for row in rows:
        value = row.get(id_field)
        if not value:
            add_error(errors, "missing_id", path.as_posix(), None, id_field)
        elif value in seen:
            add_error(errors, "duplicate_id", path.as_posix(), str(value), id_field)
        else:
            seen.add(str(value))


def scan_text_files(errors: list[dict]) -> None:
    for path in list(EXP.rglob("*")) + list((ROOT / "prompts").rglob("*")):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        if REAL_EMAIL_RE.search(text):
            add_error(errors, "personal_data", path.as_posix(), None, "consumer email domain found")
        if TOKEN_RE.search(text):
            add_error(errors, "personal_data", path.as_posix(), None, "token-like secret pattern found")


def validate() -> dict:
    errors: list[dict] = []

    cases_by_split = {
        "core": read_jsonl(DATASETS / "cases" / "core.jsonl", errors),
        "holdout": read_jsonl(DATASETS / "cases" / "holdout.jsonl", errors),
        "stress": read_jsonl(DATASETS / "cases" / "stress.jsonl", errors),
    }
    prompts_by_split = {
        "core": read_jsonl(EXP / "user_prompts" / "canonical-core.jsonl", errors),
        "holdout": read_jsonl(EXP / "user_prompts" / "canonical-holdout.jsonl", errors),
        "stress": read_jsonl(EXP / "user_prompts" / "canonical-stress.jsonl", errors),
    }
    all_cases = [row for rows in cases_by_split.values() for row in rows]
    all_prompts = [row for rows in prompts_by_split.values() for row in rows]

    for split, rows in cases_by_split.items():
        path = DATASETS / "cases" / f"{split}.jsonl"
        require_fields(rows, CASE_FIELDS, path, errors, "case_id")
        check_duplicates(rows, "case_id", path, errors)
        check_duplicates(rows, "evaluation_item_id", path, errors)
    for split, rows in prompts_by_split.items():
        path = EXP / "user_prompts" / f"canonical-{split}.jsonl"
        require_fields(rows, PROMPT_FIELDS, path, errors, "user_prompt_id")
        check_duplicates(rows, "user_prompt_id", path, errors)

    case_ids = {row["case_id"] for row in all_cases if "case_id" in row}
    eval_ids = {row["evaluation_item_id"] for row in all_cases if "evaluation_item_id" in row}
    prompt_ids = {row["user_prompt_id"] for row in all_prompts if "user_prompt_id" in row}

    fixtures = []
    for path in sorted((DATASETS / "google_workspace" / "fixtures").glob("*.json")):
        data = read_json(path, errors)
        if isinstance(data, dict):
            fixtures.append(data)
    fixture_ids = {row["fixture_snapshot_id"] for row in fixtures if "fixture_snapshot_id" in row}

    resources = []
    for name in ["gmail-resources.jsonl", "task-resources.jsonl", "calendar-resources.jsonl"]:
        path = DATASETS / "google_workspace" / "corpus" / name
        rows = read_jsonl(path, errors)
        require_fields(rows, RESOURCE_FIELDS, path, errors, "resource_id")
        check_duplicates(rows, "resource_id", path, errors)
        resources.extend(rows)
    resource_ids = {row["resource_id"] for row in resources if "resource_id" in row}

    segments_path = DATASETS / "google_workspace" / "segments" / "source-segments.jsonl"
    segments = read_jsonl(segments_path, errors)
    require_fields(segments, SEGMENT_FIELDS, segments_path, errors, "segment_id")
    check_duplicates(segments, "segment_id", segments_path, errors)
    segment_ids = {row["segment_id"] for row in segments if "segment_id" in row}

    queries_path = DATASETS / "google_workspace" / "retrieval" / "retrieval-queries.jsonl"
    gold_path = DATASETS / "google_workspace" / "retrieval" / "relevance-gold.jsonl"
    queries = read_jsonl(queries_path, errors)
    relevance = read_jsonl(gold_path, errors)
    require_fields(queries, QUERY_FIELDS, queries_path, errors, "retrieval_query_id")
    require_fields(relevance, GOLD_FIELDS, gold_path, errors, "retrieval_query_id")
    check_duplicates(queries, "retrieval_query_id", queries_path, errors)
    check_duplicates(relevance, "retrieval_query_id", gold_path, errors)
    query_ids = {row["retrieval_query_id"] for row in queries if "retrieval_query_id" in row}
    gold_query_ids = {row["retrieval_query_id"] for row in relevance if "retrieval_query_id" in row}

    for case in all_cases:
        cid = case.get("case_id")
        if case.get("user_prompt_id") not in prompt_ids:
            add_error(errors, "invalid_user_prompt_ref", "cases", str(cid), str(case.get("user_prompt_id")))
        if case.get("fixture_snapshot_id") not in fixture_ids:
            add_error(errors, "invalid_fixture_ref", "cases", str(cid), str(case.get("fixture_snapshot_id")))
        for rid in case.get("selected_resource_ids", []) + case.get("required_resource_ids", []):
            if rid not in resource_ids:
                add_error(errors, "invalid_resource_ref", "cases", str(cid), rid)
        for ev in case.get("required_evidence", []):
            if ev.get("resource_id") not in resource_ids:
                add_error(errors, "invalid_resource_ref", "case.required_evidence", str(cid), str(ev.get("resource_id")))
            if ev.get("segment_id") not in segment_ids:
                add_error(errors, "invalid_segment_ref", "case.required_evidence", str(cid), str(ev.get("segment_id")))
        bad_allowed = sorted(FORBIDDEN_TOOLS.intersection(set(case.get("allowed_actions", []))))
        if bad_allowed:
            add_error(errors, "forbidden_tool", "cases", str(cid), ",".join(bad_allowed))

    for prompt in all_prompts:
        if prompt.get("case_id") not in case_ids:
            add_error(errors, "invalid_case_ref", "user_prompts", str(prompt.get("user_prompt_id")), str(prompt.get("case_id")))

    for res in resources:
        if res.get("fixture_snapshot_id") not in fixture_ids:
            add_error(errors, "invalid_fixture_ref", "resources", str(res.get("resource_id")), str(res.get("fixture_snapshot_id")))
    for seg in segments:
        if seg.get("fixture_snapshot_id") not in fixture_ids:
            add_error(errors, "invalid_fixture_ref", "segments", str(seg.get("segment_id")), str(seg.get("fixture_snapshot_id")))
        if seg.get("resource_id") not in resource_ids:
            add_error(errors, "invalid_resource_ref", "segments", str(seg.get("segment_id")), str(seg.get("resource_id")))

    for query in queries:
        qid = query.get("retrieval_query_id")
        if query.get("case_id") not in case_ids:
            add_error(errors, "invalid_case_ref", "retrieval_queries", str(qid), str(query.get("case_id")))
        if query.get("evaluation_item_id") not in eval_ids:
            add_error(errors, "invalid_evaluation_item_ref", "retrieval_queries", str(qid), str(query.get("evaluation_item_id")))
        if query.get("fixture_snapshot_id") not in fixture_ids:
            add_error(errors, "invalid_fixture_ref", "retrieval_queries", str(qid), str(query.get("fixture_snapshot_id")))
    if query_ids != gold_query_ids:
        add_error(errors, "retrieval_gold_mismatch", "retrieval", None, f"queries={len(query_ids)} gold={len(gold_query_ids)}")
    for row in relevance:
        qid = row.get("retrieval_query_id")
        for rid in row.get("required_resource_ids", []) + row.get("optional_resource_ids", []) + row.get("forbidden_resource_ids", []) + row.get("hard_negative_resource_ids", []):
            if rid not in resource_ids:
                add_error(errors, "invalid_resource_ref", "relevance_gold", str(qid), rid)
        for sid in row.get("required_segment_ids", []) + row.get("optional_segment_ids", []):
            if sid not in segment_ids:
                add_error(errors, "invalid_segment_ref", "relevance_gold", str(qid), sid)
        if len(row.get("hard_negative_resource_ids", [])) < 3:
            add_error(errors, "hard_negative_count", "relevance_gold", str(qid), "less than 3")

    registry = read_json(DATASETS / "agent_prompt" / "reserved-node-registry.json", errors) or {}
    registry_nodes = {node.get("node_id") for node in registry.get("nodes", [])}
    if len(registry_nodes) != 19:
        add_error(errors, "node_registry_count", "agent_prompt/reserved-node-registry.json", None, str(len(registry_nodes)))

    tier_a_paths = [
        DATASETS / "agent_prompt" / "request_understanding" / "classify.jsonl",
        DATASETS / "agent_prompt" / "api_discovery_acquisition" / "plan_sources.jsonl",
        DATASETS / "agent_prompt" / "context_retriever" / "select_evidence.jsonl",
        DATASETS / "agent_prompt" / "solution_planning" / "draft_plan.jsonl",
        DATASETS / "agent_prompt" / "plan_review" / "inspect.jsonl",
    ]
    agent_counts: dict[str, int] = {}
    for path in tier_a_paths:
        rows = read_jsonl(path, errors)
        require_fields(rows, NODE_FIELDS, path, errors, "node_dataset_item_id")
        check_duplicates(rows, "node_dataset_item_id", path, errors)
        if not rows:
            add_error(errors, "empty_tier_a_dataset", path.as_posix(), None, "no rows")
        for row in rows:
            node_id = row.get("node_id")
            agent_counts[node_id] = agent_counts.get(node_id, 0) + 1
            if node_id not in registry_nodes:
                add_error(errors, "invalid_node_ref", path.as_posix(), str(row.get("node_dataset_item_id")), str(node_id))
            if row.get("case_id") not in case_ids:
                add_error(errors, "invalid_case_ref", path.as_posix(), str(row.get("node_dataset_item_id")), str(row.get("case_id")))
            if row.get("evaluation_item_id") not in eval_ids:
                add_error(errors, "invalid_evaluation_item_ref", path.as_posix(), str(row.get("node_dataset_item_id")), str(row.get("evaluation_item_id")))
            text = json.dumps(row.get("gold", {}), ensure_ascii=False)
            for tool in FORBIDDEN_TOOLS:
                if f'"tool_name": "{tool}"' in text or f'"tool_name":"{tool}"' in text:
                    add_error(errors, "forbidden_tool", path.as_posix(), str(row.get("node_dataset_item_id")), tool)

    prompt_manifest = read_yaml_as_json(ROOT / "prompts" / "agent" / "manifest.yaml", errors) or {}
    prompt_entries = prompt_manifest.get("prompt_manifest", [])
    if len(prompt_entries) != 19:
        add_error(errors, "prompt_manifest_count", "prompts/agent/manifest.yaml", None, str(len(prompt_entries)))
    prompt_ids = {entry.get("prompt_id") for entry in prompt_entries}
    missing_prompts = registry_nodes - prompt_ids
    if missing_prompts:
        add_error(errors, "prompt_manifest_missing_node", "prompts/agent/manifest.yaml", None, ",".join(sorted(missing_prompts)))

    subset = read_json(DATASETS / "cases" / "subset-manifest.json", errors) or {}
    core_ids = {row["case_id"] for row in cases_by_split["core"] if "case_id" in row}
    for key in ["smoke_case_ids", "screening_case_ids"]:
        subset_ids = set(subset.get(key, []))
        if not subset_ids.issubset(core_ids):
            add_error(errors, "subset_not_core", "subset-manifest.json", key, ",".join(sorted(subset_ids - core_ids)))
    if len(subset.get("smoke_case_ids", [])) != 5:
        add_error(errors, "smoke_count", "subset-manifest.json", None, str(len(subset.get("smoke_case_ids", []))))
    if len(subset.get("screening_case_ids", [])) != 20:
        add_error(errors, "screening_count", "subset-manifest.json", None, str(len(subset.get("screening_case_ids", []))))

    expected_counts = {"core": 60, "holdout": 12, "stress": 20}
    for split, expected in expected_counts.items():
        if len(cases_by_split[split]) != expected:
            add_error(errors, "case_count", f"cases/{split}.jsonl", None, f"{len(cases_by_split[split])}!={expected}")
    if len(all_prompts) != 92:
        add_error(errors, "canonical_prompt_count", "user_prompts", None, str(len(all_prompts)))
    if not (12 <= len(fixtures) <= 18):
        add_error(errors, "fixture_count", "fixtures", None, str(len(fixtures)))

    scenario_to_splits: dict[str, set[str]] = {}
    fixture_family_to_splits: dict[str, set[str]] = {}
    paraphrase_to_splits: dict[str, set[str]] = {}
    for case in all_cases:
        scenario_to_splits.setdefault(case.get("scenario_family_id"), set()).add(case.get("split"))
        fixture_family_to_splits.setdefault(case.get("fixture_relation_family"), set()).add(case.get("split"))
    for prompt in all_prompts:
        paraphrase_to_splits.setdefault(prompt.get("paraphrase_group_id"), set()).add(prompt.get("split"))
    for scenario, splits in scenario_to_splits.items():
        if len(splits) > 1:
            add_error(errors, "split_leakage", "cases", str(scenario), ",".join(sorted(splits)))
    for family, splits in fixture_family_to_splits.items():
        if {"core", "holdout"}.issubset(splits):
            add_error(errors, "fixture_relation_core_holdout_leakage", "cases", str(family), ",".join(sorted(splits)))
    for group, splits in paraphrase_to_splits.items():
        if len(splits) > 1:
            add_error(errors, "paraphrase_split_leakage", "user_prompts", str(group), ",".join(sorted(splits)))

    for path in sorted((EXP / "configs").glob("*.yaml")):
        data = read_yaml_as_json(path, errors)
        if not isinstance(data, dict):
            add_error(errors, "yaml_parse", path.as_posix(), None, "not an object")
        elif "holdout" in json.dumps(data, ensure_ascii=False).lower() and "prompt" in path.name:
            add_error(errors, "holdout_tuning_leakage", path.as_posix(), None, "holdout mentioned in prompt tuning config")

    manifest = read_json(EXP / "manifest.json", errors) or {}
    for entry in manifest.get("files", []):
        path = ROOT / entry.get("file_path", "")
        if not path.exists():
            add_error(errors, "manifest_missing_file", "experiments/manifest.json", entry.get("file_path"), "missing")
        elif sha256(path) != entry.get("sha256"):
            add_error(errors, "manifest_hash_mismatch", "experiments/manifest.json", entry.get("file_path"), "sha256 mismatch")

    scan_text_files(errors)

    counts = {
        "case_counts": {split: len(rows) for split, rows in cases_by_split.items()},
        "canonical_user_prompt_count": len(all_prompts),
        "fixture_snapshot_count": len(fixtures),
        "resource_counts": {
            "gmail": len([r for r in resources if r.get("source") == "GMAIL"]),
            "tasks": len([r for r in resources if r.get("source") == "TASKS"]),
            "calendar": len([r for r in resources if r.get("source") == "CALENDAR"]),
            "total": len(resources),
        },
        "segment_count": len(segments),
        "retrieval_query_count": len(queries),
        "agent_tier_a_item_counts": agent_counts,
    }
    report = {
        "status": "PASS" if not errors else "FAIL",
        **counts,
        "json_parse_errors": len([e for e in errors if "parse" in e["code"]]),
        "duplicate_id_errors": len([e for e in errors if e["code"] == "duplicate_id"]),
        "invalid_reference_errors": len([e for e in errors if e["code"].startswith("invalid_")]),
        "split_leakage_errors": len([e for e in errors if "leakage" in e["code"]]),
        "forbidden_tool_errors": len([e for e in errors if e["code"] == "forbidden_tool"]),
        "personal_data_errors": len([e for e in errors if e["code"] == "personal_data"]),
        "errors": errors,
    }
    return report


def main() -> int:
    report = validate()
    out = EXP / "reports" / "validation-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8", newline="\n") as file:
        json.dump(report, file, ensure_ascii=False, indent=2)
        file.write("\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
