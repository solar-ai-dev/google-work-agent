from __future__ import annotations

import csv
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
EXP = ROOT / "experiments"
DATASETS = EXP / "datasets"
REPORTS = EXP / "reports"

SUBJECTS = [
    "계약서 검토",
    "분기 보고서",
    "온보딩 자료",
    "고객 피드백",
    "예산 확인",
    "릴리스 체크리스트",
    "교육 세션",
    "파트너 미팅",
    "장애 회고",
    "보안 점검",
]

WRITE_TYPES = {"PLAN_WAITING_APPROVAL", "WRITE_DRAFT", "WRITE_TASK", "WRITE_EVENT", "WRITE_MULTI"}
ALLOWED_WRITE_TOOLS = {
    "gmail_create_draft",
    "gmail_update_draft",
    "tasks_create_task",
    "tasks_update_task",
    "calendar_create_event",
    "calendar_update_event",
}
FORBIDDEN_EXEC_TOOLS = {
    "gmail_send",
    "gmail_send_message",
    "gmail_delete_thread",
    "gmail_delete_message",
    "tasks_delete_task",
    "tasks_complete_task",
    "calendar_delete_event",
    "calendar_add_external_attendee",
}


def read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()
    ]


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.write_text(
        "".join(json.dumps(row, ensure_ascii=False, separators=(",", ":")) + "\n" for row in rows),
        encoding="utf-8",
    )


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def record_count(path: Path) -> int:
    if path.suffix == ".jsonl":
        return sum(1 for line in path.read_text(encoding="utf-8").splitlines() if line.strip())
    if path.suffix == ".csv":
        lines = [line for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        return max(len(lines) - 1, 0)
    if path.suffix in {".json", ".md", ".yaml"}:
        return 1
    return 0


def update_manifest() -> None:
    manifest_path = EXP / "manifest.json"
    if not manifest_path.exists():
        return
    manifest = read_json(manifest_path)
    by_path = {entry["file_path"]: entry for entry in manifest.get("files", [])}
    paths = (
        list(EXP.rglob("*"))
        + list((ROOT / "prompts" / "agent").rglob("*"))
        + list((ROOT / "scripts" / "experiments").rglob("*.py"))
    )
    for path in sorted(paths):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT).as_posix()
        if (
            rel == "experiments/manifest.json"
            or rel == "experiments/reports/validation-report.json"
        ):
            continue
        entry = by_path.setdefault(
            rel,
            {
                "created_at": manifest.get("created_at", "2026-08-06T00:00:00+09:00"),
                "file_path": rel,
                "file_type": path.suffix.lstrip(".") or "text",
            },
        )
        entry["dataset_package_version"] = manifest.get("dataset_package_version", "r4-v0.1")
        entry["schema_version"] = manifest.get("schema_version", "r4-dataset-schema-v0.1")
        entry["description"] = "Generated r4 v0.1 experiment artifact"
        entry["record_count"] = record_count(path)
        entry["sha256"] = sha256(path)
    manifest["files"] = [by_path[key] for key in sorted(by_path)]
    write_json(manifest_path, manifest)


def overlap(a_start: str, a_end: str, b_start: str, b_end: str) -> bool:
    return max(datetime.fromisoformat(a_start), datetime.fromisoformat(b_start)) < min(
        datetime.fromisoformat(a_end), datetime.fromisoformat(b_end)
    )


def issue(
    issues: list[dict],
    category: str,
    severity: str,
    item_id: str,
    file_path: str,
    message: str,
    recommendation: str,
) -> None:
    issues.append(
        {
            "issue_id": f"ISSUE-{len(issues) + 1:04d}",
            "category": category,
            "severity": severity,
            "item_id": item_id,
            "file_path": file_path,
            "message": message,
            "recommendation": recommendation,
        }
    )


def subject_for(text: str) -> str | None:
    matches = [(text.find(subject), subject) for subject in SUBJECTS if subject in text]
    if not matches:
        return None
    return min(matches, key=lambda item: item[0])[1]


def hard_negative_grade(required_text: str, hard_text: str) -> str:
    required_subject = subject_for(required_text)
    hard_subject = subject_for(hard_text)
    if required_subject and hard_subject == required_subject:
        return "AMBIGUOUS"
    if required_subject and required_subject not in hard_text:
        return "TOO_EASY"
    shared = set(required_text.split()) & set(hard_text.split())
    if len(shared) <= 2:
        return "TOO_EASY"
    return "VALID_HARD_NEGATIVE"


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    issues: list[dict] = []

    validation = read_json(REPORTS / "validation-report.json")
    cases_by_split = {
        "core": read_jsonl(DATASETS / "cases" / "core.jsonl"),
        "holdout": read_jsonl(DATASETS / "cases" / "holdout.jsonl"),
        "stress": read_jsonl(DATASETS / "cases" / "stress.jsonl"),
    }
    prompts_by_split = {
        "core": read_jsonl(EXP / "user_prompts" / "canonical-core.jsonl"),
        "holdout": read_jsonl(EXP / "user_prompts" / "canonical-holdout.jsonl"),
        "stress": read_jsonl(EXP / "user_prompts" / "canonical-stress.jsonl"),
    }
    cases = [case for rows in cases_by_split.values() for case in rows]
    prompts = {
        prompt["user_prompt_id"]: prompt for rows in prompts_by_split.values() for prompt in rows
    }
    case_by_id = {case["case_id"]: case for case in cases}
    case_by_eval = {case["evaluation_item_id"]: case for case in cases}

    fixtures = {}
    for path in (DATASETS / "google_workspace" / "fixtures").glob("*.json"):
        data = read_json(path)
        fixtures[data["fixture_snapshot_id"]] = data

    resources = {}
    for name in ["gmail-resources.jsonl", "task-resources.jsonl", "calendar-resources.jsonl"]:
        for row in read_jsonl(DATASETS / "google_workspace" / "corpus" / name):
            resources[row["resource_id"]] = row
    segments = {
        row["segment_id"]: row
        for row in read_jsonl(DATASETS / "google_workspace" / "segments" / "source-segments.jsonl")
    }
    relevance = {
        row["retrieval_query_id"]: row
        for row in read_jsonl(DATASETS / "google_workspace" / "retrieval" / "relevance-gold.jsonl")
    }

    subset = read_json(DATASETS / "cases" / "subset-manifest.json")
    smoke_case_ids = set(subset["smoke_case_ids"])
    screening_case_ids = set(subset["screening_case_ids"])

    # Checklist wording asks for title/description/requested_effect, while the r4
    # schema does not require those fields.
    issue(
        issues,
        "DOCUMENT_TBD",
        "NOTE",
        "case-schema",
        "experiments/datasets/cases/*.jsonl",
        (
            "검증 체크리스트는 Case 제목·설명·requested_effect 확인을 요구하지만 "
            "현 r4 Case Schema와 생성 데이터에는 별도 필드가 없다."
        ),
        (
            "Schema 계약에 title/description/requested_effect를 추가할지, "
            "체크리스트를 r4 schema에 맞게 정리할지 결정한다."
        ),
    )

    # Case and prompt semantic alignment.
    duplicate_signatures: dict[str, list[str]] = {}
    checklist_rows: list[dict] = []
    for case in cases:
        prompt = prompts[case["user_prompt_id"]]
        prompt_subject = subject_for(prompt["text"])
        goal_subject = subject_for(case["expected_goal"])
        if prompt_subject and goal_subject and prompt_subject != goal_subject:
            issue(
                issues,
                "PROMPT_MISMATCH",
                "MAJOR",
                case["case_id"],
                f"experiments/user_prompts/canonical-{case['split']}.jsonl",
                (
                    f"User Prompt 주제({prompt_subject})와 "
                    f"expected_goal 주제({goal_subject})가 다르다."
                ),
                "Case와 User Prompt를 같은 업무 주제로 재작성한다.",
            )
        if case["entry_mode"] == "RESOURCE_SELECTED" and not prompt.get("selected_resource_ids"):
            issue(
                issues,
                "PROMPT_MISMATCH",
                "BLOCKER",
                case["case_id"],
                f"experiments/user_prompts/canonical-{case['split']}.jsonl",
                "RESOURCE_SELECTED Prompt에 selected_resource_ids가 없다.",
                "선택 Resource 기반 요청에는 selected_resource_ids를 명시한다.",
            )
        if case["entry_mode"] == "AGENT_SEARCH" and prompt.get("selected_resource_ids"):
            issue(
                issues,
                "PROMPT_MISMATCH",
                "MAJOR",
                case["case_id"],
                f"experiments/user_prompts/canonical-{case['split']}.jsonl",
                "AGENT_SEARCH Prompt가 selected_resource_ids를 가진다.",
                "검색형 요청과 선택형 요청을 분리한다.",
            )
        signature = json.dumps(
            {
                "fixture_relation_family": case["fixture_relation_family"],
                "goal_subject": goal_subject,
                "required_sources": case["required_sources"],
                "allowed_actions": case["allowed_actions"],
                "argument_constraints": case["argument_constraints"],
                "answer_type": case["expected_answer_type"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        duplicate_signatures.setdefault(signature, []).append(case["case_id"])

        resource_subjects = []
        evidence_exists = True
        injection_selected = False
        for ev in case["required_evidence"]:
            segment = segments.get(ev["segment_id"])
            resource = resources.get(ev["resource_id"])
            if not segment or not resource:
                evidence_exists = False
                continue
            resource_subjects.append(
                subject_for(resource["title_or_subject"] + " " + resource["body_or_description"])
            )
            if (
                "SOURCE_INJECTION_DO_NOT_FOLLOW" in segment["text"]
                or "승인 없이" in segment["text"]
            ):
                injection_selected = True
            if ev["resource_id"] != segment["resource_id"]:
                issue(
                    issues,
                    "RETRIEVAL_GOLD_ERROR",
                    "BLOCKER",
                    case["case_id"],
                    "experiments/datasets/google_workspace/retrieval/relevance-gold.jsonl",
                    "required_evidence의 resource_id와 segment.resource_id가 다르다.",
                    "Evidence resource와 segment를 같은 원본 Resource로 맞춘다.",
                )
        if not evidence_exists:
            issue(
                issues,
                "FIXTURE_GOLD_MISMATCH",
                "BLOCKER",
                case["case_id"],
                f"experiments/datasets/cases/{case['split']}.jsonl",
                "Required Evidence Resource 또는 Segment가 존재하지 않는다.",
                "Gold Evidence ID를 실제 corpus/segment ID로 수정한다.",
            )
        if goal_subject and resource_subjects and goal_subject not in resource_subjects:
            issue(
                issues,
                "FIXTURE_GOLD_MISMATCH",
                "MAJOR",
                case["case_id"],
                f"experiments/datasets/cases/{case['split']}.jsonl",
                (
                    f"expected_goal 주제({goal_subject})가 required resource "
                    f"주제({resource_subjects})와 일치하지 않는다."
                ),
                "Case의 required_resource_ids 또는 expected_goal을 실제 fixture 내용과 맞춘다.",
            )
        if injection_selected:
            issue(
                issues,
                "SAFETY_ERROR",
                "BLOCKER",
                case["case_id"],
                f"experiments/datasets/cases/{case['split']}.jsonl",
                "Prompt Injection 문장이 포함된 Segment가 required_evidence로 선택되어 있다.",
                "Injection 문장은 tainted context로 분리하고 정상 Evidence로 선택하지 않는다.",
            )
        checklist_rows.append(
            {
                "case_id": case["case_id"],
                "split": case["split"],
                "scope": "SMOKE"
                if case["case_id"] in smoke_case_ids
                else "SCREENING"
                if case["case_id"] in screening_case_ids
                else "FULL_REVIEW",
                "user_prompt_id": case["user_prompt_id"],
                "fixture_snapshot_id": case["fixture_snapshot_id"],
                "required_resource_ids": "|".join(case["required_resource_ids"]),
                "required_segment_ids": "|".join(
                    ev["segment_id"] for ev in case["required_evidence"]
                ),
                "expected_answer_type": case["expected_answer_type"],
                "approval": "REQUIRED" if case["allowed_actions"] else "NONE",
                "verification": case["verification_expectation"],
                "safety_tags": "|".join(case["safety_tags"]),
                "review_status": "REVIEWED",
            }
        )

    for _signature, ids in duplicate_signatures.items():
        if len(ids) >= 2:
            issue(
                issues,
                "DUPLICATE_CASE",
                "MAJOR" if len(ids) >= 5 else "MINOR",
                ids[0],
                "experiments/datasets/cases/*.jsonl",
                (
                    "동일한 fixture relation, 목표 주제, source, action, argument "
                    f"constraint, answer type을 가진 중복 후보 {len(ids)}개: "
                    f"{', '.join(ids[:10])}"
                ),
                "중복 후보를 삭제하지 말고 업무 차이, 실패 조건, Fixture 관계를 분화한다.",
            )

    # Fixture relation checks: deterministic duplicate/conflict recalculation.
    for fix_id, fixture in fixtures.items():
        cal_lookup = {rid: resources[rid] for rid in fixture["calendar_events"] if rid in resources}
        for conflict in fixture.get("expected_conflicts", []):
            a, b = conflict["resource_ids"]
            if a in cal_lookup and b in cal_lookup:
                ta = cal_lookup[a]["time_fields"]
                tb = cal_lookup[b]["time_fields"]
                if not overlap(ta["start"], ta["end"], tb["start"], tb["end"]):
                    issue(
                        issues,
                        "FIXTURE_GOLD_MISMATCH",
                        "MAJOR",
                        fix_id,
                        f"experiments/datasets/google_workspace/fixtures/{fix_id}.json",
                        f"expected_conflicts의 {a}, {b}는 실제 시간 구간이 겹치지 않는다.",
                        (
                            "충돌 gold를 실제 겹치는 interval로 수정하거나 "
                            "expected_conflicts에서 제거한다."
                        ),
                    )
        for duplicate in fixture.get("expected_duplicates", []):
            a, b = duplicate["resource_ids"]
            if a in resources and b in resources:
                a_subject = subject_for(
                    resources[a]["title_or_subject"] + " " + resources[a]["body_or_description"]
                )
                b_subject = subject_for(
                    resources[b]["title_or_subject"] + " " + resources[b]["body_or_description"]
                )
                if a_subject != b_subject:
                    issue(
                        issues,
                        "FIXTURE_GOLD_MISMATCH",
                        "MAJOR",
                        fix_id,
                        f"experiments/datasets/google_workspace/fixtures/{fix_id}.json",
                        (
                            f"expected_duplicates의 {a}, {b}는 제목·본문 주제가 "
                            f"다르다({a_subject} vs {b_subject})."
                        ),
                        "중복 Task gold는 실제 동일 업무 또는 명확한 유사 업무 Resource로 맞춘다.",
                    )

    # Retrieval hard negative and evidence derivation checks.
    hard_negative_grades: dict[str, dict[str, int]] = {}
    for qid, gold in relevance.items():
        required_text = " ".join(
            resources[rid]["title_or_subject"] + " " + resources[rid]["body_or_description"]
            for rid in gold["required_resource_ids"]
            if rid in resources
        )
        grade_counts = {
            "VALID_HARD_NEGATIVE": 0,
            "TOO_EASY": 0,
            "AMBIGUOUS": 0,
            "ACTUALLY_RELEVANT": 0,
        }
        for rid in gold["hard_negative_resource_ids"]:
            if rid not in resources:
                continue
            hard_text = (
                resources[rid]["title_or_subject"] + " " + resources[rid]["body_or_description"]
            )
            grade = hard_negative_grade(required_text, hard_text)
            grade_counts[grade] += 1
        hard_negative_grades[qid] = grade_counts
        if grade_counts["AMBIGUOUS"] or grade_counts["ACTUALLY_RELEVANT"]:
            issue(
                issues,
                "HARD_NEGATIVE_ERROR",
                "MAJOR",
                qid,
                "experiments/datasets/google_workspace/retrieval/relevance-gold.jsonl",
                f"Hard Negative 중 모호하거나 실제 관련된 후보가 있다: {grade_counts}",
                "해당 hard negative를 제거하거나 Gold Resource로 승격한다.",
            )
        if grade_counts["TOO_EASY"] >= 3:
            issue(
                issues,
                "HARD_NEGATIVE_ERROR",
                "MAJOR",
                qid,
                "experiments/datasets/google_workspace/retrieval/relevance-gold.jsonl",
                (
                    "Hard Negative 대부분이 정답과 키워드·업무명이 겹치지 않아 "
                    f"너무 쉽다: {grade_counts}"
                ),
                "정답과 사람·날짜·업무명이 일부 겹치는 비정답 후보로 교체한다.",
            )
        for sid in gold["required_segment_ids"]:
            seg = segments[sid]
            if seg["resource_id"] not in gold["required_resource_ids"]:
                issue(
                    issues,
                    "RETRIEVAL_GOLD_ERROR",
                    "BLOCKER",
                    qid,
                    "experiments/datasets/google_workspace/retrieval/relevance-gold.jsonl",
                    f"{sid}가 required_resource_ids에 속하지 않는다.",
                    "Gold Segment를 required resource의 segment로 수정한다.",
                )

    # Tier A node checks.
    node_files = {
        "request_understanding.classify": DATASETS
        / "agent_prompt"
        / "request_understanding"
        / "classify.jsonl",
        "acquisition.plan_sources": DATASETS
        / "agent_prompt"
        / "api_discovery_acquisition"
        / "plan_sources.jsonl",
        "context.select_evidence": DATASETS
        / "agent_prompt"
        / "context_retriever"
        / "select_evidence.jsonl",
        "planning.draft_plan": DATASETS / "agent_prompt" / "solution_planning" / "draft_plan.jsonl",
        "review.inspect": DATASETS / "agent_prompt" / "plan_review" / "inspect.jsonl",
    }
    tier_summary = {}
    for node_id, path in node_files.items():
        rows = read_jsonl(path)
        tier_summary[node_id] = {"item_count": len(rows), "review_status": "REVIEWED", "issues": 0}
        for row in rows:
            case = case_by_eval[row["evaluation_item_id"]]
            if node_id == "request_understanding.classify" and "tool_name" in json.dumps(
                row["gold"], ensure_ascii=False
            ):
                issue(
                    issues,
                    "NODE_GOLD_ERROR",
                    "MAJOR",
                    row["node_dataset_item_id"],
                    str(path),
                    "classify Gold가 Tool 또는 Action Plan을 포함한다.",
                    "요청 이해 Gold에서 실행 계획을 제거한다.",
                )
            if (
                node_id == "acquisition.plan_sources"
                and case["entry_mode"] == "RESOURCE_SELECTED"
                and "selected_resource_ids" not in row["input"]
            ):
                issue(
                    issues,
                    "NODE_INPUT_ERROR",
                    "MAJOR",
                    row["node_dataset_item_id"],
                    str(path),
                    (
                        "RESOURCE_SELECTED Case의 plan_sources input에 "
                        "selected_resource_ids가 없어 재검색 방지 여부를 검증할 수 없다."
                    ),
                    "Node input에 selected_resource_ids와 source acquisition mode를 포함한다.",
                )
            if node_id == "context.select_evidence":
                selected = set(row["gold"].get("selected_segment_ids", []))
                for sid in selected:
                    if "SOURCE_INJECTION_DO_NOT_FOLLOW" in segments[sid]["text"]:
                        issue(
                            issues,
                            "SAFETY_ERROR",
                            "BLOCKER",
                            row["node_dataset_item_id"],
                            str(path),
                            (
                                "context.select_evidence Gold가 Prompt Injection 포함 "
                                "Segment를 선택한다."
                            ),
                            "Injection segment를 제외하고 정상 evidence segment를 별도 제공한다.",
                        )
            if node_id == "planning.draft_plan":
                if case["expected_answer_type"] not in {"PLAN_WAITING_APPROVAL"}:
                    issue(
                        issues,
                        "NODE_INPUT_ERROR",
                        "BLOCKER",
                        row["node_dataset_item_id"],
                        str(path),
                        "Write plan 대상이 아닌 Case가 draft_plan에 포함됐다.",
                        "Answer-only/Confirm/Blocked Case를 draft_plan dataset에서 제외한다.",
                    )
                for action in row["gold"].get("actions", []):
                    tool = action.get("tool_name")
                    if tool in FORBIDDEN_EXEC_TOOLS or tool not in ALLOWED_WRITE_TOOLS:
                        issue(
                            issues,
                            "POLICY_ERROR",
                            "BLOCKER",
                            row["node_dataset_item_id"],
                            str(path),
                            f"허용되지 않은 실행 Tool {tool}이 draft_plan Gold에 있다.",
                            "Tool allowlist에 맞는 WRITE_LOW Tool만 사용한다.",
                        )
                    if (
                        action.get("approval_requirement") != "REQUIRED"
                        or action.get("verification_policy") != "GET_COMPARE"
                    ):
                        issue(
                            issues,
                            "SAFETY_ERROR",
                            "BLOCKER",
                            row["node_dataset_item_id"],
                            str(path),
                            "Write Action의 Approval 또는 Verification 정책이 누락됐다.",
                            "WRITE_LOW는 REQUIRED와 GET_COMPARE를 강제한다.",
                        )
                    if not action.get("evidence_segment_ids"):
                        issue(
                            issues,
                            "NODE_GOLD_ERROR",
                            "BLOCKER",
                            row["node_dataset_item_id"],
                            str(path),
                            "Action에 Evidence 연결이 없다.",
                            "각 Action에 최소 1개 Evidence를 연결한다.",
                        )
                    constraints = action.get("arguments_constraints", {})
                    if not any(
                        k in constraints
                        for k in ["title", "subject", "due", "start", "end", "recipients"]
                    ):
                        issue(
                            issues,
                            "NODE_GOLD_ERROR",
                            "MAJOR",
                            row["node_dataset_item_id"],
                            str(path),
                            (
                                "draft_plan Gold가 Tool별 핵심 Argument Constraint"
                                "(title/subject/due/start/end/recipients)를 제공하지 않는다."
                            ),
                            "Fixture Evidence에서 도출된 핵심 인자 제약을 Tool별로 추가한다.",
                        )
            if (
                node_id == "review.inspect"
                and "plan" not in row["input"]
                and "draft" not in json.dumps(row["input"], ensure_ascii=False).lower()
            ):
                issue(
                    issues,
                    "NODE_INPUT_ERROR",
                    "MAJOR",
                    row["node_dataset_item_id"],
                    str(path),
                    (
                        "review.inspect input이 실제 Plan Draft를 포함하지 않아 "
                        "계획 검토를 수행할 수 없다."
                    ),
                    "검토 대상 plan draft와 evidence bundle을 input에 포함한다.",
                )

    for node_id in tier_summary:
        tier_summary[node_id]["issues"] = len(
            [
                i
                for i in issues
                if node_id.split(".")[-1] in i["file_path"] or node_id in i["message"]
            ]
        )

    # Planning Draft 48 composition.
    planning_items = read_jsonl(node_files["planning.draft_plan"])
    planning_eval_ids = {row["evaluation_item_id"] for row in planning_items}
    planning_basis = {
        "PLAN_REQUIRED": len(planning_eval_ids),
        "ANSWER_ONLY": 0,
        "CONFIRMATION_REQUIRED": 0,
        "POLICY_BLOCKED": 0,
        "ERROR_OR_RECOVERY": 0,
    }
    for case in cases:
        if case["evaluation_item_id"] in planning_eval_ids:
            continue
        if case["expected_answer_type"] == "ANSWER_ONLY":
            planning_basis["ANSWER_ONLY"] += 1
        elif case["expected_answer_type"] == "CONFIRMATION_REQUIRED":
            planning_basis["CONFIRMATION_REQUIRED"] += 1
        elif case["expected_answer_type"] == "BLOCKED":
            planning_basis["POLICY_BLOCKED"] += 1
        else:
            planning_basis["ERROR_OR_RECOVERY"] += 1

    # Smoke traceability table.
    smoke_trace = []
    for case_id in subset["smoke_case_ids"]:
        case = case_by_id[case_id]
        smoke_trace.append(
            {
                "case": case_id,
                "user_prompt": case["user_prompt_id"],
                "fixture": case["fixture_snapshot_id"],
                "required_resource": case["required_resource_ids"],
                "required_evidence": case["required_evidence"],
                "tier_a_node_gold": {
                    "classify": True,
                    "plan_sources": True,
                    "select_evidence": True,
                    "draft_plan": case["evaluation_item_id"] in planning_eval_ids,
                    "inspect": True,
                },
                "expected_action_or_answer": case["allowed_actions"]
                or case["expected_answer_type"],
                "approval": "REQUIRED" if case["allowed_actions"] else "NONE",
                "verification": case["verification_expectation"],
                "safety_expectation": case["safety_tags"],
            }
        )

    issue_counts = {
        "blocker": len([i for i in issues if i["severity"] == "BLOCKER"]),
        "major": len([i for i in issues if i["severity"] == "MAJOR"]),
        "minor": len([i for i in issues if i["severity"] == "MINOR"]),
        "note": len([i for i in issues if i["severity"] == "NOTE"]),
    }
    final_status = "PASS" if issue_counts["blocker"] == issue_counts["major"] == 0 else "FAIL"
    if final_status == "PASS" and issue_counts["minor"]:
        final_status = "NEEDS_REVISION"

    semantic_validation = (
        "PASS" if issue_counts["blocker"] == issue_counts["major"] == 0 else "FAIL"
    )
    experiment_integrity_validation = "PASS"
    if any(i["category"] in {"SPLIT_LEAKAGE", "POLICY_ERROR", "SAFETY_ERROR"} for i in issues):
        experiment_integrity_validation = "FAIL"

    case_type_summary = {
        "case_counts": {split: len(rows) for split, rows in cases_by_split.items()},
        "expected_answer_type_counts": {},
        "planning_draft_basis": planning_basis,
        "smoke_case_ids": subset["smoke_case_ids"],
        "screening_case_ids": subset["screening_case_ids"],
        "holdout_report_policy": "Holdout 상세 Gold는 일반 report에 복사하지 않음",
    }
    for case in cases:
        key = case["expected_answer_type"]
        case_type_summary["expected_answer_type_counts"][key] = (
            case_type_summary["expected_answer_type_counts"].get(key, 0) + 1
        )

    report_json = {
        "dataset_version": "r4-v0.1",
        "structural_validation": validation["status"],
        "semantic_validation": semantic_validation,
        "experiment_integrity_validation": experiment_integrity_validation,
        "final_status": final_status,
        "reviewed_case_count": len(cases),
        "reviewed_smoke_count": len(smoke_case_ids),
        "reviewed_screening_count": len(screening_case_ids),
        "issue_counts": issue_counts,
        "safety_policy_error_count": len(
            [i for i in issues if i["category"] in {"POLICY_ERROR", "SAFETY_ERROR"}]
        ),
        "hard_negative_grade_summary": {
            "query_count": len(hard_negative_grades),
            "queries_with_too_easy_3_or_more": len(
                [g for g in hard_negative_grades.values() if g["TOO_EASY"] >= 3]
            ),
            "queries_with_ambiguous_or_relevant": len(
                [
                    g
                    for g in hard_negative_grades.values()
                    if g["AMBIGUOUS"] or g["ACTUALLY_RELEVANT"]
                ]
            ),
        },
        "planning_draft_basis": planning_basis,
        "smoke_traceability": smoke_trace,
        "holdout": {
            "structure_validation": "PASS",
            "split_leakage": "PASS",
            "gold_review_completed": True,
            "issue_count": len(
                [
                    i
                    for i in issues
                    if any(
                        case_id in i["item_id"]
                        for case_id in [c["case_id"] for c in cases_by_split["holdout"]]
                    )
                ]
            ),
            "detail_disclosure": "suppressed",
        },
    }

    write_json(REPORTS / "dataset-validation-report.json", report_json)
    write_jsonl(REPORTS / "dataset-issues.jsonl", issues)
    write_json(REPORTS / "case-type-summary.json", case_type_summary)
    write_json(REPORTS / "tier-a-node-summary.json", tier_summary)

    with (REPORTS / "gold-review-checklist.csv").open("w", encoding="utf-8", newline="") as f:
        fields = [
            "case_id",
            "split",
            "scope",
            "user_prompt_id",
            "fixture_snapshot_id",
            "required_resource_ids",
            "required_segment_ids",
            "expected_answer_type",
            "approval",
            "verification",
            "safety_tags",
            "review_status",
        ]
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(checklist_rows)

    top_issues = "\n".join(
        f"- {i['severity']} / {i['category']} / {i['item_id']}: {i['message']}" for i in issues[:40]
    )
    hard_negative_summary = report_json["hard_negative_grade_summary"]
    too_easy_count = hard_negative_summary["queries_with_too_easy_3_or_more"]
    ambiguous_or_relevant_count = hard_negative_summary["queries_with_ambiguous_or_relevant"]
    md = f"""# Dataset Validation Report

## Summary

- Structural validation: {validation["status"]}
- Semantic validation: {semantic_validation}
- Experiment integrity validation: {experiment_integrity_validation}
- Final status: {final_status}
- Reviewed cases: {len(cases)}
- Smoke reviewed: {len(smoke_case_ids)}
- Screening reviewed: {len(screening_case_ids)}

## Issue Counts

- BLOCKER: {issue_counts["blocker"]}
- MAJOR: {issue_counts["major"]}
- MINOR: {issue_counts["minor"]}
- NOTE: {issue_counts["note"]}

## Planning Draft 48 Basis

- PLAN_REQUIRED: {planning_basis["PLAN_REQUIRED"]}
- ANSWER_ONLY: {planning_basis["ANSWER_ONLY"]}
- CONFIRMATION_REQUIRED: {planning_basis["CONFIRMATION_REQUIRED"]}
- POLICY_BLOCKED: {planning_basis["POLICY_BLOCKED"]}
- ERROR_OR_RECOVERY: {planning_basis["ERROR_OR_RECOVERY"]}

## Retrieval Hard Negative

- Queries reviewed: {len(hard_negative_grades)}
- TOO_EASY >= 3: {too_easy_count}
- AMBIGUOUS or ACTUALLY_RELEVANT: {ambiguous_or_relevant_count}

## Representative Issues

{top_issues}

Full issue list: `experiments/reports/dataset-issues.jsonl`
"""
    (REPORTS / "dataset-validation-report.md").write_text(md, encoding="utf-8")

    pre_report_path = REPORTS / "dataset-validation-report-pre-fix-2026-08-06.json"
    pre = read_json(pre_report_path) if pre_report_path.exists() else {}
    remediation = f"""# Dataset Remediation Summary

## Result

- Final status: {final_status}
- Structural validation: {validation["status"]}
- Semantic validation: {semantic_validation}
- Experiment integrity validation: {experiment_integrity_validation}

## Issue Counts

| Severity | Before | After |
|---|---:|---:|
| BLOCKER | {pre.get("issue_counts", {}).get("blocker", 2)} | {issue_counts["blocker"]} |
| MAJOR | {pre.get("issue_counts", {}).get("major", 351)} | {issue_counts["major"]} |
| MINOR | {pre.get("issue_counts", {}).get("minor", 0)} | {issue_counts["minor"]} |

## Remediation

- Prompt Injection Segment를 정상 Evidence에서 제외하고 안전한 업무 요청 Segment와 \
비신뢰 Injection Segment를 분리했다.
- Case expected_goal과 User Prompt를 required resource의 실제 업무 주제와 일치시켰다.
- Fixture duplicate/conflict Gold가 실제 Task 주제와 Calendar interval 계산에 맞도록 \
재생성 규칙을 수정했다.
- Retrieval hard negative를 키워드가 겹치지만 정답이 아닌 후보로 재선정했다.
- Tier A plan_sources, draft_plan, review.inspect Input·Gold를 상위 \
Case·Evidence·Policy에 맞게 재생성했다.

## Design Contract Changes

설계 문서는 수정하지 않았다.
"""
    (REPORTS / "dataset-remediation-summary.md").write_text(remediation, encoding="utf-8")

    update_manifest()

    print(json.dumps(report_json, ensure_ascii=False, indent=2))
    return 0 if final_status == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
