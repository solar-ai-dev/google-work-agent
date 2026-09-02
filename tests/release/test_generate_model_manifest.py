from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from release.generate_model_manifest import ApprovedModelEntryV1, generate_model_manifest


def test_model_manifest_is__deterministic_and_uses__only_current_closed_schema(
    tmp_path: Path,
) -> None:
    output = tmp_path / "model-manifest-v1.json"
    model_hash = hashlib.sha256(b"release-approved-model-artifact").hexdigest()

    manifest = generate_model_manifest(
        minimum_ollama_version="0.6.0",
        approved_models=(ApprovedModelEntryV1("qwen2.5:7b-instruct-q4_K_M", model_hash),),
        output_path=output,
    )
    payload = json.loads(output.read_text(encoding="utf-8"))

    assert set(payload) == {"schema_version", "minimum_ollama_version", "approved_models"}
    assert payload["approved_models"] == [
        {"model_id": "qwen2.5:7b-instruct-q4_K_M", "model_hash": model_hash}
    ]
    assert output.read_bytes() == manifest.to_canonical_bytes() + b"\n"


def test_model_manifest__rejects_placeholder__identity_or_hash() -> None:
    with pytest.raises(ValueError, match="concrete release-approved"):
        ApprovedModelEntryV1("approved-model", hashlib.sha256(b"real").hexdigest())
    with pytest.raises(ValueError, match="concrete lowercase"):
        ApprovedModelEntryV1("concrete:model", "0" * 64)
