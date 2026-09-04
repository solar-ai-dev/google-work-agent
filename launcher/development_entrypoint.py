"""Explicit non-installed Product launcher for local development smoke."""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import threading
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path

from uvicorn import Config, Server

from google_work_agent.adapters.llm.runtime.llm_credential_router import (
    SessionMemorySecretStore,
)
from google_work_agent.adapters.system.default_browser_launcher import (
    DefaultBrowserLauncherAdapter,
)
from google_work_agent.api.app import create_app
from google_work_agent.api.composition import ProductionRuntimeConfig
from launcher.allocate_dynamic_port import allocate_dynamic_port
from launcher.bootstrap_secret import create_bootstrap_secret
from launcher.open_product_ui import build_product_ui_url, open_product_ui
from launcher.readiness import ServiceReadiness, wait_for_service_ready

MCP_MANIFEST_VERSION = "2026-08-07.p0"
PROJECT_ROOT = Path(__file__).resolve().parents[1]


class _ThreadServiceProbe:
    def __init__(self, thread: threading.Thread, exit_code: list[int]) -> None:
        self._thread = thread
        self._exit_code = exit_code

    def poll(self) -> int | None:
        return None if self._thread.is_alive() else self._exit_code[0]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Start Google Work Agent development Product")
    parser.add_argument("--runtime-root", type=Path, default=PROJECT_ROOT / "runtime/development")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--launch-descriptor", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    arguments = parser.parse_args(argv)
    if arguments.host != "127.0.0.1":
        raise ValueError("development launcher permits only 127.0.0.1")
    if not 0 <= arguments.port <= 65535:
        raise ValueError("port must be 0 or a valid TCP port")
    if arguments.startup_timeout <= 0:
        raise ValueError("startup-timeout must be positive")
    if not (PROJECT_ROOT / "frontend/dist/index.html").is_file():
        raise RuntimeError("DEVELOPMENT_FRONTEND_NOT_BUILT")

    reservation = allocate_dynamic_port() if arguments.port == 0 else None
    port = reservation.port if reservation is not None else arguments.port
    bootstrap_secret = create_bootstrap_secret()
    service_instance_id = f"dev-{os.getpid()}-{os.urandom(8).hex()}"
    runtime_root = arguments.runtime_root.resolve()
    descriptor_path = (
        None if arguments.launch_descriptor is None else arguments.launch_descriptor.resolve()
    )
    server_holder: list[Server] = []
    server_socket: socket.socket | None = None
    thread: threading.Thread | None = None
    exit_code = [1]
    try:
        production_config = ProductionRuntimeConfig.development(
            runtime_root=runtime_root,
            working_directory=PROJECT_ROOT,
            mcp_manifest_version=MCP_MANIFEST_VERSION,
            keyring_store=SessionMemorySecretStore(),
        )

        def request_process_exit() -> None:
            if server_holder:
                server_holder[0].should_exit = True

        application = create_app(
            production_config=production_config,
            host=arguments.host,
            port=port,
            bootstrap_secret=bootstrap_secret,
            service_instance_id=service_instance_id,
            request_process_exit=request_process_exit,
        )
        server = Server(
            Config(
                application,
                host=arguments.host,
                port=port,
                access_log=False,
                proxy_headers=False,
                server_header=False,
                date_header=False,
                log_level="warning",
            )
        )
        server_holder.append(server)
        if reservation is not None:
            server_socket = reservation.take_socket()

        def run_server() -> None:
            try:
                if server_socket is None:
                    server.run()
                else:
                    server.run(sockets=[server_socket])
                exit_code[0] = 0
            except Exception as error:
                print(
                    f"Development service failed: {type(error).__name__}: {error}",
                    file=sys.stderr,
                    flush=True,
                )
                exit_code[0] = 1

        thread = threading.Thread(target=run_server, name="gwa-development-server")
        thread.start()
        readiness = wait_for_service_ready(
            _ThreadServiceProbe(thread, exit_code),  # type: ignore[arg-type]
            port=port,
            service_instance_id=service_instance_id,
            expected_release_version=production_config.release_version,
            expected_api_contract_version=production_config.api_contract_version,
            timeout_seconds=arguments.startup_timeout,
        )
        bootstrap_url = build_product_ui_url(
            port=port,
            bootstrap_secret=bootstrap_secret,
            service_instance_id=service_instance_id,
        )
        if descriptor_path is not None:
            _write_launch_descriptor(
                descriptor_path,
                port=port,
                bootstrap_url=bootstrap_url,
                service_instance_id=service_instance_id,
                readiness=readiness,
            )
        if not arguments.no_browser:
            open_product_ui(
                DefaultBrowserLauncherAdapter(),
                port=port,
                bootstrap_secret=bootstrap_secret,
                service_instance_id=service_instance_id,
            )
        bootstrap_secret = ""
        print(f"Google Work Agent development Product ready: http://127.0.0.1:{port}/")
        if descriptor_path is not None:
            print(f"Launch descriptor: {descriptor_path}")
        while thread.is_alive():
            thread.join(timeout=0.5)
        return exit_code[0]
    except KeyboardInterrupt:
        return 0
    finally:
        if server_holder:
            server_holder[0].should_exit = True
        if thread is not None and thread.is_alive():
            thread.join(timeout=10)
        if server_socket is not None:
            with suppress(OSError):
                server_socket.close()
        if reservation is not None:
            reservation.release()
        if descriptor_path is not None:
            descriptor_path.unlink(missing_ok=True)


def _write_launch_descriptor(
    path: Path,
    *,
    port: int,
    bootstrap_url: str,
    service_instance_id: str,
    readiness: ServiceReadiness,
) -> None:
    payload = {
        "schema_version": 1,
        "base_url": f"http://127.0.0.1:{port}",
        "bootstrap_url": bootstrap_url,
        "service_instance_id": service_instance_id,
        "process_id": os.getpid(),
        "readiness_state": readiness.state,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    descriptor_fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(descriptor_fd, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, sort_keys=True, separators=(",", ":"))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        _restrict_owner_only(temporary)
        os.replace(temporary, path)
        _restrict_owner_only(path)
    finally:
        temporary.unlink(missing_ok=True)


def _restrict_owner_only(path: Path) -> None:
    os.chmod(path, 0o600)
    if os.name != "nt":
        return
    identity = subprocess.run(
        ["whoami", "/user", "/fo", "csv", "/nh"],
        check=True,
        capture_output=True,
        text=True,
        timeout=5,
    ).stdout
    match = re.search(r"S-1-[0-9-]+", identity)
    if match is None:
        raise RuntimeError("DEVELOPMENT_DESCRIPTOR_PERMISSION_DENIED")
    subprocess.run(
        [
            "icacls",
            str(path),
            "/inheritance:r",
            "/grant:r",
            f"*{match.group(0)}:F",
            "*S-1-5-18:F",
        ],
        check=True,
        capture_output=True,
        timeout=10,
    )


if __name__ == "__main__":
    raise SystemExit(main())
