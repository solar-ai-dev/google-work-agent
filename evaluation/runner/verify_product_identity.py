"""Fail-closed Product and Prompt identity preflight for current Evaluation runs."""

from __future__ import annotations

import hashlib
import inspect
import subprocess
from dataclasses import dataclass
from pathlib import Path

from evaluation.contracts.evaluation_contract import load_strict_json
from evaluation.contracts.experiment_config import ExperimentConfigV1
from evaluation.targets.target_registry import resolve_target

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_PRODUCT_SOURCE_ROOT = _REPOSITORY_ROOT / "src"
_PROMPT_ROOT = _PRODUCT_SOURCE_ROOT / "google_work_agent/application/prompt_runtime"
_PROMPT_MANIFEST = _PROMPT_ROOT / "prompt_manifest.json"


class ProductIdentityError(ValueError):
    """Raised when the configured candidate is not the Product code being executed."""


@dataclass(frozen=True, slots=True)
class VerifiedProductIdentity:
    product_commit_sha: str
    product_tree_hash: str
    prompt_bundle_version: str
    target_symbol: str


def verify_product_identity(config: ExperimentConfigV1) -> VerifiedProductIdentity:
    """Resolve Product identity from Git, callable source, and verified Prompt artifacts."""

    configured_commit = _git("rev-parse", f"{config.product_commit_sha}^{{commit}}")
    configured_tree = _git("rev-parse", f"{configured_commit}:src")
    current_tree = _git("rev-parse", "HEAD:src")
    if configured_tree != current_tree:
        raise ProductIdentityError(
            "configured Product commit does not match the loaded source tree"
        )
    if _git("status", "--porcelain=v1", "--untracked-files=all", "--", "src"):
        raise ProductIdentityError("Product source tree contains uncommitted changes")

    target = resolve_target(config.target)
    target_callable = target.load()
    try:
        target_source = Path(inspect.getfile(target_callable)).resolve()
        target_source.relative_to(_PRODUCT_SOURCE_ROOT)
    except (TypeError, ValueError) as error:
        raise ProductIdentityError(
            "resolved target is outside the pinned Product source tree"
        ) from error

    prompt_bundle_version = _verify_prompt_artifacts(config)

    return VerifiedProductIdentity(
        product_commit_sha=configured_commit,
        product_tree_hash=configured_tree,
        prompt_bundle_version=prompt_bundle_version,
        target_symbol=f"{target.module}:{target.symbol}",
    )


def _git(*arguments: str) -> str:
    completed = subprocess.run(
        ("git", "-C", str(_REPOSITORY_ROOT), *arguments),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise ProductIdentityError("cannot independently resolve Product Git identity")
    return completed.stdout.strip()


def _verify_prompt_artifacts(config: ExperimentConfigV1) -> str:
    try:
        payload = load_strict_json(_PROMPT_MANIFEST.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as error:
        raise ProductIdentityError("Product Prompt manifest is not strict readable JSON") from error
    if not isinstance(payload, dict) or set(payload) != {
        "schema_version",
        "prompt_bundle_version",
        "activation_policy",
        "slots",
    }:
        raise ProductIdentityError("Product Prompt manifest root is not the closed contract")
    bundle_version = payload.get("prompt_bundle_version")
    slots = payload.get("slots")
    if not isinstance(bundle_version, str) or not isinstance(slots, list) or not slots:
        raise ProductIdentityError("Product Prompt manifest identity is incomplete")
    source_names: set[str] = set()
    prompt_by_runtime_node: dict[str, str] = {}
    for value in slots:
        if not isinstance(value, dict):
            raise ProductIdentityError("Product Prompt slot must be an object")
        prompt_id = value.get("prompt_id")
        slot_id = value.get("prompt_slot_id")
        runtime_node_id = value.get("runtime_node_id")
        source = value.get("source")
        expected_hash = value.get("content_hash")
        if (
            not isinstance(prompt_id, str)
            or prompt_id != slot_id
            or not isinstance(runtime_node_id, str)
            or not isinstance(source, str)
            or source != f"sources/{prompt_id}.md"
            or not isinstance(expected_hash, str)
            or len(expected_hash) != 64
            or value.get("activation_status") != "RUNTIME_ACTIVE"
            or any(
                value.get(field) is not True
                for field in (
                    "node_dev_pass",
                    "node_holdout_pass",
                    "safety_gate_pass",
                    "manifest_approved",
                )
            )
        ):
            raise ProductIdentityError("Product Prompt slot identity or activation is invalid")
        source_path = (_PROMPT_ROOT / source).resolve()
        try:
            source_path.relative_to(_PROMPT_ROOT / "sources")
            actual_hash = hashlib.sha256(source_path.read_bytes()).hexdigest()
        except (OSError, ValueError) as error:
            raise ProductIdentityError("Product Prompt source is unavailable") from error
        if actual_hash != expected_hash:
            raise ProductIdentityError("Product Prompt source hash does not match its manifest")
        if runtime_node_id in prompt_by_runtime_node:
            raise ProductIdentityError("Product Prompt runtime Node identity is duplicated")
        prompt_by_runtime_node[runtime_node_id] = prompt_id
        source_names.add(Path(source).name)
    actual_sources = {path.name for path in (_PROMPT_ROOT / "sources").glob("*.md")}
    if source_names != actual_sources:
        raise ProductIdentityError("Product Prompt source set does not match its manifest")
    if config.prompt_bundle_version != bundle_version:
        raise ProductIdentityError("configured Prompt bundle does not match Product artifacts")
    if config.target.target_kind == "NODE":
        if prompt_by_runtime_node.get(config.target.target_id) != config.prompt_id:
            raise ProductIdentityError("configured Prompt does not own the Product Node target")
    elif config.prompt_id != bundle_version:
        raise ProductIdentityError("Subgraph/Main Profile evaluation must pin the Prompt bundle")
    return bundle_version


__all__ = [
    "ProductIdentityError",
    "VerifiedProductIdentity",
    "verify_product_identity",
]
