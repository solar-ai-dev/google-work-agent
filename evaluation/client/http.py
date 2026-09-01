"""Tiny HTTP-only client for the supported local Product API."""

from __future__ import annotations

import json
import time
from http.cookiejar import CookieJar
from typing import cast
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener


class ProductApiError(RuntimeError):
    """Raised when the public Product API cannot satisfy an evaluation request."""


class ProductApiClient:
    """Invoke the Product through HTTP without importing Product internals."""

    def __init__(self, base_url: str, *, timeout_seconds: float = 10.0) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost"}:
            raise ValueError("Product evaluation only supports the loopback HTTP API")
        if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an HTTP origin without a path, query, or fragment")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._base_url = base_url.rstrip("/")
        self._origin = f"{parsed.scheme}://{parsed.netloc}"
        self._timeout_seconds = timeout_seconds
        self._opener = build_opener(HTTPCookieProcessor(CookieJar()))

    def liveness(self) -> dict[str, object]:
        return self._request("GET", "/health/live")

    def bootstrap(self, bootstrap_secret: str) -> dict[str, object]:
        if not bootstrap_secret:
            raise ValueError("bootstrap_secret is required")
        return self._request(
            "POST",
            "/api/v1/session/bootstrap",
            {
                "schema_version": 1,
                "bootstrap_secret": bootstrap_secret,
                "frontend_api_contract_version": "1",
            },
        )

    def store_session_llm_credential(
        self, *, provider: str, api_key: str, command_id: str
    ) -> dict[str, object]:
        """Configure a public Product session without retaining the secret."""

        if not provider or not api_key or not command_id:
            raise ValueError("provider, api_key, and command_id are required")
        return self._request(
            "PUT",
            f"/api/v1/credentials/llm/{quote(provider, safe='')}",
            {
                "schema_version": 1,
                "command_id": command_id,
                "api_key": api_key,
                "storage_mode": "SESSION_ONLY",
            },
        )

    def update_settings(
        self, *, command_id: str, settings_patch: dict[str, object]
    ) -> dict[str, object]:
        """Apply supported public settings needed by an evaluation environment."""

        if not command_id:
            raise ValueError("command_id is required")
        return self._request(
            "PUT",
            "/api/v1/settings",
            {
                "schema_version": 1,
                "command_id": command_id,
                "settings_patch": {"schema_version": 1, **settings_patch},
            },
        )

    def create_conversation(self, *, command_id: str, title: str) -> dict[str, object]:
        return self._request(
            "POST",
            "/api/v1/conversations",
            {"schema_version": 1, "command_id": command_id, "title": title},
        )

    def start_run(
        self,
        *,
        command_id: str,
        conversation_id: str,
        request_text: str,
        entry_mode: str,
        selected_resource_handles: list[str],
        requested_mode: str,
    ) -> dict[str, object]:
        return self._request(
            "POST",
            "/api/v1/runs",
            {
                "api_contract_version": "1",
                "command_id": command_id,
                "conversation_id": conversation_id,
                "request_text": request_text,
                "entry_mode": entry_mode,
                "selected_resource_handles": selected_resource_handles,
                "requested_mode": requested_mode,
            },
        )

    def get_run(self, run_id: str) -> dict[str, object]:
        return self._request("GET", f"/api/v1/runs/{quote(run_id, safe='')}")

    def wait_for_observable_result(
        self,
        run_id: str,
        *,
        timeout_seconds: float = 60.0,
        poll_interval_seconds: float = 0.1,
    ) -> dict[str, object]:
        """Poll until a terminal or user-controlled wait state is publicly visible."""

        if timeout_seconds <= 0 or poll_interval_seconds <= 0:
            raise ValueError("poll timing must be positive")
        observable = {
            "COMPLETED",
            "CANCELLED",
            "FAILED",
            "WAITING_CONFIRMATION",
            "WAITING_APPROVAL",
            "FAILED_RETRYABLE",
            "REAUTH_REQUIRED",
            "RECOVERY_REQUIRED",
        }
        deadline = time.monotonic() + timeout_seconds
        latest: dict[str, object] = {}
        while time.monotonic() < deadline:
            latest = self.get_run(run_id)
            run = latest.get("run")
            if isinstance(run, dict) and run.get("status") in observable:
                return latest
            time.sleep(poll_interval_seconds)
        raise ProductApiError(f"run did not reach an observable state: {run_id}")

    def _request(
        self, method: str, path: str, payload: dict[str, object] | None = None
    ) -> dict[str, object]:
        body = None if payload is None else json.dumps(payload).encode("utf-8")
        request = Request(
            self._base_url + path,
            data=body,
            method=method,
            headers={
                "Accept": "application/json",
                "Content-Type": "application/json",
                "Origin": self._origin,
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "X-API-Contract-Version": "1",
            },
        )
        try:
            with self._opener.open(request, timeout=self._timeout_seconds) as response:
                value = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            raise ProductApiError(f"Product API returned HTTP {error.code} for {path}") from error
        except (URLError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ProductApiError(f"Product API request failed for {path}") from error
        if not isinstance(value, dict) or not all(isinstance(key, str) for key in value):
            raise ProductApiError(f"Product API returned a non-object response for {path}")
        return cast(dict[str, object], value)
