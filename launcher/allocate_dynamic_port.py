"""Reserve a loopback-only OS-assigned dynamic port."""

from __future__ import annotations

import socket
from dataclasses import dataclass, field


@dataclass(slots=True)
class DynamicPortReservation:
    port: int
    _socket: socket.socket | None = field(repr=False)

    def release(self) -> None:
        reserved = self._socket
        self._socket = None
        if reserved is not None:
            reserved.close()

    def take_socket(self) -> socket.socket:
        """Transfer the held listener to an in-process loopback server."""

        reserved = self._socket
        if reserved is None:
            raise RuntimeError("dynamic port reservation is already released")
        self._socket = None
        return reserved

    def __enter__(self) -> DynamicPortReservation:
        return self

    def __exit__(self, *_args: object) -> None:
        self.release()


def allocate_dynamic_port() -> DynamicPortReservation:
    """Hold the loopback reservation until immediately before child spawn."""

    reserved = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        reserved.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        reserved.bind(("127.0.0.1", 0))
        port = int(reserved.getsockname()[1])
    except OSError:
        reserved.close()
        raise
    return DynamicPortReservation(port=port, _socket=reserved)
