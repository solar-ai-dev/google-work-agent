"""Minimal dataset → public API → grader → JSON result runner."""

from __future__ import annotations

import argparse
import json
import os
import uuid
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from getpass import getpass
from pathlib import Path
from typing import cast

from evaluation.client import ProductApiClient
from evaluation.dataset import CANONICAL_CASES_PATH, file_sha256, load_case
from evaluation.grader import EvaluationGrade, grade_case


def run_case(
    client: ProductApiClient,
    *,
    case: Mapping[str, object],
    dataset_path: Path,
    product_sha: str,
    experiment_name: str,
    candidate_id: str,
    requested_mode: str,
) -> dict[str, object]:
    """Run one case through the supported Product API and grade public evidence."""

    case_id = _required_string(case, "case_id")
    conversation = client.create_conversation(
        command_id=f"evaluation-conversation-{uuid.uuid4().hex}",
        title=f"Evaluation {case_id}",
    )
    conversation_id = _required_string(conversation, "conversation_id")
    selected = _string_list(case.get("selected_resource_handles", []), "selected_resource_handles")
    started = client.start_run(
        command_id=f"evaluation-run-{uuid.uuid4().hex}",
        conversation_id=conversation_id,
        request_text=_required_string(case, "canonical_user_prompt"),
        entry_mode=_required_string(case, "entry_mode"),
        selected_resource_handles=selected,
        requested_mode=requested_mode,
    )
    snapshot = client.wait_for_observable_result(_required_string(started, "run_id"))
    observed = normalize_snapshot(snapshot)
    grade = grade_case(case, observed)
    return build_result(
        case_id=case_id,
        dataset_path=dataset_path,
        product_sha=product_sha,
        experiment_name=experiment_name,
        candidate_id=candidate_id,
        requested_mode=requested_mode,
        observed=observed,
        grade=grade,
    )


def normalize_snapshot(snapshot: Mapping[str, object]) -> dict[str, object]:
    """Normalize only documented API fields into grader observations."""

    run = _mapping(snapshot.get("run"), "run")
    messages = _object_list(snapshot.get("messages", []), "messages")
    actions = _object_list(snapshot.get("actions", []), "actions")
    normalized_actions = [
        {
            "action_id": action.get("action_id"),
            "tool": action.get("tool_name"),
            "effect": action.get("effect_type"),
            "status": action.get("status"),
        }
        for action in actions
    ]
    tool_calls = [
        action
        for action in normalized_actions
        if action.get("status") in {"EXECUTED", "VERIFIED", "UNKNOWN_RESULT"}
    ]
    assistant_messages = [
        message.get("content")
        for message in messages
        if message.get("role") == "ASSISTANT" and isinstance(message.get("content"), str)
    ]
    status = run.get("status")
    terminal_state = (
        "BLOCKED" if isinstance(status, str) and status.startswith("WAITING_") else status
    )
    return {
        "final_answer": assistant_messages[-1] if assistant_messages else "",
        "evidence_ids": [],
        "evidence_resource_refs": _context_resource_refs(snapshot.get("context_preview")),
        "actions": normalized_actions,
        "tool_calls": tool_calls,
        "approvals": snapshot.get("approvals", []),
        "verification_events": _verification_events(snapshot.get("verification_summary")),
        "unknown_result_events": [],
        "interactions": _interaction_projection(snapshot),
        "terminal_state": terminal_state,
        "durable_effects": [],
    }


def build_result(
    *,
    case_id: str,
    dataset_path: Path,
    product_sha: str,
    experiment_name: str,
    candidate_id: str,
    requested_mode: str,
    observed: Mapping[str, object],
    grade: EvaluationGrade,
) -> dict[str, object]:
    """Create a small reproducible result artifact."""

    grader_path = Path(__file__).with_name("grader.py")
    return {
        "schema_version": 1,
        "experiment_name": experiment_name,
        "case_id": case_id,
        "candidate_id": candidate_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "dataset": {
            "path": dataset_path.as_posix(),
            "sha256": file_sha256(dataset_path),
        },
        "product_sha": product_sha,
        "profile": requested_mode,
        "grader_sha256": file_sha256(grader_path),
        "metrics": {
            "passed": grade.passed,
            "hard_gate_passed": grade.hard_gate_passed,
        },
        "grade": grade.as_dict(),
        "observed": dict(observed),
    }


def write_result(path: Path, result: Mapping[str, object]) -> None:
    """Atomically write one local or curated JSON result."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.write_text(
            json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one public-boundary Product evaluation")
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--dataset", type=Path, default=CANONICAL_CASES_PATH)
    parser.add_argument("--case-id", required=True)
    parser.add_argument("--product-sha", required=True)
    parser.add_argument("--experiment-name", required=True)
    parser.add_argument("--candidate-id", required=True)
    parser.add_argument(
        "--requested-mode", choices=("AUTO", "LOCAL_GPU", "API_LLM"), default="AUTO"
    )
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)

    client = ProductApiClient(arguments.base_url)
    client.bootstrap(getpass("Product bootstrap secret: "))
    case = load_case(arguments.case_id, arguments.dataset)
    result = run_case(
        client,
        case=case,
        dataset_path=arguments.dataset,
        product_sha=arguments.product_sha,
        experiment_name=arguments.experiment_name,
        candidate_id=arguments.candidate_id,
        requested_mode=arguments.requested_mode,
    )
    write_result(arguments.output, result)
    metrics = _mapping(result.get("metrics"), "metrics")
    return 0 if metrics.get("passed") is True else 2


def _context_resource_refs(value: object) -> list[str]:
    if not isinstance(value, Mapping):
        return []
    refs = value.get("resource_refs", [])
    return [item for item in refs if isinstance(item, str)] if isinstance(refs, list) else []


def _verification_events(value: object) -> list[dict[str, object]]:
    if not isinstance(value, Mapping):
        return []
    rows = value.get("per_action", [])
    if not isinstance(rows, list):
        return []
    return [cast(dict[str, object], row) for row in rows if isinstance(row, dict)]


def _interaction_projection(snapshot: Mapping[str, object]) -> list[object]:
    pending = snapshot.get("pending_interrupt")
    return [] if pending is None else [pending]


def _mapping(value: object, field: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        raise ValueError(f"{field} must be an object")
    return cast(Mapping[str, object], value)


def _object_list(value: object, field: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list):
        raise ValueError(f"{field} must be an array")
    return [_mapping(item, field) for item in value]


def _required_string(value: Mapping[str, object], field: str) -> str:
    item = value.get(field)
    if not isinstance(item, str) or not item:
        raise ValueError(f"{field} must be a non-empty string")
    return item


def _string_list(value: object, field: str) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a string array")
    return cast(list[str], value)


if __name__ == "__main__":
    raise SystemExit(main())
