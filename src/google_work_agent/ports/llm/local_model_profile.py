"""Release-owned local multi-model profile contract."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Literal

_IDENTITY_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,255}")


class LocalInferenceClass(StrEnum):
    WORKER = "WORKER"
    REASONING = "REASONING"


@dataclass(frozen=True, slots=True)
class LocalModelProfileV1:
    schema_version: Literal[1]
    profile_id: str
    runtime: Literal["OLLAMA"]
    worker_model_id: str
    reasoning_model_id: str
    default_inference_class: LocalInferenceClass
    prompt_inference_classes: tuple[tuple[str, LocalInferenceClass], ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1 or self.runtime != "OLLAMA":
            raise ValueError("unsupported local model profile")
        for value in (self.profile_id, self.worker_model_id, self.reasoning_model_id):
            if value != value.strip() or _IDENTITY_PATTERN.fullmatch(value) is None:
                raise ValueError("local model profile identity is invalid")
        prompt_ids = [prompt_id for prompt_id, _inference_class in self.prompt_inference_classes]
        if prompt_ids != sorted(prompt_ids) or len(prompt_ids) != len(set(prompt_ids)):
            raise ValueError("prompt inference-class mappings must be sorted and unique")
        if any(
            prompt_id != prompt_id.strip()
            or _IDENTITY_PATTERN.fullmatch(prompt_id) is None
            or not isinstance(inference_class, LocalInferenceClass)
            for prompt_id, inference_class in self.prompt_inference_classes
        ):
            raise ValueError("prompt inference-class mapping is invalid")

    @property
    def model_ids(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.worker_model_id, self.reasoning_model_id)))

    def inference_class_for_prompt(self, prompt_id: str) -> LocalInferenceClass:
        return next(
            (
                inference_class
                for candidate, inference_class in self.prompt_inference_classes
                if candidate == prompt_id
            ),
            self.default_inference_class,
        )

    def model_id_for_prompt(self, prompt_id: str) -> str:
        if self.inference_class_for_prompt(prompt_id) is LocalInferenceClass.WORKER:
            return self.worker_model_id
        return self.reasoning_model_id

    def to_canonical_bytes(self) -> bytes:
        return json.dumps(
            {
                "schema_version": self.schema_version,
                "profile_id": self.profile_id,
                "runtime": self.runtime,
                "models": {
                    LocalInferenceClass.WORKER.value: self.worker_model_id,
                    LocalInferenceClass.REASONING.value: self.reasoning_model_id,
                },
                "default_inference_class": self.default_inference_class.value,
                "prompt_inference_classes": {
                    prompt_id: inference_class.value
                    for prompt_id, inference_class in self.prompt_inference_classes
                },
            },
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")

    @classmethod
    def from_bytes(cls, content: bytes) -> LocalModelProfileV1:
        payload = json.loads(content.decode("utf-8"), object_pairs_hook=_unique_object)
        expected = {
            "schema_version",
            "profile_id",
            "runtime",
            "models",
            "default_inference_class",
            "prompt_inference_classes",
        }
        if not isinstance(payload, dict) or set(payload) != expected:
            raise ValueError("LocalModelProfileV1 fields mismatch")
        models = payload["models"]
        routes = payload["prompt_inference_classes"]
        if not isinstance(models, dict) or set(models) != {"WORKER", "REASONING"}:
            raise ValueError("LocalModelProfileV1 models mismatch")
        if not isinstance(routes, dict):
            raise ValueError("prompt_inference_classes must be an object")
        string_fields = ("profile_id", "runtime", "default_inference_class")
        if payload["schema_version"] != 1 or any(
            not isinstance(payload[field], str) for field in string_fields
        ):
            raise ValueError("LocalModelProfileV1 field type mismatch")
        if any(not isinstance(models[key], str) for key in ("WORKER", "REASONING")):
            raise ValueError("LocalModelProfileV1 model type mismatch")
        if any(
            not isinstance(key, str) or not isinstance(value, str)
            for key, value in routes.items()
        ):
            raise ValueError("prompt inference-class mapping type mismatch")
        try:
            default = LocalInferenceClass(payload["default_inference_class"])
            mappings = tuple(
                sorted(
                    (
                        (prompt_id, LocalInferenceClass(inference_class))
                        for prompt_id, inference_class in routes.items()
                    ),
                    key=lambda item: item[0],
                )
            )
        except ValueError as error:
            raise ValueError("unsupported local inference class") from error
        return cls(
            schema_version=1,
            profile_id=payload["profile_id"],
            runtime=payload["runtime"],
            worker_model_id=models["WORKER"],
            reasoning_model_id=models["REASONING"],
            default_inference_class=default,
            prompt_inference_classes=mappings,
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


__all__ = ["LocalInferenceClass", "LocalModelProfileV1"]
