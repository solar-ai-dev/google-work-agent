"""Single runtime authority for installed and approved local-model selection."""

from __future__ import annotations

from dataclasses import dataclass

from google_work_agent.ports.llm.llm_runtime_status_port import LocalModelRuntimeOptionV1
from google_work_agent.ports.llm.local_model_catalog_port import LocalModelCatalogPort
from google_work_agent.ports.llm.runtime_selection import LlmRuntimeSelectionV1
from google_work_agent.ports.llm.structured_inference_contracts import ApprovedModelInfo


@dataclass(frozen=True, slots=True)
class LocalModelSelectionResolver:
    runtime_selection: LlmRuntimeSelectionV1
    catalog: LocalModelCatalogPort
    allow_development_models: bool = False

    def get_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        approved = self.runtime_selection.get_approved_model(model_id)
        if approved is not None:
            return approved
        profile = self.runtime_selection.local_model_profile
        if (
            not self.allow_development_models
            or profile is None
            or model_id not in profile.model_ids
        ):
            return None
        installed = next(
            (item for item in self.catalog.list_installed_models() if item.model_id == model_id),
            None,
        )
        if installed is None:
            return None
        digest = None if installed.digest is None else installed.digest.removeprefix("sha256:")
        return ApprovedModelInfo(
            model_id=installed.model_id,
            runtime="OLLAMA",
            manifest_version="DEVELOPMENT",
            schema_version="1",
            digest=digest,
        )

    def get_selected_model(self) -> ApprovedModelInfo | None:
        profile = self.runtime_selection.local_model_profile
        if profile is not None:
            if not self._profile_ready():
                return None
            return self.get_approved_model(profile.reasoning_model_id)
        selected_model_id = self.runtime_selection.selected_model_id
        if selected_model_id is None:
            return None
        return self._installed_approved_model(selected_model_id)

    def get_model_for_prompt(self, prompt_id: str) -> ApprovedModelInfo | None:
        profile = self.runtime_selection.local_model_profile
        if profile is None:
            return self.get_selected_model()
        if not self._profile_ready():
            return None
        return self.get_approved_model(profile.model_id_for_prompt(prompt_id))

    def list_options(self) -> tuple[LocalModelRuntimeOptionV1, ...]:
        profile = self.runtime_selection.local_model_profile
        active_ids = (
            frozenset(profile.model_ids)
            if profile is not None
            else frozenset(
                ()
                if self.runtime_selection.selected_model_id is None
                else (self.runtime_selection.selected_model_id,)
            )
        )
        installed_models = self.catalog.list_installed_models()
        installed_by_id = {item.model_id: item for item in installed_models}
        model_ids = [item.model_id for item in installed_models]
        model_ids.extend(sorted(active_ids.difference(installed_by_id)))
        return tuple(
            LocalModelRuntimeOptionV1(
                schema_version=1,
                model_id=model_id,
                installed=model_id in installed_by_id,
                approved=self.get_approved_model(model_id) is not None,
                selected=model_id in active_ids,
            )
            for model_id in model_ids
        )

    def _profile_ready(self) -> bool:
        profile = self.runtime_selection.local_model_profile
        return profile is not None and all(
            self._installed_approved_model(model_id) is not None
            for model_id in profile.model_ids
        )

    def _installed_approved_model(self, model_id: str) -> ApprovedModelInfo | None:
        installed = next(
            (item for item in self.catalog.list_installed_models() if item.model_id == model_id),
            None,
        )
        if installed is None:
            return None
        approved = self.get_approved_model(model_id)
        if approved is None:
            return None
        installed_digest = (
            None if installed.digest is None else installed.digest.removeprefix("sha256:")
        )
        if approved.digest is not None and installed_digest != approved.digest:
            return None
        return approved


__all__ = ["LocalModelSelectionResolver"]
