"""Canonical installed-product Launcher orchestration."""

from __future__ import annotations

import argparse
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from google_work_agent.adapters.system.default_browser_launcher import DefaultBrowserLauncherAdapter
from launcher.acquire_single_instance import SingleInstanceLease, acquire_single_instance
from launcher.allocate_dynamic_port import DynamicPortReservation, allocate_dynamic_port
from launcher.bootstrap_secret import create_bootstrap_secret
from launcher.create_service_instance_id import ServiceInstanceIdentity, create_service_instance_id
from launcher.open_product_ui import open_product_ui
from launcher.prepare_data_directory import DataDirectoryLayout, prepare_data_directory
from launcher.readiness import wait_for_service_ready
from launcher.release_build_config import load_signed_build_config
from launcher.request_existing_instance_ui import request_existing_instance_ui
from launcher.serve_instance_control import InstanceControlServer, serve_instance_control
from launcher.shutdown_service import shutdown_service
from launcher.start_service import StartedService, start_service
from launcher.verify_installation import verify_installation


def main(argv: Sequence[str] | None = None) -> int:
    """Run one installed Launcher instance and coordinate the child lifecycle."""

    parser = argparse.ArgumentParser(description="Start Google Work Agent")
    parser.add_argument("--install-root", type=Path)
    parser.add_argument("--startup-timeout", type=float, default=30.0)
    parser.add_argument("--shutdown-timeout", type=float, default=30.0)
    arguments = parser.parse_args(argv)
    install_root = _resolve_install_root(arguments.install_root)

    layout: DataDirectoryLayout | None = None
    lease: SingleInstanceLease | None = None
    reservation: DynamicPortReservation | None = None
    identity: ServiceInstanceIdentity | None = None
    service: StartedService | None = None
    control: InstanceControlServer | None = None
    safe_error_code: str | None = None
    try:
        installation = verify_installation(install_root)
        build_config = load_signed_build_config(installation)
        layout = prepare_data_directory()
        lease = acquire_single_instance(layout.runtime_dir)
        if not lease.acquired:
            return 0 if request_existing_instance_ui(lease.control_endpoint) else 2

        reservation = allocate_dynamic_port()
        bootstrap_secret = create_bootstrap_secret()
        identity = create_service_instance_id(
            layout.runtime_dir,
            host="127.0.0.1",
            port=reservation.port,
            control_endpoint=lease.control_endpoint,
        )
        lease = lease.bind_service_instance(identity.service_instance_id)
        service = start_service(
            installation=installation,
            build_config=build_config,
            data_directory=layout,
            port_reservation=reservation,
            service_instance_id=identity.service_instance_id,
            bootstrap_secret=bootstrap_secret,
        )
        identity = identity.bind_service_pid(service.pid)
        browser = DefaultBrowserLauncherAdapter()
        wait_for_service_ready(
            service,
            port=identity.port,
            service_instance_id=identity.service_instance_id,
            expected_release_version=build_config.app_version,
            expected_api_contract_version=build_config.api_contract_version,
            timeout_seconds=arguments.startup_timeout,
        )

        def open_existing_ui() -> None:
            open_product_ui(browser, port=identity.port)

        control = serve_instance_control(
            lease.control_endpoint,
            on_open_ui=open_existing_ui,
        )
        open_product_ui(
            browser,
            port=identity.port,
            bootstrap_secret=bootstrap_secret,
            service_instance_id=identity.service_instance_id,
        )
        bootstrap_secret = ""
        while service.poll() is None:
            try:
                service.wait(timeout=1.0)
            except subprocess.TimeoutExpired:
                continue
        return 0 if service.poll() == 0 else 1
    except KeyboardInterrupt:
        safe_error_code = None
        return 0
    except Exception as error:
        safe_error_code = getattr(error, "safe_code", "LAUNCHER_START_FAILED")
        print(f"Launcher failed: {safe_error_code}", file=sys.stderr)
        return 1
    finally:
        if reservation is not None:
            reservation.release()
        if layout is not None and lease is not None and lease.acquired:
            shutdown_service(
                service=service,
                control_server=control,
                identity=identity,
                lease=lease,
                marker_path=layout.shutdown_marker_path,
                timeout_seconds=arguments.shutdown_timeout,
                safe_error_code=safe_error_code,
            )


def _resolve_install_root(explicit: Path | None) -> Path:
    if explicit is None:
        return Path(sys.executable).resolve().parent.parent
    if not explicit.is_absolute():
        raise ValueError("install root must be absolute")
    return explicit.resolve()


if __name__ == "__main__":
    raise SystemExit(main())
