"""Start the verified FastAPI service child without secret CLI or environment leakage."""

from __future__ import annotations

import json
import os
import signal
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from launcher.allocate_dynamic_port import DynamicPortReservation
from launcher.prepare_data_directory import DataDirectoryLayout
from launcher.release_build_config import SignedBuildConfigV1
from launcher.verify_installation import VerifiedInstallation

_SERVICE_RELATIVE_PATH = "service/GoogleWorkAgentService.exe"
_ALLOWED_PARENT_ENVIRONMENT = ("SYSTEMROOT", "WINDIR", "TEMP", "TMP", "USERPROFILE")


class ServiceStartError(RuntimeError):
    def __init__(self, safe_code: str) -> None:
        super().__init__(safe_code)
        self.safe_code = safe_code


@dataclass(slots=True)
class StartedService:
    process: Any
    executable_path: Path

    @property
    def pid(self) -> int:
        return int(self.process.pid)

    def poll(self) -> int | None:
        result = self.process.poll()
        return None if result is None else int(result)

    def wait(self, timeout: float | None = None) -> int:
        return int(self.process.wait(timeout=timeout))

    def request_graceful_shutdown(self) -> None:
        if self.poll() is not None:
            return
        if os.name == "nt":
            self.process.send_signal(signal.CTRL_BREAK_EVENT)
        else:  # pragma: no cover - official product target is Windows
            self.process.terminate()

    def force_terminate(self) -> None:
        if self.poll() is None:
            self.process.kill()


def start_service(
    *,
    installation: VerifiedInstallation,
    build_config: SignedBuildConfigV1,
    data_directory: DataDirectoryLayout,
    port_reservation: DynamicPortReservation,
    service_instance_id: str,
    bootstrap_secret: str,
    process_factory: Any = subprocess.Popen,
) -> StartedService:
    """Spawn the hash-verified child and hand bootstrap/config through stdin once."""

    if not bootstrap_secret or not service_instance_id:
        raise ValueError("bootstrap_secret and service_instance_id are required")
    executable = (installation.install_root / Path(*_SERVICE_RELATIVE_PATH.split("/"))).resolve()
    if executable not in installation.verified_files or not executable.is_file():
        raise ServiceStartError("SERVICE_EXECUTABLE_UNVERIFIED")
    if (
        build_config.build_channel.upper() != "DEVELOPMENT"
        and executable not in installation.code_signature_verified_files
    ):
        raise ServiceStartError("SERVICE_EXECUTABLE_SIGNATURE_UNVERIFIED")
    service_dir = executable.parent
    environment = {
        key: value for key in _ALLOWED_PARENT_ENVIRONMENT if (value := os.environ.get(key))
    }
    environment["PYTHONNOUSERSITE"] = "1"
    payload = json.dumps(
        {
            "schema_version": 1,
            "service_instance_id": service_instance_id,
            "bootstrap_secret": bootstrap_secret,
            "signed_build_config": asdict(build_config),
            "verified_release_files": installation.manifest["files"],
            "code_signature_verified_paths": [
                path.relative_to(installation.install_root).as_posix()
                for path in installation.code_signature_verified_files
                if path in installation.verified_files
            ],
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    command = [
        str(executable),
        "--host",
        "127.0.0.1",
        "--port",
        str(port_reservation.port),
        "--data-dir",
        str(data_directory.root),
    ]
    log_path = data_directory.logs_dir / "service.stderr.log"
    creation_flags = (
        subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        if os.name == "nt"
        else 0
    )
    port_reservation.release()
    try:
        with log_path.open("ab") as error_log:
            process = process_factory(
                command,
                cwd=service_dir,
                env=environment,
                stdin=subprocess.PIPE,
                stdout=subprocess.DEVNULL,
                stderr=error_log,
                shell=False,
                creationflags=creation_flags,
            )
        if process.stdin is None:
            if process.poll() is None:
                process.kill()
            raise ServiceStartError("SERVICE_BOOTSTRAP_CHANNEL_UNAVAILABLE")
        process.stdin.write(payload + b"\n")
        process.stdin.flush()
        process.stdin.close()
    except (OSError, subprocess.SubprocessError, BrokenPipeError, ValueError) as error:
        if "process" in locals() and process.poll() is None:
            process.kill()
        raise ServiceStartError("SERVICE_START_FAILED") from error
    return StartedService(process=process, executable_path=executable)
