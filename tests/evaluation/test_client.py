from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

from evaluation.client import ProductApiClient


class _ProductBoundaryHandler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/health/live":
            self._send({"status": "LIVE"})
        elif self.path == "/api/v1/runs/run-1":
            self._send({"run": {"status": "COMPLETED"}})
        else:
            self.send_error(404)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        if self.path == "/api/v1/session/bootstrap":
            assert payload["schema_version"] == 1
            assert payload["bootstrap_secret"] == "bootstrap"
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Set-Cookie", "gwa_session=test; Path=/")
            body = b'{"session_established":true}'
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/v1/conversations":
            assert "gwa_session=test" in self.headers.get("Cookie", "")
            self._send({"conversation_id": "conversation-1"}, status=201)
        elif self.path == "/api/v1/runs":
            assert payload["conversation_id"] == "conversation-1"
            self._send({"run_id": "run-1"}, status=202)
        else:
            self.send_error(404)

    def do_PUT(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length).decode("utf-8"))
        assert "gwa_session=test" in self.headers.get("Cookie", "")
        if self.path == "/api/v1/credentials/llm/gemini":
            assert payload["api_key"] == "key"
            assert payload["storage_mode"] == "SESSION_ONLY"
            self._send({"status": "CONFIGURED"})
        elif self.path == "/api/v1/settings":
            assert payload["settings_patch"]["preferred_llm_mode"] == "API_LLM"
            self._send({"preferred_llm_mode": "API_LLM"})
        else:
            self.send_error(404)

    def log_message(self, format: str, *args: object) -> None:
        del format, args

    def _send(self, value: dict[str, object], *, status: int = 200) -> None:
        body = json.dumps(value).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def test_client_uses_only__http_boundary_and__preserves_session_cookie() -> None:
    server = ThreadingHTTPServer(("127.0.0.1", 0), _ProductBoundaryHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        port = cast(tuple[str, int], server.server_address)[1]
        client = ProductApiClient(f"http://127.0.0.1:{port}")
        assert client.liveness() == {"status": "LIVE"}
        assert client.bootstrap("bootstrap")["session_established"] is True
        assert client.store_session_llm_credential(
            provider="gemini", api_key="key", command_id="credential-1"
        )["status"] == "CONFIGURED"
        assert client.update_settings(
            command_id="settings-1", settings_patch={"preferred_llm_mode": "API_LLM"}
        )["preferred_llm_mode"] == "API_LLM"
        conversation = client.create_conversation(command_id="cmd-1", title="Evaluation")
        started = client.start_run(
            command_id="cmd-2",
            conversation_id=str(conversation["conversation_id"]),
            request_text="hello",
            entry_mode="AGENT_SEARCH",
            selected_resource_handles=[],
            requested_mode="AUTO",
        )
        snapshot = client.wait_for_observable_result(str(started["run_id"]))
        assert snapshot["run"] == {"status": "COMPLETED"}
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)
