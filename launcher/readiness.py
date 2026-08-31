"""Wait for service liveness and readiness with bounded polling."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, cast
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from launcher.start_service import StartedService


class ServiceReadinessError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(frozen=True, slots=True)
class ServiceReadiness:
    state: Literal["READY", "SAFE_MODE"]
    checks: tuple[dict[str, object], ...]


def wait_for_service_ready(
    service: StartedService,
    *,
    port: int,
    service_instance_id: str,
    expected_release_version: str,
    expected_api_contract_version: str,
    timeout_seconds: float = 30.0,
    poll_interval_seconds: float = 0.1,
    opener: Callable[..., Any] = urlopen,
    monotonic: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> ServiceReadiness:
    """Return only after liveness identity and required readiness are coherent."""

    if timeout_seconds <= 0 or poll_interval_seconds <= 0:
        raise ValueError("readiness timing values must be positive")
    deadline = monotonic() + timeout_seconds
    live_confirmed = False
    while (remaining := deadline - monotonic()) > 0:
        exit_code = service.poll()
        if exit_code is not None:
            raise ServiceReadinessError("SERVICE_EARLY_EXIT")
        try:
            if not live_confirmed:
                live = _get_json(
                    f"http://127.0.0.1:{port}/health/live",
                    opener=opener,
                    timeout=min(1.0, remaining),
                )
                live_confirmed = (
                    live.get("status") == "LIVE"
                    and live.get("service_instance_id") == service_instance_id
                    and live.get("release_version") == expected_release_version
                    and live.get("api_contract_version") == expected_api_contract_version
                )
            if live_confirmed:
                remaining = deadline - monotonic()
                if remaining <= 0:
                    break
                ready = _get_json(
                    f"http://127.0.0.1:{port}/health/ready",
                    opener=opener,
                    timeout=min(1.0, remaining),
                )
                state = ready.get("status")
                checks = ready.get("checks")
                build_identity_matches = (
                    ready.get("release_version") == expected_release_version
                    and ready.get("api_contract_version") == expected_api_contract_version
                )
                if state == "READY" and build_identity_matches and _all_checks_ready(checks):
                    return ServiceReadiness("READY", tuple(cast(list[dict[str, object]], checks)))
                if state == "SAFE_MODE" and build_identity_matches and isinstance(checks, list):
                    return ServiceReadiness(
                        "SAFE_MODE", tuple(cast(list[dict[str, object]], checks))
                    )
        except (OSError, HTTPError, URLError, UnicodeError, json.JSONDecodeError, ValueError):
            pass
        sleep(min(poll_interval_seconds, max(0.0, deadline - monotonic())))
    raise ServiceReadinessError("SERVICE_NOT_READY")


def _get_json(url: str, *, opener: Callable[..., Any], timeout: float) -> dict[str, object]:
    request = Request(url, method="GET", headers={"Accept": "application/json"})
    with opener(request, timeout=timeout) as response:
        content = response.read(65_537)
    if len(content) > 65_536:
        raise ValueError("health response is too large")
    payload = json.loads(content.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("health response must be an object")
    return payload


def _all_checks_ready(checks: object) -> bool:
    return (
        bool(checks)
        and isinstance(checks, list)
        and all(isinstance(check, dict) and check.get("state") == "READY" for check in checks)
    )
