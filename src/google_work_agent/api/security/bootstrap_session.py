"""Bootstrap Secret consumption and Local Session establishment only."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from google_work_agent.api.security.bootstrap import BootstrapGrantStore
from google_work_agent.api.security.sessions import LocalSessionManager

Compatibility = Literal["COMPATIBLE", "INCOMPATIBLE"]


@dataclass(frozen=True, slots=True)
class BootstrapSessionResult:
    allowed: bool
    detail_code: str
    session_token: str | None = None
    compatibility: Compatibility | None = None


@dataclass(frozen=True, slots=True)
class BootstrapSessionService:
    grant_store: BootstrapGrantStore
    session_manager: LocalSessionManager
    service_instance_id: str
    api_contract_version: str

    def establish(
        self,
        *,
        bootstrap_secret: str,
        frontend_api_contract_version: str,
        now_ms: int,
    ) -> BootstrapSessionResult:
        consume_result = self.grant_store.consume(
            secret=bootstrap_secret,
            service_instance_id=self.service_instance_id,
            now_ms=now_ms,
        )
        if not consume_result.allowed:
            return BootstrapSessionResult(
                allowed=False,
                detail_code=consume_result.detail_code,
            )
        compatibility: Compatibility = (
            "COMPATIBLE"
            if frontend_api_contract_version == self.api_contract_version
            else "INCOMPATIBLE"
        )
        return BootstrapSessionResult(
            allowed=True,
            detail_code="BOOTSTRAP_CONSUMED",
            session_token=self.session_manager.issue(
                service_instance_id=self.service_instance_id,
                now_ms=now_ms,
                compatible=compatibility == "COMPATIBLE",
            ),
            compatibility=compatibility,
        )
