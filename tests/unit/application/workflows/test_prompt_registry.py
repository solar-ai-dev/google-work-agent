from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import cast

import pytest
from tests.support.prompt_manifests import (
    canonical_prompt_manifest_path,
    canonical_prompt_runtime_input_contract_v1_path,
    write_draft_manifest,
    write_runtime_active_manifest,
)

from google_work_agent.application.orchestration.contracts import PROMPT_SELECTION_KEY_FIELDS
from google_work_agent.application.orchestration.prompt_registry import (
    InactivePromptArtifactError,
    default_prompt_manifest_path,
    discover_canonical_prompt_manifest_path,
    load_prompt_reference,
)

_REPO_ROOT = Path(__file__).resolve().parents[4]


def test_default_prompt_manifest_path_uses_canonical_r91_bundle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        "GOOGLE_WORK_AGENT_PROMPT_MANIFEST_PATH",
        str(Path("C:/tmp/arbitrary-manifest.json")),
    )

    assert default_prompt_manifest_path() == canonical_prompt_manifest_path()
    assert default_prompt_manifest_path().name == "prompt-manifest-v0.9.1.json"


def test_discover_canonical_prompt_manifest_path_picks_highest_semver(tmp_path: Path) -> None:
    (tmp_path / "prompt-manifest-v0.8.2.json").write_text("{}", encoding="utf-8")
    (tmp_path / "prompt-manifest-v0.8.3.json").write_text("{}", encoding="utf-8")
    (tmp_path / "prompt-manifest-v0.8.10.json").write_text("{}", encoding="utf-8")
    (tmp_path / "README.md").write_text("not a manifest", encoding="utf-8")
    (tmp_path / "profile-semantic-responsibility-map-v1.json").write_text("{}", encoding="utf-8")

    selected = discover_canonical_prompt_manifest_path(tmp_path)

    assert selected.name == "prompt-manifest-v0.8.10.json"


def test_discover_canonical_prompt_manifest_path_requires_a_directory(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="not available"):
        discover_canonical_prompt_manifest_path(tmp_path / "does-not-exist")


def test_discover_canonical_prompt_manifest_path_requires_a_versioned_manifest(
    tmp_path: Path,
) -> None:
    (tmp_path / "README.md").write_text("not a manifest", encoding="utf-8")

    with pytest.raises(FileNotFoundError, match="no prompt-manifest"):
        discover_canonical_prompt_manifest_path(tmp_path)


def test_load_prompt_reference_succeeds_for_runtime_active_slot(tmp_path: Path) -> None:
    manifest_path = write_runtime_active_manifest(
        tmp_path,
        prompt_ids={"planning.compose_arguments.revise"},
    )

    prompt_ref = load_prompt_reference("planning.compose_arguments.revise", manifest_path)

    assert prompt_ref.prompt_id == "planning.compose_arguments.revise"
    assert prompt_ref.node_state == "SEMANTIC_REVISION"
    assert prompt_ref.input_schema_version == "r8.6-runtime-input-snapshot-v1"
    assert prompt_ref.output_schema_version == "r8.6-output-contract-snapshot-v1"


def test_load_prompt_reference_distinguishes_missing_from_inactive_artifact(
    tmp_path: Path,
) -> None:
    draft_manifest_path = write_draft_manifest(
        tmp_path, prompt_ids={"planning.compose_arguments"}
    )
    with pytest.raises(InactivePromptArtifactError, match="planning.compose_arguments"):
        load_prompt_reference("planning.compose_arguments", draft_manifest_path)

    with pytest.raises(LookupError, match="planning.missing_slot"):
        load_prompt_reference("planning.missing_slot", canonical_prompt_manifest_path())


def test_prompt_selection_key_excludes_failure_reason_code() -> None:
    assert "failure_reason_code" not in PROMPT_SELECTION_KEY_FIELDS


def test_legacy_slot_format_uses_runtime_activation_boundary(tmp_path: Path) -> None:
    manifest_path = tmp_path / "legacy-prompt-manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "prompt_bundle_version": "0.7.0-r7",
                "activation_policy": "legacy",
                "slots": [
                    {
                        "slot_id": "analysis.analyze",
                        "agent_role": "work_analysis",
                        "purpose": "analyze",
                        "version": "0.4.0-r7",
                        "activation_status": "DRAFT",
                        "files": [],
                        "failure_reason_codes": [],
                        "input_schema": "legacy-input",
                        "output_schema": "legacy-output",
                        "content_hash": "hash",
                        "assembled_path": "legacy.md",
                        "assembled_hash": "hash",
                    }
                ],
            },
            ensure_ascii=True,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(InactivePromptArtifactError, match="analysis.analyze"):
        load_prompt_reference("analysis.analyze", manifest_path)


def _load_json(path: Path) -> dict[str, object]:
    return cast(dict[str, object], json.loads(path.read_text(encoding="utf-8")))


def _contract_slot_ids(contract: dict[str, object]) -> set[str]:
    return set(cast(dict[str, object], contract["slots"]))


def _manifest_slots(manifest: dict[str, object]) -> list[dict[str, object]]:
    return cast(list[dict[str, object]], manifest["slots"])


def _manifest_slot_ids(manifest: dict[str, object]) -> set[str]:
    return {cast(str, slot["slot_id"]) for slot in _manifest_slots(manifest)}


def test_canonical_required_slot_set_equals_manifest_slot_set() -> None:
    """Prompt Runtime Contract Closure: the required-set fixture is
    prompt-runtime-input-contract-v1.json's own "slots" keys -- the single
    source of truth this repo has for "which PromptRefs must exist" -- and
    it must be a set-equal match against the manifest, not just a count
    match (30/30 with different names would not be PASS)."""
    contract = _load_json(canonical_prompt_runtime_input_contract_v1_path())
    manifest = _load_json(canonical_prompt_manifest_path())

    canonical_slots = _contract_slot_ids(contract)
    manifest_slots = _manifest_slot_ids(manifest)

    assert canonical_slots - manifest_slots == set()
    assert manifest_slots - canonical_slots == set()
    assert canonical_slots == manifest_slots


def test_retired_slots_are_not_present_in_manifest_or_contract_slots() -> None:
    """The 3 slots Prompt Runtime Contract Closure determined
    DETERMINISTICALLY_REPLACED must not reappear as live PromptRefs in
    either artifact, and the retirement itself must be documented in the
    contract's own retired_slots record."""
    contract = _load_json(canonical_prompt_runtime_input_contract_v1_path())
    manifest = _load_json(canonical_prompt_manifest_path())

    retired = {
        "request_understanding.classify.revise",
        "retrieval.assess_sufficiency.revise",
        "work_analysis.analyze.reassess",
    }
    manifest_slots = _manifest_slot_ids(manifest)
    contract_slots = _contract_slot_ids(contract)
    retired_slots_record = set(cast(dict[str, object], contract["retired_slots"]))

    assert retired.isdisjoint(manifest_slots)
    assert retired.isdisjoint(contract_slots)
    assert retired == retired_slots_record


def test_manifest_source_and_assembled_artifacts_exist_and_hash_validate() -> None:
    """Manifest closure invariant (Prompt Runtime Contract Closure section 12):
    every manifest slot's source files and assembled file exist on disk, and
    content_hash/assembled_hash match what's actually there -- using the same
    concat-then-sha256 / CRLF-normalize-then-sha256 algorithm
    prompt_registry.py's own _read_instruction_text enforces at call time."""
    manifest = _load_json(canonical_prompt_manifest_path())

    for slot in _manifest_slots(manifest):
        source_paths = [_REPO_ROOT / cast(str, f) for f in cast(list[object], slot["files"])]
        for source_path in source_paths:
            assert source_path.is_file(), f"{slot['slot_id']}: missing source {source_path}"
        concatenated = b"".join(path.read_bytes() for path in source_paths)
        assert hashlib.sha256(concatenated).hexdigest() == slot["content_hash"], slot["slot_id"]

        assembled_path = _REPO_ROOT / cast(str, slot["assembled_path"])
        assert assembled_path.is_file(), f"{slot['slot_id']}: missing assembled {assembled_path}"
        assembled_bytes = assembled_path.read_bytes()
        assert hashlib.sha256(assembled_bytes).hexdigest() == slot["assembled_hash"], slot[
            "slot_id"
        ]
        assert assembled_bytes == concatenated.replace(b"\r\n", b"\n"), slot["slot_id"]


def test_every_manifest_slot_has_an_input_contract_entry() -> None:
    """Required PromptRef has input contract (section 12 Manifest closure)."""
    contract = _load_json(canonical_prompt_runtime_input_contract_v1_path())
    manifest = _load_json(canonical_prompt_manifest_path())

    contract_slots = _contract_slot_ids(contract)
    for slot in _manifest_slots(manifest):
        assert slot["slot_id"] in contract_slots, slot["slot_id"]


@pytest.mark.parametrize(
    ("slot_id", "own_type", "foreign_types"),
    [
        (
            "retrieval.plan_query.repair",
            "RetrievalQueryPlanV2",
            ("EvidenceSelectionResultV2", "SufficiencyResultV2"),
        ),
        (
            "retrieval.plan_query.revise",
            "RetrievalQueryPlanV2",
            ("EvidenceSelectionResultV2", "SufficiencyResultV2"),
        ),
        (
            "retrieval.select_evidence.repair",
            "EvidenceSelectionResultV2",
            ("RetrievalQueryPlanV2", "SufficiencyResultV2"),
        ),
        (
            "retrieval.select_evidence.revise",
            "EvidenceSelectionResultV2",
            ("RetrievalQueryPlanV2", "SufficiencyResultV2"),
        ),
        (
            "retrieval.assess_sufficiency.repair",
            "SufficiencyResultV2",
            ("RetrievalQueryPlanV2", "EvidenceSelectionResultV2"),
        ),
    ],
)
def test_retrieval_repair_revise_prompts_reference_only_their_own_output_type(
    slot_id: str, own_type: str, foreign_types: tuple[str, ...]
) -> None:
    """PHASE 3 closure: the assembled repair/revise instruction for each
    retrieval node must name only its own Output Type, never another
    retrieval node's (e.g. select_evidence.repair must not tell the model
    to repair a RetrievalQueryPlanV2)."""
    manifest = _load_json(canonical_prompt_manifest_path())
    slot = next(s for s in _manifest_slots(manifest) if s["slot_id"] == slot_id)
    assembled_text = (_REPO_ROOT / cast(str, slot["assembled_path"])).read_text(encoding="utf-8")

    assert own_type in assembled_text
    for foreign_type in foreign_types:
        assert foreign_type not in assembled_text
