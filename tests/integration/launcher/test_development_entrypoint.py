from __future__ import annotations

import ast
import importlib
import json
import os
import stat
import subprocess
import sys
import time
from http.cookiejar import CookieJar
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qs, urlsplit
from urllib.request import HTTPCookieProcessor, Request, build_opener

import pytest
from launcher.development_entrypoint import main

ROOT = Path(__file__).resolve().parents[3]


def test_development_entrypoint__imports_and_rejects__non_loopback_bind() -> None:
    module = importlib.import_module("launcher.development_entrypoint")

    assert callable(module.main)
    with pytest.raises(ValueError, match="127.0.0.1"):
        main(["--host", "0.0.0.0"])


def test_development_launcher__reuses_product_composition__without_second_root() -> None:
    path = ROOT / "launcher/development_entrypoint.py"
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source)
    constructed = {
        node.func.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }

    assert "ProductionRuntimeConfig.development" in source
    assert source.count("create_app(") == 1
    assert "build_production_runtime(" not in source
    assert "DeferredApiContainer(" not in source
    assert "ApiContainer(" not in source
    assert not {name for name in constructed if name.endswith(("Handler", "Registry"))}
    assert {
        path
        for path in (ROOT / "src/google_work_agent").rglob("*.py")
        if "def build_production_runtime(" in path.read_text(encoding="utf-8")
    } == {ROOT / "src/google_work_agent/api/composition.py"}


def test_development_commands__contain_zero_stale__module_references() -> None:
    candidates = [ROOT / "README.md", ROOT / ".claude/launch.json"]
    candidates.extend((ROOT / "docs/canonical").rglob("*.md"))
    offenders = [
        path
        for path in candidates
        if "google_work_agent.launcher.dev" in path.read_text(encoding="utf-8")
    ]

    assert offenders == []


def test_development_process__serves_authenticated_product__and_cleans_descriptor(
    tmp_path: Path,
) -> None:
    descriptor = tmp_path / "development-launch.json"
    runtime_root = tmp_path / "runtime"
    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "launcher.development_entrypoint",
            "--runtime-root",
            str(runtime_root),
            "--port",
            "0",
            "--no-browser",
            "--launch-descriptor",
            str(descriptor),
            "--startup-timeout",
            "30",
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    output = ""
    bootstrap_secret = ""
    try:
        launch = _wait_for_descriptor(descriptor, process)
        base_url = cast(str, launch["base_url"])
        bootstrap_url = cast(str, launch["bootstrap_url"])
        bootstrap_secret = parse_qs(urlsplit(bootstrap_url).fragment)["bootstrap_secret"][0]
        service_instance_id = cast(str, launch["service_instance_id"])

        assert urlsplit(base_url).hostname == "127.0.0.1"
        assert cast(int, urlsplit(base_url).port) > 0
        assert launch["readiness_state"] == "READY"
        assert isinstance(launch["process_id"], int)
        assert launch["process_id"] > 0
        _assert_owner_only(descriptor)

        cookie_jar = CookieJar()
        opener = build_opener(HTTPCookieProcessor(cookie_jar))
        ready = _request_json(opener, f"{base_url}/health/ready")
        assert ready["status"] == "READY"

        with opener.open(f"{base_url}/", timeout=5) as response:
            frontend = response.read().decode("utf-8")
        assert response.status == 200
        assert '<div id="root"></div>' in frontend

        bootstrap = _request_json(
            opener,
            f"{base_url}/api/v1/session/bootstrap",
            method="POST",
            base_url=base_url,
            payload={
                "schema_version": 1,
                "bootstrap_secret": bootstrap_secret,
                "frontend_api_contract_version": "1",
            },
        )
        assert bootstrap["session_established"] is True
        assert bootstrap["service_instance_id"] == service_instance_id
        assert len(cookie_jar) == 1

        runtime = _request_json(
            opener,
            f"{base_url}/api/v1/runtime",
            base_url=base_url,
        )
        assert runtime["schema_version"] == 1
        assert runtime["session_status"] == "ESTABLISHED"

        shutdown = _request_json(
            opener,
            f"{base_url}/api/v1/control/shutdown",
            method="POST",
            base_url=base_url,
            payload={"schema_version": 1, "command_id": "development-process-test"},
        )
        assert shutdown == {"schema_version": 1, "accepted": True}
        output = "\n".join(process.communicate(timeout=20))
        assert process.returncode == 0
        assert not descriptor.exists()
        assert bootstrap_secret not in output
    finally:
        if process.poll() is None:
            process.terminate()
            try:
                output = "\n".join(process.communicate(timeout=10))
            except subprocess.TimeoutExpired:
                process.kill()
                output = "\n".join(process.communicate(timeout=10))
        descriptor.unlink(missing_ok=True)


def _wait_for_descriptor(path: Path, process: subprocess.Popen[str]) -> dict[str, Any]:
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        if path.is_file():
            payload = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                return cast(dict[str, Any], payload)
        if process.poll() is not None:
            stdout, stderr = process.communicate(timeout=5)
            raise AssertionError(f"launcher exited before descriptor: {stdout}\n{stderr}")
        time.sleep(0.05)
    raise AssertionError("development launch descriptor was not created")


def _request_json(
    opener: Any,
    url: str,
    *,
    method: str = "GET",
    base_url: str | None = None,
    payload: dict[str, object] | None = None,
) -> dict[str, Any]:
    body = None if payload is None else json.dumps(payload).encode("utf-8")
    headers = {"Accept": "application/json"}
    if base_url is not None:
        headers.update(
            {
                "Origin": base_url,
                "Sec-Fetch-Site": "same-origin",
                "Sec-Fetch-Mode": "cors",
                "Sec-Fetch-Dest": "empty",
                "X-Api-Contract-Version": "1",
            }
        )
    if body is not None:
        headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=headers, method=method)
    with opener.open(request, timeout=10) as response:
        result = json.loads(response.read().decode("utf-8"))
    assert isinstance(result, dict)
    return cast(dict[str, Any], result)


def _assert_owner_only(path: Path) -> None:
    if os.name != "nt":
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        return
    identity = subprocess.run(
        ["whoami"],
        check=True,
        capture_output=True,
        timeout=5,
    ).stdout.decode("utf-8").strip().lower()
    result = subprocess.run(
        ["icacls", str(path)],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    acl = result.stdout.lower()
    entries = [line for line in acl.splitlines() if ":(" in line]
    assert len(entries) == 2
    assert any(identity in line for line in entries)
    assert any("system" in line for line in entries)
    assert "(i)" not in acl
